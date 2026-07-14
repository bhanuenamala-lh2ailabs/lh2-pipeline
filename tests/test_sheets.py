"""Phase 5b tests — Google Sheets sync against an in-memory fake spreadsheet.
No gspread, no network. Covers: net-new qualified append, idempotency, #
continuation, review overwrite + missing-field, and the stats row."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lh2_pipeline.config import GatesConfig, SheetsConfig
from lh2_pipeline.export.sheets_sync import (
    QUALIFIED_COLUMNS,
    REVIEW_COLUMNS,
    STATS_COLUMNS,
    SheetsSyncer,
)
from lh2_pipeline.models import Company, Person
from lh2_pipeline.store import Store


# --- fakes ----------------------------------------------------------------- #
class FakeWorksheet:
    def __init__(self, values=None):
        self.values = [list(r) for r in (values or [])]

    def get_all_values(self):
        return [[str(c) for c in row] for row in self.values]

    def append_rows(self, rows):
        self.values.extend([list(r) for r in rows])

    def clear(self):
        self.values = []

    def insert_header(self, header):
        self.values.insert(0, list(header))

    def set_header(self, header):
        if self.values:
            self.values[0] = list(header)
        else:
            self.values.append(list(header))


class FakeSpreadsheet:
    def __init__(self):
        self.tabs: dict[str, FakeWorksheet] = {}

    def get_worksheet(self, title):
        return self.tabs.get(title)

    def create_worksheet(self, title):
        ws = FakeWorksheet()
        self.tabs[title] = ws
        return ws

    def seed(self, title, values):
        self.tabs[title] = FakeWorksheet(values)
        return self.tabs[title]


class _Export:
    google_search_resolver = "https://www.google.com/search?q={query}"


class FakeCfg:
    def __init__(self, root: Path):
        self.sheets = SheetsConfig(enabled=True, spreadsheet_key="key")
        self.export = _Export()
        self.gates = GatesConfig(blocklist_known_file=None)   # no exclusion files
        self.project_root = root

    def abspath(self, rel):
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)

    @property
    def exports_dir(self):
        return self.project_root / "data" / "exports"


def _now():
    return datetime(2026, 7, 13, 9, 30, tzinfo=timezone.utc)


def _syncer(tmp_path, ss):
    return SheetsSyncer(FakeCfg(tmp_path), spreadsheet=ss, now_fn=_now)


def _full_firm(store, domain="foo.com", name="Foo Labs"):
    store.upsert_company(Company(domain=domain, company_name=name,
                                 website=f"https://{domain}", city="Pune",
                                 hq_country="India", founded_year=2018,
                                 size_band="10-49", gate_pass=True))
    store.upsert_person(Person(domain=domain, name="A Founder", role="CEO",
                               is_primary=True, linkedin_url="https://linkedin.com/in/a",
                               phone="+919876543210", email="a@%s" % domain,
                               name_source="signalhire", notes="sources: signalhire"))


def _store(tmp_path, fname="s.sqlite"):
    s = Store(tmp_path / fname)
    s.init_db()
    return s


# --- qualified (append-only, net-new) -------------------------------------- #
def test_qualified_appends_only_four_field_firms(tmp_path):
    s = _store(tmp_path)
    _full_firm(s)                       # 4/4 → qualifies
    # a 3/4 firm (no email) must NOT appear in Qualified
    s.upsert_company(Company(domain="bar.com", company_name="Bar", website="https://bar.com",
                             hq_country="India", founded_year=2019, size_band="10-49", gate_pass=True))
    s.upsert_person(Person(domain="bar.com", name="B Founder", is_primary=True,
                           linkedin_url="https://linkedin.com/in/b", phone="+919000000000"))
    ss = FakeSpreadsheet()
    n = _syncer(tmp_path, ss).sync_qualified(s)
    assert n == 1
    ws = ss.tabs["Qualified Leads"]
    assert ws.values[0] == QUALIFIED_COLUMNS
    row = ws.values[1]
    assert row[0] == 1                          # numbering starts at 1
    assert row[4] == "a@foo.com"                # Email is column 5
    assert row[-1] == "2026-07-13T09:30:00+00:00"   # Synced At
    s.close()


def test_qualified_is_idempotent(tmp_path):
    s = _store(tmp_path)
    _full_firm(s)
    ss = FakeSpreadsheet()
    syncer = _syncer(tmp_path, ss)
    assert syncer.sync_qualified(s) == 1
    # second run: firm already in the sheet (by domain) → nothing appended
    assert syncer.sync_qualified(s) == 1 - 1
    assert len(ss.tabs["Qualified Leads"].values) == 2   # header + 1 row only
    s.close()


def test_qualified_continues_numbering(tmp_path):
    s = _store(tmp_path)
    _full_firm(s, domain="new.com", name="New Co")
    ss = FakeSpreadsheet()
    # pre-existing sheet with a row numbered 130 (an unrelated delivered firm)
    ss.seed("Qualified Leads", [QUALIFIED_COLUMNS,
            [130, '=HYPERLINK("https://old.com","Old")', "", "", "", "", "", "",
             "", "", "", "", "", "", "", ""]])
    n = _syncer(tmp_path, ss).sync_qualified(s)
    assert n == 1
    assert ss.tabs["Qualified Leads"].values[-1][0] == 131      # continues from 130
    s.close()


# --- review (overwrite, exactly 3/4) --------------------------------------- #
def test_review_overwrites_and_flags_missing(tmp_path):
    s = _store(tmp_path)
    # 3/4: missing phone
    s.upsert_company(Company(domain="baz.com", company_name="Baz", website="https://baz.com",
                             hq_country="India", founded_year=2019, size_band="10-49", gate_pass=True))
    s.upsert_person(Person(domain="baz.com", name="C Founder", is_primary=True,
                           linkedin_url="https://linkedin.com/in/c", email="c@baz.com"))
    _full_firm(s)      # 4/4 → NOT in review
    ss = FakeSpreadsheet()
    n = _syncer(tmp_path, ss).sync_review(s)
    assert n == 1
    ws = ss.tabs["Under Review"]
    assert ws.values[0] == REVIEW_COLUMNS
    assert ws.values[1][0] == "Baz"
    assert ws.values[1][-2] == "Phone"          # Missing Field(s)
    # re-run overwrites (still exactly one review row, no growth)
    _syncer(tmp_path, ss).sync_review(s)
    assert len([r for r in ss.tabs["Under Review"].values if r != REVIEW_COLUMNS]) == 1
    s.close()


# --- stats ----------------------------------------------------------------- #
def test_stats_row(tmp_path):
    s = _store(tmp_path)
    _full_firm(s)                               # 1 qualified (4/4)
    ss = FakeSpreadsheet()
    stats = _syncer(tmp_path, ss).sync_stats(s)
    assert stats["Date"] == "2026-07-13"
    assert stats["Firms Enriched"] == 1
    assert stats["Qualified (4/4)"] == 1
    assert stats["All-Four %"] == "100%"
    assert ss.tabs["Pipeline Stats"].values[0] == STATS_COLUMNS
    s.close()


# --- header reconciliation (backfills a missing/stale header) -------------- #
def test_qualified_backfills_missing_header(tmp_path):
    s = _store(tmp_path)
    _full_firm(s, domain="hdr.com", name="Hdr Co")
    ss = FakeSpreadsheet()
    # tab has DATA rows but no header (a manual-clear artifact)
    ss.seed("Qualified Leads", [
        [1, '=HYPERLINK("https://old.com","Old")'] + [""] * (len(QUALIFIED_COLUMNS) - 2)])
    _syncer(tmp_path, ss).sync_qualified(s)
    vals = ss.tabs["Qualified Leads"].values
    assert vals[0] == QUALIFIED_COLUMNS          # header inserted above the data
    assert vals[1][1].endswith('"Old")')         # pre-existing data row preserved
    assert vals[2][1].endswith('"Hdr Co")')      # new firm appended


def test_qualified_overwrites_stale_header(tmp_path):
    s = _store(tmp_path)
    ss = FakeSpreadsheet()
    ss.seed("Qualified Leads", [["#", "Company", "OLD SCHEMA"]])   # same anchor, wrong cols
    _syncer(tmp_path, ss).sync_qualified(s)
    assert ss.tabs["Qualified Leads"].values[0] == QUALIFIED_COLUMNS


# --- dry-run writes nothing ------------------------------------------------ #
def test_dry_run_writes_nothing(tmp_path):
    s = _store(tmp_path)
    _full_firm(s)
    ss = FakeSpreadsheet()
    summary = _syncer(tmp_path, ss).sync_all(s, dry_run=True)
    assert summary["qualified"] == 1
    # tabs got created (header) but no data rows appended in dry-run
    assert ss.tabs["Qualified Leads"].values == [QUALIFIED_COLUMNS]
    s.close()
