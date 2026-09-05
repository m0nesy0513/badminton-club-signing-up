# -*- coding: utf-8 -*-
"""管理頁 — 場次管理 / 名單匯出 / 會員名單"""
import csv as _csv
import io as _io
import hmac as _hmac
from datetime import datetime as _dt, time as _time, timedelta as _td

import pandas as pd
import streamlit as st

from core import (MACAU, RegError, fmt_dt_short, fmt_event_title, get_setting,
                  get_store, iso, norm_name, now_macau, parse_date)

st.set_page_config(page_title="管理 Admin", page_icon="⚙️", layout="wide")

store, mode = get_store()
ADMIN_PW = get_setting("ADMIN_PASSWORD", "admin")

if not st.session_state.get("admin_ok"):
    st.title("⚙️ 管理 Admin")
    with st.form("login"):
        pw = st.text_input("管理員密碼 Admin password", type="password")
        ok = st.form_submit_button("登入 Login", type="primary")
    if ok:
        if _hmac.compare_digest(pw.encode("utf-8"), str(ADMIN_PW).encode("utf-8")):
            st.session_state.admin_ok = True
            st.rerun()
        else:
            st.error("密碼錯誤 Wrong password")
    if mode == "local":
        st.caption("本地模式，預設密碼 admin。Local mode, default password 'admin'.")
    st.stop()

if mode == "local":
    st.warning("本地模式：資料存於 ./data CSV。部署到 Streamlit Cloud 並配置 secrets 後自動切換 Google Sheets。")

tab_events, tab_list, tab_members, tab_settings = st.tabs(
    ["📅 場次 Sessions", "📤 名單 Rosters", "👥 會員 Members", "⚙️ 設定 Settings"])

