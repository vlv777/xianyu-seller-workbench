# -*- coding: utf-8 -*-
"""闲鱼助手 · 存储：会话 / 消息 / 日志（SQLite，纯本地）"""
import sqlite3
import threading
import time
from pathlib import Path

DB_FILE = Path(__file__).resolve().parent / "assistant.db"
_lock = threading.RLock()
_conn = None


def set_db_file(path):
    global DB_FILE
    DB_FILE = Path(path)


def init():
    global _conn
    _conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations(
            cid TEXT PRIMARY KEY,
            buyer_id TEXT,
            buyer_nick TEXT,
            mode TEXT DEFAULT 'auto',
            needs_human INTEGER DEFAULT 0,
            suggested TEXT DEFAULT '',
            last_ts REAL DEFAULT 0,
            last_text TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cid TEXT,
            direction TEXT,
            sender TEXT,
            text TEXT,
            ts REAL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_msg ON messages(cid, direction, ts, text);
        CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            level TEXT,
            text TEXT
        );
        """
    )
    _conn.commit()


def add_message(cid, direction, sender, text, ts=None):
    """返回 True 表示新消息，False 表示重复。"""
    ts = float(ts if ts is not None else time.time())
    with _lock:
        try:
            _conn.execute(
                "INSERT INTO messages(cid, direction, sender, text, ts) VALUES(?,?,?,?,?)",
                (cid, direction, sender, text, ts),
            )
            _conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def remove_message(cid, direction, ts, text):
    with _lock:
        _conn.execute(
            "DELETE FROM messages WHERE cid=? AND direction=? AND ts=? AND text=?",
            (cid, direction, float(ts), text),
        )
        _conn.commit()


def upsert_conversation(cid, buyer_id="", nick="", last_text="", last_ts=None):
    last_ts = float(last_ts if last_ts is not None else time.time())
    with _lock:
        row = _conn.execute("SELECT cid FROM conversations WHERE cid=?", (cid,)).fetchone()
        if row is None:
            _conn.execute(
                "INSERT INTO conversations(cid, buyer_id, buyer_nick, last_ts, last_text) VALUES(?,?,?,?,?)",
                (cid, buyer_id, nick, last_ts, last_text),
            )
        else:
            _conn.execute(
                """UPDATE conversations SET
                   buyer_id=CASE WHEN ?!='' THEN ? ELSE buyer_id END,
                   buyer_nick=CASE WHEN ?!='' THEN ? ELSE buyer_nick END,
                   last_ts=?, last_text=? WHERE cid=?""",
                (buyer_id, buyer_id, nick, nick, last_ts, last_text, cid),
            )
        _conn.commit()


def get_conversations():
    with _lock:
        rows = _conn.execute(
            "SELECT cid, buyer_id, buyer_nick, mode, needs_human, suggested, last_ts, last_text "
            "FROM conversations ORDER BY last_ts DESC"
        ).fetchall()
    return [
        {
            "cid": r[0], "buyer_id": r[1], "buyer_nick": r[2], "mode": r[3],
            "needs_human": bool(r[4]), "suggested": r[5], "last_ts": r[6], "last_text": r[7],
        }
        for r in rows
    ]


def get_conversation(cid):
    with _lock:
        row = _conn.execute(
            "SELECT cid, buyer_id, buyer_nick, mode, needs_human, suggested FROM conversations WHERE cid=?",
            (cid,),
        ).fetchone()
    if not row:
        return None
    return {"cid": row[0], "buyer_id": row[1], "buyer_nick": row[2], "mode": row[3],
            "needs_human": bool(row[4]), "suggested": row[5]}


def set_conversation(cid, mode=None, needs_human=None, suggested=None, nick=None):
    sets, args = [], []
    if mode is not None:
        sets.append("mode=?")
        args.append(mode)
    if needs_human is not None:
        sets.append("needs_human=?")
        args.append(1 if needs_human else 0)
    if suggested is not None:
        sets.append("suggested=?")
        args.append(suggested)
    if nick is not None:
        sets.append("buyer_nick=?")
        args.append(nick)
    if not sets:
        return
    args.append(cid)
    with _lock:
        _conn.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE cid=?", args)
        _conn.commit()


def get_messages(cid, limit=200):
    with _lock:
        rows = _conn.execute(
            "SELECT direction, sender, text, ts FROM messages WHERE cid=? ORDER BY ts DESC LIMIT ?",
            (cid, limit),
        ).fetchall()
    return [
        {"direction": r[0], "sender": r[1], "text": r[2], "ts": r[3]}
        for r in reversed(rows)
    ]


def log(level, text):
    with _lock:
        _conn.execute("INSERT INTO logs(ts, level, text) VALUES(?,?,?)", (time.time(), level, text))
        _conn.execute("DELETE FROM logs WHERE id < (SELECT MAX(id) FROM logs) - 2000")
        _conn.commit()


def get_logs(after_id=0, limit=200):
    with _lock:
        rows = _conn.execute(
            "SELECT id, ts, level, text FROM logs WHERE id>? ORDER BY id ASC LIMIT ?",
            (after_id, limit),
        ).fetchall()
    return [{"id": r[0], "ts": r[1], "level": r[2], "text": r[3]} for r in rows]
