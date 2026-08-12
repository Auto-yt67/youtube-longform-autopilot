"""
Stage 3: Image sourcing.
Pulls images from Wikimedia Commons for each segment. Free, no API key,
no login required for reads. Filters to only fully clear licenses
(public domain / CC0 / CC-BY / CC-BY-SA) so nothing risks a copyright claim.
"""

import re
import requests
from pathlib import Path

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CarProfessorPipeline/1.0 (educational YouTube automation; contact: set-your-email-here)"

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
    search_resp = requests.get(
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
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    search_resp.raise_for_status()
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
    """Search + download images for a segment. Returns list of local file paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    images = search_images(query, limit=limit)
    paths = []

    for i, img in enumerate(images):
        try:
            resp = requests.get(img["url"], headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            ext = img["url"].split(".")[-1].split("?")[0][:4]
            out_path = out_dir / f"{i:02d}.{ext}"
            out_path.write_bytes(resp.content)
            paths.append(str(out_path))
        except Exception as e:
            print(f"  ! skipped image ({e}): {img.get('title')}")
            continue

    return paths


if __name__ == "__main__":
    results = search_images("Bugatti Veyron", limit=4)
    for r in results:
        print(r["title"], "-", r["license"], "-", r["url"])
