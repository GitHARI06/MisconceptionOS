"""Small PostgreSQL-backed account service for the student application."""

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
import uuid
from typing import Any, Dict, Optional

from .config import settings

logger = logging.getLogger("misconception_os.auth")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountService:
    ITERATIONS = 310_000
    TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30

    def __init__(self):
        self.database_url = settings.DATABASE_URL
        self._psycopg = None
        self._dict_row = None
        if self.database_url:
            try:
                import psycopg
                from psycopg.rows import dict_row
                self._psycopg = psycopg
                self._dict_row = dict_row
                self.ensure_schema()
            except Exception as exc:
                logger.warning("Account storage is unavailable: %s", exc)
                self._psycopg = None

    @property
    def enabled(self) -> bool:
        return bool(self.database_url and self._psycopg)

    def _connect(self):
        if not self.enabled:
            raise RuntimeError("PostgreSQL account storage is not configured")
        return self._psycopg.connect(self.database_url, row_factory=self._dict_row)

    def ensure_schema(self):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS student_accounts (
                        id TEXT PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        class_level TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, AccountService.ITERATIONS)
        return f"pbkdf2_sha256${AccountService.ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            salt = base64.urlsafe_b64decode(salt_b64.encode())
            expected = base64.urlsafe_b64decode(digest_b64.encode())
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def public_user(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "class_level": row["class_level"],
        }

    def create_account(self, username: str, email: str, password: str, class_level: str) -> Dict[str, Any]:
        username = username.strip()
        email = email.strip().lower()
        class_level = class_level.strip()
        if len(username) < 2 or len(username) > 40 or len(password) < 8 or len(password) > 256 or not class_level:
            raise ValueError("Username (2-40 characters), class, and a password of at least 8 characters are required.")
        if not EMAIL_RE.match(email):
            raise ValueError("Please enter a valid email address.")
        # Usernames and emails are matched case-insensitively at login, so
        # they must also be unique case-insensitively.
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM student_accounts WHERE lower(username) = lower(%s) OR lower(email) = lower(%s) "
                    "OR lower(username) = lower(%s) OR lower(email) = lower(%s) LIMIT 1",
                    (username, email, email, username),
                )
                if cursor.fetchone():
                    raise ValueError("That username or email is already registered.")
        row = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email,
            "password_hash": self._hash_password(password),
            "class_level": class_level,
        }
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO student_accounts
                        (id, username, email, password_hash, class_level)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id, username, email, class_level""",
                        (row["id"], row["username"], row["email"], row["password_hash"], row["class_level"]),
                    )
                    return cursor.fetchone()
        except Exception as exc:
            if "duplicate key" in str(exc).lower() or "unique" in str(exc).lower():
                raise ValueError("That username or email is already registered.") from exc
            raise

    def authenticate(self, identity: str, password: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT id, username, email, password_hash, class_level
                    FROM student_accounts WHERE lower(username) = lower(%s) OR lower(email) = lower(%s)""",
                    (identity.strip(), identity.strip()),
                )
                row = cursor.fetchone()
        if not row or not self._verify_password(password, row["password_hash"]):
            return None
        return self.public_user(row)

    def issue_token(self, user: Dict[str, Any]) -> str:
        expires = int(time.time()) + self.TOKEN_TTL_SECONDS
        payload = f"{user['id']}:{expires}"
        signature = hmac.new(settings.AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()

    def user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            decoded = base64.urlsafe_b64decode(token.encode()).decode()
            user_id, expires, signature = decoded.split(":", 2)
            payload = f"{user_id}:{expires}"
            expected = hmac.new(settings.AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected) or int(expires) < int(time.time()):
                return None
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT id, username, email, class_level FROM student_accounts WHERE id = %s", (user_id,))
                    row = cursor.fetchone()
            return self.public_user(row) if row else None
        except Exception:
            return None


account_service = AccountService()
