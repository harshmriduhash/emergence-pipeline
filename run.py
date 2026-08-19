#!/usr/bin/env python3
"""One command, topic in, memos out.

    python run.py --topic "AI agents for SMBs" --limit 15

Each stage writes its output to disk before the next stage runs, and each
stage will reuse what's already on disk unless --refresh is passed. That's
the whole "replayable" requirement from the assignment: you can re-run
analyze/memo alone after tweaking the prompt, without re-hitting HN and
burning a new set of API calls for data you already have.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pipeline.source_hn import source_show_hn
from pipeline.enrich_github import enrich_with_github
from pipeline.analyze import analyze_candidate, AnalysisError
from pipeline.memo import render_memo
from pipeline.models import Candidate, Analysis

# Three flat output directories, one per stage — mirrors the pipeline's
# three named stages 1:1, so "where did stage X's output go" is never a
# question you have to look up.
OUT_RAW = Path("outputs/raw")
OUT_ANALYSIS = Path("outputs/analysis")
OUT_MEMOS = Path("outputs/memos")


def slugify(name: str) -> str:
    # Used for both the topic (raw file name) and each candidate name
    # (analysis/memo file names) — a single shared function so a startup
    # called e.g. "Foo & Bar!" always maps to the exact same filename
    # across all three stages, which is what makes the per-stage caching
    # in stage_analyze/stage_memo actually line up.
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "-", s) or "unnamed"


def stage_source(topic: str, limit: int, min_points: int, refresh: bool) -> list[Candidate]:
    raw_path = OUT_RAW / f"{slugify(topic)}.json"
    if raw_path.exists() and not refresh:
        # Cache hit: reload from disk instead of re-querying HN. This is
        # what makes a re-run of `python run.py --topic "..."` free and
        # instant if you're only iterating on the analysis prompt.
        print(f"[source] reusing {raw_path} (--refresh to re-fetch)")
        data = json.loads(raw_path.read_text())
        candidates = [Candidate.from_dict(c) for c in data]
    else:
        print(f"[source] querying HN Show HN for: {topic!r}")
        candidates = source_show_hn(topic, limit=limit, min_points=min_points)
        print(f"[source] found {len(candidates)} candidates, enriching with GitHub where possible")
        # Enrichment happens here, once, before caching to disk — so a
        # cached raw file already includes GitHub data and doesn't need
        # network calls again on reuse, even with --refresh off.
        candidates = [enrich_with_github(c) for c in candidates]
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps([c.to_dict() for c in candidates], indent=2))
        print(f"[source] wrote {raw_path}")

    if not candidates:
        # A loud warning rather than a silent empty list — a zero-result
        # run should be obviously visible in the terminal output, since
        # it usually means the topic string is too narrow, not that
        # there are genuinely zero relevant startups on HN.
        print("[source] WARNING: zero candidates found. Try a broader topic or lower --min-points.")
    return candidates


def stage_analyze(candidates: list[Candidate], refresh: bool) -> list[tuple[Candidate, Analysis]]:
    results = []
    OUT_ANALYSIS.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        # Cached per-candidate, not per-batch — so if candidate #7 out of
        # 15 fails validation, candidates #1-6 and #8-15 that already
        # succeeded don't need to be re-analyzed (and re-billed) on the
        # next run; only the failed one gets retried.
        out_path = OUT_ANALYSIS / f"{slugify(c.name)}.json"
        if out_path.exists() and not refresh:
            print(f"[analyze] reusing {out_path}")
            analysis = Analysis.from_dict(json.loads(out_path.read_text()))
        else:
            print(f"[analyze] scoring: {c.name}")
            try:
                analysis = analyze_candidate(c)
            except AnalysisError as e:
                # Printed to stderr (not stdout) and the loop continues —
                # this is the "skip and log, don't crash the batch"
                # behavior the README documents. One malformed LLM
                # response should cost you one memo, not the whole run.
                print(f"[analyze] SKIPPING {c.name}: {e}", file=sys.stderr)
                continue
            out_path.write_text(json.dumps(analysis.to_dict(), indent=2))
        results.append((c, analysis))
    return results


def stage_memo(results: list[tuple[Candidate, Analysis]]) -> None:
    OUT_MEMOS.mkdir(parents=True, exist_ok=True)
    for c, a in results:
        # No caching check here, unlike the two stages above — memo
        # rendering is cheap, pure string formatting with no network or
        # LLM call, so there's no cost to always regenerating it. This
        # also means editing memo.py's template and re-running instantly
        # refreshes every memo without needing a --refresh flag for this
        # stage specifically.
        memo_text = render_memo(c, a)
        out_path = OUT_MEMOS / f"{slugify(c.name)}.md"
        out_path.write_text(memo_text)
        print(f"[memo] wrote {out_path}  -> {a.verdict}")


def main():
    parser = argparse.ArgumentParser(description="Seed-stage sourcing/analysis/memo pipeline")
    parser.add_argument("--topic", required=True, help='e.g. "AI agents for SMBs"')
    parser.add_argument("--limit", type=int, default=15, help="max candidates to source (10-20)")
    parser.add_argument("--min-points", type=int, default=0, help="floor on HN points")
    parser.add_argument("--refresh", action="store_true", help="re-fetch/re-analyze, ignore cached outputs")
    args = parser.parse_args()

    candidates = stage_source(args.topic, args.limit, args.min_points, args.refresh)
    if not candidates:
        # Exit cleanly (code 0, not an error) on zero candidates — an
        # empty result for a valid-but-narrow topic isn't a pipeline
        # failure, so it shouldn't look like one to a calling script.
        sys.exit(0)

    results = stage_analyze(candidates, args.refresh)
    stage_memo(results)

    # A one-line summary at the end so a partner running this doesn't have
    # to open every memo just to see the shape of the batch (how many
    # worth a meeting vs. worth watching vs. passed on).
    took_meeting = [c for c, a in results if a.verdict == "Take a meeting"]
    watch = [c for c, a in results if a.verdict == "Watch"]
    print(f"\nDone. {len(results)} memos written to {OUT_MEMOS}/")
    print(f"  Take a meeting: {len(took_meeting)}  |  Watch: {len(watch)}  |  Pass: {len(results) - len(took_meeting) - len(watch)}")


if __name__ == "__main__":
    main()
