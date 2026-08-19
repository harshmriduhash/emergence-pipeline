# Process Reflection & AI Workflow Notes

`DECISIONS.md` covers the step-by-step technical log. This document outlines the engineering decisions, trade-offs, and reflections from building and iterating on this pipeline alongside AI tools.

---

## 1. Where I Overrode or Redirected AI Suggestions

- **Flat File System vs. Database**: AI assistants often default to suggesting SQLite or ORMs for data pipeline storage. I explicitly opted for a flat file-based workflow (`outputs/raw/`, `outputs/analysis/`, `outputs/memos/`). This keeps every stage 100% replayable, transparent, and directly diffable in Git without needing local DB setup.
- **Provider & SDK Migration**: When migrating from Anthropic (`anthropic`) to Groq (`groq`), I ensured we used Groq's standard SDK while retaining our strict output validation layer (`pipeline/analyze.py::_validate`). Rather than trusting LLM outputs blindly, every model response is validated against exact score bounds and schema requirements before being saved.

---

## 2. What I Intentionally Didn't Build (and Why)

- **Multi-source Scraping (Twitter/X, Crunchbase)**: While multi-source coverage sounds attractive on paper, Twitter and Crunchbase lack free, stable public APIs. Building fragile web scrapers would introduce silent runtime failures. I chose to go deep on Hacker News Algolia search + GitHub enrichment, ensuring high data reliability.
- **Async Job Queues / Web Frameworks**: The assignment explicitly cautions against overengineering. A CLI script with clear stage caching achieves the exact replayability partners need without the operational overhead of Celery, Redis, or web UI servers.

---

## 3. What Surprised Me Running Against Real Data

- **GitHub Unauthenticated Rate Limits**: Running against real repos immediately surfaced GitHub's strict 60 req/hr unauthenticated rate limit (HTTP 403). This reinforced the necessity of graceful degradation — candidate enrichment fails quietly and preserves the candidate rather than failing the batch.
- **LLM Schema Deviations & Reasoning Blocks**: Some models (such as reasoning/thinking models) wrapped output in `<think>` tags or occasionally scored individual rubric dimensions on a 0–100 scale rather than their specific dimension caps (e.g. 0–20 for Buyer Fit). Implementing defensive JSON cleaning and validation (`_validate()`) proved critical so malformed model output gets skipped and logged rather than corrupting investment memos.

---

## 4. What I Would Build Next With More Time

1. **Automatic Rate-Limit Backoff**: Implement exponential backoff for LLM API calls to gracefully handle potential 429 rate limits during large batch runs.
2. **Authenticated GitHub Enrichment**: Add optional `GITHUB_TOKEN` support to enable deeper metric collection (commit velocity, open issue resolution time) beyond unauthenticated API limits.
