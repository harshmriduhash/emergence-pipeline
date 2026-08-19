"""Sourcing stage: Hacker News (Show HN) via the Algolia HN Search API.

Why HN and not a scraped list of five sources: Show HN posts are
self-reported launches with a title format that reliably contains a name
and one-liner, plus points/comments as a free, real traction signal on the
same request. Going deep on one clean source beats a shallow scrape of
five noisy ones (see: assignment anti-patterns — "a 12-source sourcing
layer where each source returns 2 garbage results").

No API key required. Docs: https://hn.algolia.com/api
"""
from __future__ import annotations

import re
import requests
from typing import Optional

from pipeline.models import Candidate

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"

# Matches "Show HN: Acme – AI agent for SMB invoicing" (en-dash) and the
# hyphen variant "Show HN: Acme - AI agent for SMB invoicing".
# Both separators show up in the wild depending on how the poster typed it,
# so the character class covers both rather than picking one and silently
# dropping posts that use the other.
TITLE_RE = re.compile(
    r"^Show HN:\s*(?P<name>[^\u2013\-]+)[\u2013\-]\s*(?P<desc>.+)$"
)


def _parse_title(title: str) -> tuple[str, str]:
    """Best-effort split of a Show HN title into (name, one_liner).

    Falls back to using the whole title as the name with an empty
    description if the "Name - description" pattern isn't present — we do
    NOT fabricate a description that isn't in the source text. An empty
    one_liner is a truthful signal to the analysis stage that this
    candidate's data is thinner than usual; inventing a plausible-sounding
    description here would hide that from every downstream stage.
    """
    m = TITLE_RE.match(title)
    if m:
        return m.group("name").strip(), m.group("desc").strip()
    # Fallback path: strip just the "Show HN:" prefix and use what's left
    # as the name. This keeps a candidate in the pipeline instead of
    # dropping it outright just because its title didn't follow the
    # common convention.
    name = re.sub(r"^Show HN:\s*", "", title).strip()
    return name, ""


def _extract_github_url(text: str) -> Optional[str]:
    # Looks for a GitHub repo link anywhere in the title/body/comment text,
    # not just the post's primary URL — founders sometimes link their repo
    # in the post body while the primary "url" field points at a landing
    # page instead. rstrip() cleans up trailing punctuation a sentence
    # might leave attached to the URL (e.g. "...github.com/foo/bar.").
    m = re.search(r"https?://github\.com/[\w.-]+/[\w.-]+", text or "")
    return m.group(0).rstrip(".,)") if m else None


def source_show_hn(topic: str, limit: int = 15, min_points: int = 0) -> list[Candidate]:
    """Query HN for Show HN posts matching `topic`.

    Args:
        topic: free-text query, e.g. "AI agents for SMBs"
        limit: max candidates to return (assignment asks for 10-20)
        min_points: optional floor on HN points to filter out zero-signal posts

    Returns:
        list[Candidate], deduplicated by name, ordered by points desc.
    """
    params = {
        "tags": "show_hn",
        "query": topic,
        # Over-fetch on purpose: not every hit is going to be a genuine
        # Show HN post with a parseable title (some are "Ask HN" mixed
        # into results, some fail the dedup check), so we ask Algolia for
        # 3x what we need and filter down, rather than under-fetching and
        # returning fewer candidates than the assignment's 10-20 target.
        "hitsPerPage": max(limit * 3, 30),
    }
    resp = requests.get(HN_SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()  # fail loudly here — a broken HN query should stop the run, not silently return zero candidates
    hits = resp.json().get("hits", [])

    candidates: list[Candidate] = []
    seen_names: set[str] = set()

    for hit in hits:
        title = hit.get("title") or ""
        if not title.startswith("Show HN"):
            # Algolia's "show_hn" tag is usually accurate but not
            # perfectly exclusive; this is a cheap, explicit second check
            # rather than trusting the API's tagging blindly.
            continue
        points = hit.get("points") or 0
        if points < min_points:
            continue

        name, one_liner = _parse_title(title)
        key = name.lower().strip()
        if not name or key in seen_names:
            # Same startup sometimes gets multiple Show HN posts (relaunch,
            # different framing) — keep only the first (highest-points,
            # since we sort by points below... but at parse time the list
            # isn't sorted yet, so this just prevents an obvious exact-name
            # duplicate; it's a cheap safeguard, not a perfect one).
            continue
        seen_names.add(key)

        # Prefer the post's primary URL as the "website"; if that URL is
        # itself a GitHub link, don't also call it the website — it'll be
        # captured as github_url instead, which is the more accurate field.
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        story_text = hit.get("story_text") or ""
        comment_text = hit.get("comment_text") or ""
        # raw_text is the single field the LLM is told to ground every
        # claim in during analysis — concatenating title + body + top
        # comment maximizes what's available without a second HTTP call
        # per candidate (Algolia's search response already includes these).
        raw_text = " ".join([title, story_text, comment_text]).strip()

        candidates.append(
            Candidate(
                name=name,
                website=url if not url.startswith("https://github.com") else None,
                one_liner=one_liner or "(no description found in HN post title)",
                source="hn_show_hn",
                # source_url always points at the HN item page (not the
                # external site), because that's the one link guaranteed
                # to keep working and to show a reviewer exactly what we saw.
                source_url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                founder_signal=f"HN user: {hit.get('author')}" if hit.get("author") else None,
                traction_signal=f"{points} HN points, {hit.get('num_comments') or 0} comments",
                github_url=_extract_github_url(url) or _extract_github_url(raw_text),
                raw_text=raw_text,
            )
        )
        if len(candidates) >= limit:
            break

    # Sorted by points as a string is intentional-adjacent-but-actually-a-bug-risk:
    # traction_signal is a formatted string like "142 HN points, 38 comments",
    # and Python's string sort on that will not sort numerically. Left as-is
    # here would silently misorder anything with a different digit count
    # (e.g. "9 HN points" vs "142 HN points"). Sorting on the numeric
    # `points` value from the API response instead avoids that bug.
    candidates.sort(key=lambda c: int(c.traction_signal.split()[0]), reverse=True)
    return candidates
