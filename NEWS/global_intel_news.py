#!/usr/bin/env python3
"""Fetch overseas RSS/Atom feeds into global_intel JSON + Markdown outputs."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RULES = BASE_DIR / "public" / "global_intel_rules.json"
DEFAULT_DB = BASE_DIR / "data" / "news_history.db"
USER_AGENT = "ERIS-GlobalIntel/1.0 (+https://hugme2.com/news/)"

try:
    from news_db import save_fetch
except ImportError:
    save_fetch = None  # type: ignore[assignment,misc]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_published(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsedate_to_datetime(raw)
    except Exception:
        return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        if child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)
    return _strip_html(re.sub(r"\s+", " ", "".join(parts)).strip())


def _load_rules(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch_feed(url: str, timeout: float = 20.0) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_feed(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    tag = root.tag.rsplit("}", 1)[-1].lower()
    items: list[dict[str, str]] = []
    if tag == "rss":
        channel = root.find("channel")
        if channel is None:
            return items
        for item in channel.findall("item"):
            items.append(
                {
                    "title": _text(item.find("title")),
                    "link": _text(item.find("link")),
                    "summary": _text(item.find("description")),
                    "published": _text(item.find("pubDate")),
                }
            )
        return items
    if tag == "feed":
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            link = ""
            for ln in entry.findall("a:link", ns):
                href = ln.attrib.get("href")
                if href:
                    link = href
                    break
            items.append(
                {
                    "title": _text(entry.find("a:title", ns)),
                    "link": link,
                    "summary": _text(entry.find("a:summary", ns)) or _text(entry.find("a:content", ns)),
                    "published": _text(entry.find("a:updated", ns)) or _text(entry.find("a:published", ns)),
                }
            )
    return items


def _age_hours(published: datetime | None, now: datetime) -> float | None:
    if not published:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return round((now - published).total_seconds() / 3600, 2)


def _matches_sector_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    blob = (text or "").lower()
    return any(str(keyword).lower() in blob for keyword in keywords if str(keyword).strip())


def _entry_matches_sector(
    *,
    feed: dict[str, Any],
    category: dict[str, Any],
    title: str,
    summary: str,
) -> bool:
    if feed.get("trust_feed"):
        return True
    keywords = feed.get("match_keywords") or category.get("match_keywords") or []
    return _matches_sector_keywords(f"{title} {summary}", keywords)


def _feed_item_cap(rules: dict[str, Any], feed: dict[str, Any]) -> int:
    if feed.get("max_items") is not None:
        return max(0, int(feed["max_items"]))
    return max(0, int(rules.get("max_items_per_feed", 8)))


_SIGNAL_RE = re.compile(
    r"(\$[\d,.]+|\b\d+(\.\d+)?%|\b\d{1,3}(,\d{3})+\b|"
    r"\b(launch|launches|raises|raised|ban|bans|breach|scam|fraud|hack|"
    r"acquire|acquires|lawsuit|fine|settlement|regulation|verify|monetiz|"
    r"payment|dating|onlyfans|ransomware|phishing)\b)",
    re.I,
)


def _split_sentences(text: str) -> list[str]:
    cleaned = _strip_html(text or "")
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", cleaned)
    return [p.strip(" -•\t") for p in parts if len(p.strip(" -•\t")) >= 24]


def extract_key_points(
    title: str,
    summary: str,
    keywords: list[str] | None = None,
    *,
    limit: int = 3,
) -> list[str]:
    """Pick the most signal-rich sentences from title+summary as key points."""
    keywords = [str(k).lower() for k in (keywords or []) if str(k).strip()]
    candidates = _split_sentences(summary)
    title_clean = _strip_html(title or "").strip()
    if title_clean and not any(title_clean.lower() == c.lower() for c in candidates):
        candidates = [title_clean] + candidates

    scored: list[tuple[int, int, str]] = []
    for idx, sentence in enumerate(candidates):
        lower = sentence.lower()
        score = 0
        if _SIGNAL_RE.search(sentence):
            score += 3
        score += sum(1 for kw in keywords if kw and kw in lower)
        if any(ch.isdigit() for ch in sentence):
            score += 1
        if 40 <= len(sentence) <= 220:
            score += 1
        if score <= 0 and idx > 0:
            continue
        scored.append((score, -idx, sentence[:240]))

    scored.sort(reverse=True)
    points: list[str] = []
    seen: set[str] = set()
    for score, _, sentence in scored:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        points.append(sentence)
        if len(points) >= limit:
            break

    if not points and title_clean:
        points = [title_clean[:240]]
    if not points and summary:
        fallback = _strip_html(summary)[:240].strip()
        if fallback:
            points = [fallback]
    return points


def collect_items(rules: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    now = _now()
    max_age = float(rules.get("max_age_hours", 72))
    target_total = int(rules.get("target_total", 150))
    require_key_points = bool(rules.get("require_key_points", True))
    selected: list[dict[str, Any]] = []
    deficits: dict[str, int] = {}
    category_order: dict[str, int] = {}

    for index, cat in enumerate(rules.get("categories", [])):
        name = str(cat.get("name", "Unknown"))
        category_order[name] = index
        quota = int(cat.get("quota", 0))
        region = str(cat.get("region", "全球"))
        cat_keywords = list(cat.get("match_keywords") or [])
        picked = 0
        for feed in cat.get("feeds", []):
            if picked >= quota:
                break
            url = str(feed.get("url", "")).strip()
            if not url:
                continue
            source = str(feed.get("title", url))
            feed_cap = _feed_item_cap(rules, feed)
            feed_picked = 0
            try:
                xml_text = _fetch_feed(url)
                entries = _parse_feed(xml_text)
            except (URLError, ET.ParseError, TimeoutError, ValueError) as exc:
                print(f"[warn] feed failed {url}: {exc}", file=sys.stderr)
                continue
            for entry in entries:
                if picked >= quota or feed_picked >= feed_cap:
                    break
                published = _parse_published(entry.get("published"))
                age = _age_hours(published, now)
                if age is not None and age > max_age:
                    continue
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "").strip()
                if not title or not link:
                    continue
                if not _entry_matches_sector(
                    feed=feed,
                    category=cat,
                    title=title,
                    summary=summary,
                ):
                    continue
                feed_keywords = list(feed.get("match_keywords") or [])
                key_points = extract_key_points(
                    title,
                    summary,
                    feed_keywords or cat_keywords,
                )
                if require_key_points and not key_points:
                    continue
                selected.append(
                    {
                        "id": str(uuid.uuid4()),
                        "category": name,
                        "sector": name,
                        "region": region,
                        "subcategory": source,
                        "title": title,
                        "summary": summary[:500],
                        "key_points": key_points,
                        "url": link,
                        "source": source,
                        "published_at": (published or now).isoformat(),
                        "age_hours": age if age is not None else None,
                        "_category_order": index,
                    }
                )
                picked += 1
                feed_picked += 1
        if picked < quota:
            deficits[name] = quota - picked

    selected.sort(key=lambda item: (item.get("_category_order", 999), item.get("published_at", "")))
    for item in selected:
        item.pop("_category_order", None)

    if len(selected) > target_total:
        selected = selected[:target_total]
    return selected, deficits


def render_markdown(items: list[dict[str, Any]], generated_at: datetime, deficits: dict[str, int]) -> str:
    lines = [
        "# Global Intel News",
        "",
        f"- Generated: {generated_at.isoformat()}",
        f"- Total: {len(items)}",
        "",
    ]
    if deficits:
        lines.append("## Deficits")
        for name, gap in deficits.items():
            lines.append(f"- {name}: {gap}")
        lines.append("")
    current = None
    for item in items:
        cat = item.get("category", "Unknown")
        if cat != current:
            current = cat
            lines.extend(["", f"## {cat}", ""])
        lines.append(f"### {item.get('title', '')}")
        lines.append(f"- Source: {item.get('source', '')}")
        lines.append(f"- URL: {item.get('url', '')}")
        key_points = item.get("key_points") or []
        if key_points:
            lines.append("- 重点:")
            for point in key_points:
                lines.append(f"  - {point}")
        elif item.get("summary"):
            lines.append(f"- Summary: {item['summary']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch global intel RSS/Atom news")
    parser.add_argument("--rules", default=str(DEFAULT_RULES))
    parser.add_argument("--output-dir", default=str(BASE_DIR / "output"))
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    rules_path = Path(args.rules)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rules = _load_rules(rules_path)
    items, deficits = collect_items(rules)
    target_total = int(rules.get("target_total", 150))
    if not args.allow_partial and len(items) < target_total:
        print(f"only collected {len(items)}/{target_total}", file=sys.stderr)
        return 2

    stamp = _now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": _now().isoformat(),
        "target_total": target_total,
        "max_items_per_feed": int(rules.get("max_items_per_feed", 8)),
        "total": len(items),
        "deficits": deficits,
        "items": items,
    }
    json_path = output_dir / f"global_intel_{stamp}.json"
    md_path = output_dir / f"global_intel_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(items, _now(), deficits), encoding="utf-8")
    if save_fetch is not None:
        run_id = save_fetch(
            payload,
            run_key=json_path.stem,
            json_path=str(json_path),
            markdown_path=str(md_path),
            db_path=DEFAULT_DB,
        )
        print(f"DB: run_id={run_id}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print(f"Total: {len(items)}/{target_total}")
    if deficits:
        print(f"Deficits: {json.dumps(deficits, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
