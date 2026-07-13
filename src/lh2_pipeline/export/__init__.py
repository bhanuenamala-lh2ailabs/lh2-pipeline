"""Phase 5 export orchestration."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from ..logging_setup import get_logger
from .csv_writer import (
    COLUMNS,
    build_rows,
    write_append_csv,
    write_csv,
    write_linkedin_review,
    write_xlsx,
)

log = get_logger("lh2.export")

__all__ = ["run_export", "build_rows", "write_csv", "write_linkedin_review",
           "write_xlsx", "write_append_csv", "COLUMNS"]


def _template_header_and_next_index(path: Path) -> tuple[list[str], int]:
    """Read an existing sheet's header and the next free row number (max # + 1)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None) or COLUMNS
        nums = [int(r[0]) for r in reader if r and r[0].strip().isdigit()]
    return header, (max(nums) + 1 if nums else 1)


def run_export(cfg, store, hyperlinked=False, xlsx=False, out=None,  # noqa: ANN001
               append_to=None, require_founder=False, require_full=False,
               exclude_file=None, limit=None, start_index=None) -> dict:
    resolver = cfg.export.google_search_resolver
    exports = cfg.exports_dir

    # Append-ready CSV that matches an existing sheet's columns + continues numbering.
    if append_to:
        template_path = cfg.abspath(str(append_to))
        header, next_idx = _template_header_and_next_index(template_path)
        if start_index is not None:
            next_idx = start_index

        exclude_domains = set()
        if exclude_file:
            ef = cfg.abspath(str(exclude_file))
            if ef.exists():
                exclude_domains = {
                    ln.strip().lower() for ln in ef.read_text(encoding="utf-8").splitlines()
                    if ln.strip()
                }

        append_path = exports / "append_ready.csv"
        n = write_append_csv(
            store, append_path, header, start_index=next_idx,
            enriched_only=True, require_founder=require_founder, require_full=require_full,
            exclude_domains=exclude_domains, limit=limit,
            hyperlinked=True, resolver=resolver,   # =HYPERLINK on Company (site, or Google fallback)
        )
        result = {"append_rows": n, "append_csv": str(append_path),
                  "start_index": next_idx, "matched_header_cols": len(header),
                  "excluded": len(exclude_domains)}
        log.info("append_export_complete", **result)
        return result

    suffix = "_hyperlinked" if hyperlinked else ""
    csv_path = Path(out) if out else exports / f"targets{suffix}.csv"
    n = write_csv(store, csv_path, hyperlinked, resolver)

    review_path = exports / "linkedin_review.csv"
    r = write_linkedin_review(store, review_path)

    result = {"rows": n, "csv": str(csv_path), "linkedin_review_rows": r, "review": str(review_path)}

    if xlsx:
        xlsx_path = (Path(out).with_suffix(".xlsx") if out else exports / f"targets{suffix}.xlsx")
        write_xlsx(store, xlsx_path, hyperlinked, resolver, cfg.export.xlsx_house_style)
        result["xlsx"] = str(xlsx_path)

    log.info("export_complete", **result)
    return result
