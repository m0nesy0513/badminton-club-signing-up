# -*- coding: utf-8 -*-
"""自檢腳本

python selfcheck.py          # 核心邏輯測試（使用臨時資料夾，不污染專案）
python selfcheck.py --demo   # 另在本機 ./data 生成演示資料（供瀏覽器實測）
"""
import os
import shutil
import sys
import tempfile
from datetime import timedelta

from core import (CSVBackend, ClubStore, EventNotOpen, RegError, iso,
                  now_macau)

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅ PASS" if cond else "❌ FAIL"), name, extra)


def main():
    tmp = tempfile.mkdtemp(prefix="bmc_selfcheck_")
    store = ClubStore(CSVBackend(tmp))
    now = now_macau()
    today = now.date()
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    past_open = iso(now.replace(microsecond=0))  # 已開放的開搶時間

    # 1) 建場次
    ev1 = store.add_event(monday, "20:00", 2,
                          now - timedelta(minutes=10), now + timedelta(days=1))
    ev2 = store.add_event(monday + timedelta(days=1), "20:00", 28,
                          now - timedelta(minutes=10))
    ev3 = store.add_event(monday + timedelta(days=2), "20:00", 28,
                          now - timedelta(minutes=10))
    ev4 = store.add_event(monday + timedelta(days=3), "20:00", 28,
                          now - timedelta(minutes=10))
    ev5 = store.add_event(monday + timedelta(days=7), "20:00", 28,
                          now + timedelta(days=8))
    check("建立場次 add_event", all([ev1, ev2, ev3, ev4, ev5]))

    # 2) 搶位：滿 2 後進候補
    r1 = store.register(ev1, "陳大文")
    r2 = store.register(ev1, "李家豪")
    r3 = store.register(ev1, "黃美琪")
    r4 = store.register(ev1, "周小明")
    check("先到先得 first-come-first-served",
          r1["role"] == "confirmed" and r2["role"] == "confirmed"
          and r3["role"] == "waitlist" and r3["position"] == 1
          and r4["position"] == 2)

    # 3) 重複報名去重
    dup = store.register(ev1, " 陳大文 ")
    check("重複報名 duplicate check", dup["duplicate"] is True)

    # 4) 取消 → 候補自動遞補
    regs = store.registrations(ev1)["actives"]
    chen = next(r for r in regs if r["name"] == "陳大文")
    store.cancel(chen["reg_id"])
    actives = store.registrations(ev1)["actives"]
    roles = {r["name"]: (r["role"], r["position"]) for r in actives}
    check("取消自動遞補 waitlist auto-promote",
          roles["李家豪"] == ("confirmed", 0)
          and roles["黃美琪"] == ("confirmed", 0)
          and roles["周小明"] == ("waitlist", 1))

    # 5) 已付標記 + 匯出
    li = next(r for r in actives if r["name"] == "李家豪")
    store.set_paid(li["reg_id"], True)
    header, rows = store.export_rows(ev1)
    by_name = {r[3]: r for r in rows}
    check("匯出內容 export rows",
          by_name["李家豪"][6] == "是" and by_name["李家豪"][4] == "正選"
          and by_name["周小明"][4] == "候補1"
          and header[6].startswith("已付"))

    # 6) 每週第 3 場統計（提示用，不攔截）
    store.register(ev2, "陳大文")
    store.register(ev3, "陳大文")
    store.register(ev4, "陳大文")
    check("本週場數統計 week count = 3",
          store.active_week_count("陳大文", monday) == 3)

    # 7) 未開放不可報名
    try:
        store.register(ev5, "測試員")
        check("未開放攔截 not-open guard", False, "(should raise)")
    except EventNotOpen:
        check("未開放攔截 not-open guard", True)

    # 8) 縮容 → 多出的自動轉候補
    store.update_event(ev2, {"capacity": 1})
    actives2 = store.registrations(ev2)["actives"]
    check("縮容自動降候補 capacity shrink",
          sum(1 for r in actives2 if r["role"] == "confirmed") == 1)

    # 9) 會員名單（報名接口不寫會員表——搶位高峰只做一次寫入；名單在首次確認身份時維護）
    store.seed_members(["甲", "乙", "丙"], replace=True)
    check("會員名單 members replace", set(store.members()) == {"甲", "乙", "丙"})
    store.seed_members(["丁丁"])
    check("會員名單 members append", set(store.members()) == {"甲", "乙", "丙", "丁丁"})

    # 10) 匯出分頁同步
    store.sync_export_tab()
    check("匯出分頁 sync export tab",
          os.path.exists(os.path.join(tmp, "export.csv")))

    shutil.rmtree(tmp, ignore_errors=True)

    if all(RESULTS):
        print(f"\n🎉 全部通過 {len(RESULTS)}/{len(RESULTS)}")
    else:
        print(f"\n💥 有 {RESULTS.count(False)} 項失敗")
        sys.exit(1)


def seed_demo():
    """在 ./data 生成演示資料，供本地瀏覽器實測。"""
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    shutil.rmtree(data_dir, ignore_errors=True)
    store = ClubStore(CSVBackend(data_dir))
    now = now_macau()
    today = now.date()
    store.seed_members(["陳大文", "李家豪", "黃美琪", "周小明", "張嘉欣",
                        "吳志強", "何雅文", "林俊傑", "Eric Smith", "Sarah Johnson"])
    store.add_event(today, "20:00", 3, now - timedelta(minutes=40), now + timedelta(hours=4))
    store.add_event(today + timedelta(days=1), "20:00", 24, now - timedelta(minutes=40))
    print(f"演示資料已寫入 {data_dir}")


if __name__ == "__main__":
    main()
    if "--demo" in sys.argv:
        seed_demo()
