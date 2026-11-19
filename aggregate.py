#!/usr/bin/env python3
"""
CTP Magazine aggregator.

Fetches every cleared feed listed in rss-feeds.md, extracts title / link /
excerpt / date / image per item, dedupes by link AND by near-duplicate
title (same story from different feeds), applies the per-feed
republication rules from the clearance list, and writes articles.json.

Republication rules (from rss-feeds.md — the clearance is the rule):
  * FULL TEXT  (14 feeds: NASA x7 public domain, ESO CC BY 4.0,
    The Conversation CC BY-ND 4.0, Frontiers x4 CC-BY, PLOS ONE CC-BY)
    -> carry the feed's full description / content.
  * ABSTRACT + LINK (7 arXiv feeds: title + abstract are CC0)
    -> carry title + abstract + link. No 200-word cap (CC0).
  * EXCERPT + LINK (all 93 others)
    -> title + the short excerpt the RSS feed supplies, HARD ceiling
       200 words, + prominent link back. Never more.

Images: usable only where the licence covers them (NASA public domain,
ESO CC BY 4.0, Frontiers / PLOS ONE CC-BY author-owned figures).
The Conversation's licence explicitly EXCLUDES images, so its images
are stored but marked not-for-reuse. Every other feed's images are
stored but marked not-for-reuse; the site renders text-only cards
for those. Per-image log (source URL, licence, credit, date checked)
goes to image_log.json. The hero rotator is NEVER auto-populated
from RSS — see build-spec.md; image_hero_eligible flags the
11-feed hand-picked safe pool only.

Stdlib only (urllib + xml.etree). No feedparser dependency, so the
same script runs unchanged in GitHub Actions with setup-python.

Usage:  python3 aggregate.py [--feeds rss-feeds.md] [--out articles.json]
Exit code 0 even if individual feeds fail (failures are logged, the
rest of the run continues). Exit code 1 only if the feed list itself
cannot be read or no feed at all succeeded.
"""

import argparse
import concurrent.futures
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(__file__).resolve().parent
FEEDS_MD = BASE / "rss-feeds.md"
OUT_JSON = BASE / "articles.json"
IMAGE_LOG_JSON = BASE / "image_log.json"
REPORT_JSON = BASE / "aggregate-report.json"

MAX_WORDS_EXCERPT = 200          # hard ceiling, Phys.org's own stated limit
MAX_WORDS_FULL_TEXT = 5000       # safety valve only; RSS full text is far shorter
MAX_WORDS_ABSTRACT = 1000        # safety valve only; abstracts are ~150-300 words
# READABILITY RULE (2026-11-19, site-wide, enforced in code): no card may
# ever render as one unformatted wall. Every excerpt the aggregator writes
# is a readable teaser — paragraph breaks preserved, capped at the first
# 3 paragraphs / ~300 words / ~1500 characters, whichever comes first.
# The republication ceilings above still govern what the magazine MAY
# carry; these display caps govern what the CARD shows. The full article
# is always one click away on the source link.
MAX_PARAS_DISPLAY = 3            # card shows at most 3 paragraphs
MAX_WORDS_DISPLAY = 300          # card shows at most ~300 words
MAX_CHARS_DISPLAY = 1500         # card shows at most ~1500 characters
MAX_PARA_CHARS = 600             # no single paragraph over ~600 chars
MAX_ITEMS_PER_FEED = 25          # Google News returns ~100; take the newest 25
MAX_ITEMS_TOTAL = 300            # newest first
FETCH_TIMEOUT = 25
WORKERS = 16
USER_AGENT = "CTPMagazineAggregator/1.0 (+https://ctp-magazine.github.io/)"

# ---------------------------------------------------------------------------
# Feed list parsing (rss-feeds.md)
# ---------------------------------------------------------------------------

TERMS_FULL = "full_text"
TERMS_ABSTRACT = "abstract"
TERMS_EXCERPT = "excerpt"

# Publishers whose images the licence covers (per image-legalities research).
# The Conversation is FULL TEXT for text but its licence EXCLUDES images,
# so it is deliberately absent here.
IMAGE_USABLE_PUBLISHERS = {
    "nasa",
    "european southern observatory",
    "frontiers media",
    "plos",
}
# Hero rotator safe pool (build-spec.md): NASA x7 + ESO + 3 CC-BY journals.
# The two newer Frontiers journals are CC-BY but NOT in the hero pool
# until confirmed — do not add them here without checking.
HERO_POOL_FEEDS = {
    "NASA Breaking News", "NASA Image of the Day", "NASA — main news feed",
    "NASA — International Space Station", "NASA — Artemis",
    "NASA — Technology", "NASA Science — Photojournal",
    "ESO News", "Frontiers in Science",
    "Frontiers — Astronomy and Space Sciences", "PLOS ONE",
}
AGENCY_CREDITS = ("getty", "reuters", "associated press", "ap ", "afp",
                  "shutterstock", "alamy", "reprinted")


