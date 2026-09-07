"""Part 3 - blockchain verification package.

The four API functions live in ``blockchain.verify`` (imported directly to avoid
pulling in web3 just to use the pure hashing helpers):

    from blockchain.verify import (
        hash_discovered_data,
        upload_verification_record,
        lookup_verification_record,
        verify_discovered_data,
        record_and_verify,
    )

Pure, dependency-free hashing helpers are re-exported here for convenience.
"""

import warnings

# The offline LOCAL chain (`eth-tester` / `py-evm`) pulls in a legacy
# `cached_property` that emits a noisy, harmless DeprecationWarning on Python
# 3.12+ (`asyncio.iscoroutinefunction` deprecation). It is not from our code;
# quiet it so demo output stays readable.
warnings.filterwarnings(
    "ignore",
    message=r".*asyncio\.iscoroutinefunction.*is deprecated.*",
    category=DeprecationWarning,
)

from .hashing import canonical_timestamp, compute_fingerprint, fingerprint_hex, normalize_url

__all__ = [
    "compute_fingerprint",
    "fingerprint_hex",
    "normalize_url",
    "canonical_timestamp",
]
