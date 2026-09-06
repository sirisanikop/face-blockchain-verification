"""
Tests 1-4 from the task brief: the SHA-256 fingerprint must be deterministic and
must change when (and only when) the image, the URL, or the timestamp changes.

Pure functions only - no network, no blockchain. Run either with pytest or directly:

    python -m blockchain.tests.test_hashing
"""

from blockchain.hashing import canonical_timestamp, compute_fingerprint, normalize_url

IMG_A = b"\x89PNG\r\n\x1a\n" + b"A" * 1024
IMG_B = b"\x89PNG\r\n\x1a\n" + b"B" * 1024
URL = "https://twitter.com/someone/status/1725000000000000000"
TS = 1725638400


# 1. same image + same URL + same timestamp -> same hash
def test_same_inputs_produce_same_hash():
    assert compute_fingerprint(IMG_A, URL, TS) == compute_fingerprint(IMG_A, URL, TS)


# 2. different image -> different hash
def test_different_image_changes_hash():
    assert compute_fingerprint(IMG_A, URL, TS) != compute_fingerprint(IMG_B, URL, TS)


# 3. different URL -> different hash
def test_different_url_changes_hash():
    other = "https://twitter.com/someone/status/9999999999999999999"
    assert compute_fingerprint(IMG_A, URL, TS) != compute_fingerprint(IMG_A, other, TS)


# 4. different timestamp -> different hash
def test_different_timestamp_changes_hash():
    assert compute_fingerprint(IMG_A, URL, TS) != compute_fingerprint(IMG_A, URL, TS + 1)


# Supporting guarantees for determinism ------------------------------------------------
def test_digest_is_32_bytes():
    assert len(compute_fingerprint(IMG_A, URL, TS)) == 32


def test_url_normalization_is_stable():
    # scheme + host case, default port and #fragment are ignored...
    assert normalize_url("HTTPS://Twitter.com:443/Someone#top") == "https://twitter.com/Someone"
    # ...a lone trailing "/" (empty path) is dropped...
    assert normalize_url("http://host.example/") == "http://host.example"
    # ...but a trailing slash on a real path is kept (can be a different resource)...
    assert normalize_url("https://h.example/Someone/") == "https://h.example/Someone/"
    # ...and path case + query string are preserved (they can be significant)
    assert normalize_url("https://h.example/A/b?x=1&y=2") == "https://h.example/A/b?x=1&y=2"


def test_equivalent_urls_hash_the_same():
    a = compute_fingerprint(IMG_A, "https://Example.com/p/1#frag", TS)
    b = compute_fingerprint(IMG_A, "https://example.com:443/p/1", TS)
    assert a == b


def test_canonical_timestamp_forms():
    assert canonical_timestamp(1725638400) == "1725638400"
    assert canonical_timestamp("1725638400") == "1725638400"
    assert canonical_timestamp(1725638400.9) == "1725638400"


def _run_all():
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {name}")
            passed += 1
    print(f"\n{passed} hashing tests passed.")


if __name__ == "__main__":
    _run_all()