# ---------------------------------------------------------------------------
# Topic tagging (2026-11-19): every article carries a `topic` so the
# Topics module can filter the list like MSN — each topic returns the
# stories from its own feeds. One clear dict, keyed by feed number
# (rss-feeds.md sections). NDE is checked first because IANDS (#23) and
# Windbridge (#69) sit inside the Consciousness sections (3 and 8).
# Unmapped feeds fall through to "Science & the Future" — topic is
# never left blank. All 114 feed numbers are covered exactly once.
# ---------------------------------------------------------------------------
TOPIC_SPACE = "Space & Astronomy"
TOPIC_UFO = "UFOs & UAPs"
TOPIC_CONSCIOUSNESS = "Consciousness"
TOPIC_NDE = "Near-Death Experiences"
TOPIC_PHYSICS = "Physics & Preprints"
TOPIC_FUTURE = "Science & the Future"
TOPICS = (TOPIC_SPACE, TOPIC_UFO, TOPIC_CONSCIOUSNESS, TOPIC_NDE,
          TOPIC_PHYSICS, TOPIC_FUTURE)

TOPIC_FEEDS = {
    # NDE first: #23 and #69 sit inside the Consciousness sections.
    # Only these five feeds are NDE: IANDS #23, Windbridge #69, Google
    # News near-death experience #78, Google News afterlife #89,
    # Bing News near-death experience #91. IONS #24 stays Consciousness.
    TOPIC_NDE: {23, 69, 78, 89, 91},
    # Space & Astronomy: sections 1 (#1-17) + 6 (#54-58) + space/astro
    # aggregator feeds (#81 space, #82 astronomy, #88 interstellar
    # travel, #94 space, #95 astronomy).
    TOPIC_SPACE: set(range(1, 18)) | {54, 55, 56, 57, 58, 81, 82, 88, 94, 95},
    # UFOs & UAPs: sections 2 (#18-22) + 7 (#59-61) + UAP/disclosure
    # aggregator feeds (#79 UAP, #80 unidentified flying object,
    # #84 UFO disclosure, #85 UAP disclosure, #92 UFO, #93 UAP).
    TOPIC_UFO: {18, 19, 20, 21, 22, 59, 60, 61, 79, 80, 84, 85, 92, 93},
    # Consciousness: sections 3 (#24-30; #23 is NDE) + 8 (#62-68, #70-71;
    # #69 is NDE) + consciousness/spirituality aggregator feeds.
    TOPIC_CONSCIOUSNESS: (set(range(24, 31)) | set(range(62, 69)) | {70, 71}
                          | {77, 83, 86, 87, 90, 96, 97, 98, 99, 100, 101,
                             102, 103, 104, 105, 106, 107, 108, 109, 110,
                             113, 114}),
    # Physics & Preprints: sections 4 (#31-36) + 9 (#72-76).
    TOPIC_PHYSICS: set(range(31, 37)) | set(range(72, 77)),
    # Science & the Future: section 5 (#37-53) + the two unclaimed
    # aggregator feeds (#111 ancient civilizations, #112 extreme weather).
    TOPIC_FUTURE: set(range(37, 54)) | {111, 112},
}


def topic_for_feed(num: int) -> str:
    """Topic for a feed number (rss-feeds.md). NDE is checked first;
    anything unmapped is the catch-all, never blank."""
    for topic in (TOPIC_NDE, TOPIC_SPACE, TOPIC_UFO, TOPIC_CONSCIOUSNESS,
                  TOPIC_PHYSICS, TOPIC_FUTURE):
        if num in TOPIC_FEEDS[topic]:
            return topic
    return TOPIC_FUTURE


def classify_terms(terms_cell: str) -> str:
    t = terms_cell.upper()
    if "FULL TEXT" in t:
        return TERMS_FULL
    if "ABSTRACT" in t:
        return TERMS_ABSTRACT
    return TERMS_EXCERPT


def clean_cell(cell: str) -> str:
    cell = re.sub(r"\*\*", "", cell)          # strip markdown bold
    cell = re.sub(r"\s+", " ", cell).strip()
    return cell


