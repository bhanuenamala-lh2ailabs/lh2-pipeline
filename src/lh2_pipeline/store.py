"""SQLite data store: migrations, typed upserts, cache get/set.

DEVIATION NOTE (flagged to the human): the BUILD SPEC lists DuckDB *or* SQLite
("SQLite fine if simpler"). We use stdlib ``sqlite3`` — zero install risk on
Python 3.14, and the access surface here (upsert + cache + cursor) is small
enough that swapping to DuckDB later is a localized change in this file only.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .models import (
    SCHEMA_SQL,
    CacheEntry,
    Company,
    Person,
    RawListing,
    utcnow,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class Store:
    """Thin typed wrapper over a SQLite connection."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

    # -- lifecycle --------------------------------------------------------- #
    def init_db(self) -> None:
        """Idempotently create all tables/indexes, then run column migrations."""
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created. ``CREATE TABLE IF
        NOT EXISTS`` never alters an existing table, so new columns are added here
        idempotently (ignoring the 'duplicate column' error on already-migrated DBs)."""
        migrations = [
            ("people", "email", "TEXT"),
            ("people", "email_source", "TEXT"),
        ]
        for table, col, coltype in migrations:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- raw_listings ------------------------------------------------------ #
    def insert_raw_listing(self, row: RawListing) -> None:
        """Insert a scraped listing. Idempotent on (source, source_url, company_name)."""
        with self.tx() as c:
            c.execute(
                """
                INSERT OR IGNORE INTO raw_listings
                  (source, source_url, scraped_at, company_name, website_raw,
                   city, founded_year_raw, size_raw, segment_raw, extra_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.source,
                    row.source_url,
                    _iso(row.scraped_at),
                    row.company_name,
                    row.website_raw,
                    row.city,
                    row.founded_year_raw,
                    row.size_raw,
                    row.segment_raw,
                    _json(row.extra_json),
                ),
            )

    def iter_raw_listings(self) -> Iterator[RawListing]:
        cur = self._conn.execute("SELECT * FROM raw_listings ORDER BY id")
        for r in cur:
            yield RawListing(
                id=r["id"],
                source=r["source"],
                source_url=r["source_url"],
                scraped_at=datetime.fromisoformat(r["scraped_at"]),
                company_name=r["company_name"] or "",
                website_raw=r["website_raw"],
                city=r["city"],
                founded_year_raw=r["founded_year_raw"],
                size_raw=r["size_raw"],
                segment_raw=r["segment_raw"],
                extra_json=json.loads(r["extra_json"]) if r["extra_json"] else {},
            )

    # -- companies --------------------------------------------------------- #
    def upsert_company(self, co: Company) -> None:
        """Insert or update a company by domain. Preserves created_at on update."""
        co.updated_at = utcnow()
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO companies
                  (domain, company_name, website, city, state, hq_country,
                   founded_year, founded_source, size_band, size_source, segment,
                   status, sources_json, gate_pass, gate_reason, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(domain) DO UPDATE SET
                   company_name=excluded.company_name,
                   website=excluded.website,
                   city=excluded.city,
                   state=excluded.state,
                   hq_country=excluded.hq_country,
                   founded_year=excluded.founded_year,
                   founded_source=excluded.founded_source,
                   size_band=excluded.size_band,
                   size_source=excluded.size_source,
                   segment=excluded.segment,
                   status=excluded.status,
                   sources_json=excluded.sources_json,
                   gate_pass=excluded.gate_pass,
                   gate_reason=excluded.gate_reason,
                   updated_at=excluded.updated_at
                """,
                (
                    co.domain,
                    co.company_name,
                    co.website,
                    co.city,
                    co.state,
                    co.hq_country,
                    co.founded_year,
                    co.founded_source,
                    co.size_band,
                    co.size_source,
                    co.segment,
                    co.status,
                    _json(co.sources_json),
                    int(co.gate_pass),
                    co.gate_reason,
                    _iso(co.created_at),
                    _iso(co.updated_at),
                ),
            )

    def get_company(self, domain: str) -> Optional[Company]:
        r = self._conn.execute(
            "SELECT * FROM companies WHERE domain = ?", (domain,)
        ).fetchone()
        return self._row_to_company(r) if r else None

    def iter_companies(self, gate_pass: Optional[bool] = None) -> Iterator[Company]:
        if gate_pass is None:
            cur = self._conn.execute("SELECT * FROM companies ORDER BY domain")
        else:
            cur = self._conn.execute(
                "SELECT * FROM companies WHERE gate_pass = ? ORDER BY domain",
                (int(gate_pass),),
            )
        for r in cur:
            yield self._row_to_company(r)

    @staticmethod
    def _row_to_company(r: sqlite3.Row) -> Company:
        return Company(
            domain=r["domain"],
            company_name=r["company_name"] or "",
            website=r["website"],
            city=r["city"],
            state=r["state"],
            hq_country=r["hq_country"],
            founded_year=r["founded_year"],
            founded_source=r["founded_source"],
            size_band=r["size_band"],
            size_source=r["size_source"],
            segment=r["segment"],
            status=r["status"] or "",
            sources_json=json.loads(r["sources_json"]) if r["sources_json"] else [],
            gate_pass=bool(r["gate_pass"]),
            gate_reason=r["gate_reason"],
            created_at=datetime.fromisoformat(r["created_at"]),
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )

    # -- people ------------------------------------------------------------ #
    def upsert_person(self, p: Person) -> None:
        """Insert or update a person by (domain, name)."""
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO people
                  (domain, name, role, name_source, linkedin_url, linkedin_source,
                   linkedin_confirmed, phone, phone_source, email, email_source,
                   is_primary, confidence, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(domain, name) DO UPDATE SET
                   role=excluded.role,
                   name_source=excluded.name_source,
                   linkedin_url=excluded.linkedin_url,
                   linkedin_source=excluded.linkedin_source,
                   linkedin_confirmed=excluded.linkedin_confirmed,
                   phone=excluded.phone,
                   phone_source=excluded.phone_source,
                   email=excluded.email,
                   email_source=excluded.email_source,
                   is_primary=excluded.is_primary,
                   confidence=excluded.confidence,
                   notes=excluded.notes
                """,
                (
                    p.domain,
                    p.name,
                    p.role,
                    p.name_source.value if hasattr(p.name_source, "value") else p.name_source,
                    p.linkedin_url,
                    p.linkedin_source,
                    int(p.linkedin_confirmed),
                    p.phone,
                    p.phone_source,
                    p.email,
                    p.email_source,
                    int(p.is_primary),
                    p.confidence.value if hasattr(p.confidence, "value") else p.confidence,
                    p.notes,
                ),
            )

    def delete_people(self, domain: str) -> None:
        """Remove all person rows for a domain (clean slate before re-deriving)."""
        with self.tx() as c:
            c.execute("DELETE FROM people WHERE domain = ?", (domain,))

    def people_for(self, domain: str) -> list[Person]:
        cur = self._conn.execute(
            "SELECT * FROM people WHERE domain = ? ORDER BY is_primary DESC, id",
            (domain,),
        )
        return [self._row_to_person(r) for r in cur]

    @staticmethod
    def _row_to_person(r: sqlite3.Row) -> Person:
        return Person(
            id=r["id"],
            domain=r["domain"],
            name=r["name"] or "(verify)",
            role=r["role"],
            name_source=r["name_source"],
            linkedin_url=r["linkedin_url"],
            linkedin_source=r["linkedin_source"],
            linkedin_confirmed=bool(r["linkedin_confirmed"]),
            phone=r["phone"],
            phone_source=r["phone_source"],
            email=r["email"] if "email" in r.keys() else None,
            email_source=r["email_source"] if "email_source" in r.keys() else None,
            is_primary=bool(r["is_primary"]),
            confidence=r["confidence"],
            notes=r["notes"],
        )

    # -- no_domain bucket -------------------------------------------------- #
    def add_no_domain(self, company_name: str, city: Optional[str], source: str, url: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO no_domain (company_name, city, source, source_url, created_at) "
                "VALUES (?,?,?,?,?)",
                (company_name, city, source, url, _iso(utcnow())),
            )

    # -- cache (write-through) -------------------------------------------- #
    def cache_get(self, key: str) -> Optional[Any]:
        r = self._conn.execute(
            "SELECT value_json FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if r is None:
            return None
        return json.loads(r["value_json"]) if r["value_json"] is not None else None

    def cache_set(self, key: str, value: Any) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO cache (key, value_json, created_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, _json(value), _iso(utcnow())),
            )

    def cache_has(self, key: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM cache WHERE key = ? LIMIT 1", (key,)
            ).fetchone()
            is not None
        )

    # -- quota ledger (persistent per-provider accounting) ---------------- #
    def quota_get(self, provider: str, metric: str, window_key: str) -> tuple[int, Optional[int]]:
        """Return (used, limit_value) for a provider/metric/window; (0, None) if absent."""
        r = self._conn.execute(
            "SELECT used, limit_value FROM quota WHERE provider=? AND metric=? AND window_key=?",
            (provider, metric, window_key),
        ).fetchone()
        return (r["used"], r["limit_value"]) if r else (0, None)

    def quota_add(self, provider: str, metric: str, window_key: str,
                  delta: int = 1, limit_value: Optional[int] = None) -> int:
        """Atomically add ``delta`` to a quota counter; returns the new used total.
        ``limit_value`` (if given) is recorded/updated for reference."""
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO quota (provider, metric, window_key, used, limit_value, updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(provider, metric, window_key) DO UPDATE SET
                   used = quota.used + excluded.used,
                   limit_value = COALESCE(excluded.limit_value, quota.limit_value),
                   updated_at = excluded.updated_at
                """,
                (provider, metric, window_key, delta, limit_value, _iso(utcnow())),
            )
        used, _ = self.quota_get(provider, metric, window_key)
        return used

    # -- counts (for logging) --------------------------------------------- #
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in ("raw_listings", "companies", "people", "cache", "no_domain"):
            out[t] = self._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        out["companies_gate_pass"] = self._conn.execute(
            "SELECT COUNT(*) AS n FROM companies WHERE gate_pass = 1"
        ).fetchone()["n"]
        return out


def open_store(cfg) -> Store:  # noqa: ANN001 — cfg is config.Config
    """Open (and migrate) the store described by ``cfg``."""
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    store.init_db()
    return store
