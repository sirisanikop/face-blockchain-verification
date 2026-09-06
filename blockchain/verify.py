"""
Part 3 - blockchain verification of the discovered post.

Public API (the four functions the task asks for):

    hash_discovered_data(...)      -> SHA-256 fingerprint (+ the exact fields hashed)
    upload_verification_record(...) -> stores fingerprint+metadata on-chain, waits, returns tx info
    lookup_verification_record(...) -> reads a stored record back from the chain
    verify_discovered_data(...)     -> recompute locally, compare to on-chain, report VERIFIED / NOT VERIFIED

Plus:
    record_and_verify(...)          -> the one call pipeline.py makes: hash -> upload -> lookup -> verify,
                                       prints the demo output and writes blockchain_record.json

CLI:
    python -m blockchain.verify demo   --image test_images/test7.jpg --url <post-url>
    python -m blockchain.verify verify --record-file results/test7/blockchain_record.json
    python -m blockchain.verify verify --record-file <file> --tamper-image <other.jpg>
"""

import argparse
import json
import time
from pathlib import Path

from .chain import call_fn, get_account, get_contract, get_web3, send_tx
from .hashing import canonical_timestamp, compute_fingerprint, hexnorm, normalize_url
from .image_source import resolve_image_bytes

RECORD_FILENAME = "blockchain_record.json"


# --------------------------------------------------------------------------------------
# 1. HASH
# --------------------------------------------------------------------------------------
def hash_discovered_data(url, timestamp, image_path=None, image_bytes=None, image_url=None):
    """
    Compute the deterministic SHA-256 fingerprint of the discovered post.

    Hashed pre-image (see blockchain/hashing.py for the full spec):
        raw_image_bytes || 0x1F || normalized_url || 0x1F || canonical_timestamp

    Args:
        url        : discovered post URL (page URL from Part 2).
        timestamp  : unix seconds - generate ONCE at match time, then persist & reuse.
        image_path : local file of the matched image (preferred - the bytes Part 2 matched).
        image_bytes: raw bytes, if the caller already has them.
        image_url  : a direct image URL, used only if path/bytes are unavailable.

    Returns a dict:
        fingerprint_hex, fingerprint (bytes), url, url_normalized,
        timestamp (int), image_bytes_len, image_source
    """
    if not url:
        raise ValueError("hash_discovered_data: url is required")
    if timestamp is None:
        raise ValueError(
            "hash_discovered_data: timestamp is required "
            "(generate it once when the match is found, then persist it)"
        )

    data, source = resolve_image_bytes(
        image_path=image_path,
        image_bytes=image_bytes,
        image_url=image_url,
        page_url=url,
    )
    fingerprint = compute_fingerprint(data, url, timestamp)
    return {
        "fingerprint_hex": fingerprint.hex(),
        "fingerprint": fingerprint,
        "url": url,
        "url_normalized": normalize_url(url),
        "timestamp": int(canonical_timestamp(timestamp)),
        "image_bytes_len": len(data),
        "image_source": source,
    }


# --------------------------------------------------------------------------------------
# 2. UPLOAD
# --------------------------------------------------------------------------------------
def upload_verification_record(fingerprint, url, timestamp,
                               w3=None, account=None, contract=None):
    """
    Store (fingerprint, url, timestamp) on-chain via FaceVerification.storeRecord,
    wait for the transaction receipt, and return transaction info.

    Returns: tx_hash, block_number, record_id, contract_address, chain_id, uploader
    """
    w3 = w3 or get_web3()
    account = account or get_account(w3)
    contract = contract or get_contract(w3)

    if isinstance(fingerprint, str):
        fingerprint = bytes.fromhex(hexnorm(fingerprint))
    if not isinstance(fingerprint, (bytes, bytearray)) or len(fingerprint) != 32:
        raise ValueError("upload_verification_record: fingerprint must be a 32-byte SHA-256 digest")

    ts = int(canonical_timestamp(timestamp))

    # storeRecord(bytes32 fingerprint, string url, uint256 timestamp)
    receipt = send_tx(
        w3, account,
        contract.functions.storeRecord(bytes(fingerprint), url, ts),
    )
    if receipt.status != 1:
        raise RuntimeError(f"storeRecord transaction reverted (tx {receipt.transactionHash.hex()})")

    # The record's numeric id comes from the RecordStored event.
    events = contract.events.RecordStored().process_receipt(receipt)
    if events:
        record_id = int(events[0]["args"]["id"])
    else:  # fallback: last index
        record_id = int(call_fn(contract.functions.totalRecords())) - 1

    tx_hash = receipt.transactionHash
    return {
        "tx_hash": tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash),
        "block_number": int(receipt.blockNumber),
        "record_id": record_id,
        "contract_address": contract.address,
        "chain_id": int(w3.eth.chain_id),
        "uploader": account.address,
    }