def parse_feed_list(path: Path) -> list[dict]:
    """Parse every markdown table row in rss-feeds.md that carries a feed."""
    feeds = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        num = cells[0].strip()
        if not num.isdigit():                 # header / separator rows
            continue
        url = cells[3].strip()
        if not url.startswith(("http://", "https://")):
            continue
        feeds.append({
            "num": int(num),
            "feed": clean_cell(cells[1]),
            "publisher": clean_cell(cells[2]),
            "url": url,
            "terms": classify_terms(cells[4]),
            "terms_raw": clean_cell(cells[4]),
            "attribution": clean_cell(cells[5]),
            "cleared": clean_cell(cells[6]) if len(cells) > 6 else "",
        })
    feeds.sort(key=lambda f: f["num"])
    return feeds


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> bytes:
    """Fetch with retries. Some servers drop the first connection
    (RemoteDisconnected) or reject the feed Accept header (415);
    retry with backoff, then with browser-like headers, and for
    http:// URLs also try the https:// variant as a last resort."""
    last_exc = None
    candidates = [url]
    if url.startswith("http://"):
        candidates.append("https://" + url[len("http://"):])
    for candidate in candidates:
        for attempt, headers in enumerate((
            _FEED_HEADERS,
            _BROWSER_HEADERS,
            _BROWSER_HEADERS,
        )):
            try:
                req = urllib.request.Request(candidate, headers=headers)
                with urllib.request.urlopen(req,
                                            timeout=FETCH_TIMEOUT) as resp:
                    raw = resp.read()
                if raw[:2] == b"\x1f\x8b":         # gzip magic bytes
                    raw = gzip.decompress(raw)
                return raw
            except urllib.error.HTTPError as exc:
                last_exc = exc
                # 415/403/406: the server dislikes our headers — the next
                # attempt uses browser headers. Anything else: stop here.
                if exc.code not in (403, 406, 415) or attempt == 2:
                    break
            except Exception as exc:              # timeouts, disconnects
                last_exc = exc
                if attempt == 2:
                    break
            time.sleep(2 * (attempt + 1))
    raise last_exc


_FEED_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, "
              "application/xml, text/xml, */*;q=0.8",
    "Accept-Encoding": "gzip",
}
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip",
}


# ---------------------------------------------------------------------------
# XML parsing (namespace-agnostic: RSS 2.0, Atom, RDF/RSS 1.0)
# ---------------------------------------------------------------------------

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(elem, names) -> str:
    """First matching direct child's text (names = set of local names)."""
    for child in elem:
        if local(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def child_attr(elem, names, attr) -> str:
    for child in elem:
        if local(child.tag) in names and child.get(attr):
            return child.get(attr).strip()
    return ""


def find_descendants(elem, name: str):
    return [e for e in elem.iter() if local(e.tag) == name]


def strip_html(text: str) -> str:
    """Strip HTML but PRESERVE paragraph breaks: block closers (</p>,
    </div>, </li>, headings, blockquote) and <br> become paragraph
    separators (\"\\n\\n\") before the tags are removed, and whitespace is
    collapsed only WITHIN a paragraph. Returns paragraphs separated by
    \"\\n\\n\". Titles (no block tags) come back as a single line, as before."""
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text,
                  flags=re.S | re.I)
    text = re.sub(r"</(p|div|li|h[1-6]|blockquote|tr|section|article)>",
                  "\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    paras = [re.sub(r"\s+", " ", p).strip()
             for p in text.split("\n\n")]
    paras = [p for p in paras if p]
    return "\n\n".join(paras)


