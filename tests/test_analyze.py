import json
from unittest.mock import MagicMock
import pytest

from pipeline.models import Candidate
from pipeline.analyze import analyze_candidate, AnalysisError


def _sample_candidate() -> Candidate:
    return Candidate(
        name="Ledgerly",
        website="https://ledgerly.example.com",
        one_liner="AI bookkeeper that reconciles books nightly",
        source="hn_show_hn",
        source_url="https://news.ycombinator.com/item?id=1001",
        traction_signal="142 HN points, 38 comments",
    )


def test_analyze_candidate_success():
    valid_payload = {
        "candidate_name": "Ledgerly",
        "team": "Founders previously ran a bookkeeping service.",
        "product": "Nightly AI reconciliation of small-business books.",
        "market": "SMB bookkeeping market.",
        "risks": ["Data accuracy risk"],
        "scores": {
            "workflow_specificity": 26,
            "buyer_fit": 18,
            "traction_signal": 20,
            "team_credibility": 9,
            "market_why_now": 7,
        },
        "verdict": "Take a meeting",
        "verdict_rationale": "Strong workflow focus and clear buyer fit.",
        "change_my_mind": ["Customer retention data"],
        "claims_with_sources": [{"claim": "142 HN points", "source": "traction_signal"}],
        "data_gaps": ["No funding history found"],
    }

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(valid_payload)
    mock_client.chat.completions.create.return_value.choices = [mock_choice]

    analysis = analyze_candidate(_sample_candidate(), client=mock_client)

    assert analysis.candidate_name == "Ledgerly"
    assert analysis.verdict == "Take a meeting"
    assert analysis.scores.workflow_specificity == 26
    mock_client.chat.completions.create.assert_called_once()


def test_analyze_candidate_invalid_json():
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "This is not valid JSON"
    mock_client.chat.completions.create.return_value.choices = [mock_choice]

    with pytest.raises(AnalysisError, match="model did not return valid JSON"):
        analyze_candidate(_sample_candidate(), client=mock_client)


def test_analyze_candidate_validation_failure():
    invalid_payload = {
        "candidate_name": "Ledgerly",
        "team": "Founders previously ran a bookkeeping service.",
        "verdict": "Invalid Verdict Option",
    }

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(invalid_payload)
    mock_client.chat.completions.create.return_value.choices = [mock_choice]

    with pytest.raises(AnalysisError, match="missing required fields"):
        analyze_candidate(_sample_candidate(), client=mock_client)
