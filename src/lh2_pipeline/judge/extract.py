"""Director/founder extraction prompt (Phase 3a). Uses Haiku via ClaudeClient.

Prompt is verbatim from the BUILD SPEC §5a. Output: list of {name, role}.
Uses only names present in the text — never invents.
"""

from __future__ import annotations

from typing import Any

from .claude_client import ClaudeClient

SYSTEM = (
    "You extract company directors/founders from registry text. "
    "Output strict JSON only: a list of objects {\"name\": str, \"role\": str}. "
    "Use only names present in the text. If none, return []. No commentary."
)


def _user(company_name: str, city: str, raw_text: str) -> str:
    return f"{company_name} / {city} / {raw_text}"


def extract_directors(
    client: ClaudeClient, company_name: str, city: str, raw_text: str, model: str | None = None
) -> list[dict[str, Any]]:
    if not (raw_text and raw_text.strip()):
        return []
    result = client.judge_json("extract", SYSTEM, _user(company_name, city or "", raw_text), model)
    # Defensive: coerce to the expected shape, drop entries without a name.
    out: list[dict[str, Any]] = []
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and str(item.get("name", "")).strip():
                out.append({"name": str(item["name"]).strip(), "role": str(item.get("role", "")).strip()})
    return out