def parse_date(raw: str):
    """Return an aware datetime, or None if unparseable/missing."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)       # RFC 2822 (RSS pubDate)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:                                      # ISO 8601 (Atom)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def extract_image(item) -> tuple[str, str]:
    """Return (image_url, media_credit). Prefer media:content / thumbnail,
    then enclosure, then the first <img> in the content/description HTML.
    A media:content entry counts as an image unless it explicitly
    declares video/audio (NASA feeds carry YouTube embeds as
    media:content medium="video" — those must be skipped)."""
    for mc in find_descendants(item, "content"):
        url = mc.get("url", "")
        medium, mtype = mc.get("medium", ""), mc.get("type", "")
        if not url:
            continue
        if medium == "video" or mtype.startswith(("video", "audio")):
            continue
        if medium == "image" or mtype.startswith("image") \
                or re.search(r"\.(jpe?g|png|gif|webp|avif)(\?|$)",
                             url, re.I):
            return url.strip(), media_credit(mc)
    for th in find_descendants(item, "thumbnail"):
        if th.get("url"):
            return th.get("url").strip(), media_credit(th)
    for enc in find_descendants(item, "enclosure"):
        url, etype = enc.get("url", ""), enc.get("type", "")
        if url and etype.startswith("image"):
            return url.strip(), ""
    # First <img> in content:encoded, then in description/summary.
    for tag in ("encoded", "content", "description", "summary"):
        for node in find_descendants(item, tag):
            if not node.text:
                continue
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', node.text,
                          re.I)
            if m:
                return m.group(1).strip(), ""
    return "", ""


def media_credit(elem) -> str:
    for c in find_descendants(elem, "credit"):
        if c.text:
            return c.text.strip()
    return ""


# HTML named entities that are NOT valid in XML (e.g. &nbsp; in a
# Squarespace feed). Replaced with numeric references in the fallback
# sanitiser below. CDATA sections are left untouched.
_HTML_ENTITIES = {
    "nbsp": "&#160;", "rsquo": "&#8217;", "lsquo": "&#8216;",
    "rdquo": "&#8221;", "ldquo": "&#8220;", "mdash": "&#8212;",
    "ndash": "&#8211;", "hellip": "&#8230;", "copy": "&#169;",
    "reg": "&#174;", "trade": "&#8482;", "laquo": "&#171;",
    "raquo": "&#187;", "middot": "&#183;", "bull": "&#8226;",
    "deg": "&#176;", "plusmn": "&#177;", "times": "&#215;",
    "divide": "&#247;", "frac12": "&#189;", "frac14": "&#188;",
    "frac34": "&#190;", "eacute": "&#233;", "egrave": "&#232;",
    "agrave": "&#224;", "aacute": "&#225;", "ouml": "&#246;",
    "uuml": "&#252;", "auml": "&#228;", "szlig": "&#223;",
    "ccedil": "&#231;", "ntilde": "&#241;", "iexcl": "&#161;",
    "iquest": "&#191;", "sect": "&#167;", "para": "&#182;",
    "sup2": "&#178;", "sup3": "&#179;", "micro": "&#181;",
    "alpha": "&#945;", "beta": "&#946;", "gamma": "&#947;",
    "delta": "&#948;", "pi": "&#960;", "omega": "&#969;",
    "prime": "&#8242;", "Prime": "&#8243;", "larr": "&#8592;",
    "rarr": "&#8594;", "harr": "&#8596;", "darr": "&#8595;",
    "uarr": "&#8593;", "ne": "&#8800;", "le": "&#8804;",
    "ge": "&#8805;", "infin": "&#8734;", "asymp": "&#8776;",
    "sum": "&#8721;",
}
_BARE_AMP = re.compile(
    r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_INVALID_XML_CHARS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitise_xml(text: str) -> bytes:
    """Second-chance parse for sloppy feeds: strip leading junk, fix
    bare & and HTML-only entities OUTSIDE CDATA sections, drop
    control characters that XML forbids. CDATA content is untouched."""
    parts = re.split(r"(<!\[CDATA\[.*?\]\]>)", text, flags=re.S)
    out = []
    for part in parts:
        if part.startswith("<![CDATA["):
            out.append(part)
            continue
        for name, ref in _HTML_ENTITIES.items():
            part = part.replace(f"&{name};", ref)
        part = _BARE_AMP.sub("&amp;", part)
        part = _INVALID_XML_CHARS.sub("", part)
        out.append(part)
    return "".join(out).encode("utf-8", "replace")


def parse_feed(xml_bytes: bytes, feed: dict) -> list[dict]:
    # Some feeds (AmericaSpace) emit blank lines before the <?xml
    # declaration, which strict XML rejects — strip leading whitespace.
    xml_bytes = xml_bytes.lstrip(b" \t\r\n\xef\xbb\xbf")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        # Retry once on a sanitised copy (bare &, &nbsp;, bad chars).
        root = ET.fromstring(
            sanitise_xml(xml_bytes.decode("utf-8", "replace")))
    items = []
    # RSS 2.0 / RDF items and Atom entries, in document order.
    nodes = [e for e in root.iter()
             if local(e.tag) in ("item", "entry")]
    for node in nodes[:MAX_ITEMS_PER_FEED]:
        title = strip_html(child_text(node, {"title"}))
        link = child_text(node, {"link"})
        if not link:                          # Atom: <link href="..."/>
            link = child_attr(node, {"link"}, "href")
        link = link.strip()
        if not title or not link:
            continue
        # Full content preferred for full-text / abstract feeds.
        content = ""
        for c in find_descendants(node, "encoded"):
            if c.text:
                content = c.text
                break
        if not content:
            for c in find_descendants(node, "content"):
                if c.text and c.get("type", "text").lower() in (
                        "text", "html", "xhtml"):
                    content = c.text
                    break
        desc = child_text(node, {"description", "summary"})
        body = content or desc
        date_raw = (child_text(node, {"pubdate", "published", "updated",
                                      "date"})
                    or child_text(node, {"date"}))
        # dc:date lives under the dc namespace; child_text already covers
        # it by local name ("date").
        image_url, image_credit = extract_image(node)
        items.append({
            "title": title,
            "link": link,
            "raw_text": body,
            "date_raw": date_raw,
            "date": parse_date(date_raw),
            "image": image_url,
            "image_credit_raw": image_credit,
        })
    return items


# ---------------------------------------------------------------------------
# Excerpt rules + image gating
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """Split text at sentence boundaries (. ! ? followed by a capital or
    a number). Used to break an over-long paragraph into readable chunks."""
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'“\(\[]?[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]


def break_long_paragraph(para: str, max_len: int = MAX_PARA_CHARS) -> list[str]:
    """Break one over-long paragraph into sentence chunks, each at most
    ~max_len characters. Falls back to word-boundary chunks when the
    paragraph has no sentence boundaries (one giant sentence)."""
    if len(para) <= max_len:
        return [para]
    sents = split_sentences(para)
    if len(sents) <= 1:
        words = para.split()
        chunks, cur = [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_len:
                chunks.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip() if cur else w
        if cur:
            chunks.append(cur)
        return chunks
    chunks, cur = [], ""
    for s in sents:
        if cur and len(cur) + 1 + len(s) > max_len:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip() if cur else s
    if cur:
        chunks.append(cur)
    return chunks


def to_display_paragraphs(text: str, max_paras: int, max_words: int,
                          max_chars: int) -> str:
    """Turn paragraph-preserved text into a readable card teaser: at most
    max_paras paragraphs, max_words words, and max_chars characters
    (ellipsis included), whichever limit is hit first. Over-long
    paragraphs are broken at sentence boundaries so no single paragraph
    is a wall. Returns paragraphs separated by \"\\n\\n\"."""
    src_paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not src_paras:
        return ""
    # 1. Take source paragraphs up to the word limit.
    kept, words, truncated = [], 0, False
    for p in src_paras:
        pw = p.split()
        room = max_words - words
        if room <= 0:
            truncated = True
            break
        if len(pw) > room:
            kept.append(" ".join(pw[:room]))
            words += room
            truncated = True
            break
        kept.append(p)
        words += len(pw)
    # 2. Break any over-long paragraph at sentence boundaries.
    disp = []
    for p in kept:
        disp.extend(break_long_paragraph(p))
    # 3. Cap display paragraphs, then total characters (ellipsis included).
    if len(disp) > max_paras:
        disp = disp[:max_paras]
        truncated = True
    out = "\n\n".join(disp)
    if len(out) > max_chars:
        cut = out[:max_chars - 1]
        idx = max(cut.rfind(" "), cut.rfind("\n"))
        if idx > 0:
            cut = cut[:idx]
        out = cut.rstrip(" .,;:\n") + "…"
        truncated = True
    elif truncated:
        out = out.rstrip(" .,;:\n") + "…"
    return out


