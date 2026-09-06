"""
Self-contained Part 3 demo on the in-process eth-tester chain.

No RPC, no faucet, no keys. It:
    1. deploys FaceVerification to a local in-process EVM,
    2. takes a real image from test_images/ and a sample post URL,
    3. hashes -> uploads -> waits -> looks up -> verifies  (expect VERIFIED),
    4. re-verifies with a tampered image                    (expect NOT VERIFIED).

Run:
    python -m blockchain.demo_local
    python -m blockchain.demo_local --image test_images/test6.jpg --url https://example.com/post

This exercises the SAME functions pipeline.py calls; only the chain differs
(local EVM here vs. Sepolia/Amoy when RPC_URL is configured).
"""

import argparse
import json
import tempfile
import warnings
from pathlib import Path

# eth-tester / py-evm internals emit a harmless DeprecationWarning on this Python.
warnings.filterwarnings("ignore", category=DeprecationWarning)

from web3 import EthereumTesterProvider, Web3

from . import verify as V
from .deploy import deploy

_LOCAL_PK = "0x" + "0" * 63 + "1"
_SAMPLE_URL = "https://www.instagram.com/p/DEMO12345/"


def main():
    ap = argparse.ArgumentParser(description="Local (no-testnet) Part 3 demo")
    ap.add_argument("--image", default="test_images/test7.jpg")
    ap.add_argument("--url", default=_SAMPLE_URL)
    args = ap.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")

    # 1. local chain + contract
    w3 = Web3(EthereumTesterProvider())
    account = w3.eth.account.from_key(_LOCAL_PK)
    address, abi = deploy(w3, account, write_abi=False)
    contract = w3.eth.contract(address=address, abi=abi)
    print(f"Local chain ready. FaceVerification @ {address} (chainId {w3.eth.chain_id})\n")

    fixed_ts = 1_725_638_400  # fixed so the run is reproducible

    # 2-3. hash -> upload -> lookup -> verify
    h = V.hash_discovered_data(url=args.url, timestamp=fixed_ts, image_path=str(image_path))
    print("MATCH FOUND")
    print(f"URL: {args.url}")
    print(f"\nIMAGE HASH / FINGERPRINT:\n  {h['fingerprint_hex']}")
    print(f"  (source: {h['image_source']}, {h['image_bytes_len']} bytes)")

    print("\nUPLOADING TO BLOCKCHAIN...")
    tx = V.upload_verification_record(h["fingerprint"], args.url, fixed_ts,
                                      w3=w3, account=account, contract=contract)
    print("TRANSACTION CONFIRMED")
    print(f"  Transaction Hash: {tx['tx_hash']}")
    print(f"  Block: {tx['block_number']}  Record id: {tx['record_id']}")

    print("\nLOOKING UP ON-CHAIN RECORD...")
    onchain = V.lookup_verification_record(tx["record_id"], w3=w3, contract=contract)
    print(f"ON-CHAIN FINGERPRINT:\n  {onchain['fingerprint_hex']}")
    print(f"LOCAL FINGERPRINT:\n  {h['fingerprint_hex']}")

    good = V.verify_discovered_data(record_id=tx["record_id"], url=args.url,
                                    timestamp=fixed_ts, image_path=str(image_path),
                                    w3=w3, contract=contract)
    print(f"\nSTATUS: {good['status']}")
    assert good["status"] == "VERIFIED", "expected VERIFIED for the original data"

    # 4. tamper check -> NOT VERIFIED
    print("\n--- tamper check: same URL + timestamp, ONE image byte changed ---")
    original = image_path.read_bytes()
    tampered_file = Path(tempfile.mkdtemp()) / "tampered.jpg"
    tampered_file.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))

    bad = V.verify_discovered_data(record_id=tx["record_id"], url=args.url,
                                   timestamp=fixed_ts, image_path=str(tampered_file),
                                   w3=w3, contract=contract)
    print(f"ON-CHAIN FINGERPRINT:\n  {bad['onchain_fingerprint']}")
    print(f"LOCAL FINGERPRINT (tampered):\n  {bad['local_fingerprint']}")
    print(f"\nSTATUS: {bad['status']}")
    assert bad["status"] == "NOT VERIFIED", "expected NOT VERIFIED for tampered data"

    print("\n" + json.dumps({"verified_case": good["status"],
                             "tampered_case": bad["status"]}, indent=2))
    print("\nLocal Part 3 demo OK.")


if __name__ == "__main__":
    main()
