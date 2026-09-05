# -*- coding: utf-8 -*-
"""會員報名頁 — 微信 / 瀏覽器直接打開的 H5 報名入口"""
import json

import streamlit as st

from core import (RegError, fmt_countdown, fmt_dt_short, fmt_event_title,
                  get_setting, get_store, norm_name, now_macau, parse_date)

st.set_page_config(page_title="羽毛球會報名 Badminton Sign-up", page_icon="🏸", layout="centered")

st.markdown("""<style>
#MainMenu, footer {visibility: hidden;}
/* 手機字體放大，按鈕好點 */
[data-testid="stAppViewBlockContainer"] {padding-top: 1.2rem;}
button {font-size: 1.05rem !important;}
</style>""", unsafe_allow_html=True)

store, mode = get_store()
CLUB_NAME = get_setting("CLUB_NAME", "澳門大學羽毛球會")


@st.cache_data(ttl=30, show_spinner=False)
def _snapshot():
    """一次 API 調用讀取全三張表，30 秒緩存。根治 429。"""
    return store.snapshot()


@st.cache_data(ttl=30, show_spinner=False)
def _board():
    """基於 _snapshot 的快照推導出場次 + 報名狀態，不再獨立讀 API。"""
    snap = _snapshot()
    today_iso = f"{now_macau().date():%Y-%m-%d}"
    events = store._list_events_from(snap["events"])
    upcoming = [e for e in events if e["date"] >= today_iso][:8]
    regs = {e["event_id"]: store.registrations_from(e["event_id"], events, snap["registrations"])
            for e in upcoming}
    return upcoming, regs


@st.cache_data(ttl=30, show_spinner=False)
def _week_count(name, date_iso):
    """基於 _snapshot 推導，不讀 API。"""
    d = parse_date(date_iso)
    if not d:
        return 0
    snap = _snapshot()
    events = store._list_events_from(snap["events"])
    return store._week_count_from(name, d, events, snap["registrations"])


@st.cache_data(ttl=30, show_spinner=False)
def _members_list():
    """基於 _snapshot，不讀 API。"""
    return sorted({norm_name(r.get("name")) for r in _snapshot()["members"]
                   if norm_name(r.get("name"))})


def _clear_all_cache():
    """清掉所有快取（報名/取消/會員變動後調用）。"""
    _snapshot.clear()
    _board.clear()
    _week_count.clear()
    _members_list.clear()


def _identity(store) -> str:
    """身份用 session_state + URL query param 記住，零 JS、同步、秒開。"""
    ss = st.session_state
    qp_user = st.query_params.get("user")
    if qp_user and norm_name(qp_user) and not ss.get("member_name"):
        ss.member_name = norm_name(qp_user)

    if ss.get("member_name"):
        c1, c2 = st.columns([5, 1])
        c1.caption(f"👤 {ss.member_name}")
        if c2.button("更改 Change", key="btn_change_name"):
            ss.member_name = ""
            try:
                del st.query_params["user"]
            except Exception:
                pass
            st.rerun()
        return ss.member_name

    members = _members_list()
    with st.form("form_identity", border=True):
        st.text_input(
            "輸入或選擇姓名 Type or pick your name",
            max_chars=24, key="ident_name",
            help="可直接輸入；已登記會員會自動提示 Can type directly; known members auto-suggest")
        # 已登記會員快捷選擇（按下即填入，無需展開「其他」）
        picked = ""
        if members:
            picked = st.selectbox(
                "或選擇已登記會員 Or pick a known member",
                ["（不選 not selected）"] + members, index=0)
        sent = st.form_submit_button("確定 Confirm", type="primary", use_container_width=True)
    if sent:
        manual = norm_name(ss.get("ident_name", ""))
        final = manual or (norm_name(picked) if picked and picked != "（不選 not selected）" else "")
        ss.pop("ident_name", None)
        if final:
            ss.member_name = final
            st.query_params["user"] = final
            try:
                store.seed_members([final])
            except Exception:
                pass
            st.rerun()
        st.error("請輸入或選擇姓名 Please type or pick a name")
    return ""