def apply_terms(raw_text: str, terms: str) -> tuple[str, int]:
    """Return (excerpt, word_count). The republication rule still governs
    what the magazine MAY carry (full text / abstract / excerpt), but the
    CARD shows a readable teaser: paragraph breaks preserved, first 3
    paragraphs / ~300 words / ~1500 characters. Excerpt feeds keep their
    200-word hard ceiling (the tighter limit wins). The full article is
    always one click away on the source link."""
    text = strip_html(raw_text)   # now paragraph-preserving ("\n\n")
    if terms == TERMS_FULL:
        limit = min(MAX_WORDS_FULL_TEXT, MAX_WORDS_DISPLAY)
    elif terms == TERMS_ABSTRACT:
        limit = min(MAX_WORDS_ABSTRACT, MAX_WORDS_DISPLAY)
    else:
        limit = MAX_WORDS_EXCERPT   # 200, the hard ceiling
    text = to_display_paragraphs(text, MAX_PARAS_DISPLAY, limit,
                                 MAX_CHARS_DISPLAY)
    return text, len(text.split())


def image_usable(feed: dict, image_url: str, credit: str) -> tuple[bool, str]:
    """Per-image gating. Returns (usable, reason)."""
    if not image_url:
        return False, "no image in feed item"
    pub = feed["publisher"].lower()
    if not any(p in pub for p in IMAGE_USABLE_PUBLISHERS):
        return False, f"licence does not cover images ({feed['publisher']})"
    credit_l = (credit or "").lower()
    if any(a in credit_l for a in AGENCY_CREDITS):
        return False, f"image credit is third-party/agency: {credit}"
    if "reprinted" in (credit or "").lower():
        return False, "figure captioned as reprinted with permission"
    if feed["publisher"].lower().startswith("the conversation"):
        return False, "The Conversation licence excludes images"
    return True, "licence covers images"


def normalise_link(link: str) -> str:
    link = link.strip().split("#")[0]
    if link.endswith("/"):
        link = link[:-1]
    return link


