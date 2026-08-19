"""Analysis stage: sends each candidate + the fixed thesis to Groq,
gets back structured JSON, validates it against our schema before
trusting it.

We validate rather than blindly trust the model's JSON because a memo
built on a malformed score or a missing verdict is worse than one
candidate failing loudly and getting skipped — see the assignment:
"robust to bad or missing data" applies to LLM output too, not just HN's.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import groq

from pipeline.models import Candidate, Analysis, ScoreBreakdown

# Prompts live as their own .md files, not as Python string constants —
# this keeps them diffable and directly readable by a reviewer without
# reading Python, and it's the actual, unedited prompt used (see README).
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "analysis_prompt.md"
THESIS_PATH = Path(__file__).parent.parent / "prompts" / "thesis.md"

def _load_env():
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

# Overridable via env var rather than hardcoded, so a model swap doesn't
# require a code change — just `export ANALYSIS_MODEL=...` before running.
MODEL = os.environ.get("ANALYSIS_MODEL", "openai/gpt-oss-120b")

VALID_VERDICTS = {"Pass", "Watch", "Take a meeting"}
# The max for each dimension mirrors prompts/thesis.md exactly. Duplicated
# here (rather than imported from the markdown) so a score can be checked
# with a simple int, but if you change a weight in thesis.md, update this
# dict too — see README for that maintenance note.
SCORE_MAXES = {
    "workflow_specificity": 30,
    "buyer_fit": 20,
    "traction_signal": 25,
    "team_credibility": 15,
    "market_why_now": 10,
}


class AnalysisError(Exception):
    """Raised when the model's output fails validation. Caller (run.py)
    decides whether to skip the candidate or halt — we skip, and log why,
    so one bad LLM response doesn't take down an entire batch run."""


def _build_prompt(candidate: Candidate) -> str:
    template = PROMPT_PATH.read_text()
    thesis = THESIS_PATH.read_text()
    # Full candidate JSON, not a hand-picked subset of fields — the model
    # is instructed (in the prompt) to ground every claim in a named
    # field, so it needs to see all of them, including ones that might be
    # empty/None. An empty field is itself information ("no data here").
    candidate_json = json.dumps(candidate.to_dict(), indent=2)
    return template.format(thesis=thesis, candidate_json=candidate_json)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()

    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part_str = part.strip()
            if part_str.startswith("json"):
                part_str = part_str[4:].strip()
            if part_str.startswith("{") and part_str.endswith("}"):
                text = part_str
                break

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    return json.loads(text.strip())


def _validate(data: dict) -> None:
    # Fails fast and specifically (naming exactly what's wrong) rather
    # than letting a KeyError/TypeError surface later inside memo
    # rendering, where the error would be harder to trace back to "the
    # model's response was malformed."
    required = {
        "candidate_name", "team", "product", "market", "risks", "scores",
        "verdict", "verdict_rationale", "change_my_mind",
    }
    missing = required - data.keys()
    if missing:
        raise AnalysisError(f"missing required fields: {missing}")

    if data["verdict"] not in VALID_VERDICTS:
        # Catches the case where the model writes "Meeting" or "Take a Meeting"
        # (wrong case) instead of the exact string the memo template and any
        # downstream aggregation logic expects.
        raise AnalysisError(f"invalid verdict: {data['verdict']!r}")

    scores = data["scores"]
    for dim, cap in SCORE_MAXES.items():
        if dim not in scores:
            raise AnalysisError(f"missing score dimension: {dim}")
        val = scores[dim]
        # isinstance(bool, int) is True in Python, but a JSON `true`
        # decoded as a Python bool would still pass a naive int check and
        # produce a nonsense score if not caught explicitly here.
        if isinstance(val, bool) or not isinstance(val, int) or not (0 <= val <= cap):
            raise AnalysisError(f"score {dim}={val!r} out of range 0-{cap}")


def analyze_candidate(candidate: Candidate, client: groq.Groq | None = None) -> Analysis:
    """Runs one candidate through the LLM and returns a validated Analysis.

    Raises AnalysisError if the model's output doesn't pass validation —
    the caller (run.py) catches this per-candidate so one bad response
    doesn't take down the whole batch.
    """
    # client is an injectable parameter (not just built internally) so
    # tests can pass a fake/mock client without needing a real API key —
    # not exercised in the current test suite, but kept open for that.
    client = client or groq.Groq()  # reads GROQ_API_KEY from env; raises clearly if unset
    prompt = _build_prompt(candidate)

    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=2000,  # generous headroom for a 5-field structured analysis without truncation risk
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content or ""

    try:
        data = _extract_json(text)
    except json.JSONDecodeError as e:
        # Include a slice of the raw response in the error — when this
        # fires, seeing what the model actually said is what lets you fix
        # the prompt, not just know that it failed.
        raise AnalysisError(f"model did not return valid JSON: {e}\nraw: {text[:500]}")

    _validate(data)

    # claims_with_sources and data_gaps are allowed to be legitimately
    # absent from the model's JSON (e.g. a candidate with no traceable
    # claims at all) — default to empty lists rather than treating their
    # absence as a validation failure, since an empty list is meaningfully
    # different from "the model forgot to fill this in."
    data.setdefault("claims_with_sources", [])
    data.setdefault("data_gaps", [])
    data["scores"] = ScoreBreakdown(**data["scores"])
    return Analysis(**data)
