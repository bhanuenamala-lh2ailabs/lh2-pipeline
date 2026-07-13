"""Phase 6 orchestration: chain crawl -> build -> enrich -> score -> export.

Each step is skippable and resumable. Caching guarantees mean a second run with
no --refresh makes ~zero external calls and re-produces the same export.

Incremental: --since enables only_new enrichment (skip already-enriched firms),
so a monthly re-run is cheap beyond caching alone.
"""

from __future__ import annotations

from .logging_setup import get_logger

log = get_logger("lh2.run")


def run_all(
    cfg,                          # noqa: ANN001
    store,                        # noqa: ANN001
    since=None,
    refresh=False,
    max_enrich=None,
    do_crawl=True,
    do_build=True,
    do_enrich=True,
    do_score=True,
    do_export=True,
    do_sheets=True,
    hyperlinked=True,
    xlsx=False,
) -> dict:
    summary: dict = {"since": since, "refresh": refresh}
    only_new = bool(since)

    # 1. crawl — never let a missing prereq / block crash the chain.
    if do_crawl:
        try:
            from .crawl import run_crawl

            summary["crawl"] = run_crawl(cfg, store, refresh=refresh)
        except RuntimeError as e:
            log.info("crawl_skipped", reason=str(e))
            summary["crawl"] = {"skipped": str(e)}

    # 2. build
    if do_build:
        from .transform import run_build

        summary["build"] = run_build(cfg, store)

    # 3. enrich
    if do_enrich:
        from .enrich import run_enrich

        try:
            summary["enrich"] = run_enrich(
                cfg, store, max_enrich=max_enrich, refresh=refresh, only_new=only_new
            )
        except RuntimeError as e:
            log.info("enrich_skipped", reason=str(e))
            summary["enrich"] = {"skipped": str(e)}

    # 4. score
    if do_score:
        from .judge import run_score

        try:
            summary["score"] = run_score(cfg, store)
        except RuntimeError as e:
            log.info("score_skipped", reason=str(e))
            summary["score"] = {"skipped": str(e)}

    # 5. export
    if do_export:
        from .export import run_export

        summary["export"] = run_export(cfg, store, hyperlinked=hyperlinked, xlsx=xlsx)

    # 5b. Google Sheets sync — failure here must NOT crash the run (CSV is the
    # backup). Only attempted when enabled + configured.
    if do_sheets and getattr(cfg, "sheets", None) and cfg.sheets.enabled:
        try:
            from .export.sheets_sync import run_sheets_sync

            summary["sheets"] = run_sheets_sync(cfg, store)
        except Exception as e:  # noqa: BLE001 — never let Sheets break the pipeline
            log.info("sheets_sync_failed", err=str(e))
            summary["sheets"] = {"skipped": str(e)}

    log.info("run_complete", steps=list(summary))
    return summary
