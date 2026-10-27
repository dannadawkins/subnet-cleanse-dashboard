import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import config

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = Path(config("SUBNET_CLEANSE_DB", default="") or PROJECT_ROOT / "estado_subnets.db")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS estado (
            subnet TEXT PRIMARY KEY,
            estado TEXT,
            nota TEXT,
            ultima_actualizacion TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS site_suggestions (
            subnet TEXT PRIMARY KEY,
            suggested_site TEXT,
            confidence TEXT,
            candidates TEXT,
            evidence TEXT,
            checked_at TEXT
        )
        """
    )
    return connection


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_statuses() -> list[dict]:
    with transaction() as connection:
        rows = connection.execute("SELECT subnet, estado, nota FROM estado").fetchall()
    return [dict(row) for row in rows]


def save_status(subnet: str, status: str, notes: str) -> None:
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO estado (subnet, estado, nota, ultima_actualizacion)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(subnet) DO UPDATE SET
                estado=excluded.estado,
                nota=excluded.nota,
                ultima_actualizacion=excluded.ultima_actualizacion
            """,
            (subnet, status, notes),
        )


def get_suggestions(subnets: list[str] | None = None) -> list[dict]:
    with transaction() as connection:
        if subnets is None:
            rows = connection.execute(
                "SELECT subnet, suggested_site, confidence, candidates, evidence FROM site_suggestions"
            ).fetchall()
        elif not subnets:
            return []
        else:
            placeholders = ",".join("?" for _ in subnets)
            rows = connection.execute(
                f"""
                SELECT subnet, suggested_site, confidence, candidates, evidence
                FROM site_suggestions WHERE subnet IN ({placeholders})
                """,
                subnets,
            ).fetchall()
    return [dict(row) for row in rows]


def save_suggestion(result: dict) -> None:
    candidates = ", ".join(f"{site} ({score:g})" for site, score in result.get("candidates", {}).items())
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO site_suggestions
                (subnet, suggested_site, confidence, candidates, evidence, checked_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(subnet) DO UPDATE SET
                suggested_site=excluded.suggested_site,
                confidence=excluded.confidence,
                candidates=excluded.candidates,
                evidence=excluded.evidence,
                checked_at=excluded.checked_at
            """,
            (
                result["subnet"],
                result.get("suggested_site_id") or "",
                result.get("confidence", ""),
                candidates,
                "; ".join(result.get("evidence", [])),
            ),
        )


def clear_suggestion(subnet: str) -> None:
    with transaction() as connection:
        connection.execute("DELETE FROM site_suggestions WHERE subnet = ?", (subnet,))
