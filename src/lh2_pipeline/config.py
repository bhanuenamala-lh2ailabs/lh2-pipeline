"""Load and validate config.yaml + .env.

Single source of truth for tunables. Everything downstream takes a ``Config``
instance rather than reading the YAML or environment directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Config sections (pydantic v2 — validation happens on load)
# --------------------------------------------------------------------------- #
class RunConfig(BaseModel):
    data_dir: str = "data"
    db_path: str = "data/pipeline.sqlite"
    raw_html_dir: str = "data/raw_html"
    exports_dir: str = "data/exports"


class CrawlConfig(BaseModel):
    workers_per_host: int = 1
    delay_min_seconds: float = 2.0
    delay_max_seconds: float = 5.0
    max_pages_per_city: int = 50
    request_timeout_seconds: int = 45
    retry_attempts: int = 3
    honor_robots: bool = True
    user_agents: list[str] = Field(default_factory=list)
    sources: dict[str, bool] = Field(default_factory=dict)
    cities: list[str] = Field(default_factory=list)

    @field_validator("delay_max_seconds")
    @classmethod
    def _max_ge_min(cls, v: float, info):  # noqa: ANN001
        lo = info.data.get("delay_min_seconds", 0.0)
        if v < lo:
            raise ValueError("delay_max_seconds must be >= delay_min_seconds")
        return v

    def enabled_sources(self) -> list[str]:
        return [name for name, on in self.sources.items() if on]


class GatesConfig(BaseModel):
    hq_country: str = "India"
    founded_max_year: int = 2022
    # Size gate by representative headcount (midpoint of the scraped range),
    # assigned to buckets 1-100 / 100-500 / 500-1000. Admit target buckets within
    # [min, max]. (size_bands_* are legacy/unused by the gate; kept for compat.)
    size_buckets: list[str] = Field(default_factory=lambda: ["1-100", "100-500", "500-1000"])
    size_min_headcount: int = 10          # exclude sub-10 freelancers (set 1 to include)
    size_max_headcount: int = 1000        # matches the top bucket edge
    size_bands_include: list[str] = Field(default_factory=lambda: ["10-49", "50-249"])
    size_bands_exclude: list[str] = Field(default_factory=lambda: ["<10", "250+"])
    blocklist_outsourcers: list[str] = Field(default_factory=list)
    blocklist_known_domains: list[str] = Field(default_factory=list)
    blocklist_known_names: list[str] = Field(default_factory=list)
    # Optional CSV of already-known LH2 firms; its "Company" column is excluded.
    blocklist_known_file: Optional[str] = None
    # Net-new exclusion of previously-mined/delivered firms. name_files contribute
    # both company names AND any embedded domains (=HYPERLINK / Domain column);
    # domain_files are one-domain-per-line .txt (or a CSV with a domain column).
    exclude_name_files: list[str] = Field(default_factory=list)
    exclude_domain_files: list[str] = Field(default_factory=list)


class SignalhireConfig(BaseModel):
    enabled: bool = True
    e164_default_region: str = "IN"


class RegistryConfig(BaseModel):
    enabled: bool = True
    provider: str = "zaubacorp"


class CompanySiteConfig(BaseModel):
    enabled: bool = True


class LinkedinOptionalConfig(BaseModel):
    enabled: bool = False
    provider: str = "proxycurl"


class EnrichConfig(BaseModel):
    max_enrich: int = 1000
    signalhire: SignalhireConfig = Field(default_factory=SignalhireConfig)
    registry: RegistryConfig = Field(default_factory=RegistryConfig)
    company_site: CompanySiteConfig = Field(default_factory=CompanySiteConfig)
    linkedin_optional: LinkedinOptionalConfig = Field(default_factory=LinkedinOptionalConfig)


class JudgeConfig(BaseModel):
    model_extract: str = "claude-haiku-4-5-20251001"
    model_match: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 1024
    fuzzy_threshold: int = 88


class XlsxStyle(BaseModel):
    header_fill: str = "1F3864"
    band_fill: str = "EAF0F8"
    font: str = "Arial"
    font_size: int = 10


class ExportConfig(BaseModel):
    schema_version: int = 1
    google_search_resolver: str = "https://www.google.com/search?q={query}"
    xlsx_house_style: XlsxStyle = Field(default_factory=XlsxStyle)


# --------------------------------------------------------------------------- #
# Providers — rate-limit + quota governance (the "never hit the limit" layer)
# --------------------------------------------------------------------------- #
class ProviderLimits(BaseModel):
    """Documented ceilings for one provider. Rate keys (per_second/minute/hour)
    drive the RateLimiter; quota keys (per_day / monthly_credits) drive the
    QuotaLedger. All optional — absent = unconstrained on that dimension."""
    model_config = ConfigDict(extra="allow")
    requests_per_second: Optional[float] = None
    requests_per_minute: Optional[float] = None
    requests_per_hour: Optional[int] = None
    requests_per_day: Optional[int] = None
    search_per_day: Optional[int] = None
    person_items_per_minute: Optional[int] = None
    monthly_credits: Optional[int] = None
    free_calls_per_month: Optional[int] = None
    concurrency: Optional[int] = None


class ProviderConfig(BaseModel):
    enabled: bool = False
    limits: ProviderLimits = Field(default_factory=ProviderLimits)
    reset: str = "daily_utc"        # daily_utc | monthly | none
    # Hard monthly credit budget for contact REVEALS (email+phone). Spent fairly
    # across the month: each day's allowance = remaining_budget / days_left. None
    # = uncapped. This is a real business cap (not rate-safety), so it's used in
    # full — no safety_margin applied.
    monthly_credit_budget: Optional[int] = None


class ProviderDefaults(BaseModel):
    safety_margin: float = 0.8      # run at 80% of every documented limit
    max_retries: int = 4
    backoff_base_seconds: float = 2.0
    honor_retry_after: bool = True


class ProvidersConfig(BaseModel):
    """Container: shared defaults + waterfall cascade order + per-provider blocks.
    Provider blocks are arbitrary names, captured via ``extra='allow'`` and
    coerced to ProviderConfig on access."""
    model_config = ConfigDict(extra="allow")
    defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)
    cascade: dict[str, list[str]] = Field(default_factory=dict)

    def provider(self, name: str) -> Optional[ProviderConfig]:
        raw = (self.__pydantic_extra__ or {}).get(name)
        if raw is None:
            return None
        return raw if isinstance(raw, ProviderConfig) else ProviderConfig(**raw)


class SheetsConfig(BaseModel):
    """Google Sheets auto-sync. credentials_file is a service-account JSON (secret,
    gitignored); the sheet must be shared with that service account as Editor."""
    enabled: bool = False
    credentials_file: str = "google_service_account.json"
    spreadsheet_key: str = ""
    qualified_tab: str = "Qualified Leads"
    review_tab: str = "Under Review"
    stats_tab: str = "Pipeline Stats"


class Secrets(BaseModel):
    """Loaded from .env / environment. Never logged in full."""

    anthropic_api_key: Optional[str] = None
    signalhire_api_key: Optional[str] = None
    proxycurl_api_key: Optional[str] = None
    coresignal_api_key: Optional[str] = None

    def masked(self) -> dict[str, str]:
        def mask(v: Optional[str]) -> str:
            if not v:
                return "(unset)"
            return f"{v[:4]}…{v[-2:]}" if len(v) > 6 else "set"

        return {
            "anthropic_api_key": mask(self.anthropic_api_key),
            "signalhire_api_key": mask(self.signalhire_api_key),
            "proxycurl_api_key": mask(self.proxycurl_api_key),
            "coresignal_api_key": mask(self.coresignal_api_key),
        }


class Config(BaseModel):
    run: RunConfig = Field(default_factory=RunConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    enrich: EnrichConfig = Field(default_factory=EnrichConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    sheets: SheetsConfig = Field(default_factory=SheetsConfig)
    secrets: Secrets = Field(default_factory=Secrets)

    # Absolute project root (dir containing config.yaml). Not serialized to YAML.
    project_root: Path = Field(default_factory=Path.cwd, exclude=True)

    # -- resolved absolute paths ------------------------------------------- #
    def abspath(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)

    @property
    def db_path(self) -> Path:
        return self.abspath(self.run.db_path)

    @property
    def raw_html_dir(self) -> Path:
        return self.abspath(self.run.raw_html_dir)

    @property
    def exports_dir(self) -> Path:
        return self.abspath(self.run.exports_dir)

    def ensure_dirs(self) -> None:
        for d in (self.abspath(self.run.data_dir), self.raw_html_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG_FILENAME = "config.yaml"


def find_config(start: Optional[Path] = None) -> Path:
    """Walk up from ``start`` (cwd) looking for config.yaml."""
    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / DEFAULT_CONFIG_FILENAME
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find {DEFAULT_CONFIG_FILENAME} in {cur} or any parent."
    )


def load_secrets(project_root: Path) -> Secrets:
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # fall back to ambient environment
    return Secrets(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        signalhire_api_key=os.getenv("SIGNALHIRE_API_KEY") or None,
        proxycurl_api_key=os.getenv("PROXYCURL_API_KEY") or None,
        coresignal_api_key=os.getenv("CORESIGNAL_API_KEY") or None,
    )


def load_config(path: Optional[Path] = None) -> Config:
    """Load + validate config.yaml and .env. Raises on invalid config."""
    cfg_path = Path(path) if path else find_config()
    project_root = cfg_path.parent

    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    cfg = Config(**raw)
    cfg.project_root = project_root
    cfg.secrets = load_secrets(project_root)
    return cfg
