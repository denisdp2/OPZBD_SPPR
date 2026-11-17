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
                CREATE TABLE IF NOT EXISTS drafts (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    data TEXT NOT NULL
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

    def register(self, login: str, password: str) -> User | None:
        password_hash = hash_password(password)
        with self._db() as con:
            row = con.execute(
                "INSERT INTO users (login, password_hash, role) VALUES (?, ?, 'user') "
                "ON CONFLICT(login) DO NOTHING RETURNING id",
                (login, password_hash),
            ).fetchone()
        return User(id=row["id"], login=login, role="user") if row else None

    def list_users(self) -> list[User]:
        with self._db() as con:
            return [
                User(id=row["id"], login=row["login"], role=row["role"])
                for row in con.execute("SELECT id, login, role FROM users ORDER BY login")
            ]

    def update_profile(
        self, user: User, login: str, current_password: str, new_password: str | None
    ) -> bool:
        with self._db() as con:
            row = con.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user.id,)
            ).fetchone()
            if row is None or not verify_password(current_password, row["password_hash"]):
                return False
            password_hash = hash_password(new_password) if new_password else row["password_hash"]
            updated = con.execute(
                "UPDATE users SET login = ?, password_hash = ? WHERE id = ? AND password_hash = ?",
                (login, password_hash, user.id, row["password_hash"]),
            )
            if updated.rowcount and new_password:
                con.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))
            return updated.rowcount > 0

    def read_draft(self, user_id: int) -> str | None:
        with self._db() as con:
            row = con.execute("SELECT data FROM drafts WHERE user_id = ?", (user_id,)).fetchone()
        return row["data"] if row else None

    def save_draft(self, user_id: int, data: str) -> None:
        with self._db() as con:
            con.execute(
                "INSERT INTO drafts (user_id, data) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
                (user_id, data),
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