st.title(f"🏸 {CLUB_NAME}")
st.caption("會員場次報名 Session Sign-up · 定時開搶 · 先到先得 First come, first served")

name = _identity(store)
if not name:
    st.info("請先輸入或選擇姓名，再進行報名。Please type or pick your name first.")
else:
    upcoming, regs = _board()
    now = now_macau()

    wc = _week_count(name, f"{now.date():%Y-%m-%d}")
    st.caption(f"本週已報名 {wc} 場 · {name}，你好！You have {wc} session(s) this week.")

    if not upcoming:
        st.info("暫無場次，請等管理員發佈。No sessions scheduled yet.")

    for ev in upcoming:
        info = regs[ev["event_id"]]
        actives, cancelled = info["actives"], info["cancelled"]
        confirmed = [r for r in actives if r["role"] == "confirmed"]
        waitlist = [r for r in actives if r["role"] == "waitlist"]
        mine = next((r for r in actives if r["name"] == name), None)
        my_cancelled = next((r for r in cancelled if norm_name(r.get("name")) == name), None)
        open_at = ev["open_at"]
        is_open = (open_at is None) or (open_at <= now)
        full = len(confirmed) >= ev["capacity"]

        with st.container(border=True):
            top = st.columns([3, 1])
            top[0].markdown(f"**🏸 {fmt_event_title(ev)}**")
            top[1].markdown(f"<div style='text-align:right'><b>{len(confirmed)}</b>/{ev['capacity']} 名額</div>",
                            unsafe_allow_html=True)
            st.progress(min(1.0, len(confirmed) / max(1, ev["capacity"])),
                        text=f"已報 Registered {len(confirmed)}/{ev['capacity']}")

            if not is_open:
                remain = (open_at - now).total_seconds()
                ts = int(open_at.timestamp())
                # span 自帶 data-ts（開搶時刻 epoch）與 data-remain（初始剩餘秒）
                # JS 每秒讀 data-ts 重新計算，不依賴外部 targets 對象何時注入
                st.markdown(
                    f"🔒 報名將於 **{fmt_dt_short(open_at)}** 開放 Opens at {fmt_dt_short(open_at)} · "
                    f"尚餘 <strong id='bcm_cd_{ev['event_id']}' class='bcm_cd' data-ts='{ts}' data-remain='{int(remain)}'>"
                    f"{fmt_countdown(remain)}</strong>",
                    unsafe_allow_html=True)
            else:
                if mine:
                    if mine["role"] == "confirmed":
                        st.success("🟢 已報名 · 正選 You're in")
                    else:
                        st.warning(f"🟡 候補中 Waitlist #{mine['position']}")
                    if st.button("取消報名 Cancel", key=f"cancel_{ev['event_id']}"):
                        store.cancel(mine["reg_id"])
                        _clear_all_cache()
                        st.toast("已取消 Cancelled · 候補自動遞補 Waitlist auto-promoted")
                        st.rerun()
                else:
                    if my_cancelled:
                        st.caption("已取消 Cancelled — 可重新報名 You can register again")
                    label = "加入候補 Join waitlist" if full else "報名 Sign up"
                    if st.button(label, type="primary", key=f"reg_{ev['event_id']}"):
                        try:
                            res = store.register(ev["event_id"], name)
                            _clear_all_cache()
                            if res.get("duplicate"):
                                st.toast("你已在名單中 Already registered")
                            else:
                                st.toast("報名成功 You're in!" if res["role"] == "confirmed"
                                         else "已加入候補 On the waitlist")
                                if _week_count(name, ev["date"]) >= 3:
                                    st.warning("溫馨提示：這是你本週第 3 場。原則上建議每週兩場，記得量力而行。"
                                               "Note: this is your 3rd session this week (2 recommended).")
                            st.rerun()
                        except RegError as e:
                            st.error(str(e))

                st.caption("提前取消不處罰，名額自動由候補遞補。Cancel anytime — no penalty, waitlist auto-promotes.")

            with st.expander("查看名單 View list"):
                if confirmed:
                    st.markdown("🟢 **正選 Confirmed**：" + "、".join(r["name"] for r in confirmed))
                if waitlist:
                    st.markdown("🟡 **候補 Waitlist**：" + "、".join(f"{r['name']} #{r['position']}" for r in waitlist))
                if not confirmed and not waitlist:
                    st.caption("還沒有人報名 Nobody yet.")

