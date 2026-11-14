"""SQLite: tài khoản, phiên đỗ xe (lịch sử) và nhật ký sự kiện."""
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL,
    entry_at TEXT NOT NULL,
    exit_at TEXT,
    duration_s INTEGER,
    fee INTEGER,
    source TEXT DEFAULT 'camera'
);
CREATE INDEX IF NOT EXISTS idx_sessions_entry ON sessions(entry_at);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    slot_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
-- Lượt xe qua cổng (theo biển số): vào cổng -> ra cổng. Phí thu ở cổng ra tính theo bảng này.
CREATE TABLE IF NOT EXISTS visits(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT NOT NULL,
    entry_at TEXT NOT NULL,
    exit_at TEXT,
    slot_id INTEGER,
    entry_img TEXT,
    exit_img TEXT,
    entry_conf REAL,
    exit_conf REAL,
    duration_s INTEGER,
    fee INTEGER,
    status TEXT NOT NULL DEFAULT 'inside',   -- inside | done
    entry_mode TEXT DEFAULT 'auto',          -- auto (camera) | manual (quản lý nhập tay)
    exit_mode TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_visits_plate ON visits(plate, status);
CREATE INDEX IF NOT EXISTS idx_visits_entry ON visits(entry_at);
-- Mọi lần đọc biển ở cổng (kể cả bị từ chối) để tra soát
CREATE TABLE IF NOT EXISTS plate_reads(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    gate TEXT NOT NULL,
    plate TEXT,
    guess TEXT,
    conf REAL,
    image TEXT,
    result TEXT NOT NULL,                     -- allowed | denied_unread | denied_duplicate | denied_nomatch | denied_full
    visit_id INTEGER,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_reads_ts ON plate_reads(ts);
"""

# cột thêm vào bảng có sẵn (DB cũ): (bảng, cột, kiểu)
MIGRATIONS = [("sessions", "plate", "TEXT"), ("sessions", "visit_id", "INTEGER"),
              ("plate_reads", "read_ms", "INTEGER"), ("plate_reads", "total_ms", "INTEGER")]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init():
    global _conn
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            cols = {r[1] for r in _conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        _conn.commit()


def execute(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur.lastrowid


def query(sql, params=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None