# ---------------------------------------------------------------------------
# Near-duplicate detection (2026-11-19): different RSS feeds pull the same
# story, so deduping by link alone leaves repeats — e.g. seven "Afterlife
# With Archie" casting stories from the Google News "afterlife" feed.
# Titles are compared by word-set similarity; when two articles are
# near-duplicates the newest is kept and the rest are dropped. This runs
# in aggregate.py itself (after the 300 cap), so every 12h run dedupes
# the same way — never a one-off cleanup of articles.json.
# ---------------------------------------------------------------------------

TITLE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "its", "it", "is", "are", "as", "new", "this",
    "that", "these", "those", "will", "would", "can", "could", "has",
    "have", "had", "be", "been", "was", "were", "into", "over", "under",
    "after", "before", "between", "about", "against", "through", "during",
    "per", "via", "vs",
}
NEAR_DUP_JACCARD = 0.50       # word-set Jaccard at or above this = duplicate
NEAR_DUP_JACCARD_MIN = 4      # ... and at least this many shared words
NEAR_DUP_OVERLAP = 0.80       # shorter title mostly inside the longer one
NEAR_DUP_OVERLAP_MIN = 5      # ... and at least this many shared words
AGGREGATOR_WINDOW_MIN = 120   # same aggregator feed, same day, this close


def title_word_set(title: str) -> frozenset:
    """Normalised word set for a headline: lowercase, punctuation gone,
    trailing source suffix stripped (" - IMDb", " | Space photo of the
    day..."), stopwords and single-letter alpha tokens dropped. Digits
    are kept — "Voyager 1" and "Voyager 2" are different stories."""
    t = (title or "").strip()
    # Strip one trailing source suffix (" - X" / " | X", short segment).
    for sep in (" | ", " - "):
        idx = t.rfind(sep)
        if idx > 0 and len(t[idx + len(sep):].split()) <= 5:
            t = t[:idx]
            break
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    words = set()
    for w in t.split():
        if w in TITLE_STOPWORDS:
            continue
        if len(w) == 1 and w.isalpha():   # stray "s" from possessives
            continue
        words.add(w)
    return frozenset(words)


def titles_near_duplicate(a: frozenset, b: frozenset) -> bool:
    """True when two normalised title word sets describe the same story:
    identical sets, or a high Jaccard similarity, or the shorter set
    mostly contained in the longer one. Thresholds are deliberately
    conservative — collapsing two genuinely different stories is worse
    than leaving a repeat in. Guard: two long titles that differ by a
    single content word/number are NOT collapsed — that is how distinct
    stories look ("Voyager 1" vs "Voyager 2", "Work" vs "Singles"
    horoscope), not how repeats look."""
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 6 and len(b) >= 6 and len(a ^ b) <= 2:
        return False
    inter = len(a & b)
    if inter == 0:
        return False
    jaccard = inter / len(a | b)
    if jaccard >= NEAR_DUP_JACCARD and inter >= NEAR_DUP_JACCARD_MIN:
        return True
    overlap = inter / min(len(a), len(b))
    if overlap >= NEAR_DUP_OVERLAP and inter >= NEAR_DUP_OVERLAP_MIN:
        return True
    return False


def same_event_aggregator(a: dict, kept_a: dict, ws, ks,
                          freq: dict) -> bool:
    """Second signal, for aggregator feeds only (Google News / Bing News):
    they return many outlets covering the SAME event on the same day,
    often with headlines that share almost no words — UPI's "casts new
    versions of Riverdale favorites" vs TVLine's cast list are the same
    casting announcement. Same aggregator feed, same day, within 2
    hours, and the headlines share either >= 3 content words, or >= 2
    content words that are rare by feed count (each in <= 2 feeds) —
    the rarity bar is what keeps two different stories in the same topic
    feed apart ("Astronomers discover a triple-star system" vs "a giant
    star eats another star" share only the generic "astronomers" /
    "star"). Rarity is measured by feed count, not title count, because
    a story arriving as 13 near-identical variants would inflate its
    own words' title frequency. Restricted to aggregator feeds on
    purpose: publisher feeds (NASA, arXiv, ...) put out distinct items,
    and the same test false-positives on them (two arXiv papers in one
    category share generic words). `freq` maps each word to the number
    of distinct feeds whose titles contain it, counted over the
    300-article dedupe input."""
    feed = a["feed"]
    if not (feed.startswith("Google News")
            or feed.startswith("Bing News")):
        return False
    if feed != kept_a["feed"]:
        return False
    da, db = a["date"], kept_a["date"]
    if not da or not db or da[:10] != db[:10]:
        return False
    if abs((a["_date_sort"] - kept_a["_date_sort"]).total_seconds()) \
            > AGGREGATOR_WINDOW_MIN * 60:
        return False
    shared = ws & ks
    if len(shared) >= 3:
        return True
    rare = [w for w in shared if freq.get(w, 0) <= 2]
    return len(shared) >= 2 and len(rare) >= 2


