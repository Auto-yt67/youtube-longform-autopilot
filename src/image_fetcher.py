"""
Stage 3: Image sourcing.
Pulls images from Wikimedia Commons for each segment. Free, no API key,
no login required for reads. Filters to only fully clear licenses
(public domain / CC0 / CC-BY / CC-BY-SA) so nothing risks a copyright claim.
"""

import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CarProfessorPipeline/1.0 (educational YouTube automation; contact: set-your-email-here)"
REQUEST_DELAY_SECONDS = 1.0  # be a good citizen - avoid tripping Wikimedia's rate limiter

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_retry = Retry(
    total=5,
    backoff_factor=3,  # 3s, 6s, 12s, 24s, 48s - gives 429s real time to clear
    status_forcelist=[429, 502, 503, 504],
    respect_retry_after_header=True,
    allowed_methods=["GET"],
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))

# Licenses we consider safe to reuse freely
ALLOWED_LICENSE_PATTERNS = [
    r"public domain",
    r"cc0",
    r"cc[-\s]?by(?!-nc)",  # matches CC-BY and CC-BY-SA, excludes CC-BY-NC
]


def _is_license_clear(extmetadata: dict) -> bool:
    license_short = extmetadata.get("LicenseShortName", {}).get("value", "").lower()
    if not license_short:
        return False
    if "nc" in license_short or "nd" in license_short:
        # No-commercial or No-derivatives clauses are too restrictive - skip
        return False
    return any(re.search(p, license_short) for p in ALLOWED_LICENSE_PATTERNS)


def search_images(query: str, limit: int = 6) -> list:
    """Search Commons for images matching a query, return license-clear results."""
    time.sleep(REQUEST_DELAY_SECONDS)  # self-throttle before every search call
    try:
        search_resp = _session.get(
            COMMONS_API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": 6,  # File namespace
                "gsrlimit": limit * 3,  # over-fetch since some will be filtered out
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": 1600,
            },
            timeout=30,
        )
        search_resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  ! search failed for '{query}' after retries ({e}) - skipping this query")
        return []

    pages = search_resp.json().get("query", {}).get("pages", {})

    results = []
    for page in pages.values():
        infos = page.get("imageinfo", [])
        if not infos:
            continue
        info = infos[0]
        extmeta = info.get("extmetadata", {})
        if not _is_license_clear(extmeta):
            continue
        results.append({
            "title": page.get("title", ""),
            "url": info.get("thumburl") or info.get("url"),
            "license": extmeta.get("LicenseShortName", {}).get("value", "unknown"),
            "artist": extmeta.get("Artist", {}).get("value", ""),
        })
        if len(results) >= limit:
            break

    return results


def download_images(query: str, out_dir: Path, limit: int = 4) -> list:
    """Search + download images for a segment. Returns list of local file paths.
    Never raises - a failed search or download just means fewer (or zero) images
    for this segment, not a crashed pipeline."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        images = search_images(query, limit=limit)
    except Exception as e:
        print(f"  ! unexpected error searching '{query}' ({e}) - skipping this segment's images")
        return []

    paths = []
    for i, img in enumerate(images):
        time.sleep(REQUEST_DELAY_SECONDS)  # self-throttle before every download too
        try:
            resp = _session.get(img["url"], timeout=30)
            resp.raise_for_status()
            ext = img["url"].split(".")[-1].split("?")[0][:4]
            out_path = out_dir / f"{i:02d}.{ext}"
            out_path.write_bytes(resp.content)
            paths.append(str(out_path))
        except Exception as e:
            print(f"  ! skipped image ({e}): {img.get('title')}")
            continue

    return paths


def _query_variations(primary_query: str, item_name: str) -> list:
    """
    Build a list of progressively broader search queries to try, so an item is
    less likely to end up with zero images just because the specific query was
    too narrow. Order matters - most specific first.
    """
    import re
    variations = [primary_query]

    # the item name itself (often cleaner than a hand-written query)
    if item_name and item_name not in variations:
        variations.append(item_name)

    # item name with parentheticals stripped, e.g. "BMW 3 Series (E30)" -> "BMW 3 Series"
    stripped = re.sub(r"\([^)]*\)", "", item_name).strip()
    if stripped and stripped not in variations:
        variations.append(stripped)

    # item name with years stripped, e.g. "Ford Model T 1908" -> "Ford Model T"
    no_years = re.sub(r"\b(1[89]\d{2}|20\d{2})\b", "", stripped or item_name).strip()
    no_years = re.sub(r"\s+", " ", no_years)
    if no_years and no_years not in variations:
        variations.append(no_years)

    return variations


def download_images_with_fallback(primary_query: str, item_name: str,
                                   out_dir: Path, limit: int = 4) -> list:
    """
    Try the primary query, then progressively broader fallbacks, stopping as
    soon as one yields usable images. Dramatically reduces how often a segment
    ends up with zero images (which is what caused the grid to show fewer cars
    than the title claimed).
    """
    for q in _query_variations(primary_query, item_name):
        paths = download_images(q, out_dir, limit=limit)
        if paths:
            if q != primary_query:
                print(f"    (used fallback query '{q}' for '{item_name}')")
            return paths
    return []


if __name__ == "__main__":
    results = search_images("Bugatti Veyron", limit=4)
    for r in results:
        print(r["title"], "-", r["license"], "-", r["url"])
