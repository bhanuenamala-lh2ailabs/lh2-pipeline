"""Pydantic models mirroring the DB tables, plus the SQL DDL.

Tables (see BUILD SPEC §2):
  raw_listings  — one row per (source, listing) as scraped, pre-dedupe
  companies     — one row per unique firm (post-dedupe, post-gate), pk = domain
  people        — founders/SPOCs linked to a company
  cache         — generic enrichment / LLM cache, write-through
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Confidence(str, Enum):
    green = "green"
    amber = "amber"
    red = "red"


class NameSource(str, Enum):
    registry = "registry"
    company_site = "company_site"
    directory = "directory"


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class RawListing(BaseModel):
    id: Optional[int] = None
    source: str
    source_url: str
    scraped_at: datetime = Field(default_factory=utcnow)
    company_name: str = ""
    website_raw: Optional[str] = None
    city: Optional[str] = None
    founded_year_raw: Optional[str] = None
    size_raw: Optional[str] = None
    segment_raw: Optional[str] = None
    extra_json: dict[str, Any] = Field(default_factory=dict)


class Company(BaseModel):
    domain: str                          # pk — canonical registered domain (dedupe key)
    company_name: str = ""
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    hq_country: Optional[str] = None
    founded_year: Optional[int] = None
    founded_source: Optional[str] = None
    size_band: Optional[str] = None
    size_source: Optional[str] = None    # provenance: raw size string
    size_bucket: Optional[str] = None    # 1-100 / 100-500 / 500-1000 (approx, from headcount)
    segment: Optional[str] = None
    status: str = ""                     # Independent / Acquired(..) / blank
    sources_json: list[dict[str, str]] = Field(default_factory=list)  # [{source,url}]
    gate_pass: bool = False
    gate_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Person(BaseModel):
    id: Optional[int] = None
    domain: str                          # fk -> companies.domain
    name: str = "(verify)"
    role: Optional[str] = None           # e.g. "Founder & CEO"
    name_source: Optional[str] = None    # registry / company_site / directory
    linkedin_url: Optional[str] = None
    linkedin_source: Optional[str] = None
    linkedin_confirmed: bool = False
    phone: Optional[str] = None
    phone_source: Optional[str] = None   # signalhire
    email: Optional[str] = None
    email_source: Optional[str] = None   # signalhire (provenance only; sales verifies)
    is_primary: bool = False             # SPOC 1 vs SPOC 2
    confidence: Optional[Confidence] = None
    notes: Optional[str] = None


class CacheEntry(BaseModel):
    key: str                             # e.g. "signalhire:<domain>", "claude:extract:<hash>"
    value_json: Any
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# DDL — SQLite. Kept inline so store.py can run migrations idempotently.
# --------------------------------------------------------------------------- #
SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS raw_listings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    scraped_at       TEXT NOT NULL,
    company_name     TEXT,
    website_raw      TEXT,
    city             TEXT,
    founded_year_raw TEXT,
    size_raw         TEXT,
    segment_raw      TEXT,
    extra_json       TEXT
);
CREATE INDEX IF NOT EXISTS ix_raw_source      ON raw_listings(source);
CREATE INDEX IF NOT EXISTS ix_raw_city        ON raw_listings(city);
CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_src_url ON raw_listings(source, source_url, company_name);

CREATE TABLE IF NOT EXISTS companies (
    domain         TEXT PRIMARY KEY,
    company_name   TEXT,
    website        TEXT,
    city           TEXT,
    state          TEXT,
    hq_country     TEXT,
    founded_year   INTEGER,
    founded_source TEXT,
    size_band      TEXT,
    size_source    TEXT,
    size_bucket    TEXT,
    segment        TEXT,
    status         TEXT,
    sources_json   TEXT,
    gate_pass      INTEGER NOT NULL DEFAULT 0,
    gate_reason    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_companies_gate ON companies(gate_pass);

CREATE TABLE IF NOT EXISTS people (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    domain             TEXT NOT NULL REFERENCES companies(domain),
    name               TEXT,
    role               TEXT,
    name_source        TEXT,
    linkedin_url       TEXT,
    linkedin_source    TEXT,
    linkedin_confirmed INTEGER NOT NULL DEFAULT 0,
    phone              TEXT,
    phone_source       TEXT,
    email              TEXT,
    email_source       TEXT,
    is_primary         INTEGER NOT NULL DEFAULT 0,
    confidence         TEXT,
    notes              TEXT
);
CREATE INDEX IF NOT EXISTS ix_people_domain ON people(domain);
-- One primary + one secondary per company, keyed by (domain, name) for idempotent upsert.
CREATE UNIQUE INDEX IF NOT EXISTS ux_people_domain_name ON people(domain, name);

CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value_json TEXT,
    created_at TEXT NOT NULL
);

-- Persistent per-provider quota accounting (survives restarts, so a killed run
-- never double-spends). window_key = the reset bucket, e.g. "2026-07-13" (daily)
-- or "2026-07" (monthly) or "all" (never-resetting prepaid credits).
CREATE TABLE IF NOT EXISTS quota (
    provider    TEXT NOT NULL,
    metric      TEXT NOT NULL,          -- e.g. "requests" | "search" | "credits"
    window_key  TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    limit_value INTEGER,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (provider, metric, window_key)
);

-- Tracks the no-website bucket for human review (Phase 2 canonicalize).
CREATE TABLE IF NOT EXISTS no_domain (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT,
    city         TEXT,
    source       TEXT,
    source_url   TEXT,
    created_at   TEXT NOT NULL
);
"""
