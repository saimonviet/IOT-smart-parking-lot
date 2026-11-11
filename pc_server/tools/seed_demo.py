"""Sinh dữ liệu lịch sử giả (7 ngày) để biểu đồ Phân tích có dữ liệu xem thử.
Chạy: python tools/seed_demo.py   (từ thư mục pc_server, khi server đang TẮT)
"""
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db  # noqa: E402
from app.layout import Layout  # noqa: E402
from app.state import calc_fee  # noqa: E402

db.init()
SLOT_IDS = Layout().slot_ids
now = datetime.now(timezone.utc)
n = 0
for day in range(7, 0, -1):
    for _ in range(random.randint(25, 60)):
        # cao điểm sáng 7-9h và chiều 16-18h
        hour = random.choices(range(6, 22), weights=[3, 8, 9, 6, 4, 4, 5, 4, 4, 7, 9, 8, 5, 3, 2, 1])[0]
        entry = (now - timedelta(days=day)).astimezone().replace(
            hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59)).astimezone(timezone.utc)
        dur = random.randint(10, 6 * 60) * 60
        db.execute("INSERT INTO sessions(slot_id,entry_at,exit_at,duration_s,fee,source) VALUES(?,?,?,?,?,?)",
                   (random.choice(SLOT_IDS), entry.isoformat(timespec="seconds"),
                    (entry + timedelta(seconds=dur)).isoformat(timespec="seconds"), dur, calc_fee(dur), "camera"))
        n += 1
print(f"Đã thêm {n} phiên đỗ xe giả.")