# ---------------------------------------------------------------------------
# Per-feed worker
# ---------------------------------------------------------------------------

def process_feed(feed: dict) -> dict:
    result = {"feed": feed, "items": [], "error": None, "count": 0}
    try:
        raw = fetch_url(feed["url"])
        if not raw.strip():
            raise ValueError("empty response")
        head = raw.lstrip()[:200].lower()
        if head.startswith(b"<html") or head.startswith(b"<!doctype html"):
            raise ValueError("returned an HTML page, not a feed")
        parsed = parse_feed(raw, feed)
    except Exception as exc:                  # never let one feed kill the run
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    articles = []
    for it in parsed:
        excerpt, wc = apply_terms(it["raw_text"], feed["terms"])
        usable, usable_reason = image_usable(
            feed, it["image"], it["image_credit_raw"])
        # APOD items: the image credit lives on the APOD article page, not
        # in the feed, and APOD images are routinely credited to a named
        # astrophotographer (verified 2026-11-19: the 2026-11-19 Horsehead
        # image is credited to Mark E. Killion). The feed alone cannot
        # verify the image as NASA-only, so APOD images are never usable
        # for thumbnails — do not guess, leave the card text-only.
        if (usable and feed["publisher"].lower() == "nasa"
                and (it["title"].lower().startswith("apod")
                     or "/apod" in it["link"].lower())):
            usable = False
            usable_reason = ("APOD image — credit is on the article page, "
                             "often a named photographer; not verifiable "
                             "from the feed")
        credit = it["image_credit_raw"] or feed["publisher"]
        articles.append({
            "title": it["title"],
            "link": it["link"],
            "source": feed["publisher"],
            "publisher": feed["publisher"],
            "feed": feed["feed"],
            "topic": topic_for_feed(feed["num"]),
            "date": it["date"].isoformat() if it["date"] else None,
            "_date_sort": it["date"] or datetime.min.replace(
                tzinfo=timezone.utc),
            "excerpt": excerpt,
            "_words": wc,
            "terms": feed["terms"],
            "attribution": feed["attribution"],
            "image": it["image"],
            "image_usable": usable,
            "image_credit": credit if it["image"] else "",
            "image_licence": feed["terms_raw"],
            "image_usable_reason": usable_reason,
            "image_hero_eligible": (
                usable and feed["feed"] in HERO_POOL_FEEDS),
        })
    result["items"] = articles
    result["count"] = len(articles)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="CTP Magazine RSS aggregator")
    ap.add_argument("--feeds", default=str(FEEDS_MD))
    ap.add_argument("--out", default=str(OUT_JSON))
    ap.add_argument("--image-log", default=str(IMAGE_LOG_JSON))
    ap.add_argument("--report", default=str(REPORT_JSON))
    args = ap.parse_args()

    checked = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        feeds = parse_feed_list(Path(args.feeds))
    except Exception as exc:
        print(f"FATAL: cannot read feed list {args.feeds}: {exc}",
              file=sys.stderr)
        return 1
    print(f"Feeds in list: {len(feeds)}")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for res in ex.map(process_feed, feeds):
            results.append(res)

    succeeded = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]
    print(f"Feeds succeeded: {len(succeeded)} / {len(feeds)}")
    for r in failed:
        print(f"  FAILED #{r['feed']['num']} {r['feed']['feed']} "
              f"({r['feed']['url']}): {r['error']}")

    # Dedupe by normalised link, newest first; keep the first (newest) copy.
    all_items = [a for r in succeeded for a in r["items"]]
    all_items.sort(key=lambda a: a["_date_sort"], reverse=True)
    seen, deduped = set(), []
    dupes = 0
    for a in all_items:
        key = normalise_link(a["link"])
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        deduped.append(a)
    print(f"Items fetched: {len(all_items)}; duplicates removed: {dupes}; "
          f"unique: {len(deduped)}")

    deduped = deduped[:MAX_ITEMS_TOTAL]
    print(f"Capped at newest {MAX_ITEMS_TOTAL}: {len(deduped)} articles")

    # Near-duplicate pass (same story, different feed/headline): newest
    # first, keep the first of each group, drop the rest. Two signals:
    # title similarity (Jaccard/overlap on normalised word sets) and the
    # aggregator-event signal (same Google/Bing News feed, same day,
    # within 2h, shared words with a rarity bar). Word frequencies are
    # counted over the 300-article input so the rarity bar is measured
    # against this run. Runs AFTER the cap, so the final count drops by
    # the number of repeats removed.
    # Word rarity is measured by FEED count, not title count: a story
    # that arrives as 13 near-identical variants inflates its own
    # words' title frequency, so title counts would call "archie" common
    # exactly when it is most distinctive. Feed count does not inflate
    # that way ("archie" is in 1 feed; "star" is in many).
    from collections import defaultdict
    _word_feeds = defaultdict(set)
    for _a in deduped:
        for _w in title_word_set(_a["title"]):
            _word_feeds[_w].add(_a["feed"])
    _freq = {w: len(fs) for w, fs in _word_feeds.items()}
    kept_sets, kept_arts, final, near_groups = [], [], [], []
    near_dupes = 0
    for a in deduped:
        ws = title_word_set(a["title"])
        hit, signal = None, ""
        for i, ks in enumerate(kept_sets):
            if titles_near_duplicate(ws, ks):
                hit, signal = i, "title-similarity"
                break
            if same_event_aggregator(a, kept_arts[i], ws, ks, _freq):
                hit, signal = i, "aggregator-event"
                break
        if hit is None:
            kept_sets.append(ws)
            kept_arts.append(a)
            final.append(a)
        else:
            near_dupes += 1
            near_groups.append({
                "kept_title": final[hit]["title"],
                "kept_feed": final[hit]["feed"],
                "kept_link": final[hit]["link"],
                "dropped_title": a["title"],
                "dropped_feed": a["feed"],
                "dropped_link": a["link"],
                "signal": signal,
            })
    deduped = final
    print(f"Near-duplicates removed: {near_dupes}; "
          f"articles after dedupe: {len(deduped)}")

    # Excerpt-rule audit: no excerpt-feed item over 200 words.
    over = [a for a in deduped
            if a["terms"] == TERMS_EXCERPT and a["_words"] > MAX_WORDS_EXCERPT]
    print(f"Excerpt-feed items over {MAX_WORDS_EXCERPT} words: {len(over)}")
    for a in over:
        print(f"  OVER-LIMIT {a['_words']}w: {a['title'][:80]}")

    # Final article objects (drop internal sort/word-count keys).
    # The image field carries a URL ONLY when the image is cleared for
    # reuse — an uncleared image is blanked here, so the card template
    # can render a thumbnail from `image` alone and every other card
    # stays text-only. The raw URL is still recorded in image_log.json
    # for the audit trail.
    articles = []
    image_log = []
    for a in deduped:
        articles.append({
            "title": a["title"],
            "link": a["link"],
            "source": a["source"],
            "publisher": a["publisher"],
            "feed": a["feed"],
            "topic": a["topic"],
            "date": a["date"],
            "excerpt": a["excerpt"],
            "terms": a["terms"],
            "attribution": a["attribution"],
            "image": a["image"] if a["image_usable"] else "",
            "image_usable": a["image_usable"],
            "image_credit": a["image_credit"],
            "image_hero_eligible": a["image_hero_eligible"],
        })
        if a["image"]:
            image_log.append({
                "image_url": a["image"],
                "article_link": a["link"],
                "article_title": a["title"],
                "source": a["source"],
                "licence": a["image_licence"],
                "credit": a["image_credit"],
                "usable": a["image_usable"],
                "usable_reason": a["image_usable_reason"],
                "hero_eligible": a["image_hero_eligible"],
                "date_checked": checked,
            })

    Path(args.out).write_text(
        json.dumps(articles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    Path(args.image_log).write_text(
        json.dumps({"generated": checked, "images": image_log},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    n_usable = sum(1 for a in articles if a["image_usable"])
    n_hero = sum(1 for a in articles if a["image_hero_eligible"])
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "date_checked": checked,
        "feeds_total": len(feeds),
        "feeds_succeeded": len(succeeded),
        "feeds_failed": [
            {"num": r["feed"]["num"], "feed": r["feed"]["feed"],
             "url": r["feed"]["url"], "error": r["error"]}
            for r in failed
        ],
        "items_fetched": len(all_items),
        "duplicates_removed": dupes,
        "near_duplicates_removed": near_dupes,
        "near_duplicate_groups": near_groups,
        "articles_written": len(articles),
        "excerpt_over_limit": len(over),
        "images_logged": len(image_log),
        "images_usable": n_usable,
        "images_hero_eligible": n_hero,
        "terms_breakdown": {
            t: sum(1 for a in articles if a["terms"] == t)
            for t in (TERMS_FULL, TERMS_ABSTRACT, TERMS_EXCERPT)
        },
        "topic_breakdown": {
            t: sum(1 for a in articles if a["topic"] == t)
            for t in TOPICS
        },
        "articles_without_topic": sum(
            1 for a in articles if not a.get("topic")),
    }
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    print(f"Wrote {args.out}: {len(articles)} articles "
          f"({report['terms_breakdown']})")
    print(f"Images logged: {len(image_log)} "
          f"({n_usable} usable, {n_hero} hero-eligible)")
    print(f"Wrote {args.image_log} and {args.report}")
    if not succeeded:
        print("FATAL: no feed succeeded", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
