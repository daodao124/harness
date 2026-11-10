
import asyncio
import sqlite3
import uuid

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "incidents.db"
)


class IdempotencyConflictError(Exception):
    """Same key was used with different incident data."""


class IncidentInput(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10)
    severity: Literal["low", "medium", "high", "critical"]


class IncidentResult(BaseModel):
    incident_id: str
    title: str
    description: str
    severity: str
    status: str
    created_at: datetime


def initialize_database(conn: sqlite3.Connection):
    """Create or migrate the incidents table."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            idempotency_key TEXT
        )
    """)

    # Migration for the database created in earlier steps
    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(incidents)"
        )
    }

    if "idempotency_key" not in columns:
        conn.execute(
            "ALTER TABLE incidents "
            "ADD COLUMN idempotency_key TEXT"
        )

    # Enforce uniqueness at the database level
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_incidents_idempotency_key
        ON incidents(idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def save_incident(
    data: IncidentInput,
    idempotency_key: str,
) -> IncidentResult:

    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > 256
    ):
        raise ValueError("Invalid idempotency_key")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with closing(
        sqlite3.connect(DB_PATH, timeout=10)
    ) as conn:

        conn.row_factory = sqlite3.Row

        with conn:
            # Lock writes during check + insert
            conn.execute("BEGIN IMMEDIATE")

            initialize_database(conn)

            # Check whether this request already succeeded
            existing = conn.execute(
                """
                SELECT *
                FROM incidents
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()

            if existing is not None:

                # Prevent reusing the same key for new data
                if (
                    existing["title"] != data.title
                    or existing["description"] != data.description
                    or existing["severity"] != data.severity
                ):
                    raise IdempotencyConflictError(
                        "Idempotency key was already used "
                        "for a different incident."
                    )

                # Return the original incident
                return IncidentResult.model_validate(
                    dict(existing)
                )

            # Create new incident only if key is new
            incident = IncidentResult(
                incident_id=str(uuid.uuid4()),
                title=data.title,
                description=data.description,
                severity=data.severity,
                status="open",
                created_at=datetime.now(timezone.utc),
            )

            conn.execute(
                """
                INSERT INTO incidents (
                    incident_id,
                    title,
                    description,
                    severity,
                    status,
                    created_at,
                    idempotency_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.incident_id,
                    incident.title,
                    incident.description,
                    incident.severity,
                    incident.status,
                    incident.created_at.isoformat(),
                    idempotency_key,
                ),
            )

            return incident


async def create_incident(
    title: str,
    description: str,
    severity: str,
    *,
    idempotency_key: str,
) -> IncidentResult:

    data = IncidentInput.model_validate({
        "title": title,
        "description": description,
        "severity": severity,
    })

    return await asyncio.to_thread(
        save_incident,
        data,
        idempotency_key,
    )
