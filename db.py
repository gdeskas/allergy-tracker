"""SQLite persistence for symptoms. Lives on the always-on machine (the Mac);
not committed to the repo. Pollen is handled separately in pollen_store.py."""
import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS symptoms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,          -- ISO datetime with timezone offset
    severity    INTEGER,                -- 1-5 if parsed from the message, else NULL
    notes       TEXT,                   -- the message text
    chat_id     TEXT,
    raw_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_symptoms_ts ON symptoms(ts);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_symptom(ts, severity, notes, chat_id, raw_message):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO symptoms (ts, severity, notes, chat_id, raw_message) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, severity, notes, chat_id, raw_message),
        )
        return cur.lastrowid


def symptoms_between(start_iso, end_iso):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM symptoms WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start_iso, end_iso),
        ).fetchall()
        return [dict(r) for r in rows]
