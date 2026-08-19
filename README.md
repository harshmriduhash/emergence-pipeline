# AI-Augmented Investment Pipeline

An automated triage tool for a seed-stage VC firm. It takes a topic
("AI agents for SMBs"), goes and finds real startups launching in that
space right now, scores each one against a fixed, written-down investment
thesis, and hands back a one-page Pass / Watch / Take-a-meeting memo per
startup — with every claim in the memo traceable back to where it came
from.

## What problem this solves

Partners at an early-stage VC firm spend hours a week manually scanning
Hacker News, Product Hunt, Twitter, Crunchbase, and similar sources for
promising new companies, then writing a memo by hand for each one worth a
second look. Most of what they find gets passed on — this is fundamentally
a triage problem, not a decision problem. This tool automates the triage
layer: it does the scanning and the first-pass write-up, so a partner's
time goes toward the small number of companies that clear the bar, not
toward reading and rejecting the other 90%.

## Who it's for

A VC partner (or anyone doing structured startup screening) who wants:
- A fast, repeatable way to sweep a topic for new launches
- A consistent scoring lens applied to every candidate, not vibes that
  shift from one company to the next
- A memo they can trust and skim in under a minute, with sources they can
  actually check if something looks off

## How it works, end to end

The pipeline has three stages, each one doing exactly one job and handing
its output to the next stage as a file on disk. No stage reaches back into
a previous stage's internals — the only thing passed forward is the file.

```
   "AI agents for SMBs"
            |
            v
   ┌─────────────────┐
   │  1. SOURCE       │   Queries Hacker News (Show HN launches) for the
   │  source_hn.py    │   topic. For each real match, pulls out a name,
   │                  │   one-line description, and a traction signal
   │                  │   (HN points + comments) — all straight from the
   │                  │   post itself, nothing invented.
   └────────┬─────────┘
            │  outputs/raw/<topic>.json
            v
   ┌─────────────────┐
   │  Enrich (GitHub) │   If the launch links a GitHub repo, pulls star
   │  enrich_github.py│   count and last-push date as a second, independent
   │                  │   freshness signal. Optional — skipped silently if
   │                  │   no repo link exists or GitHub can't be reached.
   └────────┬─────────┘
            v
    ┌─────────────────┐
    │  2. ANALYZE      │   Sends the candidate's raw data + a fixed
    │  analyze.py      │   thesis + scoring rubric to Groq. Gets back a
    │                  │   structured score (5 dimensions, 0-100 total), a
    │                  │   verdict, and — critically — a note on which
    │                  │   input field grounds every claim it makes.
    │                  │   Anything malformed gets rejected and the
    │                  │   candidate is skipped, not guessed at.
    └────────┬─────────┘
            │  outputs/analysis/<name>.json
            v
   ┌─────────────────┐
   │  3. MEMO         │   Turns the structured analysis into a one-page
   │  memo.py         │   markdown memo. Verdict and reasoning go first,
   │                  │   above the fold — a partner should know the call
   │                  │   within the first two lines, not after scrolling
   │                  │   through the whole document.
   └────────┬─────────┘
            v
   outputs/memos/<name>.md   <-- what a partner actually reads
```

`run.py` is the one command that drives all three stages in order. Every
intermediate output is written to disk and cached, so if you edit the
analysis prompt and re-run, sourcing isn't repeated — you only pay for
what actually changed. This is what makes the pipeline **replayable**:
anyone can re-run any stage independently and get the same result, or
tweak one stage and re-run just the stages downstream of it.

### The thesis — the one thing every score is measured against

Every candidate is judged against a single, specific thesis, not a vague
"is this a good company" gut check:

> We back agentic AI tools that replace one specific, currently-manual
> workflow for a non-technical SMB operator — not general-purpose
> copilots — and that show real usage or traction signal within weeks of
> shipping.

Full rubric with weights is in [`prompts/thesis.md`](prompts/thesis.md).
The thesis is intentionally narrow: it's possible — expected, even — for
a genuinely interesting startup to fail it, because it isn't the kind of
company this firm is trying to find. That specificity is what makes the
resulting 0-100 score mean something.

### Why Hacker News, and only Hacker News

The assignment calls for picking one or two sources and going deep, rather
than scraping five sources shallowly. Show HN launch posts were picked
because:
- They're free to query, no API key required (Algolia's HN Search API)
- The post title itself reliably contains a name and a one-line
  description — no scraping or guessing needed
- Points and comment count are a real, immediate traction signal, on the
  exact same API call — no second request needed
- Self-reported "just shipped" launches are closer to the pre-radar
  companies a partner actually wants surfaced, versus a source like
  Crunchbase that mostly reflects companies already funded and covered

GitHub is used as an *enrichment* on top of this, not a second source — it
only kicks in when a candidate's post happens to link a repo, and it's
allowed to fail silently. That keeps the sourcing to one deep well
instead of several shallow, unreliable ones.

## What you get out

Three directories, all committed to this repo so a reviewer can read
everything without having to run anything themselves:

| Directory | Contents |
|---|---|
| `outputs/raw/<topic>.json` | Every sourced candidate, exactly as pulled from HN + GitHub, before any AI judgment touches it |
| `outputs/analysis/<name>.json` | The structured, thesis-scored analysis Groq produced for one candidate, already validated |
| `outputs/memos/<name>.md` | The final one-page memo — what a partner actually reads |

