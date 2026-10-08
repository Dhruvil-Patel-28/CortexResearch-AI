"""Offline tests for source adapters (parse functions run against fixtures)."""

from __future__ import annotations

from sources.arxiv import build_query, parse_arxiv_feed
from sources.base import FeedItem
from sources.github_trending import parse_github_search
from sources.hackernews import parse_hn_item
from sources.reddit import parse_reddit_rss
from sources.rss import load_feeds, parse_rss_feed, strip_html

# ─── Hacker News ───

HN_ITEM = {
    "by": "tosh",
    "descendants": 214,
    "id": 12345678,
    "score": 412,
    "time": 1717603200,
    "title": "Show HN: An open-source agent framework",
    "type": "story",
    "url": "https://example.com/agent-framework",
}


def test_parse_hn_item_ok():
    item = parse_hn_item(HN_ITEM, min_score=100)
    assert item is not None
    assert item.source == "hackernews"
    assert item.title.startswith("Show HN")
    assert item.url == "https://example.com/agent-framework"
    assert item.metrics["score"] == 412
    assert item.published_at.endswith("+00:00")


def test_parse_hn_item_below_threshold_and_non_story():
    assert parse_hn_item(HN_ITEM, min_score=500) is None
    assert parse_hn_item({**HN_ITEM, "type": "comment"}, min_score=0) is None
    assert parse_hn_item({}, min_score=0) is None


def test_parse_hn_item_falls_back_to_hn_url():
    item = parse_hn_item({**HN_ITEM, "url": ""}, min_score=0)
    assert item is not None
    assert item.url == "https://news.ycombinator.com/item?id=12345678"


# ─── arXiv ───

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/2406.00001v1</id>
    <title>Graph RAG for   Multi-Hop Question Answering</title>
    <summary>A study of graph-based retrieval over long documents.</summary>
    <published>2026-06-01T10:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <link href="http://arxiv.org/abs/2406.00001v1" rel="alternate" type="text/html"/>
    <category term="cs.CL"/>
  </entry>
</feed>
"""


def test_parse_arxiv_feed():
    items = parse_arxiv_feed(ARXIV_XML)
    assert len(items) == 1
    item = items[0]
    assert item.source == "arxiv"
    assert item.title == "Graph RAG for Multi-Hop Question Answering"
    assert item.author == "Ada Lovelace, Alan Turing"
    assert item.metrics["categories"] == ["cs.CL"]


def test_build_query():
    assert build_query(["agents"], []) == 'all:"agents"'
    assert build_query(None, ["cs.AI", "cs.LG"]) == "cat:cs.AI OR cat:cs.LG"
    assert build_query(None, []) == "cat:cs.AI"


# ─── Reddit ───

REDDIT_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>r/MachineLearning</title>
  <entry>
    <title>New open-source eval toolkit</title>
    <link href="https://www.reddit.com/r/MachineLearning/comments/abc123/x/"/>
    <updated>2026-06-01T10:00:00+00:00</updated>
    <author><name>/u/someone</name></author>
  </entry>
</feed>
"""


def test_parse_reddit_rss():
    items = parse_reddit_rss(REDDIT_RSS, "MachineLearning")
    assert len(items) == 1
    assert items[0].source == "reddit"
    assert items[0].author == "someone"
    assert items[0].metrics["subreddit"] == "MachineLearning"
    assert items[0].published_at.endswith("+00:00")


# ─── GitHub ───

GH_PAYLOAD = {
    "items": [
        {
            "full_name": "acme/agentkit",
            "html_url": "https://github.com/acme/agentkit",
            "description": "Agent eval toolkit",
            "stargazers_count": 900,
            "forks_count": 40,
            "language": "Python",
            "created_at": "2026-06-01T00:00:00Z",
            "owner": {"login": "acme"},
            "topics": ["agents", "evals"],
        }
    ]
}


def test_parse_github_search():
    items = parse_github_search(GH_PAYLOAD)
    assert len(items) == 1
    assert items[0].title == "acme/agentkit"
    assert items[0].metrics["stars"] == 900


# ─── RSS ───

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Example Blog</title>
  <item>
    <title>Why evals matter</title>
    <link>https://example.com/evals</link>
    <description>&lt;p&gt;A post about &lt;b&gt;evals&lt;/b&gt;.&lt;/p&gt;</description>
    <pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


def test_parse_rss_feed():
    items = parse_rss_feed(RSS_XML)
    assert len(items) == 1
    item = items[0]
    assert item.source == "rss"
    assert item.title == "Why evals matter"
    assert "<" not in item.raw_text
    assert "evals" in item.raw_text
    assert item.metrics["feed"] == "Example Blog"


def test_strip_html():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello  world"


# ─── FeedItem identity ───


def test_feeditem_ids_are_stable_and_content_hash_tracks_text():
    a = FeedItem(source="hn", title="T", url="https://x", external_id="1")
    b = FeedItem(source="hn", title="T", url="https://x", external_id="1")
    assert a.id == b.id
    assert a.content_hash == b.content_hash

    c = FeedItem(source="hn", title="T changed", url="https://x", external_id="1")
    assert c.id == a.id  # identity is source+external id, not content
    assert c.content_hash != a.content_hash


# ─── Feed list loading (newline-safe under Docker bind mounts) ───


def test_load_feeds_reads_urls(tmp_path):
    feeds = tmp_path / "feeds.yaml"
    feeds.write_text(
        "feeds:\n"
        "  - name: Example\n    url: https://example.com/rss\n    topic: ai\n"
        "  - name: No URL\n    topic: ai\n",
        encoding="utf-8",
    )

    loaded = load_feeds(str(feeds))

    assert [f["url"] for f in loaded] == ["https://example.com/rss"], (
        "entries without a url are dropped"
    )


def test_load_feeds_tolerates_a_directory_instead_of_a_file(tmp_path):
    """Docker turns a missing bind-mounted file into an empty directory.

    Returning [] keeps ingest running on the other five sources rather than
    crashing the whole cycle on a config file the user never created.
    """
    mounted = tmp_path / "feeds.local.yaml"
    mounted.mkdir()

    assert load_feeds(str(mounted)) == []


def test_load_feeds_missing_file_returns_empty(tmp_path):
    assert load_feeds(str(tmp_path / "nope.yaml")) == []