# ---------------------------------------------------------------- 場次管理
with tab_events:
    st.subheader("⚡ 快速建立本週場次 Quick create this week")
    _monday = now_macau().date() + _td(days=((7 - now_macau().weekday()) % 7) or 7)
    with st.form("quick_create"):
        any_day = st.date_input("該週任何一天 Any day of that week", value=_monday)
        start_t = st.time_input("開始時間 Start time", value=_time(20, 0))
        c1, c2, c3 = st.columns(3)
        rows = []
        for i, col in enumerate((c1, c2, c3)):
            with col:
                wd = st.selectbox(f"場次{i + 1} 星期 Day", list("一二三四五六日"),
                                  index=(0, 2, 4)[i], key=f"wd{i}")
                cap = st.number_input("名額 Capacity", 1, 200, (28, 24, 24)[i], key=f"cap{i}")
                before = st.number_input("提前幾天開放 Opens days before", 0, 7, 2, key=f"bf{i}")
                ot = st.time_input("開放時刻 Open time", value=_time(21, 0), key=f"ot{i}")
            rows.append((wd, int(cap), int(before), ot))
        sent = st.form_submit_button("建立三場 Create 3 sessions", type="primary")
    if sent:
        monday = any_day - _td(days=any_day.weekday())
        try:
            for wd, cap, before, ot in rows:
                d = monday + _td(days="一二三四五六日".index(wd))
                open_at = _dt.combine(d - _td(days=before), ot, tzinfo=MACAU)
                export_at = _dt.combine(d, _time(12, 0), tzinfo=MACAU)
                store.add_event(d, f"{start_t:%H:%M}", cap, open_at, export_at)
            st.toast("已建立 3 場 Created ✔")
            st.rerun()
        except RegError as e:
            st.error(str(e))

    st.subheader("➕ 新增單一場次 Add single session")
    with st.form("single_create"):
        d = st.date_input("日期 Date", value=now_macau().date() + _td(days=1))
        sc1, sc2 = st.columns(2)
        with sc1:
            stt = st.time_input("開始 Start", value=_time(20, 0))
            cap = st.number_input("名額 Capacity", 1, 200, 24)
        with sc2:
            od = st.date_input("開放日 Open date", value=now_macau().date())
            ot = st.time_input("開放時刻 Open time", value=_time(21, 0))
        sent2 = st.form_submit_button("建立 Create")
    if sent2:
        try:
            store.add_event(d, f"{stt:%H:%M}", int(cap),
                            _dt.combine(od, ot, tzinfo=MACAU),
                            _dt.combine(d, _time(12, 0), tzinfo=MACAU))
            st.toast("已建立 Created ✔")
            st.rerun()
        except RegError as e:
            st.error(str(e))

    st.subheader("📋 所有場次 All sessions")
    today_iso = f"{now_macau().date():%Y-%m-%d}"
    for ev in reversed(store.list_events()):
        icon = "🟢" if ev["date"] >= today_iso else "⌛"
        with st.expander(f"{icon} {fmt_event_title(ev)} · {ev['capacity']} 名額 · 開放 "
                         f"{fmt_dt_short(ev['open_at']) if ev['open_at'] else '?'}"):
            with st.form(f"edit_{ev['event_id']}"):
                ec1, ec2 = st.columns(2)
                with ec1:
                    nd = st.date_input("日期 Date", value=parse_date(ev["date"]) or now_macau().date(),
                                       key=f"d_{ev['event_id']}")
                    try:
                        st_val = _dt.strptime(ev["start_time"] or "20:00", "%H:%M").time()
                    except ValueError:
                        st_val = _time(20, 0)
                    nst = st.time_input("開始 Start", value=st_val, key=f"st_{ev['event_id']}")
                    ncap = st.number_input("名額 Capacity", 1, 200, ev["capacity"],
                                           key=f"c_{ev['event_id']}")
                with ec2:
                    odt = ev["open_at"] or now_macau()
                    nod = st.date_input("開放日 Open date", value=odt.date(), key=f"od_{ev['event_id']}")
                    not_ = st.time_input("開放時刻 Open time", value=odt.time(), key=f"ot_{ev['event_id']}")
                    edt = ev["export_at"] or odt
                    ned = st.date_input("導出日 Export date", value=edt.date(), key=f"ed_{ev['event_id']}")
                    net = st.time_input("導出時刻 Export time", value=edt.time(), key=f"et_{ev['event_id']}")
                save = st.form_submit_button("💾 儲存 Save")
                rm = st.checkbox("確認刪除 Confirm delete", key=f"rm_{ev['event_id']}")
                del_btn = st.form_submit_button("🗑 刪除 Delete")
            if save:
                store.update_event(ev["event_id"], {
                    "date": f"{nd:%Y-%m-%d}", "start_time": f"{nst:%H:%M}",
                    "capacity": int(ncap),
                    "open_at": iso(_dt.combine(nod, not_, tzinfo=MACAU)),
                    "export_at": iso(_dt.combine(ned, net, tzinfo=MACAU)),
                })
                st.toast("已儲存 Saved ✔")
                st.rerun()
            if del_btn:
                if rm:
                    store.delete_event(ev["event_id"])
                    st.toast("已刪除 Deleted")
                    st.rerun()
                else:
                    st.error("請先勾選「確認刪除」 Please tick confirm first")

