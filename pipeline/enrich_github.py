"""Enrichment: adds a GitHub freshness/traction signal when a candidate's
HN post links a repo.

This is intentionally optional and silent-fail — most Show HN posts link
a product site, not a repo, and the assignment explicitly wants the
pipeline "robust to bad or missing data" rather than erroring out on it.
A candidate with no GitHub link, or a repo that's private/deleted/rate-
limited, should still make it all the way to a memo — just without this
one extra signal.
"""
from __future__ import annotations

import re
import requests

from pipeline.models import Candidate

# {owner}/{repo} slots get filled from whatever GitHub URL source_hn.py found.
GITHUB_API = "https://api.github.com/repos/{owner}/{repo}"


def _parse_owner_repo(github_url: str) -> tuple[str, str] | None:
    # Pulls owner/repo out of any github.com URL shape (with or without a
    # trailing .git, with or without a protocol prefix already stripped
    # upstream). Returns None instead of raising if the URL doesn't match
    # the expected shape — callers treat that the same as "no GitHub link."
    m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", github_url)
    if not m:
        return None
    # .git suffix shows up when someone links a clone URL instead of the
    # repo's web page; strip it so the API call targets the right slug.
    return m.group(1), m.group(2).removesuffix(".git")


def enrich_with_github(candidate: Candidate) -> Candidate:
    if not candidate.github_url:
        # Most candidates take this path — no repo link found during
        # sourcing, so there's nothing to enrich. Returning immediately
        # keeps this a no-op rather than a wasted API call.
        return candidate

    parsed = _parse_owner_repo(candidate.github_url)
    if not parsed:
        # URL matched "github.com" but not the owner/repo pattern (e.g. a
        # link to a GitHub org page, gist, or issue). Not enough to build
        # a valid API call, so skip rather than guess.
        return candidate
    owner, repo = parsed

    try:
        resp = requests.get(
            GITHUB_API.format(owner=owner, repo=repo),
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if resp.status_code != 200:
            # Covers private repos (404), renamed/deleted repos (404), and
            # rate limiting (403) with one branch — in every one of these
            # cases the correct behavior is the same: keep the candidate,
            # just without GitHub data. This was exercised for real during
            # development: an unauthenticated call from a shared sandbox IP
            # hit GitHub's rate limit on the very first live test, and this
            # branch is what kept that from crashing the whole sourcing run.
            return candidate
        data = resp.json()
    except requests.RequestException:
        # Network-level failure (timeout, DNS, connection reset) — same
        # policy as an HTTP error above: enrichment is best-effort, never
        # load-bearing for the pipeline to keep running.
        return candidate

    candidate.github_stars = data.get("stargazers_count")
    candidate.github_last_push = data.get("pushed_at")
    if candidate.github_stars is not None:
        # Append rather than replace, so the HN traction signal (points,
        # comments) is never lost even when GitHub enrichment succeeds —
        # the memo should be able to show both signals side by side.
        extra = f", {candidate.github_stars} GitHub stars (pushed {candidate.github_last_push})"
        candidate.traction_signal = (candidate.traction_signal or "").rstrip() + extra

    return candidate
