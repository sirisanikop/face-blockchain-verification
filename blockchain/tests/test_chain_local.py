"""
Tests 5-9 from the task brief, against the in-process eth-tester chain:

    5. blockchain connection
    6. upload transaction
    7. transaction confirmation
    8. blockchain lookup
    9. local-vs-on-chain verification  (both VERIFIED and NOT VERIFIED)

No external node / faucet / keys needed. Run with pytest or directly:

    python -m blockchain.tests.test_chain_local
"""

import tempfile
from pathlib import Path

from web3 import EthereumTesterProvider, Web3

from blockchain import verify as V
from blockchain.chain import _quiet_deprecations, call_fn  # quiets py-evm/eth-tester internals
from blockchain.deploy import deploy
from blockchain.hashing import compute_fingerprint, hexnorm

LOCAL_PK = "0x" + "0" * 63 + "1"  # eth-tester account #0
IMG = b"\x89PNG\r\n\x1a\n" + b"local-chain-test" * 64
URL = "https://www.instagram.com/p/ABC123/"
TS = 1725638400


def _fresh_chain():
    """New in-process chain + freshly deployed contract; returns (w3, account, contract)."""
    with _quiet_deprecations():
        w3 = Web3(EthereumTesterProvider())
        account = w3.eth.account.from_key(LOCAL_PK)
        address, abi = deploy(w3, account, write_abi=False)
        contract = w3.eth.contract(address=address, abi=abi)
    return w3, account, contract


# 5. connection
def test_connection_and_deploy():
    w3, _, contract = _fresh_chain()
    assert w3.is_connected()
    assert int(call_fn(contract.functions.totalRecords())) == 0


# 6 + 7. upload transaction is mined and confirmed
def test_upload_transaction_confirms():
    w3, account, contract = _fresh_chain()
    fp = compute_fingerprint(IMG, URL, TS)
    tx = V.upload_verification_record(fp, URL, TS, w3=w3, account=account, contract=contract)
    assert tx["record_id"] == 0
    assert tx["block_number"] >= 1
    assert len(hexnorm(tx["tx_hash"])) == 64
    assert int(call_fn(contract.functions.totalRecords())) == 1


# 8. lookup returns exactly what we stored
def test_lookup_returns_stored_record():
    w3, account, contract = _fresh_chain()
    fp = compute_fingerprint(IMG, URL, TS)
    V.upload_verification_record(fp, URL, TS, w3=w3, account=account, contract=contract)

    rec = V.lookup_verification_record(0, w3=w3, contract=contract)
    assert hexnorm(rec["fingerprint_hex"]) == hexnorm(fp)
    assert rec["url"] == URL
    assert rec["timestamp"] == TS
    assert rec["uploader"] == account.address


# 9a. verification succeeds when the data is unchanged
def test_verify_matches_for_unchanged_data():
    w3, account, contract = _fresh_chain()
    fp = compute_fingerprint(IMG, URL, TS)
    V.upload_verification_record(fp, URL, TS, w3=w3, account=account, contract=contract)

    result = V.verify_discovered_data(
        record_id=0, url=URL, timestamp=TS, image_bytes=IMG,
        w3=w3, contract=contract,
    )
    assert result["status"] == "VERIFIED"
    assert result["match"] is True


# 9b. verification fails when any hashed input is tampered
def test_verify_fails_for_tampered_image():
    w3, account, contract = _fresh_chain()
    fp = compute_fingerprint(IMG, URL, TS)
    V.upload_verification_record(fp, URL, TS, w3=w3, account=account, contract=contract)

    tampered = IMG + b"x"  # one extra byte
    result = V.verify_discovered_data(
        record_id=0, url=URL, timestamp=TS, image_bytes=tampered,
        w3=w3, contract=contract,
    )
    assert result["status"] == "NOT VERIFIED"
    assert result["match"] is False


def test_verify_fails_for_tampered_url_or_timestamp():
    w3, account, contract = _fresh_chain()
    fp = compute_fingerprint(IMG, URL, TS)
    V.upload_verification_record(fp, URL, TS, w3=w3, account=account, contract=contract)

    bad_url = V.verify_discovered_data(record_id=0, url="https://evil.example/p/ABC123/",
                                       timestamp=TS, image_bytes=IMG, w3=w3, contract=contract)
    bad_ts = V.verify_discovered_data(record_id=0, url=URL, timestamp=TS + 5,
                                      image_bytes=IMG, w3=w3, contract=contract)
    assert bad_url["status"] == "NOT VERIFIED"
    assert bad_ts["status"] == "NOT VERIFIED"


# record_file round-trip (what pipeline.py + `verify` CLI actually use)
def test_record_file_roundtrip(tmp_path=None):
    w3, account, contract = _fresh_chain()
    out = Path(tmp_path or tempfile.mkdtemp())

    img_file = out / "match.jpg"
    img_file.write_bytes(IMG)

    fp = compute_fingerprint(IMG, URL, TS)
    tx = V.upload_verification_record(fp, URL, TS, w3=w3, account=account, contract=contract)

    record = {
        "url": URL, "timestamp": TS, "image_path": str(img_file),
        "record_id": tx["record_id"], "contract_address": tx["contract_address"],
    }
    rec_file = out / "blockchain_record.json"
    import json
    rec_file.write_text(json.dumps(record))

    result = V.verify_discovered_data(record_file=str(rec_file), w3=w3, contract=contract)
    assert result["status"] == "VERIFIED"


def _run_all():
    import json  # noqa: F401  (used indirectly by round-trip test)
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {name}")
            passed += 1
    print(f"\n{passed} local-chain tests passed.")


if __name__ == "__main__":
    _run_all()
