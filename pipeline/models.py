"""Shared data models for the sourcing -> analysis -> memo pipeline.

Why dataclasses instead of pydantic: this project has no web server and no
external API contract to enforce at a boundary, so pydantic's validation
machinery would be extra dependency weight for no real benefit. Plain
dataclasses + to_dict/from_dict give us JSON-serializable objects that are
still readable/inspectable by a human opening the raw JSON files in
outputs/ — which matters because the assignment wants outputs a reviewer
can open and trust, not a black box.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Candidate:
    """One sourced startup, before any LLM analysis has touched it.

    This is intentionally "dumb data" — nothing in this class makes a
    judgment call. Judgment (scoring, verdicts) only happens in the
    Analysis stage. Keeping sourcing and judgment in separate classes
    means we can inspect exactly what raw evidence a startup was scored
    against, by opening outputs/raw/*.json without needing to re-run the LLM.
    """

    name: str  # parsed from the HN "Show HN: Name – description" title
    website: Optional[str]  # None if the HN post links a GitHub repo instead of a product site
    one_liner: str  # the "– description" half of the title; NOT LLM-generated, straight from the source
    source: str  # e.g. "hn_show_hn" — which sourcing function produced this, for traceability
    source_url: str  # permalink back to the original HN post, so any claim can be checked by a human
    founder_signal: Optional[str] = None  # whatever we could find (currently: HN username); None if nothing found
    traction_signal: str = ""  # human-readable string, e.g. "142 HN points, 38 comments" — kept as text, not just numbers, so it prints directly into memos without reformatting
    github_url: Optional[str] = None  # set by enrich_github.py if a repo link was found in the post
    github_stars: Optional[int] = None  # filled in by enrichment; stays None if enrichment failed or found nothing
    github_last_push: Optional[str] = None  # ISO date string from GitHub's API; a freshness signal separate from stars
    raw_text: str = ""  # the original post title + body + top comment text, verbatim — this is what the LLM is told to ground every claim in

    def to_dict(self) -> dict:
        # Used everywhere we write a Candidate to disk (outputs/raw/*.json)
        # or hand it to the LLM prompt as context.
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        # Mirror of to_dict — used when run.py reuses a cached raw file
        # instead of re-querying HN (the --refresh flag controls this).
        return cls(**d)


@dataclass
class ScoreBreakdown:
    """The five rubric dimensions from prompts/thesis.md, as a typed
    object rather than a loose dict — this is what lets analyze.py
    validate that the model returned a real, in-range score for every
    dimension before we trust it enough to write a memo.
    """

    workflow_specificity: int  # /30 — does it replace ONE named manual task, not "help with" many
    buyer_fit: int  # /20 — is the buyer a non-technical SMB operator, per the thesis
    traction_signal: int  # /25 — HN points/comments, GitHub activity, launch recency
    team_credibility: int  # /15 — any findable signal of relevant background; capped low if nothing found
    market_why_now: int  # /10 — deliberately the smallest weight; "big market" claims are easy to assert and hard to verify from our sourcing data, so we weight it accordingly

    @property
    def total(self) -> int:
        # Computed, not stored — so it can never drift out of sync with
        # the five components it's built from. The memo always shows a
        # total that's provably the sum of what's printed above it.
        return (
            self.workflow_specificity
            + self.buyer_fit
            + self.traction_signal
            + self.team_credibility
            + self.market_why_now
        )


@dataclass
class Analysis:
    """Structured LLM output for one candidate — the judgment layer.

    Every field here maps directly to a section of the final memo
    (see pipeline/memo.py). That 1:1 mapping is deliberate: it means the
    memo template does almost no interpretation of its own, it just
    prints what analyze.py already validated. Less room for the memo
    stage to quietly introduce claims that were never checked.
    """

    candidate_name: str
    team: str  # plain-language summary; the LLM is instructed to ground this in founder_signal/raw_text or say nothing
    product: str  # what it actually does, not what it claims to do — instructed in the prompt to stay descriptive, not promotional
    market: str  # size hint + why-now, per the thesis's market_why_now dimension
    risks: list[str]  # "what would kill this" — the assignment asks for this explicitly, not just upside
    scores: ScoreBreakdown
    verdict: str  # "Pass" | "Watch" | "Take a meeting" — validated against this exact set in analyze.py, so a typo'd verdict can never reach a memo
    verdict_rationale: str  # 2-3 sentences connecting the score to the call; this is what a partner reads first
    change_my_mind: list[str]  # the assignment explicitly asks for "2-3 things that would change your mind" — kept as its own field so it can't get buried inside verdict_rationale
    claims_with_sources: list[dict] = field(default_factory=list)
    # each entry: {"claim": str, "source": str} where "source" names which
    # Candidate field grounds it (e.g. "traction_signal", "raw_text").
    # This exists specifically to defeat the assignment's named anti-pattern:
    # "Claims in memos with no traceable source."
    data_gaps: list[str] = field(default_factory=list)
    # explicit list of what the model couldn't evaluate from the data it
    # was given. This is the mechanism that stops missing data from being
    # silently smoothed into an optimistic guess — see the analysis prompt's
    # rule 2 in prompts/analysis_prompt.md.

    def to_dict(self) -> dict:
        # asdict() recurses into ScoreBreakdown automatically since it's
        # also a dataclass, so this produces a fully flat, JSON-safe dict.
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Analysis":
        # scores arrives as a plain dict when loaded from JSON on disk;
        # rebuild it into a ScoreBreakdown so .total still works on
        # objects loaded from a cached outputs/analysis/*.json file.
        scores = ScoreBreakdown(**d["scores"])
        d = {**d, "scores": scores}
        return cls(**d)
