"""
Deterministic SHA-256 fingerprinting for Part 3 (blockchain verification).

THE HASH PRE-IMAGE (exact, byte-for-byte)
-----------------------------------------
    raw_image_bytes  ||  0x1F  ||  normalized_url (utf-8)  ||  0x1F  ||  canonical_timestamp (utf-8)

    * raw_image_bytes    : the exact bytes of the matched image file. Never re-encoded,
                           resized or re-compressed. The bytes that Part 2 face-matched.
    * 0x1F               : ASCII Unit Separator. A byte that cannot appear in a URL or in
                           a decimal timestamp, so the three fields can never "bleed" into
                           each other (prevents  a+bc  colliding with  ab+c ).
    * normalized_url     : see normalize_url() below - scheme/host lowercased, default port
                           removed, #fragment removed, path + query kept verbatim.
    * canonical_timestamp: integer unix seconds (UTC) rendered as a plain decimal string,
                           e.g. "1725638400". Generated ONCE when the match is found and
                           then persisted, so re-verification hashes the same value.

The SAME function is used when creating the on-chain record and when re-verifying,
so the two fingerprints are directly comparable.

The fingerprint changes if (and only if) the image bytes, the normalized URL, or the
timestamp change. Each of those is covered by a test in blockchain/tests/test_hashing.py.
"""

import hashlib
from urllib.parse import urlsplit, urlunsplit

# ASCII Unit Separator - domain/field separator inside the hash pre-image.
FIELD_SEP = b"\x1f"


def normalize_url(url: str) -> str:
    """
    Canonicalise a URL so that trivially-equivalent forms hash identically.

    Rules (deliberately conservative - we do NOT touch path/query, because a real
    discovered URL's query string can be semantically important):
        - strip surrounding whitespace
        - lowercase the scheme and the host
        - drop the default port (":80" for http, ":443" for https)
        - drop the "#fragment"
        - drop a lone trailing "/" (so ".../a/" and ".../a" match, but "/" stays "")
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("normalize_url: url must be a non-empty string")

    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"normalize_url: url is not absolute: {url!r}")

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = parts.path
    if path == "/":
        path = ""

    # note: parts[4] (fragment) intentionally replaced with "" to drop it.
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def canonical_timestamp(ts) -> str:
    """
    Render a timestamp as the canonical decimal string of integer unix seconds.

    Accepts int / float / numeric str. Floats are truncated to whole seconds.
    Rejects bools and negative values.
    """
    if isinstance(ts, bool):
        raise TypeError("canonical_timestamp: bool is not a valid timestamp")
    if isinstance(ts, int):
        value = ts
    elif isinstance(ts, float):
        value = int(ts)  # truncate fractional seconds
    elif isinstance(ts, str):
        value = int(ts.strip())
    else:
        raise TypeError(f"canonical_timestamp: unsupported type {type(ts).__name__}")

    if value < 0:
        raise ValueError("canonical_timestamp: timestamp must be >= 0")
    return str(value)


def compute_fingerprint(image_bytes: bytes, url: str, timestamp) -> bytes:
    """
    Return the 32-byte SHA-256 digest of the pre-image described in this module's docstring.

    This is the single source of truth for "what gets hashed". Both the upload path and
    the re-verification path call this exact function.
    """
    if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
        raise ValueError("compute_fingerprint: image_bytes must be non-empty bytes")

    h = hashlib.sha256()
    h.update(bytes(image_bytes))                              # 1. raw image bytes
    h.update(FIELD_SEP)
    h.update(normalize_url(url).encode("utf-8"))              # 2. normalized URL
    h.update(FIELD_SEP)
    h.update(canonical_timestamp(timestamp).encode("utf-8"))  # 3. canonical timestamp
    return h.digest()


def fingerprint_hex(image_bytes: bytes, url: str, timestamp) -> str:
    """Convenience: compute_fingerprint(...) as a lowercase hex string (no 0x prefix)."""
    return compute_fingerprint(image_bytes, url, timestamp).hex()


def hexnorm(value) -> str:
    """Normalise bytes / '0x..' / 'ABCD' to a bare lowercase hex string for comparison."""
    if isinstance(value, (bytes, bytearray)):
        value = value.hex()
    value = str(value).lower()
    return value[2:] if value.startswith("0x") else value
