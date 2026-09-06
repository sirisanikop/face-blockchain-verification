"""
Resolve the *actual* bytes of the discovered image, from whatever Part 2 gives us.

Part 2 (pipeline.py) hands us:
    - image_path : a local file it already downloaded and face-matched  (preferred)
    - url        : the discovered *page* URL (may itself be a direct image, or an
                   HTML page whose <meta property="og:image"> points at the image)

This module turns any of those into raw bytes, with explicit fallbacks, and NEVER
silently substitutes an unrelated image - if nothing works it raises.
"""

import os
import re

import requests

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_UA = {"User-Agent": "Mozilla/5.0 (face-blockchain-project Part3)"}


def _looks_like_image_response(resp, url: str) -> bool:
    ctype = resp.headers.get("Content-Type", "").lower()
    if "image" in ctype:
        return True
    # Some CDNs mislabel content type; fall back to the URL extension.
    return url.lower().split("?")[0].endswith(_IMAGE_EXTS)


def _download(url: str, timeout: int = 15):
    """GET a URL and return bytes iff it really is an image, else None."""
    try:
        resp = requests.get(url, timeout=timeout, headers=_UA)
    except requests.RequestException:
        return None
    if resp.status_code == 200 and resp.content and _looks_like_image_response(resp, url):
        return resp.content
    return None


def _extract_og_image(page_url: str, timeout: int = 15):
    """Scrape <meta property="og:image" content="..."> from an HTML page."""
    try:
        resp = requests.get(page_url, timeout=timeout, headers=_UA)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    for pattern in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ):
        m = re.search(pattern, resp.text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def resolve_image_bytes(image_path=None, image_bytes=None, image_url=None, page_url=None):
    """
    Return (raw_bytes, source_label).

    Resolution order (first that works wins):
        1. image_bytes   - caller already has the bytes
        2. image_path    - local file downloaded/verified by Part 2   (the normal case)
        3. image_url     - a direct image URL
        4. page_url      - try it as a direct image, then as an HTML page via og:image

    Raises RuntimeError if every source fails (we never return an unrelated image).
    """
    if image_bytes is not None:
        if len(image_bytes) == 0:
            raise ValueError("resolve_image_bytes: image_bytes is empty")
        return bytes(image_bytes), "image_bytes"

    if image_path and os.path.isfile(image_path):
        with open(image_path, "rb") as f:
            data = f.read()
        if not data:
            raise ValueError(f"resolve_image_bytes: image file is empty: {image_path}")
        return data, f"path:{image_path}"

    if image_path:
        # a path was given but does not exist - report it rather than silently skipping
        print(f"[image_source] image_path not found on disk: {image_path} - trying URLs")

    if image_url:
        data = _download(image_url)
        if data:
            return data, f"image_url:{image_url}"
        print(f"[image_source] direct image download failed: {image_url}")

    if page_url:
        data = _download(page_url)
        if data:
            return data, f"page_url_direct:{page_url}"
        og = _extract_og_image(page_url)
        if og:
            data = _download(og)
            if data:
                return data, f"og_image:{og}"
            print(f"[image_source] og:image found but download failed: {og}")
        else:
            print(f"[image_source] no og:image on page: {page_url}")

    raise RuntimeError(
        "resolve_image_bytes: could not obtain image bytes from any source "
        "(image_bytes / image_path / image_url / page_url all failed)"
    )
