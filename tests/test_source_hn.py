import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.source_hn import source_show_hn, _parse_title, _extract_github_url

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "hn_sample_response.json").read_text())


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_parse_title_standard_format():
    name, desc = _parse_title("Show HN: Ledgerly \u2013 AI bookkeeper that reconciles books")
    assert name == "Ledgerly"
    assert desc == "AI bookkeeper that reconciles books"


def test_parse_title_hyphen_variant():
    name, desc = _parse_title("Show HN: Foo - a thing that does stuff")
    assert name == "Foo"
    assert desc == "a thing that does stuff"


def test_parse_title_no_separator_falls_back_gracefully():
    name, desc = _parse_title("Show HN: Malformed Title With No Dash Separator")
    assert name == "Malformed Title With No Dash Separator"
    assert desc == ""  # must NOT fabricate a description


def test_extract_github_url_found():
    assert _extract_github_url("check it out at https://github.com/foo/bar!") == "https://github.com/foo/bar"


def test_extract_github_url_absent():
    assert _extract_github_url("no repo link here") is None


@patch("pipeline.source_hn.requests.get")
def test_source_show_hn_filters_and_parses(mock_get):
    mock_get.return_value = _FakeResponse(FIXTURE)
    candidates = source_show_hn("AI agents for SMBs", limit=10)

    names = [c.name for c in candidates]
    assert "Ledgerly" in names
    # Ask HN post must be filtered out (not a Show HN)
    assert not any("What AI tools" in c.one_liner for c in candidates)
    # sorted by traction (points) descending -> Ledgerly (142) before the codebot (12)
    assert names.index("Ledgerly") < names.index("I built an AI code review bot for enterprise teams")


@patch("pipeline.source_hn.requests.get")
def test_source_show_hn_respects_min_points(mock_get):
    mock_get.return_value = _FakeResponse(FIXTURE)
    candidates = source_show_hn("AI agents for SMBs", limit=10, min_points=50)
    assert all(c.name != "Malformed Title With No Dash Separator" for c in candidates)
    assert len(candidates) == 1  # only Ledgerly clears 50 points


@patch("pipeline.source_hn.requests.get")
def test_source_show_hn_empty_hits_returns_empty_list(mock_get):
    mock_get.return_value = _FakeResponse({"hits": []})
    candidates = source_show_hn("nonsense topic xyz", limit=10)
    assert candidates == []


@patch("pipeline.source_hn.requests.get")
def test_source_show_hn_sorts_numerically_not_lexicographically(mock_get):
    # Regression test: a naive `sort(key=lambda c: c.traction_signal)` sorts
    # the formatted string, so "9 HN points" would incorrectly rank above
    # "142 HN points" (string comparison of "9" vs "1" is not comparing
    # point counts). Candidates below are crafted so a string sort and a
    # numeric sort disagree, to prove we're doing the numeric one.
    fixture = {
        "hits": [
            {
                "title": "Show HN: LowButLex \u2013 sorts high as a string, low as a number",
                "url": "https://a.example.com", "author": "a", "points": 9,
                "num_comments": 1, "objectID": "1", "story_text": "", "comment_text": None,
            },
            {
                "title": "Show HN: HighButLex \u2013 sorts low as a string, high as a number",
                "url": "https://b.example.com", "author": "b", "points": 142,
                "num_comments": 1, "objectID": "2", "story_text": "", "comment_text": None,
            },
        ]
    }
    mock_get.return_value = _FakeResponse(fixture)
    candidates = source_show_hn("test", limit=10)
    assert [c.name for c in candidates] == ["HighButLex", "LowButLex"]
