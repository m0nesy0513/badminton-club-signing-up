# -*- coding: utf-8 -*-
"""管理員代發布工具 — 直接寫線上 Google Sheet，等於替你按後台「發佈場次」。

用法（由 AI 代操作，人話轉成參數）:
  查看現有場次:   python publish.py list
  發佈一場:       python publish.py add --date 2026-09-09 --start 20:00 --capacity 24 --open-days 2 --open-time 21:00
  預覽不寫入:     加 --dry-run
  刪除某天場次:   python publish.py delete --date 2026-09-09

open_at 預設 = 場次日期前 N 天的 open-time（Macau 時區）
export_at 預設 = 場次當天 12:00（與管理頁 quick-create 一致）
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import SheetsBackend, WD_ZH  # noqa: E402

MACAU = ZoneInfo("Asia/Macau")
HERE = os.path.dirname(os.path.abspath(__file__))
SA_PATH = os.path.join(HERE, "service_account.json")
SHEET_ID = "10LlaCWLbxWvVu8-9K9FYeMvYoXB1KxYi8mz-BIowuOI"

WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def backend():
    if not os.path.exists(SA_PATH):
        sys.exit("找不到 service_account.json（已 gitignore，不會進倉庫）")
    with open(SA_PATH, encoding="utf-8") as f:
        info = json.load(f)
    return SheetsBackend(SHEET_ID, info)


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_ev(ev):
    d = parse_date(ev["date"]) if ev.get("date") else None
    wd = WD_ZH[d.weekday()] if d else "?"
    return (f"{ev['date']} ({wd}) {ev.get('start_time','?')} · {ev.get('capacity','?')} 位 · "
            f"開搶 {(ev.get('open_at') or '?').replace('T',' ').replace('+08:00','')} · "
            f"導出 {(ev.get('export_at') or '-').replace('T',' ').replace('+08:00','') or '-'}")


def ev_from_row(r):
    return {"event_id": r.get("event_id"), "date": str(r.get("date", "")),
            "start_time": str(r.get("start_time", "")), "capacity": r.get("capacity", ""),
            "open_at": str(r.get("open_at", "")), "export_at": str(r.get("export_at", ""))}


def action_list(b):
    rows = [ev_from_row(r) for r in b.read("events") if r.get("event_id")]
    rows.sort(key=lambda e: e["date"])
    today = date.today()
    future = [e for e in rows if e["date"] >= f"{today:%Y-%m-%d}"]
    past = [e for e in rows if e["date"] < f"{today:%Y-%m-%d}"]
    print(f"📋 現有場次 Events：{len(rows)} 場（未來 {len(future)} / 已過 {len(past)}）")
    for e in future:
        print("  🔜", fmt_ev(e))
    return rows


def action_add(b, args):
    d = parse_date(args.date)
    event_id = f"{d:%Y%m%d}"
    start = args.start
    open_at = datetime.combine(d - timedelta(days=args.open_days),
                               dtime(*[int(x) for x in args.open_time.split(":")]),
                               tzinfo=MACAU)
    export_at = datetime.combine(d, dtime(12, 0), tzinfo=MACAU)
    if open_at <= datetime.now(MACAU):
        sys.exit(f"✋ 開搶時間 {open_at:%m/%d %H:%M} 已過，請往前調 --open-days / --open-time")

    existing = [ev_from_row(r) for r in b.read("events") if r.get("event_id")]
    if any(e["event_id"] == event_id for e in existing):
        sys.exit(f"✋ {args.date} 已有場次（event_id={event_id}）。要改時間請先 delete 再 add。")

    row = {"event_id": event_id, "date": f"{d:%Y-%m-%d}", "start_time": start,
           "capacity": int(args.capacity), "open_at": open_at.isoformat(timespec="seconds"),
           "export_at": export_at.isoformat(timespec="seconds"),
           "created_at": datetime.now(MACAU).isoformat(timespec="seconds")}
    wd = WD_ZH[d.weekday()]
    print(f"{'🧪 DRY-RUN 不寫入' if args.dry_run else '📤 發佈中'}：")
    print(f"   🏸 {d.month}/{d.day} ({wd}) {start} · {args.capacity} 位")
    print(f"   🔓 開搶：{open_at:%m/%d %H:%M}（提前 {args.open_days} 天）")
    print(f"   📥 導出：{export_at:%m/%d %H:%M}")
    if args.dry_run:
        print("   （未寫入。去掉 --dry-run 正式發佈）")
        return
    b.append("events", row)
    # 回讀驗證
    got = [ev_from_row(r) for r in b.read("events") if r.get("event_id") == event_id]
    if got:
        print(f"✅ 已發佈並回讀確認：{fmt_ev(got[0])}")
        print(f"   線上首頁 → https://club-registration.streamlit.app/")
    else:
        sys.exit("⚠️ 寫入後回讀不到，請檢查 Sheet")


def action_delete(b, args):
    d = parse_date(args.date)
    event_id = f"{d:%Y%m%d}"
    events = b.read("events")
    regs = b.read("registrations")
    if not any(r.get("event_id") == event_id for r in events):
        sys.exit(f"✋ {args.date} 沒有場次")
    n_regs = sum(1 for r in regs if r.get("event_id") == event_id)
    if args.dry_run:
        print(f"🧪 DRY-RUN：將刪除 {args.date} 場次 + {n_regs} 條報名記錄")
        return
    b.delete_where("events", {"event_id": event_id})
    if n_regs:
        b.delete_where("registrations", {"event_id": event_id})
    print(f"🗑️ 已刪除 {args.date} 場次（含 {n_regs} 條報名記錄）")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出現有場次")

    pa = sub.add_parser("add", help="發佈一場")
    pa.add_argument("--date", required=True, help="場次日期 YYYY-MM-DD")
    pa.add_argument("--start", default="20:00", help="開始時間 HH:MM")
    pa.add_argument("--capacity", type=int, default=24)
    pa.add_argument("--open-days", type=int, default=2, help="提前幾天開搶")
    pa.add_argument("--open-time", default="21:00", help="開搶時刻 HH:MM")
    pa.add_argument("--dry-run", action="store_true")

    pd = sub.add_parser("delete", help="刪除某天場次")
    pd.add_argument("--date", required=True)
    pd.add_argument("--dry-run", action="store_true")

    args = p.parse_args()
    b = backend()
    if args.cmd == "list":
        action_list(b)
    elif args.cmd == "add":
        action_add(b, args)
    elif args.cmd == "delete":
        action_delete(b, args)


if __name__ == "__main__":
    main()
