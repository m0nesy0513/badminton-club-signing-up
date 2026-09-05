# -*- coding: utf-8 -*-
"""羽毛球會報名系統 — 核心邏輯與儲存層

設計要點:
- 所有時間使用 Asia/Macau (UTC+8)，儲存為帶時區的 ISO 字串。
- 報名資料「只追加」：正選/候補在讀取時按 joined_at 推導，
  併發搶位不會超賣，提前取消後候補自動遞補。
- 儲存後端可替換：Google Sheets（正式環境）或本機 CSV（開發/自檢）。
"""
from __future__ import annotations

import csv
import json
import os
import threading
import uuid
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

MACAU = ZoneInfo("Asia/Macau")
EPOCH = datetime(1970, 1, 1, tzinfo=MACAU)
WD_ZH = "一二三四五六日"

EVENT_COLS = ["event_id", "date", "start_time", "capacity", "open_at", "export_at", "created_at"]
REG_COLS = ["reg_id", "event_id", "name", "joined_at", "status", "cancelled_at", "paid"]
MEMBER_COLS = ["name", "first_seen", "last_seen"]
TABLES = {"events": EVENT_COLS, "registrations": REG_COLS, "members": MEMBER_COLS}

EXPORT_HEADER = ["場次 Session", "日期 Date", "時間 Time", "姓名 Name", "身份 Role",
                 "本週第幾場 Sessions this week", "已付 Paid", "報名時間 Registered at"]

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_write_lock = threading.Lock()


class RegError(Exception):
    """報名相關錯誤，訊息已雙語（繁中 + 英文）。"""


class EventNotFound(RegError):
    pass


class EventNotOpen(RegError):
    pass


# ---------------------------------------------------------------- 时间工具

def now_macau() -> datetime:
    return datetime.now(MACAU)


def iso(dt: datetime) -> str:
    return dt.astimezone(MACAU).isoformat(timespec="seconds")


def parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).strip())
    except ValueError:
        return None
    return d.replace(tzinfo=MACAU) if d.tzinfo is None else d


def parse_date(s):
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


def to_int(v, default=0):
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return default


def to_bool(v):
    return str(v).strip().lower() in ("true", "1", "yes", "y", "是")


def norm_name(s) -> str:
    return " ".join(str(s or "").split())


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def weekday_zh(d: date) -> str:
    return WD_ZH[d.weekday()]


def fmt_event_title(ev: dict) -> str:
    d = parse_date(ev.get("date"))
    if not d:
        return str(ev.get("event_id", "?"))
    return f"{d.month}/{d.day} ({weekday_zh(d)}) {ev.get('start_time') or ''}".strip()


def fmt_dt_short(dt: datetime) -> str:
    return f"{dt.month}/{dt.day} {dt:%H:%M}"


def fmt_countdown(seconds: float) -> str:
    s = max(0, int(seconds))
    if s >= 86400:
        return f"{s // 86400}天 {s % 86400 // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ---------------------------------------------------------------- 儲存後端

