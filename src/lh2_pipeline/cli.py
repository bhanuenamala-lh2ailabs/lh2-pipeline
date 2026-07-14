"""`lh2` CLI — typer app.

Commands (Phase 1: present + wired to config/store; phase logic stubbed where
that phase isn't built yet):

  lh2 init                       # create dirs + initialize DB
  lh2 config-check               # load+validate config and .env, print summary
  lh2 crawl   [--source --city]  # Phase 1 — populate raw_listings
  lh2 build                      # Phase 2 — canonicalize/dedupe/gate -> companies
  lh2 enrich  [--max-enrich]     # Phase 3 — founders + contacts
  lh2 score                      # Phase 4 — confidence + namesake guard
  lh2 export  [--hyperlinked]    # Phase 5 — 14-col CSV
  lh2 run                        # Phase 6 — chain all, resumable
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .config import Config, load_config
from .logging_setup import configure, get_logger
from .store import open_store

app = typer.Typer(
    add_completion=False,
    help="LH2 Indian IT-services sourcing pipeline.",
    no_args_is_help=True,
)

log = get_logger("lh2.cli")


def _load(config_path: Optional[Path]) -> Config:
    cfg = load_config(config_path)
    return cfg


# --------------------------------------------------------------------------- #
@app.callback()
def _main(
    ctx: typer.Context,
    config_path: Optional[Path] = typer.Option(
        None, "--config", help="Path to config.yaml (default: auto-discover)."
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    configure(log_level)
    ctx.obj = {"config_path": config_path}


def _cfg(ctx: typer.Context) -> Config:
    return _load(ctx.obj.get("config_path"))


# --------------------------------------------------------------------------- #
@app.command()
def version() -> None:
    """Print version."""
    typer.echo(f"lh2-pipeline {__version__}")


@app.command()
def init(ctx: typer.Context) -> None:
    """Create data dirs and initialize the database (empty tables)."""
    cfg = _cfg(ctx)
    store = open_store(cfg)
    counts = store.counts()
    store.close()
    typer.echo(f"Initialized DB at {cfg.db_path}")
    typer.echo(f"Tables ready. Row counts: {counts}")


@app.command("config-check")
def config_check(ctx: typer.Context) -> None:
    """Load + validate config.yaml and .env; print a summary (keys masked)."""
    cfg = _cfg(ctx)
    typer.echo(f"Config OK (loaded from project root: {cfg.project_root})")
    typer.echo(f"  DB path        : {cfg.db_path}")
    typer.echo(f"  Cities         : {len(cfg.crawl.cities)} configured")
    typer.echo(f"  Enabled sources: {cfg.crawl.enabled_sources() or '(none)'}")
    typer.echo(f"  Gates          : founded<={cfg.gates.founded_max_year}, "
               f"sizes={cfg.gates.size_bands_include}")
    typer.echo(f"  Enrich         : signalhire={cfg.enrich.signalhire.enabled}, "
               f"registry={cfg.enrich.registry.enabled}, "
               f"linkedin_optional={cfg.enrich.linkedin_optional.enabled}")
    typer.echo(f"  Secrets        : {cfg.secrets.masked()}")


@app.command()
def crawl(
    ctx: typer.Context,
    source: Optional[str] = typer.Option(None, "--source", help="Single source (else all enabled)."),
    city: Optional[str] = typer.Option(None, "--city", help="Single city (else all configured)."),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass raw-HTML cache."),
) -> None:
    """Phase 1 — crawl directory sources into raw_listings."""
    cfg = _cfg(ctx)
    store = open_store(cfg)
    try:
        from .crawl import run_crawl  # lazy: avoids importing playwright unless needed

        run_crawl(cfg, store, source=source, city=city, refresh=refresh)
    except NotImplementedError as e:
        typer.echo(f"[stub] crawl not yet implemented: {e}")
    except RuntimeError as e:
        typer.echo(f"crawl prerequisite missing: {e}")
        raise typer.Exit(code=2)
    finally:
        store.close()


@app.command()
def smoke(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source to smoke-test (e.g. goodfirms)."),
    city: str = typer.Option("Pune", "--city"),
) -> None:
    """Phase 1 smoke test — fetch one known city page and assert >=1 parsed row."""
    cfg = _cfg(ctx)
    from .crawl import smoke as _smoke

    try:
        n = _smoke(cfg, source, city)
    except RuntimeError as e:
        typer.echo(f"smoke prerequisite missing: {e}")
        raise typer.Exit(code=2)
    if n >= 1:
        typer.echo(f"SMOKE PASS: {source} / {city} -> {n} named rows")
    else:
        typer.echo(f"SMOKE FAIL: {source} / {city} -> 0 rows (fix selectors in crawl/{source}.py)")
        raise typer.Exit(code=1)


@app.command()
def build(ctx: typer.Context) -> None:
    """Phase 2 — canonicalize, dedupe, gate-filter raw_listings -> companies."""
    cfg = _cfg(ctx)
    store = open_store(cfg)
    try:
        from .transform import run_build

        counts = run_build(cfg, store)
        typer.echo(
            f"build: {counts['raw_listings']} raw -> {counts['unique_companies']} unique "
            f"-> {counts['gate_pass']} passing gates "
            f"({counts.get('excluded_known', 0)} excluded as already-known, "
            f"{counts['no_domain']} no-domain held for review)"
        )
    except NotImplementedError as e:
        typer.echo(f"[stub] build not yet implemented: {e}")
    finally:
        store.close()


@app.command()
def enrich(
    ctx: typer.Context,
    max_enrich: Optional[int] = typer.Option(None, "--max-enrich", help="Cap enriched firms."),
    refresh: bool = typer.Option(False, "--refresh"),
) -> None:
    """Phase 3 — founders (registry + site) and contacts (Signalhire)."""
    cfg = _cfg(ctx)
    store = open_store(cfg)
    try:
        from .enrich import run_enrich

        stats = run_enrich(cfg, store, max_enrich=max_enrich, refresh=refresh)
        typer.echo(
            f"enrich: {stats['enriched']} firms, {stats['founders']} founders, "
            f"{stats['phones']} phones, {stats.get('emails', 0)} emails | "
            f"signalhire_calls={stats['signalhire_calls']}, "
            f"claude_calls={stats['claude_calls']}"
        )
        if stats.get("credits_budget_month"):
            note = " — DAILY BUDGET REACHED" if stats.get("credit_budget_reached") else ""
            typer.echo(
                f"        credits: {stats['credits_used_today']}/{stats['credits_daily_budget']} today, "
                f"{stats['credits_used_month']}/{stats['credits_budget_month']} this month{note}"
            )
    except NotImplementedError as e:
        typer.echo(f"[stub] enrich not yet implemented: {e}")
    except RuntimeError as e:
        typer.echo(f"enrich prerequisite missing: {e}")
        raise typer.Exit(code=2)
    finally:
        store.close()


@app.command()
def score(ctx: typer.Context) -> None:
    """Phase 4 — confidence scoring + namesake guard."""
    cfg = _cfg(ctx)
    store = open_store(cfg)
    try:
        from .judge import run_score

        stats = run_score(cfg, store)
        typer.echo(
            f"score: {stats['people']} people | green={stats['green']} "
            f"amber={stats['amber']} red={stats['red']} | "
            f"LI confirmed={stats['linkedin_confirmed']} rejected={stats['linkedin_rejected']} "
            f"| registry overrides={stats['overrides']}"
        )
    except NotImplementedError as e:
        typer.echo(f"[stub] score not yet implemented: {e}")
    except RuntimeError as e:
        typer.echo(f"score prerequisite missing: {e}")
        raise typer.Exit(code=2)
    finally:
        store.close()


@app.command()
def export(
    ctx: typer.Context,
    hyperlinked: bool = typer.Option(False, "--hyperlinked", help="Wrap Company in =HYPERLINK."),
    xlsx: bool = typer.Option(False, "--xlsx", help="Also emit LH2-styled .xlsx."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output path override."),
    append_to: Optional[Path] = typer.Option(
        None, "--append-to", help="Match this sheet's columns + continue its numbering (append-ready CSV)."),
    require_founder: bool = typer.Option(
        False, "--require-founder", help="With --append-to: include only firms that have a real founder."),
    require_full: bool = typer.Option(
        False, "--require-full", help="With --append-to: only firms with founder + LinkedIn + phone all filled."),
    exclude_file: Optional[Path] = typer.Option(
        None, "--exclude-file", help="Skip domains listed in this file (e.g. already-delivered)."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Stop after N rows."),
    start_index: Optional[int] = typer.Option(None, "--start-index", help="Override the starting # number."),
) -> None:
    """Phase 5 — write the 14-column CSV deliverable."""
    cfg = _cfg(ctx)
    store = open_store(cfg)
    try:
        from .export import run_export

        res = run_export(cfg, store, hyperlinked=hyperlinked, xlsx=xlsx, out=out,
                         append_to=append_to, require_founder=require_founder,
                         require_full=require_full, exclude_file=exclude_file,
                         limit=limit, start_index=start_index)
        if "append_csv" in res:
            typer.echo(f"append-ready: {res['append_rows']} rows (numbered from #{res['start_index']}, "
                       f"{res['matched_header_cols']} cols, excluded {res['excluded']}) -> {res['append_csv']}")
            store.close()
            return
        typer.echo(f"export: {res['rows']} rows -> {res['csv']}")
        typer.echo(f"        LinkedIn review: {res['linkedin_review_rows']} rows -> {res['review']}")
        if "xlsx" in res:
            typer.echo(f"        xlsx -> {res['xlsx']}")
    except NotImplementedError as e:
        typer.echo(f"[stub] export not yet implemented: {e}")
    except RuntimeError as e:
        typer.echo(f"export prerequisite missing: {e}")
        raise typer.Exit(code=2)
    finally:
        store.close()


@app.command()
def sync(
    ctx: typer.Context,
    start_index: Optional[int] = typer.Option(None, "--start-index", help="Override the Qualified '#' start."),
    stats_only: bool = typer.Option(False, "--stats-only", help="Only append the Pipeline Stats row."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report counts; write nothing to the sheet."),
) -> None:
    """Phase 5b — push results to Google Sheets (Qualified append / Review overwrite / Stats)."""
    cfg = _cfg(ctx)
    if not cfg.sheets.enabled:
        typer.echo("sheets sync disabled (set sheets.enabled: true in config.yaml)")
        return
    store = open_store(cfg)
    try:
        from .export.sheets_sync import run_sheets_sync

        s = run_sheets_sync(cfg, store, start_index=start_index,
                            stats_only=stats_only, dry_run=dry_run)
        prefix = "[dry-run] would sync" if dry_run else "✓ Synced"
        typer.echo(f"{prefix} {s['qualified']} qualified + {s['review']} review leads to Sheets")
        if "stats" in s:
            typer.echo(f"        stats: {s['stats']}")
    except RuntimeError as e:
        typer.echo(f"sheets sync prerequisite missing: {e}")
        raise typer.Exit(code=2)
    finally:
        store.close()


@app.command("hubspot-setup")
def hubspot_setup(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be created; create nothing."),
) -> None:
    """Phase 5c — create HubSpot custom properties + the deal pipeline (idempotent)."""
    cfg = _cfg(ctx)
    if not cfg.secrets.hubspot_api_key:
        typer.echo("HUBSPOT_API_KEY not set in .env"); raise typer.Exit(code=2)
    from .export.hubspot import run_hubspot_setup

    try:
        r = run_hubspot_setup(cfg, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001
        typer.echo(f"hubspot-setup failed: {e}"); raise typer.Exit(code=1)
    prefix = "[dry-run] would create" if dry_run else "created"
    typer.echo(f"hubspot-setup: {prefix} company props {r['company_props'] or '(none)'}, "
               f"contact props {r['contact_props'] or '(none)'}, pipeline {r['pipeline'] or '(exists)'}")
    typer.echo(f"        skipped (already exist): {len(r['skipped'])}")
    if r.get("pipeline_error"):
        typer.echo(f"        NOTE: deal pipeline not created — {r['pipeline_error']}")
        typer.echo("        (HubSpot free/starter caps pipelines at 1; use the default, or upgrade. "
                   "Sync pushes companies+contacts regardless.)")


@app.command("hubspot-sync")
def hubspot_sync(
    ctx: typer.Context,
    limit: Optional[int] = typer.Option(None, "--limit", help="Cap firms pushed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report counts; push nothing."),
) -> None:
    """Phase 5c — upsert Qualified leads to HubSpot (companies + contacts + associations)."""
    cfg = _cfg(ctx)
    if not cfg.hubspot.enabled:
        typer.echo("hubspot sync disabled (set hubspot.enabled: true)"); return
    if not cfg.secrets.hubspot_api_key:
        typer.echo("HUBSPOT_API_KEY not set in .env"); raise typer.Exit(code=2)
    store = open_store(cfg)
    try:
        from .export.hubspot import run_hubspot_sync

        s = run_hubspot_sync(cfg, store, limit=limit, dry_run=dry_run)
        prefix = "[dry-run] would push" if dry_run else "✓ pushed"
        typer.echo(f"hubspot-sync: {prefix} {s['companies']} companies, "
                   f"{s['contacts']} contacts, {s['associations']} associations")
    except Exception as e:  # noqa: BLE001
        typer.echo(f"hubspot-sync failed: {e}"); raise typer.Exit(code=1)
    finally:
        store.close()


@app.command()
def run(
    ctx: typer.Context,
    since: Optional[str] = typer.Option(None, "--since", help="Incremental: only new firms."),
    refresh: bool = typer.Option(False, "--refresh"),
    max_enrich: Optional[int] = typer.Option(None, "--max-enrich"),
) -> None:
    """Phase 6 — chain crawl -> build -> enrich -> score -> export (resumable)."""
    cfg = _cfg(ctx)
    store = open_store(cfg)
    try:
        from .orchestrate import run_all

        summary = run_all(cfg, store, since=since, refresh=refresh, max_enrich=max_enrich)
        for step in ("crawl", "build", "enrich", "score", "export"):
            if step in summary:
                typer.echo(f"  {step}: {summary[step]}")
    except NotImplementedError as e:
        typer.echo(f"[stub] run not yet implemented: {e}")
    finally:
        store.close()


if __name__ == "__main__":
    app()
