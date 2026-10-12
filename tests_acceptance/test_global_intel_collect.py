"""Tests for NEWS/global_intel_news sector filtering."""

from __future__ import annotations

from unittest.mock import patch

from NEWS.global_intel_news import collect_items


RSS_TECH = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>AI startup raises funding</title>
    <link>https://example.com/ai</link>
    <description>Artificial intelligence software round</description>
    <pubDate>Sun, 07 Jun 2026 10:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Local bakery opens new branch</title>
    <link>https://example.com/bakery</link>
    <description>A new bread shop downtown</description>
    <pubDate>Sun, 07 Jun 2026 09:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

RSS_POLITICS = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Senate passes election reform bill</title>
    <link>https://example.com/pol</link>
    <description>Government vote on legislation</description>
    <pubDate>Sun, 07 Jun 2026 11:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Stock market hits record</title>
    <link>https://example.com/mkt</link>
    <description>Business earnings rally</description>
    <pubDate>Sun, 07 Jun 2026 08:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


def test_collect_items_filters_by_sector_keywords() -> None:
    rules = {
        "target_total": 10,
        "max_age_hours": 48,
        "categories": [
            {
                "name": "政治",
                "quota": 2,
                "region": "全球",
                "match_keywords": ["election", "government", "senate", "parliament"],
                "feeds": [{"title": "Test Politics", "url": "https://example.com/pol.xml"}],
            },
            {
                "name": "Tech",
                "quota": 2,
                "region": "全球",
                "match_keywords": ["ai", "software", "tech", "startup"],
                "feeds": [{"title": "TechCrunch", "url": "https://example.com/tech.xml", "trust_feed": True}],
            },
        ],
    }

    def fake_fetch(url: str) -> str:
        if "pol.xml" in url:
            return RSS_POLITICS
        if "tech.xml" in url:
            return RSS_TECH
        raise AssertionError(f"unexpected url {url}")

    with patch("NEWS.global_intel_news._fetch_feed", side_effect=fake_fetch):
        items, deficits = collect_items(rules)

    assert deficits.get("政治") == 1
    assert len(items) == 3
    sectors = {item["sector"] for item in items}
    assert sectors == {"政治", "Tech"}
    pol_items = [item for item in items if item["sector"] == "政治"]
    assert len(pol_items) == 1
    assert "Senate" in pol_items[0]["title"]
    tech_items = [item for item in items if item["sector"] == "Tech"]
    assert len(tech_items) == 2
    assert all(item["category"] == item["sector"] for item in items)
    assert tech_items[0]["subcategory"] == "TechCrunch"


def test_trust_feed_skips_keyword_filter() -> None:
    rules = {
        "target_total": 5,
        "max_age_hours": 48,
        "categories": [
            {
                "name": "Tech",
                "quota": 5,
                "region": "全球",
                "match_keywords": ["quantum"],
                "feeds": [{"title": "HN", "url": "https://example.com/hn.xml", "trust_feed": True}],
            },
        ],
    }

    with patch("NEWS.global_intel_news._fetch_feed", return_value=RSS_TECH):
        items, _ = collect_items(rules)

    assert len(items) == 2
    assert all(item["sector"] == "Tech" for item in items)


def _rss_many_items(count: int) -> str:
    items = []
    for i in range(count):
        items.append(
            f"""  <item>
    <title>AI story {i}</title>
    <link>https://example.com/ai-{i}</link>
    <description>Artificial intelligence software item {i}</description>
    <pubDate>Sun, 07 Jun 2026 {10 - i % 10:02d}:00:00 GMT</pubDate>
  </item>"""
        )
    return "<?xml version=\"1.0\"?>\n<rss><channel>\n" + "\n".join(items) + "\n</channel></rss>"


def test_collect_items_caps_each_feed_at_eight() -> None:
    rules = {
        "target_total": 50,
        "max_age_hours": 48,
        "max_items_per_feed": 8,
        "categories": [
            {
                "name": "Tech",
                "quota": 40,
                "region": "全球",
                "feeds": [{"title": "TechCrunch", "url": "https://example.com/tech.xml", "trust_feed": True}],
            },
        ],
    }

    with patch("NEWS.global_intel_news._fetch_feed", return_value=_rss_many_items(20)):
        items, deficits = collect_items(rules)

    assert len(items) == 8
    assert deficits["Tech"] == 32
    assert all(item["source"] == "TechCrunch" for item in items)