# --------------------------------------------------------------------------------------
# 3. LOOKUP
# --------------------------------------------------------------------------------------
def lookup_verification_record(record_id, w3=None, contract=None, contract_address=None):
    """Read record #record_id back from the chain (FaceVerification.getRecord)."""
    w3 = w3 or get_web3()
    contract = contract or get_contract(w3, contract_address)

    try:
        fingerprint, url, timestamp, uploader = call_fn(contract.functions.getRecord(int(record_id)))
    except Exception as e:
        from .chain import is_local

        if is_local():
            raise RuntimeError(
                "Could not read the record from the LOCAL chain. The eth-tester chain is "
                "in-process, so a record created in one `python ...` run does NOT exist in a "
                "later, separate run. For same-process re-verification see "
                "`python -m blockchain.demo_local`; for cross-process re-verification set "
                "RPC_URL to a real testnet (or a persistent local node) in .env."
            ) from e
        raise RuntimeError(
            f"Could not read record #{record_id} from the chain. Check CONTRACT_ADDRESS and "
            f"that the record id exists (totalRecords). Original error: {e}"
        ) from e

    return {
        "record_id": int(record_id),
        "fingerprint_hex": hexnorm(fingerprint),
        "url": url,
        "timestamp": int(timestamp),
        "uploader": uploader,
    }


# --------------------------------------------------------------------------------------
# 4. VERIFY
# --------------------------------------------------------------------------------------
def verify_discovered_data(record_id=None, url=None, timestamp=None,
                           image_path=None, image_bytes=None, image_url=None,
                           record_file=None, contract_address=None,
                           w3=None, contract=None):
    """
    Recompute the fingerprint from the discovered data and compare it to the on-chain record.

    Either pass record_file (a blockchain_record.json written by record_and_verify) and
    optionally override any field, or pass record_id + url + timestamp + image_* directly.

    Returns a dict with status == "VERIFIED" or "NOT VERIFIED".
    """
    if record_file:
        meta = json.loads(Path(record_file).read_text())
        record_id = meta["record_id"] if record_id is None else record_id
        url = url or meta.get("url")
        timestamp = meta.get("timestamp") if timestamp is None else timestamp
        image_path = image_path or meta.get("image_path")
        contract_address = contract_address or meta.get("contract_address")

    if record_id is None:
        raise ValueError("verify_discovered_data: record_id is required (or pass record_file)")
    if not url or timestamp is None:
        raise ValueError("verify_discovered_data: url and timestamp are required")

    w3 = w3 or get_web3()
    contract = contract or get_contract(w3, contract_address)

    # Recompute locally from the (possibly re-downloaded / possibly tampered) data.
    local = hash_discovered_data(
        url=url, timestamp=timestamp,
        image_path=image_path, image_bytes=image_bytes, image_url=image_url,
    )
    onchain = lookup_verification_record(record_id, w3=w3, contract=contract)

    match = hexnorm(local["fingerprint_hex"]) == hexnorm(onchain["fingerprint_hex"])
    return {
        "status": "VERIFIED" if match else "NOT VERIFIED",
        "match": match,
        "record_id": int(record_id),
        "local_fingerprint": hexnorm(local["fingerprint_hex"]),
        "onchain_fingerprint": hexnorm(onchain["fingerprint_hex"]),
        "url": url,
        "url_normalized": local["url_normalized"],
        "timestamp": int(canonical_timestamp(timestamp)),
        "onchain_timestamp": onchain["timestamp"],
        "image_source": local["image_source"],
        "contract_address": contract.address,
        "chain_id": int(w3.eth.chain_id),
    }


