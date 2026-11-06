"""SQLite canonical store for synthetic Hearth workshop data."""

import json
import os
import sqlite3
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Optional


MIGRATIONS = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('candidate','reinforced','confirmed')),
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lanterns (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            mode TEXT NOT NULL,
            level REAL NOT NULL CHECK(level >= 0 AND level <= 1),
            note TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            author TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS melt_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            due_at REAL
        );
        CREATE TABLE IF NOT EXISTS deletion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            deleted_at REAL NOT NULL,
            reason TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS conversation_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fixture_id TEXT NOT NULL,
            user_text TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            assistant_generation_full TEXT NOT NULL,
            assistant_delivered_text TEXT NOT NULL,
            interrupted INTEGER NOT NULL DEFAULT 0,
            interruption_offset_ms INTEGER,
            created_at REAL NOT NULL
        );
        """,
    ),
    (
        3,
        """
        ALTER TABLE melt_state ADD COLUMN completed_at REAL;
        """,
    ),
    (
        4,
        """
        ALTER TABLE memories RENAME TO memories_v3;
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('candidate','reinforced','confirmed','corrected','retired')),
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        );
        INSERT INTO memories SELECT * FROM memories_v3;
        DROP TABLE memories_v3;
        """,
    ),
]


class Store:
    def __init__(self, path: Path, memories, lanterns, settings):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA secure_delete=ON")
        os.chmod(self.path, 0o600)
        self._default_settings = deepcopy(settings)
        self._migrate()
        self._seed(memories, lanterns, settings)

    def close(self):
        with self._lock:
            self._conn.close()

    def _scrub(self):
        """Fold the WAL into the main file and truncate it so edited or deleted
        text does not linger in -wal frames. Must run outside a transaction."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _migrate(self):
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            applied = {row[0] for row in self._conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                self._conn.executescript(sql)
                self._conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, time.time())
                )

    def _seed(self, memories, lanterns, settings):
        with self._lock, self._conn:
            seeded = self._conn.execute("SELECT value FROM app_meta WHERE key='synthetic_seeded'").fetchone()
            if seeded:
                return
            now = time.time()
            self._conn.executemany(
                "INSERT INTO memories(id,category,text,status,provenance_json,created_at) VALUES(?,?,?,?,?,?)",
                [
                    (
                        item["id"], item["category"], item["text"], item["status"],
                        json.dumps({"source": "synthetic-fixture", "session_id": None}), now,
                    )
                    for item in memories
                ],
            )
            self._conn.executemany(
                "INSERT INTO lanterns(id,name,mode,level,note) VALUES(?,?,?,?,?)",
                [(item["id"], item["name"], item["mode"], item["level"], item["note"]) for item in lanterns],
            )
            self._conn.execute(
                "INSERT INTO notes(id,text,author) VALUES(1,?,?)",
                ("Thurs: less fixing, more listening.", "E"),
            )
            for key, value in settings.items():
                self._conn.execute("INSERT INTO settings(key,value_json) VALUES(?,?)", (key, json.dumps(value)))
            self._conn.execute("INSERT INTO melt_state(singleton,due_at) VALUES(1,NULL)")
            self._conn.execute("INSERT INTO app_meta(key,value) VALUES('synthetic_seeded','1')")

    def workshop(self, include_memory_text: bool = True):
        with self._lock:
            memories = [dict(row) for row in self._conn.execute(
                ("SELECT id,category,text,status FROM memories ORDER BY id" if include_memory_text
                 else "SELECT id,category,status FROM memories ORDER BY id")
            )]
            lanterns = [dict(row) for row in self._conn.execute(
                "SELECT id,name,mode,level,note FROM lanterns ORDER BY id"
            )]
            notes = [dict(row) for row in self._conn.execute(
                "SELECT id,text,author FROM notes ORDER BY id"
            )]
            settings = {
                row["key"]: json.loads(row["value_json"])
                for row in self._conn.execute("SELECT key,value_json FROM settings")
            }
        return {"memories": memories, "lanterns": lanterns, "notes": notes, "settings": settings}

    def patch_settings(self, updates):
        with self._lock, self._conn:
            for key, value in updates.items():
                self._conn.execute(
                    "INSERT INTO settings(key,value_json) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (key, json.dumps(value)),
                )
        return self.workshop(include_memory_text=False)["settings"]

    def add_memory(self, category: str, text: str, status: str = "candidate", provenance: Optional[dict] = None):
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO memories(category,text,status,provenance_json,created_at) VALUES(?,?,?,?,?)",
                (category, text, status, json.dumps(provenance or {}), time.time()),
            )
            return {"id": cursor.lastrowid, "category": category, "text": text, "status": status}

    def memories_for_prompt(self, limit: int = 60):
        """Memories the companion may use: newest first, never retired, never synthetic fixtures."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,category,text,status FROM memories WHERE status!='retired' "
                "AND COALESCE(json_extract(provenance_json,'$.source'),'')!='synthetic-fixture' "
                "ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def reinforce_memory(self, memory_id: int):
        """A candidate that comes up again becomes reinforced; anything she already kept stays as it is."""
        with self._lock, self._conn:
            row = self._conn.execute("SELECT id,category,text,status FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                return None
            status = "reinforced" if row["status"] == "candidate" else row["status"]
            if status != row["status"]:
                self._conn.execute("UPDATE memories SET status=? WHERE id=?", (status, memory_id))
            result = dict(row)
            result["status"] = status
            return result

    def keep_memory(self, memory_id: int):
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id,category,text,status FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
            if not row:
                return None
            new_status = "confirmed" if row["status"] in {"candidate", "reinforced", "corrected"} else row["status"]
            self._conn.execute("UPDATE memories SET status=? WHERE id=?", (new_status, memory_id))
            result = dict(row)
            result["status"] = new_status
            return result

    def update_memory(self, memory_id: int, updates: dict):
        clean = {key: value for key, value in updates.items() if key in {"text", "status"}}
        if "text" in clean and "status" not in clean:
            clean["status"] = "corrected"
        if not clean:
            return None
        assignments = ",".join(key + "=?" for key in clean)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE memories SET " + assignments + " WHERE id=?",
                list(clean.values()) + [memory_id],
            )
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT id,category,text,status FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
            result = dict(row)
        if "text" in clean:
            self._scrub()
        return result

    def delete_memory(self, memory_id: int, reason: str = "user_request") -> bool:
        with self._lock, self._conn:
            found = self._conn.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not found:
                return False
            self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            self._log_delete("memory", str(memory_id), reason)
        self._scrub()
        return True

    def create_note(self, text: str, author: str):
        with self._lock, self._conn:
            cursor = self._conn.execute("INSERT INTO notes(text,author) VALUES(?,?)", (text, author))
            return {"id": cursor.lastrowid, "text": text, "author": author}

    def update_note(self, note_id: int, text: str):
        with self._lock, self._conn:
            cursor = self._conn.execute("UPDATE notes SET text=? WHERE id=?", (text, note_id))
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute("SELECT id,text,author FROM notes WHERE id=?", (note_id,)).fetchone()
            result = dict(row)
        self._scrub()
        return result

    def delete_note(self, note_id: int) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
            if cursor.rowcount == 0:
                return False
            self._log_delete("note", str(note_id), "user_request")
        self._scrub()
        return True

    def create_lantern(self, name: str = ""):
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO lanterns(name,mode,level,note) VALUES(?,?,?,?)",
                (name, "unlit", 0.0, "a new lantern"),
            )
            return {"id": cursor.lastrowid, "name": name, "mode": "unlit", "level": 0.0, "note": "a new lantern"}

    def update_lantern(self, lantern_id: int, updates: dict):
        allowed = {"name", "mode", "level", "note"}
        clean = {key: value for key, value in updates.items() if key in allowed}
        if not clean:
            return None
        assignments = ",".join(key + "=?" for key in clean)
        values = list(clean.values()) + [lantern_id]
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE lanterns SET " + assignments + " WHERE id=?", values
            )
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT id,name,mode,level,note FROM lanterns WHERE id=?", (lantern_id,)
            ).fetchone()
            result = dict(row)
        if "name" in clean:
            self._scrub()
        return result

    def delete_lantern(self, lantern_id: int) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM lanterns WHERE id=?", (lantern_id,))
            if cursor.rowcount == 0:
                return False
            self._log_delete("lantern", str(lantern_id), "user_request")
        self._scrub()
        return True

    def melt_state(self):
        with self._lock:
            row = self._conn.execute(
                "SELECT due_at,completed_at FROM melt_state WHERE singleton=1"
            ).fetchone()
            due_at = row["due_at"] if row else None
            completed_at = row["completed_at"] if row else None
            return {
                "state": "scheduled" if due_at else ("completed" if completed_at else "none"),
                "due_at": due_at,
                "completed_at": completed_at,
            }

    def schedule_melt(self, due_at: float):
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT due_at FROM melt_state WHERE singleton=1"
            ).fetchone()
            if current and current["due_at"] is not None:
                return None
            self._conn.execute(
                "UPDATE melt_state SET due_at=?,completed_at=NULL WHERE singleton=1", (due_at,)
            )
        return self.melt_state()

    def cancel_melt(self):
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT due_at FROM melt_state WHERE singleton=1"
            ).fetchone()
            if current and current["due_at"] is not None and current["due_at"] <= time.time():
                return None
            self._conn.execute("UPDATE melt_state SET due_at=NULL WHERE singleton=1")
        return {"state": "none", "due_at": None, "completed_at": None}

    def advance_melt(self) -> bool:
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT due_at FROM melt_state WHERE singleton=1"
            ).fetchone()
            if not current or current["due_at"] is None:
                return False
            self._conn.execute(
                "UPDATE melt_state SET due_at=? WHERE singleton=1", (time.time() - 1,)
            )
        return self.execute_due_melt()

    def execute_due_melt(self) -> bool:
        with self._lock:
            with self._conn:
                row = self._conn.execute("SELECT due_at FROM melt_state WHERE singleton=1").fetchone()
                if not row or row["due_at"] is None or row["due_at"] > time.time():
                    return False
                for table, entity_type in (
                    ("memories", "memory"),
                    ("lanterns", "lantern"),
                    ("notes", "note"),
                    ("conversation_ledger", "conversation_turn"),
                ):
                    ids = [str(item[0]) for item in self._conn.execute("SELECT id FROM " + table)]
                    self._conn.execute("DELETE FROM " + table)
                    for entity_id in ids:
                        self._log_delete(entity_type, entity_id, "scheduled_melt")
                self._conn.execute("DELETE FROM settings")
                for key, value in self._default_settings.items():
                    self._conn.execute(
                        "INSERT INTO settings(key,value_json) VALUES(?,?)", (key, json.dumps(value))
                    )
                self._log_delete("settings", "all", "scheduled_melt")
                completed_at = time.time()
                self._conn.execute(
                    "UPDATE melt_state SET due_at=NULL,completed_at=? WHERE singleton=1",
                    (completed_at,),
                )
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")
            return True

    def deletion_log(self):
        with self._lock:
            return [dict(row) for row in self._conn.execute(
                "SELECT entity_type,entity_id,deleted_at,reason FROM deletion_log ORDER BY id"
            )]

    def privacy_counts(self):
        with self._lock:
            kept = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            return {"kept_count": kept}

    def record_turn(self, fixture_id: str, user_text: str, risk_level: str, assistant_text: str):
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO conversation_ledger(
                    fixture_id,user_text,risk_level,assistant_generation_full,
                    assistant_delivered_text,interrupted,interruption_offset_ms,created_at
                ) VALUES(?,?,?,?,?,0,NULL,?)
                """,
                (fixture_id, user_text, risk_level, assistant_text, assistant_text, time.time()),
            )
            return cursor.lastrowid

    def recent_turns(self, fixture_id: str, limit: int = 4):
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_text,assistant_delivered_text FROM conversation_ledger WHERE fixture_id=? ORDER BY id DESC LIMIT ?",
                (fixture_id, limit),
            ).fetchall()
        return [{"user": row[0], "assistant": row[1]} for row in reversed(rows)]

    def ledger(self):
        with self._lock:
            return [dict(row) for row in self._conn.execute(
                """
                SELECT id,fixture_id,user_text,risk_level,assistant_generation_full,
                       assistant_delivered_text,interrupted,interruption_offset_ms,created_at
                FROM conversation_ledger ORDER BY id
                """
            )]

    def _log_delete(self, entity_type: str, entity_id: str, reason: str):
        self._conn.execute(
            "INSERT INTO deletion_log(entity_type,entity_id,deleted_at,reason) VALUES(?,?,?,?)",
            (entity_type, entity_id, time.time(), reason),
        )