class CSVBackend:
    """本機 CSV 儲存（開發 / 自檢用），每張表一個檔案。"""

    def __init__(self, data_dir: str | None = None):
        self.dir = data_dir or _DATA_DIR
        os.makedirs(self.dir, exist_ok=True)
        for t in TABLES:
            if not os.path.exists(self._path(t)):
                self._write(t, [])

    def _path(self, table: str) -> str:
        name = "export.csv" if table == "匯出" else f"{table}.csv"
        return os.path.join(self.dir, name)

    def _read(self, table):
        p = self._path(table)
        if not os.path.exists(p):
            return []
        with open(p, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _write(self, table, rows):
        cols = TABLES.get(table) or (list(rows[0].keys()) if rows else ["value"])
        with open(self._path(table), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: str(r.get(c, "")) for c in cols})

    def read(self, table):
        return self._read(table)

    def append(self, table, row):
        rows = self._read(table)
        rows.append({c: str(row.get(c, "")) for c in TABLES[table]})
        self._write(table, rows)

    def update_where(self, table, match, updates):
        rows = self._read(table)
        for r in rows:
            if all(str(r.get(k, "")) == str(v) for k, v in match.items()):
                r.update({k: str(v) for k, v in updates.items()})
        self._write(table, rows)

    def delete_where(self, table, match):
        rows = [r for r in self._read(table)
                if not all(str(r.get(k, "")) == str(v) for k, v in match.items())]
        self._write(table, rows)

    def replace_table(self, table, header, rows):
        with open(self._path(table), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(list(header))
            w.writerows(rows)


class SheetsBackend:
    """Google Sheets 儲存（正式環境），每張表一個分頁，全部以 RAW 文本寫入。"""

    def __init__(self, sheet_id: str, service_account_info: dict):
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        self.sh = gspread.authorize(creds).open_by_key(sheet_id)
        self._ensure_tabs()

    def _ws(self, table):
        return self.sh.worksheet(table)

    def _ensure_tabs(self):
        existing = {w.title for w in self.sh.worksheets()}
        for t, cols in TABLES.items():
            if t not in existing:
                ws = self.sh.add_worksheet(title=t, rows=2000, cols=max(10, len(cols)))
                ws.append_row(cols, value_input_option="RAW")

    def read(self, table):
        vals = self._ws(table).get_all_values()
        if len(vals) < 2:
            return []
        header = [h.strip() for h in vals[0]]
        return [{h: ("" if i >= len(row) else str(row[i]).strip())
                 for i, h in enumerate(header)} for row in vals[1:]]

    def append(self, table, row):
        self._ws(table).append_row([str(row.get(c, "")) for c in TABLES[table]],
                                   value_input_option="RAW")

    def _match_indices(self, table, match):
        vals = self._ws(table).get_all_values()
        header = [h.strip() for h in vals[0]] if vals else []
        idx = {c: i for i, c in enumerate(header)}
        out = []
        for rno, row in enumerate(vals[1:], start=2):
            if all(str(row[idx[k]] if k in idx and idx[k] < len(row) else "") == str(v)
                   for k, v in match.items()):
                out.append(rno)
        return out, idx

    def update_where(self, table, match, updates):
        rows, idx = self._match_indices(table, match)
        ws = self._ws(table)
        for rno in rows:
            for k, v in updates.items():
                if k in idx:
                    ws.update_cell(rno, idx[k] + 1, str(v))

    def delete_where(self, table, match):
        rows, _ = self._match_indices(table, match)
        ws = self._ws(table)
        for rno in reversed(rows):
            ws.delete_rows(rno)

    def replace_table(self, table, header, rows):
        try:
            ws = self._ws(table)
        except Exception:
            ws = self.sh.add_worksheet(title=table, rows=max(100, len(rows) + 2),
                                       cols=max(10, len(header)))
        ws.clear()
        ws.append_row(list(header), value_input_option="RAW")
        if rows:
            ws.append_rows([[str(c) for c in r] for r in rows], value_input_option="RAW")


# ---------------------------------------------------------------- 業務層

class ClubStore:
    def __init__(self, backend):
        self.b = backend

    # ---------- 場次 ----------
    def add_event(self, d: date, start_time: str, capacity: int,
                  open_at: datetime, export_at: datetime | None = None) -> str:
        event_id = f"{d:%Y%m%d}"
        with _write_lock:
            if self.get_event(event_id):
                raise RegError(f"{d.month}/{d.day} 場次已存在 Session already exists on this date")
            self.b.append("events", {
                "event_id": event_id, "date": f"{d:%Y-%m-%d}", "start_time": start_time,
                "capacity": int(capacity), "open_at": iso(open_at),
                "export_at": iso(export_at) if export_at else "",
                "created_at": iso(now_macau()),
            })
        return event_id

    def update_event(self, event_id, updates: dict):
        payload = dict(updates)
        for k in ("open_at", "export_at"):
            if k in payload and isinstance(payload[k], datetime):
                payload[k] = iso(payload[k])
        if "date" in payload and isinstance(payload["date"], date):
            payload["date"] = f"{payload['date']:%Y-%m-%d}"
        self.b.update_where("events", {"event_id": event_id}, payload)

    def delete_event(self, event_id):
        self.b.delete_where("registrations", {"event_id": event_id})
        self.b.delete_where("events", {"event_id": event_id})

    def list_events(self) -> list[dict]:
        out = []
        for r in self.b.read("events"):
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

    def get_event(self, event_id) -> dict | None:
        for e in self.list_events():
            if e["event_id"] == event_id:
                return e
        return None

    # ---------- 報名 ----------
    def _derive(self, raw_regs, capacity):
        """按 joined_at 推導正選/候補；同名去重保留最早的有效報名。"""
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

    def _event_regs(self, event_id):
        return [r for r in self.b.read("registrations") if r.get("event_id") == event_id]

    def registrations(self, event_id) -> dict:
        ev = self.get_event(event_id)
        if not ev:
            raise EventNotFound("場次不存在 Event not found")
        actives, cancelled = self._derive(self._event_regs(event_id), ev["capacity"])
        return {"event": ev, "actives": actives, "cancelled": cancelled}

    def register(self, event_id, name) -> dict:
        name = norm_name(name)
        if not name:
            raise RegError("請先填寫姓名 Please set your name first")
        ev = self.get_event(event_id)
        if not ev:
            raise EventNotFound("場次不存在 Event not found")
        open_at = ev.get("open_at")
        if open_at and open_at > now_macau():
            raise EventNotOpen(f"報名尚未開放 Registration opens at {fmt_dt_short(open_at)}")
        with _write_lock:
            current, _ = self._derive(self._event_regs(event_id), ev["capacity"])
            for r in current:
                if r["name"] == name:
                    return {"ok": True, "duplicate": True,
                            "role": r["role"], "position": r["position"]}
            self.b.append("registrations", {
                "reg_id": new_id(), "event_id": event_id, "name": name,
                "joined_at": iso(now_macau()), "status": "active",
                "cancelled_at": "", "paid": "",
            })
        actives, _ = self._derive(self._event_regs(event_id), ev["capacity"])
        mine = next((r for r in actives if r["name"] == name), None)
        return {"ok": True, "duplicate": False,
                "role": mine["role"] if mine else "?",
                "position": (mine or {}).get("position", 0)}

    def cancel(self, reg_id):
        self.b.update_where("registrations", {"reg_id": reg_id},
                            {"status": "cancelled", "cancelled_at": iso(now_macau())})

    def set_paid(self, reg_id, paid: bool):
        self.b.update_where("registrations", {"reg_id": reg_id},
                            {"paid": "TRUE" if paid else "FALSE"})

    def active_week_count(self, name, ref_date: date) -> int:
        name = norm_name(name)
        week = ref_date.isocalendar()[:2]
        n = 0
        for ev in self.list_events():
            d = parse_date(ev["date"])
            if not d or d.isocalendar()[:2] != week:
                continue
            actives, _ = self._derive(self._event_regs(ev["event_id"]), ev["capacity"])
            if any(r["name"] == name for r in actives):
                n += 1
        return n

    # ---------- 會員 ----------
    def members(self) -> list[str]:
        return sorted({norm_name(r.get("name")) for r in self.b.read("members")
                       if norm_name(r.get("name"))})

    def seed_members(self, names, replace=False):
        names = [norm_name(n) for n in names if norm_name(n)]
        with _write_lock:
            if replace:
                self.b.delete_where("members", {})
            existing = {norm_name(r.get("name")) for r in self.b.read("members")}
            now = iso(now_macau())
            for n in dict.fromkeys(names):
                if n in existing:
                    self.b.update_where("members", {"name": n}, {"last_seen": now})
                else:
                    self.b.append("members", {"name": n, "first_seen": now, "last_seen": now})

    # ---------- 匯出 ----------
    def export_rows(self, event_id):
        info = self.registrations(event_id)
        ev = info["event"]
        ev_d = parse_date(ev["date"]) or EPOCH.date()
        week_events = [e for e in self.list_events()
                       if ((parse_date(e["date"]) or EPOCH.date()).isocalendar()[:2]
                           == ev_d.isocalendar()[:2])]
        week_regs: dict[str, set] = {}
        for e in week_events:
            actives, _ = self._derive(self._event_regs(e["event_id"]), e["capacity"])
            for r in actives:
                week_regs.setdefault(r["name"], set()).add(e["event_id"])
        rows = []
        for r in info["actives"]:
            rows.append([
                ev["event_id"], ev["date"], ev["start_time"], r["name"],
                "正選" if r["role"] == "confirmed" else f"候補{r['position']}",
                str(len(week_regs.get(r["name"], ()))),
                "是" if r["paid"] else "",
                fmt_dt_short(r["joined_dt"]),
            ])
        return EXPORT_HEADER, rows

    def sync_export_tab(self):
        header, rows_all = list(EXPORT_HEADER), []
        for ev in self.list_events():
            _, rows = self.export_rows(ev["event_id"])
            rows_all.extend(rows)
        self.b.replace_table("匯出", header, rows_all)


# ---------------------------------------------------------------- 配置載入

try:
    import streamlit as st
    _HAS_ST = True
except Exception:  # pragma: no cover - selfcheck 環境無需 streamlit 運行時
    _HAS_ST = False


def _settings_dict() -> dict:
    if not _HAS_ST:
        return {}
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def get_setting(key, default=None):
    v = _settings_dict().get(key)
    if v in (None, ""):
        v = os.environ.get(key)
    return v if v not in (None, "") else default


def _gcp_sa():
    sa = _settings_dict().get("gcp_service_account")
    if sa:
        try:
            return dict(sa)
        except Exception:
            return None
    env = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if env:
        try:
            return json.loads(env)
        except Exception:
            return None
    return None


if _HAS_ST:
    @st.cache_resource(show_spinner=False)
    def _cached_store(cfg):
        kind, sid, sa_json = cfg
        if kind == "sheets":
            return ClubStore(SheetsBackend(sid, json.loads(sa_json))), "sheets"
        return ClubStore(CSVBackend()), "local"
else:
    _cached_store = None


def get_store():
    """回傳 (ClubStore, mode)；mode 為 'sheets' 或 'local'。"""
    if _cached_store is None:
        return ClubStore(CSVBackend()), "local"
    sid = get_setting("SHEET_ID")
    sa = _gcp_sa()
    if sid and sa:
        return _cached_store(("sheets", str(sid), json.dumps(sa, sort_keys=True)))
    return _cached_store(("local", "", ""))
