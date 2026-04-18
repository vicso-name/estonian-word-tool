"""
db.py — SQLite persistence layer for Eesti Sõnad.
Schema is designed with user_id so auth can be added later without migration.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "eesti.db"))

WORD_COLUMNS = [
    "lemma", "part_of_speech", "translation", "level",
    "nimetav", "omastav", "osastav",
    "ma_inf", "da_inf", "extra_form",
    "pres_3sg", "past_3sg", "nud_form", "imper_2sg",
    "note", "status", "error", "source",
]


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS word_lists (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                user_id    INTEGER NOT NULL DEFAULT 1,
                created_at TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS list_words (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id        INTEGER NOT NULL REFERENCES word_lists(id) ON DELETE CASCADE,
                lemma          TEXT    NOT NULL DEFAULT '',
                part_of_speech TEXT    NOT NULL DEFAULT 'OTHER',
                translation    TEXT    NOT NULL DEFAULT '',
                level          TEXT    NOT NULL DEFAULT '',
                nimetav        TEXT    NOT NULL DEFAULT '',
                omastav        TEXT    NOT NULL DEFAULT '',
                osastav        TEXT    NOT NULL DEFAULT '',
                ma_inf         TEXT    NOT NULL DEFAULT '',
                da_inf         TEXT    NOT NULL DEFAULT '',
                extra_form     TEXT    NOT NULL DEFAULT '',
                pres_3sg       TEXT    NOT NULL DEFAULT '',
                past_3sg       TEXT    NOT NULL DEFAULT '',
                nud_form       TEXT    NOT NULL DEFAULT '',
                imper_2sg      TEXT    NOT NULL DEFAULT '',
                note           TEXT    NOT NULL DEFAULT '',
                status         TEXT    NOT NULL DEFAULT 'ok',
                error          TEXT    NOT NULL DEFAULT '',
                source         TEXT    NOT NULL DEFAULT 'ekilex',
                sort_order     INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (list_id, lemma)
            );
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── LISTS ────────────────────────────────────────────────────

def get_all_lists(user_id: int = 1) -> List[Dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("""
            SELECT
                wl.id,
                wl.name,
                wl.created_at,
                wl.updated_at,
                COUNT(lw.id)                                   AS word_count,
                SUM(CASE WHEN lw.status = 'ok'    THEN 1 END) AS ok_count,
                SUM(CASE WHEN lw.status = 'error' THEN 1 END) AS error_count
            FROM word_lists wl
            LEFT JOIN list_words lw ON lw.list_id = wl.id
            WHERE wl.user_id = ?
            GROUP BY wl.id
            ORDER BY wl.updated_at DESC
        """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


def get_list(list_id: int, user_id: int = 1) -> Optional[Dict[str, Any]]:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM word_lists WHERE id = ? AND user_id = ?",
            (list_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def create_list(name: str, user_id: int = 1) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO word_lists (name, user_id) VALUES (?, ?)",
            (name.strip(), user_id),
        )
    return cur.lastrowid


def rename_list(list_id: int, name: str, user_id: int = 1) -> None:
    with get_db() as db:
        db.execute(
            "UPDATE word_lists SET name = ?, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
            (name.strip(), list_id, user_id),
        )


def delete_list(list_id: int, user_id: int = 1) -> None:
    with get_db() as db:
        db.execute(
            "DELETE FROM word_lists WHERE id = ? AND user_id = ?",
            (list_id, user_id),
        )


# ── WORDS ────────────────────────────────────────────────────

def get_words(list_id: int) -> List[Dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM list_words WHERE list_id = ? ORDER BY sort_order, id",
            (list_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_words(list_id: int, words: List[Dict[str, Any]]) -> None:
    """Insert or update (on duplicate lemma) words into a list."""
    with get_db() as db:
        # Get current max sort_order
        row = db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM list_words WHERE list_id = ?",
            (list_id,),
        ).fetchone()
        next_order = (row[0] or 0) + 1

        for i, word in enumerate(words):
            db.execute(
                """
                INSERT INTO list_words
                    (list_id, lemma, part_of_speech, translation, level,
                     nimetav, omastav, osastav, ma_inf, da_inf, extra_form,
                     pres_3sg, past_3sg, nud_form, imper_2sg,
                     note, status, error, source, sort_order)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (list_id, lemma) DO UPDATE SET
                    part_of_speech = excluded.part_of_speech,
                    translation    = excluded.translation,
                    level          = excluded.level,
                    nimetav        = excluded.nimetav,
                    omastav        = excluded.omastav,
                    osastav        = excluded.osastav,
                    ma_inf         = excluded.ma_inf,
                    da_inf         = excluded.da_inf,
                    extra_form     = excluded.extra_form,
                    pres_3sg       = excluded.pres_3sg,
                    past_3sg       = excluded.past_3sg,
                    nud_form       = excluded.nud_form,
                    imper_2sg      = excluded.imper_2sg,
                    note           = excluded.note,
                    status         = excluded.status,
                    error          = excluded.error,
                    source         = excluded.source
                """,
                (
                    list_id,
                    word.get("lemma", ""),
                    word.get("part_of_speech", "OTHER"),
                    word.get("translation", ""),
                    word.get("level", ""),
                    word.get("nimetav", ""),
                    word.get("omastav", ""),
                    word.get("osastav", ""),
                    word.get("ma_inf", ""),
                    word.get("da_inf", ""),
                    word.get("extra_form", ""),
                    word.get("pres_3sg", ""),
                    word.get("past_3sg", ""),
                    word.get("nud_form", ""),
                    word.get("imper_2sg", ""),
                    word.get("note", ""),
                    word.get("status", "ok"),
                    word.get("error", ""),
                    word.get("source", "ekilex"),
                    next_order + i,
                ),
            )

        db.execute(
            "UPDATE word_lists SET updated_at = datetime('now') WHERE id = ?",
            (list_id,),
        )


def delete_word(word_id: int, list_id: int) -> bool:
    with get_db() as db:
        cur = db.execute(
            "DELETE FROM list_words WHERE id = ? AND list_id = ?",
            (word_id, list_id),
        )
        if cur.rowcount:
            db.execute(
                "UPDATE word_lists SET updated_at = datetime('now') WHERE id = ?",
                (list_id,),
            )
    return cur.rowcount > 0


EDITABLE_FIELDS = {"translation", "note", "nimetav", "omastav", "osastav",
                   "ma_inf", "da_inf", "pres_3sg", "past_3sg", "nud_form",
                   "imper_2sg", "extra_form", "level"}


def update_word_field(word_id: int, list_id: int, field: str, value: str) -> bool:
    if field not in EDITABLE_FIELDS:
        return False
    with get_db() as db:
        cur = db.execute(
            f"UPDATE list_words SET {field} = ? WHERE id = ? AND list_id = ?",
            (value.strip(), word_id, list_id),
        )
        if cur.rowcount:
            db.execute(
                "UPDATE word_lists SET updated_at = datetime('now') WHERE id = ?",
                (list_id,),
            )
    return cur.rowcount > 0