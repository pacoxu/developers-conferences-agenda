#!/usr/bin/env python3
"""Weekly check for new developer events from LF, CNCF, and vLLM.

Fetches upcoming events from:
  - https://events.linuxfoundation.org/
  - https://www.cncf.io/sponsor
  - https://vllm.ai/events

Filtering rules:
  - Exclude "office hour" / "office hours" events
  - Exclude vLLM SIG meetings
  - Outside China: only include top-level events (KubeCon, Open Source Summit, etc.)
  - Japan / Korea: also include AI Infra or cloud native related events
  - China (including Hong Kong / Macau): include all relevant events
"""

import json
import logging
import re
import sys

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filter keyword lists
# ---------------------------------------------------------------------------

EXCLUDE_KEYWORDS = [
    "office hour",
    "office hours",
    "sig meeting",
    "vllm sig",
]

# For events outside China/Japan/Korea — only include these top-level events
TOP_LEVEL_KEYWORDS = [
    "kubecon",
    "cloudnativecon",
    "open source summit",
    "openinfra summit",
    "pytorch conference",
    "linux foundation member summit",
    "agntcon",
    "mcpcon",
    "mcp dev summit",
    "openssf day",
]

# For Japan/Korea events, include if the event matches any of these
AI_CLOUD_KEYWORDS = [
    "kubecon",
    "cloudnativecon",
    "cloud native",
    "openinfra",
    "kubernetes",
    "pytorch",
    "ai infra",
    "ai infrastructure",
    "mlops",
    " ai ",
    "llm",
    "machine learning",
    "open source summit",
]

CHINA_INDICATORS = [
    "china",
    "beijing",
    "shanghai",
    "shenzhen",
    "hangzhou",
    "chengdu",
    "guangzhou",
    "wuhan",
    "nanjing",
    "hong kong",
    "hongkong",
    "macau",
    "台湾",
    "中国",
    "北京",
    "上海",
    "深圳",
    "杭州",
    "成都",
    "香港",
    "澳门",
]

JAPAN_INDICATORS = [
    "japan",
    "tokyo",
    "osaka",
    "kyoto",
    "yokohama",
    "nagoya",
    "日本",
    "東京",
    "横浜",
]

KOREA_INDICATORS = [
    "korea",
    "seoul",
    "busan",
    "한국",
    "서울",
    "부산",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 EventChecker/1.0"
    )
}


