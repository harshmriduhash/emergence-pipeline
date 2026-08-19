"""Memo stage: Analysis -> one-page markdown memo.

Design goal per the assignment's "done" bar: a partner opens this and
understands the call within 60 seconds. So the verdict and rationale go
first, above the fold, not buried after the analysis sections — a reader
should never have to scroll to find out what we're recommending.
"""
from __future__ import annotations

from pipeline.models import Analysis, Candidate

# A quick visual verdict cue for skimming a folder of memos — the emoji
# duplicates information already in the text (never the only signal),
# so nothing is lost if it doesn't render in a given viewer.
VERDICT_EMOJI = {"Pass": "\u274c", "Watch": "\U0001f440", "Take a meeting": "\u2705"}


def render_memo(candidate: Candidate, analysis: Analysis) -> str:
    s = analysis.scores
    emoji = VERDICT_EMOJI.get(analysis.verdict, "")  # empty string, not a crash, if verdict is somehow outside the known set

    # Every list field gets a fallback line instead of rendering as a bare
    # empty section — an empty "## Risks" section with nothing under it
    # reads as a mistake to a partner skimming; "(none identified)" reads
    # as a deliberate, checked answer.
    risks = "\n".join(f"- {r}" for r in analysis.risks) or "- (none identified)"
    change_mind = "\n".join(f"- {c}" for c in analysis.change_my_mind) or "- (none identified)"
    gaps = "\n".join(f"- {g}" for g in analysis.data_gaps) or "- none"
    # claims_with_sources renders each claim with its grounding field
    # inline (in italics) — this is the part of the memo that lets a
    # reviewer "spot-check one analysis and trust where its claims came
    # from," which the assignment calls out as a specific bar to clear.
    claims = "\n".join(
        f"- {c['claim']} _(source: {c['source']})_" for c in analysis.claims_with_sources
    ) or "- (see sections above)"

    return f"""# {candidate.name} {emoji}

**Verdict: {analysis.verdict}**  ({s.total}/100)

> {analysis.verdict_rationale}

---

## What would change our mind
{change_mind}

---

## Team
{analysis.team}

## Product
{analysis.product}

## Market
{analysis.market}

## Risks / open questions
{risks}

---

## Score breakdown

| Dimension | Score | Max |
|---|---|---|
| Workflow specificity | {s.workflow_specificity} | 30 |
| Buyer fit | {s.buyer_fit} | 20 |
| Traction signal | {s.traction_signal} | 25 |
| Team credibility | {s.team_credibility} | 15 |
| Market / why now | {s.market_why_now} | 10 |
| **Total** | **{s.total}** | **100** |

## Traceable claims
{claims}

## Data gaps
{gaps}

---

*Sourced from: [{candidate.source}]({candidate.source_url})*
{f"*Website: {candidate.website}*" if candidate.website else ""}
{f"*GitHub: {candidate.github_url}*" if candidate.github_url else ""}
"""
