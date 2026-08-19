# Build log

This pipeline was built in a working session with Claude, in the order
below. Documenting it plainly rather than after the fact, per the
assignment's ground rules.

## 1. Thesis, before any code

Started here on purpose — every other decision (which source, what the
score schema looks like, what counts as a red flag) is downstream of the
thesis. Landed on: agentic tools that replace one named manual SMB
workflow for a non-technical buyer, with real early traction — not a
"good companies" thesis, deliberately narrow enough to fail a company on.
Full rubric in `prompts/thesis.md`.

Rejected alternative: scoring generically on "team quality + market size,"
which was the assignment's explicit example of a thesis that's too broad
to be meaningful. Dropped it for that reason.

## 2. Source selection

Considered Product Hunt, YC directory, HN, Twitter/X, Crunchbase (the
assignment's suggested list). Picked HN Show HN posts as the single deep
source:
- Free, no API key, structured JSON via Algolia's HN Search API
- Title format ("Show HN: Name – description") gives name + one-liner for
  free, without scraping
- Points/comments are a traction signal on the same request, no second
  call needed
- Self-reported launches skew toward exactly the "just shipped, non-VC
  legible" candidates worth triaging, rather than already-funded/covered
  companies a partner would have already seen on Crunchbase

GitHub was added as *enrichment*, not a second source — only pulled when
a candidate's post links a repo, and it fails silently (see below) rather
than blocking a candidate without one. This avoids the "12 sources, 2
garbage results each" anti-pattern the assignment calls out by name.

## 3. Architecture

Three stages, each a pure function over the previous stage's disk output
(`source_hn.py` -> `analyze.py` -> `memo.py`), orchestrated by `run.py`.
No DB, no queue, no frontend — the assignment says to stop if you're
building those, and files-on-disk is sufficient for "replayable."

Each stage caches to `outputs/` and skips re-running unless `--refresh` is
passed. This came from wanting to iterate on the analysis prompt without
re-querying HN every time — burns real API calls otherwise.

## 4. Claim traceability

The assignment calls out "claims in memos with no traceable source" as an
anti-pattern. Handled it structurally rather than by instruction alone:
the analysis prompt (`prompts/analysis_prompt.md`) requires every claim to
name which input field grounds it, and `pipeline/analyze.py::_validate`
rejects the model's response if required fields or valid score ranges are
missing — a malformed analysis gets skipped and logged, not silently
included with best-guess defaults.

## 5. A real bug the live test caught

While testing `enrich_github.py` against a real public repo
(anthropics/anthropic-sdk-python), the call returned a 403 — unauthenticated
GitHub API rate limits are low enough to hit from a shared IP within a
handful of calls. This wasn't a hypothetical edge case invented for the
tests; it happened on the first live call. Confirmed the enrichment
function degrades correctly (returns the candidate unchanged, no
exception) rather than crashing the sourcing stage — which is exactly the
"robust to bad or missing data" requirement, exercised for real rather
than mocked.

Practical implication for real usage: expect GitHub enrichment to be
sparse unless you add a `GITHUB_TOKEN` for a higher rate limit — not done
here since it's optional enrichment, not a required signal.

## 6. What was cut

- Twitter/X and Crunchbase: no free/stable API access without a paid tier
  or scraping fragile enough to violate "public sources only, free tiers
  fine" in spirit.
- A confidence/uncertainty score separate from the 0-100 thesis score:
  considered it, cut it — `data_gaps` in the analysis schema does the same
  job (flag what couldn't be evaluated) without a second number to explain.
- Retrying failed LLM calls: skip-and-log was chosen over retry-with-
  backoff for a v1 — a partner re-running the command is a fine retry
  mechanism at this scale (10-20 candidates), and it keeps `analyze.py`
  simple.

## 7. Migration from Anthropic to Groq

Migrated the LLM analysis stage from Anthropic (`anthropic` library, `ANTHROPIC_API_KEY`, Claude models) to Groq (`groq` library, `GROQ_API_KEY`, default model `llama-3.3-70b-versatile`).

Key updates:
- Dependency updated in `requirements.txt` from `anthropic` to `groq`.
- Environment variable updated from `ANTHROPIC_API_KEY` to `GROQ_API_KEY` in `.env` and `.env.example`.
- `pipeline/analyze.py` updated to use `groq.Groq` client and OpenAI-compatible `chat.completions.create` API format.
- Unit test suite expanded with `tests/test_analyze.py` to cover `analyze_candidate` with mocked Groq responses.