def _get(url: str, timeout: int = 30) -> requests.Response | None:
    """Perform a GET request, returning None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
        return None


def should_include_event(name: str, location: str) -> bool:
    """Return True if the event meets the inclusion criteria."""
    name_lower = name.lower()
    location_lower = (location or "").lower()
    combined = f"{name_lower} {location_lower}"

    # 1. Always exclude office hours and SIG meetings
    for kw in EXCLUDE_KEYWORDS:
        if kw in combined:
            logger.debug("Excluding '%s' — matched exclude keyword: %s", name, kw)
            return False

    # 2. China events — include everything that passes the exclusion check
    if any(kw in combined for kw in CHINA_INDICATORS):
        return True

    # 3. Japan / Korea — include AI Infra / cloud native related
    if any(kw in combined for kw in JAPAN_INDICATORS + KOREA_INDICATORS):
        return any(kw in combined for kw in AI_CLOUD_KEYWORDS)

    # 4. Rest of the world — only top-level events
    return any(kw in name_lower for kw in TOP_LEVEL_KEYWORDS)


# ---------------------------------------------------------------------------
# LF Events scraper  — https://events.linuxfoundation.org/
# ---------------------------------------------------------------------------


def fetch_lf_events() -> list[dict]:
    """Fetch upcoming events from events.linuxfoundation.org."""
    url = "https://events.linuxfoundation.org/"
    resp = _get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: list[dict] = []

    # The LF events page renders event cards.  The class names may change, so
    # we try a few selectors and fall back to generic heading detection.
    card_selectors = [
        {"class": re.compile(r"\bevent[-_]?(?:card|item|listing)\b", re.I)},
        {"class": re.compile(r"\bcard\b", re.I)},
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.find_all(["article", "div", "li"], attrs=sel)
        if cards:
            break

    # Fallback: scan every <article> tag
    if not cards:
        cards = soup.find_all("article")

    seen: set[str] = set()
    for card in cards:
        # Try to find the event title
        title_el = card.find(
            ["h2", "h3", "h4", "h5"],
            class_=re.compile(r"title|heading|name", re.I),
        ) or card.find(["h2", "h3", "h4", "h5"])

        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        if not name or len(name) < 5 or name in seen:
            continue
        seen.add(name)

        # Link
        link_el = card.find("a", href=True)
        link = link_el["href"] if link_el else ""
        if link and link.startswith("/"):
            link = "https://events.linuxfoundation.org" + link

        # Date
        date_el = card.find(
            ["time", "span", "div", "p"],
            class_=re.compile(r"date|time|when", re.I),
        )
        date_str = date_el.get_text(strip=True) if date_el else ""

        # Location
        loc_el = card.find(
            ["span", "div", "p"],
            class_=re.compile(r"location|venue|place|where", re.I),
        )
        location = loc_el.get_text(strip=True) if loc_el else ""

        events.append(
            {
                "name": name,
                "link": link,
                "date": date_str,
                "location": location,
                "source": "LF",
            }
        )

    logger.info("LF: scraped %d raw events", len(events))
    return events


# ---------------------------------------------------------------------------
# CNCF sponsor/events scraper  — https://www.cncf.io/sponsor
# ---------------------------------------------------------------------------


def fetch_cncf_events() -> list[dict]:
    """Fetch upcoming events from the CNCF sponsor/events page."""
    url = "https://www.cncf.io/sponsor"
    resp = _get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: list[dict] = []

    # The CNCF sponsor page lists upcoming events with sponsorship tiers.
    # Try several likely selectors.
    item_selectors = [
        {"class": re.compile(r"\bevent\b", re.I)},
        {"class": re.compile(r"\bcard\b", re.I)},
        {"class": re.compile(r"\bsponsor[-_]?event\b", re.I)},
    ]

    items = []
    for sel in item_selectors:
        items = soup.find_all(["div", "article", "li", "section"], attrs=sel)
        if items:
            break

    if not items:
        # Fallback: look for any <article> or <section>
        items = soup.find_all(["article", "section"])

    seen: set[str] = set()
    for item in items:
        title_el = (
            item.find(["h2", "h3", "h4", "h5"], class_=re.compile(r"title|name|heading", re.I))
            or item.find(["h2", "h3", "h4", "h5"])
        )
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        if not name or len(name) < 5 or name in seen:
            continue
        seen.add(name)

        link_el = item.find("a", href=True)
        link = link_el["href"] if link_el else ""
        if link and link.startswith("/"):
            link = "https://www.cncf.io" + link

        date_el = item.find(["time", "span", "div"], class_=re.compile(r"date|time|when", re.I))
        date_str = date_el.get_text(strip=True) if date_el else ""

        loc_el = item.find(["span", "div"], class_=re.compile(r"location|venue|place|where", re.I))
        location = loc_el.get_text(strip=True) if loc_el else ""

        events.append(
            {
                "name": name,
                "link": link,
                "date": date_str,
                "location": location,
                "source": "CNCF",
            }
        )

    logger.info("CNCF: scraped %d raw events", len(events))
    return events


# ---------------------------------------------------------------------------
# vLLM events scraper  — https://vllm.ai/events
# ---------------------------------------------------------------------------


def fetch_vllm_events() -> list[dict]:
    """Fetch upcoming events from the vLLM events page."""
    url = "https://vllm.ai/events"
    resp = _get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: list[dict] = []

    # vLLM events page — try common patterns
    item_selectors = [
        {"class": re.compile(r"\bevent\b", re.I)},
        {"class": re.compile(r"\bcard\b", re.I)},
        {"class": re.compile(r"\bpost\b", re.I)},
    ]

    items = []
    for sel in item_selectors:
        items = soup.find_all(["div", "article", "li", "section"], attrs=sel)
        if items:
            break

    if not items:
        items = soup.find_all("article")

    seen: set[str] = set()
    for item in items:
        title_el = (
            item.find(["h2", "h3", "h4", "h5"], class_=re.compile(r"title|name|heading", re.I))
            or item.find(["h2", "h3", "h4", "h5"])
        )
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        if not name or len(name) < 5 or name in seen:
            continue
        seen.add(name)

        link_el = item.find("a", href=True)
        link = link_el["href"] if link_el else ""
        if link and link.startswith("/"):
            link = "https://vllm.ai" + link

        date_el = item.find(["time", "span", "div"], class_=re.compile(r"date|time|when", re.I))
        date_str = date_el.get_text(strip=True) if date_el else ""

        loc_el = item.find(["span", "div"], class_=re.compile(r"location|venue|place|where", re.I))
        location = loc_el.get_text(strip=True) if loc_el else ""

        events.append(
            {
                "name": name,
                "link": link,
                "date": date_str,
                "location": location,
                "source": "vLLM",
            }
        )

    logger.info("vLLM: scraped %d raw events", len(events))
    return events


# ---------------------------------------------------------------------------
# README deduplication helpers
# ---------------------------------------------------------------------------


def load_readme_state(readme_path: str = "README.md") -> tuple[set[str], set[str]]:
    """Return (known_urls, known_names) from the README."""
    try:
        with open(readme_path, encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        logger.warning("README.md not found — skipping deduplication")
        return set(), set()

    # Extract URLs from Markdown links: [text](url)
    # Use [^)] to match up to the closing parenthesis of a Markdown link.
    full_urls = {m.group(1) for m in re.finditer(r"\((https?://[^)]+)\)", content)}

    # Extract visible link text
    names = {m.group(1).strip() for m in re.finditer(r"\[([^\]]+)\]\(https?://", content)}

    return full_urls, names


def is_new_event(event: dict, known_urls: set[str], known_names: set[str]) -> bool:
    """Return True if the event is not already tracked in the README."""
    if event["link"] and event["link"] in known_urls:
        return False

    event_name_lower = event["name"].lower()
    for known in known_names:
        known_lower = known.lower()
        # Consider it a match if one string contains the other (handles slight
        # wording differences like "KubeCon EU 2026" vs "KubeCon Europe 2026")
        if len(known_lower) > 8 and (
            known_lower in event_name_lower or event_name_lower in known_lower
        ):
            return False

    return True


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def format_event_line(event: dict) -> str:
    name = event["name"]
    link = event["link"]
    date = event.get("date", "")
    location = event.get("location", "")
    source = event.get("source", "")

    link_md = f"[{name}]({link})" if link else name
    parts = [f"- {link_md}"]
    if date:
        parts.append(f" ({date})")
    if location:
        parts.append(f" — {location}")
    parts.append(f" [Source: {source}]")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info("Starting weekly event check — %s", __import__("datetime").date.today())

    readme_path = "README.md"
    known_urls, known_names = load_readme_state(readme_path)
    logger.info(
        "README state: %d known URLs, %d known event names",
        len(known_urls),
        len(known_names),
    )

    # Collect events from all sources
    all_events: list[dict] = []
    for fetch_fn in (fetch_lf_events, fetch_cncf_events, fetch_vllm_events):
        try:
            all_events.extend(fetch_fn())
        except (requests.RequestException, ValueError, AttributeError) as exc:
            logger.error("Error in %s: %s", fetch_fn.__name__, exc)

    logger.info("Total raw events fetched: %d", len(all_events))

    # Filter
    new_events: list[dict] = []
    for event in all_events:
        if not should_include_event(event["name"], event["location"]):
            logger.debug("Filtered out: %s", event["name"])
            continue
        if not is_new_event(event, known_urls, known_names):
            logger.debug("Already tracked: %s", event["name"])
            continue
        new_events.append(event)

    logger.info("New events after filtering: %d", len(new_events))

    # Save JSON for downstream workflow steps (always write the file)
    output_path = "/tmp/new_events.json"
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(new_events, fh, ensure_ascii=False, indent=2)
    logger.info("Saved new events to %s", output_path)

    if new_events:
        print("\n### New Events Found\n")
        for event in new_events:
            print(format_event_line(event))
        print()
    else:
        print("No new events found.")


if __name__ == "__main__":
    main()
