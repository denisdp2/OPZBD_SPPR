"""SQLite-хранилище пользователей и сессий."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from app.auth.passwords import hash_password, verify_password

Role = Literal["admin", "user"]
SESSION_TTL = timedelta(hours=12)


@dataclass(frozen=True)
class User:
    id: int
    login: str
    role: Role


class AuthStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'user'))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL
                );
                """
            )
            count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                con.execute(
                    "INSERT INTO users (login, password_hash, role) VALUES (?, ?, ?)",
                    ("admin", hash_password("admin"), "admin"),
                )
                con.execute(
                    "INSERT INTO users (login, password_hash, role) VALUES (?, ?, ?)",
                    ("user", hash_password("user"), "user"),
                )

    def authenticate(self, login: str, password: str) -> User | None:
        with self._db() as con:
            row = con.execute(
                "SELECT id, login, role, password_hash FROM users WHERE login = ? COLLATE NOCASE",
                (login.strip(),),
            ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return User(id=row["id"], login=row["login"], role=row["role"])

    def create_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + SESSION_TTL
        with self._db() as con:
            con.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user.id, expires.isoformat()),
            )
        return token

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        now = datetime.now(timezone.utc)
        with self._db() as con:
            row = con.execute(
                """
                SELECT u.id, u.login, u.role, s.expires_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ?
                """,
                (token,),
            ).fetchone()
            if row is None:
                return None
            expires = datetime.fromisoformat(row["expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                con.execute("DELETE FROM sessions WHERE token = ?", (token,))
                return None
        return User(id=row["id"], login=row["login"], role=row["role"])

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self._db() as con:
            con.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
