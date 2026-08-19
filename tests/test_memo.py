from pipeline.models import Candidate, Analysis, ScoreBreakdown
from pipeline.memo import render_memo


def _sample_candidate():
    return Candidate(
        name="Ledgerly",
        website="https://ledgerly.example.com",
        one_liner="AI bookkeeper that reconciles books nightly",
        source="hn_show_hn",
        source_url="https://news.ycombinator.com/item?id=1001",
        traction_signal="142 HN points, 38 comments",
    )


def _sample_analysis():
    return Analysis(
        candidate_name="Ledgerly",
        team="Founders previously ran a bookkeeping service; no prior exit found.",
        product="Nightly AI reconciliation of small-business books against bank feeds.",
        market="SMB bookkeeping is a large, fragmented, manual market.",
        risks=["Data accuracy in reconciliation is unforgiving", "Bank feed integrations are brittle"],
        scores=ScoreBreakdown(
            workflow_specificity=26, buyer_fit=18, traction_signal=20,
            team_credibility=9, market_why_now=7,
        ),
        verdict="Take a meeting",
        verdict_rationale="Specific workflow, non-technical buyer, strong HN traction.",
        change_my_mind=["Customer retention data", "Bank integration reliability at scale"],
        claims_with_sources=[{"claim": "142 HN points", "source": "traction_signal"}],
        data_gaps=["No funding history found"],
    )


def test_render_memo_includes_verdict_above_fold():
    memo = render_memo(_sample_candidate(), _sample_analysis())
    verdict_idx = memo.index("Verdict: Take a meeting")
    team_idx = memo.index("## Team")
    assert verdict_idx < team_idx  # verdict must appear before the detail sections


def test_render_memo_includes_score_total():
    memo = render_memo(_sample_candidate(), _sample_analysis())
    assert "**80**" in memo  # 26+18+20+9+7


def test_render_memo_handles_empty_lists_gracefully():
    c = _sample_candidate()
    a = _sample_analysis()
    a.risks = []
    a.change_my_mind = []
    a.data_gaps = []
    a.claims_with_sources = []
    memo = render_memo(c, a)
    assert "(none identified)" in memo
    assert "none" in memo.lower()
