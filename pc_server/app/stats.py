"""Thống kê cho trang Phân tích và các thẻ KPI."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import db


def _local(iso):
    return datetime.fromisoformat(iso).astimezone()


def overview():
    now = datetime.now().astimezone()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week0 = today0 - timedelta(days=6)
    rows = db.query("SELECT * FROM sessions WHERE entry_at >= ? OR exit_at IS NULL",
                    ((week0.astimezone(timezone.utc)).isoformat(timespec="seconds"),))

    entries_today = revenue_today = 0
    hourly = Counter()          # 24 giờ gần nhất, key = (ngày, giờ)
    revenue_day = defaultdict(int)
    entries_day = defaultdict(int)
    slot_use = Counter()
    durations = []
    since24 = now - timedelta(hours=24)
    for r in rows:
        et = _local(r["entry_at"])
        if et >= today0:
            entries_today += 1
        if et >= since24:
            hourly[et.replace(minute=0, second=0, microsecond=0)] += 1
        entries_day[et.date()] += 1
        slot_use[r["slot_id"]] += 1
        if r["exit_at"]:
            xt = _local(r["exit_at"])
            revenue_day[xt.date()] += r["fee"] or 0
            if xt >= today0:
                revenue_today += r["fee"] or 0
            if r["duration_s"] is not None:
                durations.append(r["duration_s"])

    hours = []
    base = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    for i in range(24):
        h = base + timedelta(hours=i)
        hours.append({"label": f"{h.hour:02d}h", "entries": hourly.get(h, 0)})
    days = []
    for i in range(7):
        d = (week0 + timedelta(days=i)).date()
        days.append({"label": d.strftime("%d/%m"), "revenue": revenue_day.get(d, 0),
                     "entries": entries_day.get(d, 0)})
    peak = max(hours, key=lambda x: x["entries"]) if any(h["entries"] for h in hours) else None
    return {
        "entries_today": entries_today,
        "revenue_today": revenue_today,
        "avg_duration_min": round(sum(durations) / len(durations) / 60, 1) if durations else 0,
        "peak_hour": peak["label"] if peak else None,
        "hourly": hours,
        "daily": days,
        "slot_usage": [{"slot": s, "count": c} for s, c in sorted(slot_use.items())],
    }


def history(page=1, size=15, slot=None, status="", date_from="", date_to=""):
    where, params = ["1=1"], []
    if slot:
        where.append("slot_id=?")
        params.append(slot)
    if status == "active":
        where.append("exit_at IS NULL")
    elif status == "done":
        where.append("exit_at IS NOT NULL")
    if date_from:
        where.append("entry_at >= ?")
        params.append(_day_bound(date_from, False))
    if date_to:
        where.append("entry_at < ?")
        params.append(_day_bound(date_to, True))
    w = " AND ".join(where)
    total = db.one(f"SELECT COUNT(*) c, COALESCE(SUM(fee),0) s FROM sessions WHERE {w}", params)
    rows = db.query(f"SELECT * FROM sessions WHERE {w} ORDER BY entry_at DESC LIMIT ? OFFSET ?",
                    params + [size, (page - 1) * size])
    return {"items": rows, "total": total["c"], "revenue": total["s"], "page": page, "size": size}


def _day_bound(day, plus_one):
    d = datetime.strptime(day, "%Y-%m-%d").astimezone()
    if plus_one:
        d += timedelta(days=1)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")
