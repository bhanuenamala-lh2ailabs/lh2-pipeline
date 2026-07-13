"""Namesake guard (Phase 4). Decide if a LinkedIn profile belongs to the named
person AT the named company. Prompt verbatim from BUILD SPEC §6.

Only "yes" permits writing a linkedin_url. Name-only similarity is "no".
"""

from __future__ import annotations

from typing import Literal, TypedDict

from .claude_client import ClaudeClient

SYSTEM = (
    "Decide if this LinkedIn profile belongs to the named person AT the named "
    "company. Output JSON {\"match\": \"yes\"|\"no\"|\"uncertain\", \"reason\": str}. "
    "\"yes\" ONLY if the profile's current role/experience explicitly references "
    "that company. Name-only similarity is \"no\"."
)


class MatchResult(TypedDict):
    match: Literal["yes", "no", "uncertain"]
    reason: str


def _user(name: str, company: str, city: str, profile_text: str) -> str:
    return f"{name} / {company} / {city} / {profile_text}"


def match_profile(
    client: ClaudeClient,
    name: str,
    company: str,
    city: str,
    profile_text: str,
    model: str | None = None,
) -> MatchResult:
    result = client.judge_json("match", SYSTEM, _user(name, company, city or "", profile_text), model)
    verdict = "no"
    reason = ""
    if isinstance(result, dict):
        v = str(result.get("match", "")).strip().lower()
        if v in ("yes", "no", "uncertain"):
            verdict = v
        reason = str(result.get("reason", "")).strip()
    return {"match": verdict, "reason": reason}  # type: ignore[return-value]