Because the raw and analysis files are also committed, you can trace any
line in a memo all the way back to the exact HN post or GitHub API
response it came from, without re-running anything.

## Setup

Requires Python 3.10+ and a Groq API key (the analysis stage calls
Groq — sourcing itself needs no key).

```bash
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...
```

(or copy `.env.example` to `.env` and fill it in, then load it however
your shell prefers — the pipeline itself just reads the env var directly)

## Running it

```bash
python run.py --topic "AI agents for SMBs" --limit 15
```

That single command runs all three stages and prints progress as it goes:

```
[source] querying HN Show HN for: 'AI agents for SMBs'
[source] found 14 candidates, enriching with GitHub where possible
[source] wrote outputs/raw/ai-agents-for-smbs.json
[analyze] scoring: Ledgerly
[analyze] scoring: ...
[memo] wrote outputs/memos/ledgerly.md  -> Take a meeting
...
Done. 14 memos written to outputs/memos/
  Take a meeting: 2  |  Watch: 5  |  Pass: 7
```

### Options

| Flag | What it does |
|---|---|
| `--topic` (required) | Free-text query, e.g. `"AI agents for SMBs"` |
| `--limit` | Max candidates to source, default 15 (assignment target: 10-20) |
| `--min-points` | Skip HN posts below this point threshold — useful for filtering out zero-traction noise |
| `--refresh` | Ignore all cached output and re-fetch/re-analyze from scratch |

### Re-running without re-paying for everything

Every stage caches its output by default. If you only want to change how
candidates are *scored* (e.g. you edited `prompts/analysis_prompt.md` or
`prompts/thesis.md`), delete just the analysis cache and re-run — sourcing
is skipped automatically since `outputs/raw/<topic>.json` still exists:

```bash
rm outputs/analysis/*.json outputs/memos/*.md
python run.py --topic "AI agents for SMBs"
```

To force a full refresh of everything, including re-querying HN:

```bash
python run.py --topic "AI agents for SMBs" --refresh
```

## Running the tests

```bash
pytest tests/ -v
```

15 tests, covering:
- HN title parsing, including the malformed/no-separator fallback path
- Filtering out non-Show-HN posts and duplicate names
- Correct numeric (not lexicographic-string) sorting by traction
- Memo rendering, including how empty lists (no risks found, no data
  gaps) render as an explicit "none identified" rather than a blank section
- LLM analysis parsing, schema validation, and error isolation (`test_analyze.py`)

The analysis stage (the actual LLM call) isn't covered by a live-API test
— instead it's protected by schema validation
(`pipeline/analyze.py::_validate`), which rejects any model response
missing a required field, using an invalid verdict string, or containing
an out-of-range score, before that response is ever allowed to reach a memo.

## Project layout

```
run.py                      # the one entry point — orchestrates all 3 stages
pipeline/
  models.py                 # Candidate / ScoreBreakdown / Analysis data shapes
  source_hn.py               # Stage 1: pulls candidates from HN
  enrich_github.py            # Optional enrichment: GitHub stars/last-push
  analyze.py                 # Stage 2: LLM scoring + validation
  memo.py                    # Stage 3: renders the final markdown memo
prompts/
  thesis.md                  # the investment thesis + scoring rubric (read this first)
  analysis_prompt.md          # the exact, unedited prompt sent to the LLM (Groq)
tests/
  test_source_hn.py          # HN parsing/filtering/sorting tests
  test_memo.py                # memo rendering tests
  test_analyze.py             # Groq LLM scoring & schema validation tests
  fixtures/                   # sample HN API response used by the tests
outputs/
  raw/                        # sourced candidates, per topic
  analysis/                   # scored analysis, per candidate
  memos/                      # final memos, per candidate
DECISIONS.md                 # build log — what was decided, in what order, and why
NOTES.md                     # process reflection (see note below)
```

## A note on `DECISIONS.md` vs `NOTES.md`

These serve different purposes and shouldn't be confused for each other:

- **`DECISIONS.md`** is a factual technical log — what was built, in what
  order, what was rejected and why, including a real bug (a string-vs-
  numeric sort, and a live GitHub rate-limit hit) that surfaced during
  development.
- **`NOTES.md`** covers the process reflection — how the work was actually
  approached, key engineering trade-offs, handling real data surprises, and
  reflections on working alongside AI tools.

## Known limitations

- GitHub enrichment uses unauthenticated API calls, which have a low rate
  limit per IP (this was discovered during testing, not assumed). Add a
  `GITHUB_TOKEN` and pass it as an `Authorization` header in
  `enrich_github.py` if you need it to work reliably across a large batch.
- Sourcing is Hacker News only. A topic with no recent Show HN activity
  will legitimately return zero candidates — that's a coverage gap of the
  source, not a pipeline bug (the tool warns explicitly when this happens).
- The thesis is fixed at scoring time from `prompts/thesis.md`. Changing
  the thesis after some candidates are already analyzed means old and new
  analyses aren't scored on the same rubric until you delete the old
  cache and re-run.
