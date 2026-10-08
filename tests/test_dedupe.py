"""Offline tests for cross-source story clustering."""

from __future__ import annotations

from sources.base import FeedItem
from watch.dedupe import assign_clusters, jaccard, tokens


def item(title: str, url: str = "", source: str = "hn", ext: str = "1") -> FeedItem:
    return FeedItem(
        source=source, title=title, url=url or f"https://example.com/{ext}", external_id=ext
    )


def test_tokens_strips_prefixes_and_stopwords():
    assert tokens("Show HN: An open-source agent framework") == tokens(
        "An open-source agent framework"
    )
    assert tokens("New: A tool for evals") == tokens("A tool for evals")
    assert "the" not in tokens("The future of agents")


def test_jaccard_bounds():
    assert jaccard(frozenset(), frozenset({"a"})) == 0.0
    assert jaccard(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0


def test_same_story_across_sources_clusters():
    items = [
        item("Mistral Large 4 released with open weights", source="hn", ext="h1"),
        item("Mistral Large 4 released with open weights", source="rss", ext="r1"),
        item(
            "Mistral Large 4 released with open weights and faster inference",
            source="rss",
            ext="r2",
        ),
    ]
    mapping = assign_clusters(items)
    assert len(set(mapping.values())) == 1


def test_different_stories_stay_separate():
    items = [
        item("Mistral Large 4 released with open weights", ext="a"),
        item("Chrome zero-day exploited in the wild", ext="b"),
        item("Postgres 19 improves logical replication", ext="c"),
    ]
    mapping = assign_clusters(items)
    assert len(set(mapping.values())) == 3


def test_identical_url_clusters_regardless_of_title():
    items = [
        item("Some headline about evals", url="https://example.com/post", ext="a"),
        item("Completely different wording", url="https://example.com/post/", ext="b"),
    ]
    mapping = assign_clusters(items)
    assert len(set(mapping.values())) == 1


def test_cluster_keys_are_deterministic():
    items = [item("Mistral Large 4 released with open weights", ext="h1")]
    assert assign_clusters(items)[items[0].id] == assign_clusters(items)[items[0].id]
