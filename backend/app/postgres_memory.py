"""PostgreSQL persistence for concept-scoped learner conversations."""

import json
import logging
from typing import Any, Dict, List, Optional

from .config import settings

logger = logging.getLogger("misconception_os.postgres_memory")


class PostgresConceptMemory:
    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or settings.DATABASE_URL
        self.enabled = bool(self.database_url)
        self._psycopg = None
        self._dict_row = None
        if self.enabled:
            try:
                import psycopg
                from psycopg.rows import dict_row
                self._psycopg = psycopg
                self._dict_row = dict_row
                self.ensure_schema()
            except Exception as exc:
                logger.warning("PostgreSQL concept memory is unavailable: %s", exc)
                self.enabled = False

    def _connect(self):
        if not self.enabled or not self._psycopg:
            return None
        return self._psycopg.connect(self.database_url, row_factory=self._dict_row)

    def ensure_schema(self):
        connection = self._connect()
        if connection is None:
            return
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS concept_conversations (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        concept_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        user_text TEXT NOT NULL,
                        tutor_text TEXT NOT NULL,
                        lesson_phase TEXT NOT NULL,
                        intervention_tier TEXT NOT NULL,
                        diagnostic JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_concept_conversations_session_concept
                    ON concept_conversations (session_id, concept_id, created_at)
                    """
                )

    def append_turn(
        self,
        session_id: str,
        concept_id: str,
        topic: str,
        user_text: str,
        tutor_text: str,
        lesson_phase: str,
        intervention_tier: str,
        diagnostic: Dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        connection = self._connect()
        if connection is None:
            return
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO concept_conversations
                    (session_id, concept_id, topic, user_text, tutor_text,
                     lesson_phase, intervention_tier, diagnostic)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        session_id, concept_id, topic, user_text, tutor_text,
                        lesson_phase, intervention_tier, json.dumps(diagnostic),
                    ),
                )

    def get_history(self, session_id: str, concept_id: str, limit: int = 12) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        connection = self._connect()
        if connection is None:
            return []
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_text, tutor_text, lesson_phase, intervention_tier,
                           diagnostic, created_at
                    FROM concept_conversations
                    WHERE session_id = %s AND concept_id = %s
                    ORDER BY created_at ASC, id ASC
                    LIMIT %s
                    """,
                    (session_id, concept_id, limit),
                )
                rows = cursor.fetchall()
        return [
            {
                "user": row["user_text"],
                "tutor": row["tutor_text"],
                "tier": row["intervention_tier"],
                "phase": row["lesson_phase"],
                "diagnostic": row["diagnostic"],
                "timestamp": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def get_conversations(self, session_id: str) -> Dict[str, List[Dict[str, Any]]]:
        if not self.enabled:
            return {}
        connection = self._connect()
        if connection is None:
            return {}
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT concept_id, topic, user_text, tutor_text, lesson_phase,
                           intervention_tier, diagnostic, created_at
                    FROM concept_conversations
                    WHERE session_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id,),
                )
                rows = cursor.fetchall()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["concept_id"], []).append({
                "topic": row["topic"],
                "user": row["user_text"],
                "tutor": row["tutor_text"],
                "phase": row["lesson_phase"],
                "tier": row["intervention_tier"],
                "diagnostic": row["diagnostic"],
                "timestamp": row["created_at"].isoformat(),
            })
        return grouped


concept_memory = PostgresConceptMemory()
