import pytest

from rss_watcher.handlers import ParseError, parse_add_args


def test_url_only():
    r = parse_add_args("https://hnrss.org/newest")
    assert (r.url, r.keywords, r.exclude) == ("https://hnrss.org/newest", [], [])


def test_keywords_and_exclude():
    r = parse_add_args("https://x.com/rss | python, bot | senior")
    assert r.keywords == ["python", "bot"] and r.exclude == ["senior"]


def test_exclude_only():
    r = parse_add_args("https://x.com/rss |  | crypto")
    assert r.keywords == [] and r.exclude == ["crypto"]


@pytest.mark.parametrize(
    "bad", ["", "  ", "hnrss.org/newest", "ftp://x.com/rss", "https://x | a | b | c", "https://x | " + "a" * 60]
)
def test_errors(bad):
    with pytest.raises(ParseError):
        parse_add_args(bad)


def test_only_first_line_is_used():
    r = parse_add_args("https://hnrss.org/newest | python, ai\n/last")
    assert r.keywords == ["python", "ai"]