# --------------------------------------------------------------------------------------
# Orchestrator used by pipeline.py
# --------------------------------------------------------------------------------------
def record_and_verify(image_path, url, output_dir=".", timestamp=None,
                      image_url=None, verbose=True):
    """
    Full Part 3 flow for one confirmed match:
        hash -> upload -> wait for confirmation -> lookup -> compare -> VERIFIED/NOT VERIFIED

    Writes <output_dir>/blockchain_record.json and returns it as a dict.
    Prints the demo-style progress output when verbose.
    """
    if timestamp is None:
        timestamp = int(time.time())  # generated ONCE here; persisted below; reused on re-verify

    def log(*args):
        if verbose:
            print(*args)

    log("\n" + "=" * 56)
    log("PART 3 - BLOCKCHAIN VERIFICATION")
    log("=" * 56)
    log("MATCH FOUND")
    log(f"URL: {url}")

    # --- hash -------------------------------------------------------------------------
    h = hash_discovered_data(url=url, timestamp=timestamp,
                             image_path=image_path, image_url=image_url)
    log("\nIMAGE HASH / FINGERPRINT (SHA-256):")
    log(f"  {h['fingerprint_hex']}")
    log(f"  image source  : {h['image_source']} ({h['image_bytes_len']} bytes)")
    log(f"  normalized URL: {h['url_normalized']}")
    log(f"  timestamp     : {h['timestamp']}")

    # --- upload ---------------------------------------------------------------------
    w3 = get_web3()
    account = get_account(w3)
    contract = get_contract(w3)

    log("\nUPLOADING TO BLOCKCHAIN...")
    tx = upload_verification_record(h["fingerprint"], url, timestamp,
                                    w3=w3, account=account, contract=contract)
    log("TRANSACTION CONFIRMED")
    log(f"  Transaction Hash: {tx['tx_hash']}")
    log(f"  Block           : {tx['block_number']}")
    log(f"  Record id       : {tx['record_id']}")
    log(f"  Contract        : {tx['contract_address']}  (chainId {tx['chain_id']})")

    # --- lookup + compare ----------------------------------------------------------
    log("\nLOOKING UP ON-CHAIN RECORD...")
    onchain = lookup_verification_record(tx["record_id"], w3=w3, contract=contract)
    log("ON-CHAIN FINGERPRINT:")
    log(f"  {onchain['fingerprint_hex']}")
    log("LOCAL FINGERPRINT:")
    log(f"  {h['fingerprint_hex']}")

    verified = hexnorm(h["fingerprint_hex"]) == hexnorm(onchain["fingerprint_hex"])
    status = "VERIFIED" if verified else "NOT VERIFIED"
    log(f"\nSTATUS: {status}")

    record = {
        "status": status,
        "url": url,
        "url_normalized": h["url_normalized"],
        "timestamp": h["timestamp"],
        "image_path": image_path,
        "image_source": h["image_source"],
        "image_bytes_len": h["image_bytes_len"],
        "fingerprint_hex": h["fingerprint_hex"],
        "onchain_fingerprint_hex": onchain["fingerprint_hex"],
        "tx_hash": tx["tx_hash"],
        "block_number": tx["block_number"],
        "record_id": tx["record_id"],
        "contract_address": tx["contract_address"],
        "chain_id": tx["chain_id"],
        "uploader": tx["uploader"],
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / RECORD_FILENAME
    record_path.write_text(json.dumps(record, indent=2))
    log(f"\nSaved on-chain record metadata to {record_path}")
    return record


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _cli():
    parser = argparse.ArgumentParser(description="Part 3 blockchain verification")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="hash + upload + lookup + verify for one match")
    p_demo.add_argument("--image", required=True, help="path to the matched image")
    p_demo.add_argument("--url", required=True, help="discovered post URL")
    p_demo.add_argument("--output-dir", default="results/_manual")
    p_demo.add_argument("--timestamp", type=int, default=None)

    p_ver = sub.add_parser("verify", help="re-verify a stored record against the chain")
    p_ver.add_argument("--record-file", required=True, help="path to blockchain_record.json")
    p_ver.add_argument("--tamper-image", default=None,
                       help="use a different image to demonstrate NOT VERIFIED")
    p_ver.add_argument("--tamper-url", default=None,
                       help="use a different URL to demonstrate NOT VERIFIED")

    args = parser.parse_args()

    if args.cmd == "demo":
        record_and_verify(
            image_path=args.image, url=args.url,
            output_dir=args.output_dir, timestamp=args.timestamp,
        )
        return

    # verify
    from .chain import is_local

    if is_local():
        print(
            "NOTE: running in LOCAL mode (no RPC_URL). The in-process test chain does not\n"
            "persist between separate runs, so this standalone re-verification needs a\n"
            "persistent chain. Either set RPC_URL in .env (testnet), or use\n"
            "`python -m blockchain.demo_local` which does record + re-verify in one process.\n"
        )

    overrides = {}
    if args.tamper_image:
        overrides["image_path"] = args.tamper_image
    if args.tamper_url:
        overrides["url"] = args.tamper_url

    try:
        result = verify_discovered_data(record_file=args.record_file, **overrides)
    except RuntimeError as e:
        print(f"\nERROR: {e}")
        raise SystemExit(1)

    print("\n" + "=" * 56)
    print("RE-VERIFICATION")
    print("=" * 56)
    print(f"Record id           : {result['record_id']}")
    print(f"On-chain fingerprint: {result['onchain_fingerprint']}")
    print(f"Local fingerprint   : {result['local_fingerprint']}")
    print(f"Image source        : {result['image_source']}")
    if overrides:
        print(f"(tampered inputs    : {', '.join(overrides)})")
    print(f"\nSTATUS: {result['status']}")


if __name__ == "__main__":
    _cli()