# ---------------------------------------------------------------- 名單與匯出
with tab_list:
    events = store.list_events()
    if not events:
        st.info("尚無場次 No sessions yet.")
    else:
        today_iso = f"{now_macau().date():%Y-%m-%d}"
        options = [e["event_id"] for e in events]
        labels = [f"{'🟢' if e['date'] >= today_iso else '⌛'} {fmt_event_title(e)} · {e['capacity']} 名額"
                  for e in events]
        pick = st.selectbox("選擇場次 Session", options,
                            format_func=lambda x: labels[options.index(x)])
        info = store.registrations(pick)
        ev = info["event"]
        actives = info["actives"]
        confirmed = [r for r in actives if r["role"] == "confirmed"]
        waitlist = [r for r in actives if r["role"] == "waitlist"]
        m1, m2, m3 = st.columns(3)
        m1.metric("正選 Confirmed", f"{len(confirmed)}/{ev['capacity']}")
        m2.metric("候補 Waitlist", len(waitlist))
        m3.metric("已付 Paid", sum(1 for r in confirmed if r["paid"]))

        if not actives:
            st.info("還沒有人報名 No registrations yet.")
        else:
            reg_ids = [r["reg_id"] for r in actives]
            df = pd.DataFrame([{
                "姓名 Name": r["name"],
                "身份 Role": "🟢 正選" if r["role"] == "confirmed" else f"🟡 候補#{r['position']}",
                "報名時間 At": fmt_dt_short(r["joined_dt"]),
                "已付 Paid": bool(r["paid"]),
                "移除 Remove": False,
            } for r in actives])
            edited = st.data_editor(
                df, hide_index=True, use_container_width=True, key="roster_editor",
                disabled=["姓名 Name", "身份 Role", "報名時間 At"],
                column_config={
                    "已付 Paid": st.column_config.CheckboxColumn("已付 Paid", default=False),
                    "移除 Remove": st.column_config.CheckboxColumn(
                        "移除 Remove", help="勾選並儲存 = 標記取消（釋出名額）"),
                })
            if st.button("💾 儲存變更 Save changes", type="primary"):
                changed = 0
                for (_, nr), (_, orow), rid in zip(edited.iterrows(), df.iterrows(), reg_ids):
                    if bool(nr["已付 Paid"]) != bool(orow["已付 Paid"]):
                        store.set_paid(rid, bool(nr["已付 Paid"]))
                        changed += 1
                    if bool(nr["移除 Remove"]):
                        store.cancel(rid)
                        changed += 1
                if changed:
                    st.toast(f"已儲存 {changed} 項 Saved")
                    st.rerun()
                else:
                    st.info("沒有變更 No changes")

        header, rows = store.export_rows(pick)
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        st.download_button("⬇️ 匯出 CSV Export CSV", data=buf.getvalue().encode("utf-8-sig"),
                           file_name=f"badminton_{ev['event_id']}.csv", mime="text/csv",
                           use_container_width=True)
        st.caption(f"匯出為當下即時資料 Live data at download time · 導出時間 Export time："
                   f"{fmt_dt_short(ev['export_at']) if ev['export_at'] else '未設定 not set'}")
        if st.button("🔄 同步「匯出」分頁 Sync export tab",
                     help="把所有場次名單寫入 Google Sheets 的「匯出」分頁 / data/export.csv"):
            store.sync_export_tab()
            st.toast("已同步 Synced ✔")

# ---------------------------------------------------------------- 會員名單
with tab_members:
    names = store.members()
    st.caption(f"共 {len(names)} 人 · 此名單用於會員快速選名 Powers the quick name picker")
    txt = st.text_area("每行一個姓名 One name per line", value="\n".join(names), height=300)
    if st.button("💾 儲存會員名單 Save roster", type="primary"):
        store.seed_members([norm_name(x) for x in txt.splitlines() if norm_name(x)], replace=True)
        st.toast("已儲存 Saved ✔")
        st.rerun()

# ---------------------------------------------------------------- 設定
with tab_settings:
    st.markdown(f"- 資料後端 Backend：**{'Google Sheets ✅' if mode == 'sheets' else '本機 CSV（local）'}**")
    if mode == "sheets":
        st.markdown(f"- Google Sheet：<https://docs.google.com/spreadsheets/d/{get_setting('SHEET_ID')}>")
    st.markdown("- 管理密碼 Admin password："
                + ("已配置 configured ✅" if get_setting("ADMIN_PASSWORD")
                   else "未配置（預設 admin）— 部署時請在 Secrets 設定 ADMIN_PASSWORD ⚠️"))
    st.markdown("- 部署教學見專案內 **DEPLOY.md**；本地自檢：`python selfcheck.py`")
    st.markdown("- 預設導出時間為場次當天 12:00，可在「場次」裡逐場修改")
