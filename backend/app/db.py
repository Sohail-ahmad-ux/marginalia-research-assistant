"""Tiny SQLite layer: papers, conversations, messages, eval sets/runs."""
import json
import sqlite3
import threading
import time
import uuid

from .config import settings

_lock = threading.RLock()
_conn = sqlite3.connect(settings.data_dir / "app.db", check_same_thread=False)
_conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id TEXT PRIMARY KEY, filename TEXT, title TEXT, authors TEXT, year INTEGER,
  abstract TEXT, keywords TEXT, pages INTEGER, chunks INTEGER, analysis TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, role TEXT, content TEXT,
  sources TEXT, trace TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS eval_sets (
  id TEXT PRIMARY KEY, paper_ids TEXT, items TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS eval_runs (
  id TEXT PRIMARY KEY, set_id TEXT, config TEXT, results TEXT, created_at TEXT);
"""


def init():
    with _lock:
        _conn.executescript(SCHEMA)
        _conn.commit()


def query(sql, params=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur.lastrowid


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_id():
    return uuid.uuid4().hex[:12]


def loads(s, default=None):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default


def paper_out(row):
    return {**row, "authors": loads(row["authors"], []), "keywords": loads(row["keywords"], []),
            "analysis": loads(row["analysis"], None)}


def history(conv_id, n=6):
    rows = query("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?", (conv_id, n))
    return list(reversed(rows))
