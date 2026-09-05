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


import time as _time

# 手動快取（不依賴 st.cache_data，避免對象哈希問題）
_snap_cache = {"data": None, "ts": 0}
_SNAP_TTL = 30  # 秒


def _snapshot():
    """一次 API 調用讀取全三張表，30 秒手動快取。直接調 backend.read，不依賴 store.snapshot。"""
    now_ts = _time.time()
    if _snap_cache["data"] is not None and (now_ts - _snap_cache["ts"]) < _SNAP_TTL:
        return _snap_cache["data"]
    data = {
        "events": store.b.read("events"),
        "registrations": store.b.read("registrations"),
        "members": store.b.read("members"),
    }
    _snap_cache["data"] = data
    _snap_cache["ts"] = now_ts
    return data


def _parse_events(raw):
    """从原始行解析场次列表（内联，不依赖 core 新方法）。"""
    from core import to_int, parse_dt
    out = []
    for r in raw:
        if not r.get("event_id") or not r.get("date"):
            continue
        out.append({
            "event_id": r["event_id"], "date": str(r.get("date", "")),
            "start_time": str(r.get("start_time", "")),
            "capacity": to_int(r.get("capacity"), 24),
            "open_at": parse_dt(r.get("open_at")),
            "export_at": parse_dt(r.get("export_at")),
            "created_at": r.get("created_at", ""),
        })
    out.sort(key=lambda e: (e["date"], e["start_time"]))
    return out


def _derive_regs(raw_regs, capacity):
    """内联推导正选/候补（不依赖 core 新方法）。"""
    from core import parse_dt, norm_name, to_bool, EPOCH
    actives = [dict(r) for r in raw_regs if str(r.get("status", "")) == "active"]
    dedup = {}
    for r in sorted(actives, key=lambda r: parse_dt(r.get("joined_at")) or EPOCH):
        dedup.setdefault(norm_name(r.get("name")), r)
    ordered = sorted(dedup.values(), key=lambda r: parse_dt(r.get("joined_at")) or EPOCH)
    cancelled = [r for r in raw_regs if str(r.get("status", "")) == "cancelled"]
    for i, r in enumerate(ordered):
        r["name"] = norm_name(r.get("name"))
        r["paid"] = to_bool(r.get("paid"))
        r["joined_dt"] = parse_dt(r.get("joined_at")) or EPOCH
        if i < capacity:
            r["role"], r["position"] = "confirmed", 0
        else:
            r["role"], r["position"] = "waitlist", i - capacity + 1
    return ordered, cancelled


def _board():
    """基于快照推导出场次 + 报名状态，不读 API。"""
    snap = _snapshot()
    today_iso = f"{now_macau().date():%Y-%m-%d}"
    events = _parse_events(snap["events"])
    upcoming = [e for e in events if e["date"] >= today_iso][:8]
    regs = {}
    for e in upcoming:
        ev_regs = [r for r in snap["registrations"] if r.get("event_id") == e["event_id"]]
        actives, cancelled = _derive_regs(ev_regs, e["capacity"])
        regs[e["event_id"]] = {"event": e, "actives": actives, "cancelled": cancelled}
    return upcoming, regs


def _week_count(name, date_iso):
    """基于快照推导，不读 API。"""
    from core import parse_date, norm_name
    d = parse_date(date_iso)
    if not d:
        return 0
    snap = _snapshot()
    events = _parse_events(snap["events"])
    name = norm_name(name)
    week = d.isocalendar()[:2]
    n = 0
    for ev in events:
        ev_d = parse_date(ev["date"])
        if not ev_d or ev_d.isocalendar()[:2] != week:
            continue
        ev_regs = [r for r in snap["registrations"] if r.get("event_id") == ev["event_id"]]
        actives, _ = _derive_regs(ev_regs, ev["capacity"])
        if any(r["name"] == name for r in actives):
            n += 1
    return n


def _members_list():
    """基于快照，不读 API。"""
    return sorted({norm_name(r.get("name")) for r in _snapshot()["members"]
                   if norm_name(r.get("name"))})


def _clear_all_cache():
    """清掉快取（報名/取消/會員變動後調用）。"""
    _snap_cache["data"] = None
    _snap_cache["ts"] = 0


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

# ---------------------------------------------------------------- 前端腳本（用 st.html 直接注入 app 頁面，不走 component iframe）
# 舊方案用 components.html(srcdoc iframe)，但 srcdoc 裡的 <script> 在 Streamlit
# Cloud 上不會自動執行 → 倒計時凝固。st.html（1.39+）把 HTML 直接寫進 app 文檔，
# <script> 在頁面上下文同步執行，最可靠。
# 1) 姓名框綁定 datalist 自動補全（輸入"陳"提示"陳大文"）
# 2) 鎖定場次倒計時每秒跳動；到 0 自動刷新頁面讓報名按鈕出現
_FE_JS = r"""
<script>
(function(){
  var members = __MEMBERS__;
  var win = window; // st.html 直接在 app 頁面執行，window 就是 app 視窗
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
  function pad(n){ return String(n).padStart(2,'0'); }
  // 每次注入都先清掉舊計時器再註冊新的，確保任何時刻只有一個 interval 在跑
  //（Streamlit rerun 會重新執行本段腳本，舊 interval 若不清掉會越積越多）。
  if (!win.__bcm_tick){
    win.__bcm_tick = function(){
      var now = Date.now();
      var opened = false;
      try {
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
      } catch(e){}
      if (opened && !win.__bcm_reloaded){ win.__bcm_reloaded = true; setTimeout(function(){ try{ win.location.reload(); }catch(e){} }, 700); }
    };
  }
  try { if (win.__bcm_tick_id) win.clearInterval(win.__bcm_tick_id); } catch(e){}
  win.__bcm_tick_id = win.setInterval(win.__bcm_tick, 1000);
  if (!win.__bcm_obs){
    try {
      var obs = new win.MutationObserver(function(){ setup(); });
      obs.observe(win.document.body, {childList:true, subtree:true});
      win.__bcm_obs = true;
    } catch(e){}
  }
  setup(); win.__bcm_tick();
})();
</script>
"""

_members_js = json.dumps(_members_list(), ensure_ascii=False)
st.html(_FE_JS.replace("__MEMBERS__", _members_js))

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
