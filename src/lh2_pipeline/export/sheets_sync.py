"""Phase 5b — Google Sheets auto-sync.

A parallel output channel to the CSV export: push pipeline results straight to a
live Google Sheet (three tabs) so the sales team sees fresh leads without a manual
import. Per sheetsSyncSpec.md:

  * **Qualified Leads** — APPEND-ONLY. Firms with all four fields (founder name +
    LinkedIn + phone + email) and gate_pass. Deduped against rows already in the
    sheet (by domain/name) so re-runs never duplicate. Carries a "Synced At" stamp.
  * **Under Review** — OVERWRITE each run. Firms with exactly 3 of 4 fields; a
    "Missing Field(s)" column says what's absent. A self-cleaning re-try queue.
  * **Pipeline Stats** — APPEND one metrics row per run.

Never fabricates: blank cells stay blank. Sheet I/O is abstracted behind a tiny
gateway (the methods a gspread worksheet already exposes) so tests inject a fake
in-memory sheet — no network, no gspread needed for tests. gspread + google-auth
are imported lazily (only when actually talking to Google).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from ..logging_setup import get_logger
from ..models import Person, utcnow
from ..transform.canonicalize import canonical_domain
from ..transform.exclusions import _unwrap_hyperlink, load_exclusions
from .csv_writer import (
    _company_cell,
    _email,
    _founders_cell,
    _headcount_source,
    _li,
    _notes_cell,
    _phone,
)

log = get_logger("lh2.sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Qualified tab schema (per spec — Email is column 5, "Synced At" is appended).
QUALIFIED_COLUMNS = [
    "#", "Company", "Founder(s)", "Founder LinkedIn (verified)", "Email",
    "Contact Number", "SPOC 2 Linkedin", "Contact Number 2", "Incorp. Year",
    "HQ / India delivery", "Approx. Headcount", "Size Bucket",
    "Headcount source (approx.)", "Segment", "Status", "Notes", "Synced At",
]

REVIEW_COLUMNS = [
    "Company", "Domain", "Founder(s)", "Founder LinkedIn (verified)", "Email",
    "Contact Number", "Incorp. Year", "HQ / India delivery", "Size Bucket",
    "Segment", "Missing Field(s)", "Notes",
]

STATS_COLUMNS = [
    "Date", "Firms Enriched", "Qualified (4/4)", "Review (3/4)",
    "Founder %", "LinkedIn %", "Phone %", "Email %", "All-Four %",
]

# The four required fields, in the order shown in "Missing Field(s)".
_FIELDS = ("Founder", "LinkedIn", "Phone", "Email")


# --------------------------------------------------------------------------- #
# Field presence helpers
# --------------------------------------------------------------------------- #
def _presence(primary: Optional[Person]) -> dict[str, bool]:
    if primary is None:
        return {f: False for f in _FIELDS}
    return {
        "Founder": bool(primary.name and primary.name != "(verify)"),
        "LinkedIn": bool(primary.linkedin_url),
        "Phone": bool(primary.phone),
        "Email": bool(primary.email),
    }


def _missing_fields(primary: Optional[Person]) -> list[str]:
    p = _presence(primary)
    return [f for f in _FIELDS if not p[f]]


def _sheet_phone(person: Optional[Person]) -> str:
    """Phone for a Sheets cell. We write with value_input_option=USER_ENTERED so
    =HYPERLINK renders — but that also makes Sheets parse a leading '+' as a
    formula and drop it. A leading apostrophe forces text (and is not displayed),
    preserving the E.164 '+'."""
    v = _phone(person)
    return f"'{v}" if v.startswith("+") else v


# --------------------------------------------------------------------------- #
# Gateways — real gspread wrappers (lazy import) + the interface tests fake
# --------------------------------------------------------------------------- #
class _GspreadWorksheet:
    def __init__(self, ws):  # noqa: ANN001
        self._ws = ws

    def get_all_values(self) -> list[list[str]]:
        return self._ws.get_all_values()

    def append_rows(self, rows: list[list]) -> None:
        if rows:
            self._ws.append_rows(rows, value_input_option="USER_ENTERED")

    def clear(self) -> None:
        self._ws.clear()


class _GspreadSpreadsheet:
    def __init__(self, ss):  # noqa: ANN001
        self._ss = ss

    def get_worksheet(self, title: str):
        try:
            return _GspreadWorksheet(self._ss.worksheet(title))
        except Exception:
            return None

    def create_worksheet(self, title: str):
        return _GspreadWorksheet(self._ss.add_worksheet(title=title, rows=1000, cols=26))


def _open_spreadsheet(cfg):  # noqa: ANN001
    """Authorize with the service account and open the sheet by key. Credentials
    resolve from a local JSON file (dev) OR the GOOGLE_SERVICE_ACCOUNT_JSON env
    var (CI); the key from config OR the GOOGLE_SHEETS_KEY env var. Raises
    RuntimeError (never a stack trace) on any prerequisite problem."""
    import json
    import os

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        raise RuntimeError('gspread not installed. Install with: pip install -e ".[sheets]"') from e

    # -- credentials: local file first, else env JSON (GitHub Actions) --------
    creds_path = cfg.abspath(cfg.sheets.credentials_file)
    if creds_path.exists():
        creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    else:
        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not raw:
            raise RuntimeError(
                f"no Google credentials: file {creds_path} missing and "
                "GOOGLE_SERVICE_ACCOUNT_JSON unset (share the sheet with the service account)")
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from e
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)

    # -- spreadsheet key: config first, else env --------------------------------
    key = cfg.sheets.spreadsheet_key or os.getenv("GOOGLE_SHEETS_KEY")
    if not key:
        raise RuntimeError("spreadsheet key missing — set sheets.spreadsheet_key in "
                           "config.yaml or the GOOGLE_SHEETS_KEY env var")

    gc = gspread.authorize(creds)
    try:
        return _GspreadSpreadsheet(gc.open_by_key(key))
    except Exception as e:
        raise RuntimeError(f"could not open spreadsheet {key}: {e}") from e


# --------------------------------------------------------------------------- #
# Syncer
# --------------------------------------------------------------------------- #
class SheetsSyncer:
    def __init__(self, cfg, spreadsheet=None, now_fn: Callable[[], datetime] = utcnow):  # noqa: ANN001
        self.cfg = cfg
        self._ss = spreadsheet
        self._now = now_fn
        self.resolver = cfg.export.google_search_resolver

    # -- spreadsheet / worksheet plumbing --------------------------------- #
    def _spreadsheet(self):
        if self._ss is None:
            self._ss = _open_spreadsheet(self.cfg)
        return self._ss

    def _ws_with_header(self, title: str, header: list[str]):
        """Get (or create) a tab and ensure the header row exists. Returns
        (worksheet, existing_data_rows) where data rows exclude the header."""
        ss = self._spreadsheet()
        ws = ss.get_worksheet(title)
        if ws is None:
            ws = ss.create_worksheet(title)
            ws.append_rows([header])
            return ws, []
        values = ws.get_all_values()
        if not values:
            ws.append_rows([header])
            return ws, []
        return ws, values[1:]

    # -- Qualified (append-only, net-new) --------------------------------- #
    def sync_qualified(self, store, start_index: Optional[int] = None,  # noqa: ANN001
                       limit: Optional[int] = None, dry_run: bool = False) -> int:
        ws, existing = self._ws_with_header(self.cfg.sheets.qualified_tab, QUALIFIED_COLUMNS)

        # already-present keys: domains + normalized names from the sheet, plus the
        # net-new exclusion set (delivered ledger + master + AI-Labs).
        seen_domains: set[str] = set(load_exclusions(self.cfg).domains)
        seen_names: set[str] = set()
        max_idx = start_index - 1 if start_index is not None else 0
        for row in existing:
            if not row:
                continue
            display, url = _unwrap_hyperlink(row[1]) if len(row) > 1 else (None, None)
            if url:
                d = canonical_domain(url)
                if d:
                    seen_domains.add(d)
            if display:
                seen_names.add(display.strip().lower())
            if start_index is None and row and str(row[0]).strip().isdigit():
                max_idx = max(max_idx, int(row[0].strip()))

        stamp = self._now().isoformat(timespec="seconds")
        new_rows: list[list] = []
        idx = max_idx
        for co in store.iter_companies(gate_pass=True):
            if co.domain in seen_domains or co.company_name.strip().lower() in seen_names:
                continue
            people = store.people_for(co.domain)
            primary = people[0] if people else None
            if not all(_presence(primary).values()):     # four-field only
                continue
            spoc2 = people[1] if len(people) > 1 else None
            idx += 1
            new_rows.append([
                idx,
                _company_cell(co, True, self.resolver),
                _founders_cell(people),
                _li(primary),
                _email(primary),
                _sheet_phone(primary),
                _li(spoc2),
                _sheet_phone(spoc2),
                co.founded_year or "",
                co.hq_country or "",
                co.size_band or "",
                co.size_bucket or "",
                _headcount_source(co),
                co.segment or "",
                co.status or "",
                _notes_cell(co, people),
                stamp,
            ])
            seen_domains.add(co.domain)
            if limit and len(new_rows) >= limit:
                break

        if new_rows and not dry_run:
            ws.append_rows(new_rows)
        log.info("sheets_qualified", appended=len(new_rows), dry_run=dry_run)
        return len(new_rows)

    # -- Under Review (overwrite) ----------------------------------------- #
    def sync_review(self, store, dry_run: bool = False) -> int:  # noqa: ANN001
        ws, _ = self._ws_with_header(self.cfg.sheets.review_tab, REVIEW_COLUMNS)
        rows: list[list] = []
        for co in store.iter_companies(gate_pass=True):
            people = store.people_for(co.domain)
            if not people:
                continue
            primary = people[0]
            missing = _missing_fields(primary)
            if len(missing) != 1:            # exactly 3 of 4 present → one missing
                continue
            rows.append([
                co.company_name,
                co.domain,
                _founders_cell(people),
                _li(primary),
                _email(primary),
                _sheet_phone(primary),
                co.founded_year or "",
                co.hq_country or "",
                co.size_bucket or "",
                co.segment or "",
                ", ".join(missing),
                _notes_cell(co, people),
            ])
        if not dry_run:
            ws.clear()
            ws.append_rows([REVIEW_COLUMNS] + rows)
        log.info("sheets_review", rows=len(rows), dry_run=dry_run)
        return len(rows)

    # -- Pipeline Stats (append one row) ---------------------------------- #
    def sync_stats(self, store, dry_run: bool = False) -> dict:  # noqa: ANN001
        firms = list(store.iter_companies(gate_pass=True))
        enriched = 0
        founder = linkedin = phone = email = full = 0
        for co in firms:
            people = store.people_for(co.domain)
            if not people:
                continue
            enriched += 1
            p = _presence(people[0])
            founder += p["Founder"]
            linkedin += p["LinkedIn"]
            phone += p["Phone"]
            email += p["Email"]
            full += all(p.values())
        review = sum(
            1 for co in firms
            if store.people_for(co.domain)
            and len(_missing_fields(store.people_for(co.domain)[0])) == 1
        )

        def pct(n: int) -> str:
            return f"{(100 * n / enriched):.0f}%" if enriched else "0%"

        row = [
            self._now().strftime("%Y-%m-%d"), enriched, full, review,
            pct(founder), pct(linkedin), pct(phone), pct(email), pct(full),
        ]
        if not dry_run:
            ws, _ = self._ws_with_header(self.cfg.sheets.stats_tab, STATS_COLUMNS)
            ws.append_rows([row])
        stats = dict(zip(STATS_COLUMNS, row))
        log.info("sheets_stats", **{"enriched": enriched, "qualified": full, "review": review})
        return stats

    # -- orchestration ---------------------------------------------------- #
    def sync_all(self, store, start_index: Optional[int] = None,  # noqa: ANN001
                 stats_only: bool = False, dry_run: bool = False) -> dict:
        summary: dict = {"qualified": 0, "review": 0}
        if not stats_only:
            summary["qualified"] = self.sync_qualified(store, start_index=start_index, dry_run=dry_run)
            summary["review"] = self.sync_review(store, dry_run=dry_run)
        summary["stats"] = self.sync_stats(store, dry_run=dry_run)
        return summary


def run_sheets_sync(cfg, store, start_index=None, stats_only=False, dry_run=False,  # noqa: ANN001
                    spreadsheet=None) -> dict:
    """Entry point used by the CLI and by orchestrate. Returns a summary dict."""
    return SheetsSyncer(cfg, spreadsheet=spreadsheet).sync_all(
        store, start_index=start_index, stats_only=stats_only, dry_run=dry_run
    )