# ---------------------------------------------------------------- 前端腳本（用 st.components.v1.html 注入獨立 iframe，注入即執行）
# 解決 streamlit_js_eval 在 rerun 時序中注入不可靠的問題。
# 1) 姓名框綁定 datalist 自動補全（輸入"陳"提示"陳大文"）
# 2) 鎖定場次倒計時每秒跳動；到 0 自動刷新頁面讓報名按鈕出現
import html as _html  # noqa: F401  保留供未來擴展
import streamlit.components.v1 as components

_FE_JS = r"""
<script>
(function(){
  var members = __MEMBERS__;
  var win = window.parent; // component iframe 的父頁就是 Streamlit 主頁
  function setup(){
    try {
      if (!win.__bcm_dl && members.length){
        var dl = win.document.createElement('datalist');
        dl.id = 'bcm_members';
        members.forEach(function(m){ var o = win.document.createElement('option'); o.value=m; dl.appendChild(o); });
        win.document.body.appendChild(dl);
        win.__bcm_dl = true;
      }
    } catch(e){}
    try {
      var inp = win.document.querySelector('.st-key-ident_name input');
      if (inp && !inp.getAttribute('list')) inp.setAttribute('list','bcm_members');
    } catch(e){}
  }
  if (win.__bcm_tick){ setup(); return; }
  win.__bcm_tick = true;
  function pad(n){ return String(n).padStart(2,'0'); }
  var reloaded = false;
  function tick(){
    var now = Date.now();
    var opened = false;
    win.document.querySelectorAll('.bcm_cd').forEach(function(el){
      var ts = parseInt(el.getAttribute('data-ts')||'0',10);
      if (!ts) return;
      var diff = Math.floor((ts*1000 - now)/1000);
      if (diff <= 0){ el.textContent = '即將開放 Opening…'; opened = true; }
      else {
        var d = Math.floor(diff/86400), h = Math.floor((diff%86400)/3600),
            m = Math.floor((diff%3600)/60), s = diff%60;
        el.textContent = (d>0? d+'天 ':'') + pad(h)+':'+pad(m)+':'+pad(s);
      }
    });
    if (opened && !reloaded){ reloaded = true; setTimeout(function(){ win.location.reload(); }, 700); }
  }
  setInterval(tick, 1000);
  // Streamlit rerun 後 DOM 會重建，需重新綁定 datalist
  var obs = new MutationObserver(function(){ setup(); });
  try { obs.observe(win.document.body, {childList:true, subtree:true}); } catch(e){}
  setup(); tick();
})();
</script>
"""

_members_js = json.dumps(_members_list(), ensure_ascii=False)
components.html(_FE_JS.replace("__MEMBERS__", _members_js), height=0, width=0)

# 開搶後 10 分鐘內每 5 秒刷新，即時看到名額變化（搶位進行時）
try:
    from streamlit_autorefresh import st_autorefresh
    if name:
        _post = [(now_macau() - e["open_at"]).total_seconds()
                 for e in store.list_events() if e["open_at"]]
        if any(0 <= t <= 600 for t in _post):
            st_autorefresh(interval=5000, key="ar_post")
except Exception:
    pass

if mode == "local":
    st.caption("🔧 本地模式 local mode — 資料存於 ./data（部署後自動切換 Google Sheets）")
