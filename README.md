# Face Identification + Web Search + Blockchain Verification

An end-to-end pipeline that takes a face scan, finds a matching image/post on the
open web, and then anchors that discovery on a blockchain as a tamper-evident record.

```
face scan  ->  face identification  ->  web / social search  ->  confirmed match
                                                                       |
                                                            SHA-256 fingerprint of
                                                        (image bytes + URL + timestamp)
                                                                       |
                                              upload to blockchain  ->  look record back up
                                                                       |
                                              recompute locally & compare  ->  VERIFIED / NOT VERIFIED
```

---

## What each part does

### Part 1 - Face identification (`face_id.py`)
- `get_embedding(image_path)` - detects faces with **InsightFace** (`buffalo_l`) and
  returns the 512-d embedding of the largest face (or `None`).
- `compare_faces(e1, e2, threshold=0.5)` - cosine similarity -> `(is_match, score)`.

### Part 2 - Web / social search (`web_detect.py`, `combined_search.py`)
- `web_detect.py` - Google Cloud Vision **Web Detection** (auth via `gcloud auth
  print-access-token`). Returns pages / images that match the scan.
- `combined_search.py` - runs Google Vision **and** SerpAPI Google Lens
  (`SERPAPI_API_KEY`) concurrently and returns a deduplicated list of candidate URLs.

### Part 3 - Blockchain verification (`blockchain/`)  ← this component
Once `pipeline.py` confirms a match, it:
1. reads the exact bytes of the matched image (the ones Part 2 face-matched),
2. computes a deterministic **SHA-256 fingerprint** of `image_bytes + URL + timestamp`,
3. stores `(fingerprint, url, timestamp)` on-chain via a minimal smart contract,
4. reads the record back and recomputes the fingerprint locally,
5. reports **VERIFIED** (match) or **NOT VERIFIED** (any input changed).

---

## Pipeline orchestration (`pipeline.py`)

`run_pipeline_fast(scan_image_path)`:
1. embeds the scan face,
2. gets candidate URLs from Part 2,
3. Phase 1 - downloads each candidate image and face-compares it to the scan,
4. Phase 2 - retries non-image URLs via their `<meta property="og:image">`,
5. on the first confirmed match, runs **Part 3** (`blockchain.verify.record_and_verify`),
6. writes `results/<scan>/match_result.json` (now including a `blockchain` block)
   and `results/<scan>/blockchain_record.json`.

Part 3 is **non-fatal**: if the chain/config is unavailable the pipeline still
finishes Parts 1-2. Set `ENABLE_BLOCKCHAIN=0` to skip it.

---

## Blockchain design

### Chain
- **Ethereum Sepolia** testnet is the recommended target (`CHAIN_ID=11155111`).
  Chosen because `web3.py` support is first-class, faucets are easy, block times
  (~12 s) keep the demo quick, and it is the most widely recognised testnet.
- **Polygon Amoy** (`CHAIN_ID=80002`) works with the same code - just change `.env`.
- **LOCAL mode** (no `RPC_URL`) uses an in-process `eth-tester` EVM - no node, no
  faucet, no keys. Used for offline testing and a single-process pipeline demo.

The Python code is chain-agnostic: everything is driven by `RPC_URL` / `CHAIN_ID` /
`PRIVATE_KEY` / `CONTRACT_ADDRESS`, and always sends a legacy (type-0) signed
transaction, so there is one code path across all three chains.

### Smart contract - `blockchain/contract.sol`
Minimal registry. The image is **never** stored on-chain, only its fingerprint.

```solidity
struct Record { bytes32 fingerprint; string url; uint256 timestamp; address uploader; }

function storeRecord(bytes32 fingerprint, string url, uint256 timestamp) returns (uint256 id);
function getRecord(uint256 id) view returns (bytes32, string, uint256, address);
function totalRecords() view returns (uint256);
event RecordStored(uint256 indexed id, bytes32 fingerprint, address indexed uploader, uint256 timestamp);
```

The compiled ABI is committed at `blockchain/FaceVerification_abi.json` (regenerated
by `deploy.py`).

### The SHA-256 fingerprint - `blockchain/hashing.py`
Hash pre-image, byte-for-byte:

```
raw_image_bytes  ||  0x1F  ||  normalized_url (utf-8)  ||  0x1F  ||  canonical_timestamp (utf-8)
```

- **raw_image_bytes** - the matched image file's exact bytes; never re-encoded/resized.
- **0x1F** - ASCII Unit Separator; cannot occur in a URL or a decimal timestamp, so
  the three fields cannot bleed into one another.
- **normalized_url** - `normalize_url()`: strip whitespace; lowercase scheme + host;
  drop default port (`:80`/`:443`); drop `#fragment`; drop a lone trailing `/`.
  Path and query string are kept verbatim (they can be significant).
- **canonical_timestamp** - integer Unix seconds (UTC) as a plain decimal string,
  e.g. `"1725638400"`. Generated **once** when the match is found, then persisted
  in `blockchain_record.json` and reused on re-verification (never "now").

The digest is 32 bytes and is stored on-chain as `bytes32`. It changes if and only
if the image bytes, the normalized URL, or the timestamp change. `str(dict)` / JSON
of arbitrary objects is never hashed.

### Image resolution - `blockchain/image_source.py`
`resolve_image_bytes()` tries, in order: caller-supplied bytes -> local
`image_path` (the normal case) -> direct `image_url` -> `page_url` as a direct
image -> `page_url`'s `og:image`. If every source fails it raises - it never
silently hashes an unrelated image.

---

## Public API (`blockchain/verify.py`)

```python
hash_discovered_data(url, timestamp, image_path=None, image_bytes=None, image_url=None)
    -> {fingerprint_hex, fingerprint(bytes), url_normalized, timestamp, image_source, ...}

upload_verification_record(fingerprint, url, timestamp, ...)
    -> {tx_hash, block_number, record_id, contract_address, chain_id, uploader}

lookup_verification_record(record_id, ...)
    -> {fingerprint_hex, url, timestamp, uploader}

verify_discovered_data(record_id=..., url=..., timestamp=..., image_path=..., record_file=...)
    -> {status: "VERIFIED" | "NOT VERIFIED", local_fingerprint, onchain_fingerprint, ...}

record_and_verify(image_path, url, output_dir, timestamp=None)   # used by pipeline.py
    -> full record dict, also written to <output_dir>/blockchain_record.json
```

---

## Installation

```bash
pip install -r requirements.txt
```

Part 3 alone needs only: `web3`, `py-solc-x`, `python-dotenv` (plus `eth-tester` +
`py-evm` for the offline LOCAL mode). Parts 1-2 need InsightFace / OpenCV / SerpAPI
and a `gcloud` login.

---

## Configuration

```bash
cp .env.example .env
```

| Variable | Needed for | Notes |
|---|---|---|
| `RPC_URL` | testnet | Alchemy / Infura Sepolia URL, or `https://rpc-amoy.polygon.technology`. Blank = LOCAL mode. |
| `CHAIN_ID` | testnet | `11155111` Sepolia, `80002` Amoy. Checked against the RPC. |
| `PRIVATE_KEY` | testnet | Throwaway wallet, 64 hex chars. **Never commit.** |
| `CONTRACT_ADDRESS` | testnet | Output of `python -m blockchain.deploy`. |
| `BLOCKCHAIN_LOCAL` | optional | `1` forces LOCAL mode even if `RPC_URL` is set. |
| `ENABLE_BLOCKCHAIN` | optional | `0` skips Part 3 in `pipeline.py`. |
| `SERPAPI_API_KEY` | Part 2 | Teammates' credential. |

### Wallet / RPC / testnet funds (do this yourself - never share the key)

1. **Create a throwaway wallet**
   ```bash
   python -c "from eth_account import Account; a=Account.create(); print('address', a.address); print('private_key', a.key.hex())"
   ```
   Put the private key in `.env` only.
2. **Get an RPC URL** - free app at [alchemy.com](https://www.alchemy.com/) or
   [infura.io](https://infura.io/) for Sepolia; or public
   `https://ethereum-sepolia-rpc.publicnode.com`.
3. **Fund the wallet** - a Sepolia faucet (Google Cloud Web3 faucet, Alchemy
   faucet, or the pk910 PoW faucet). ~0.05 ETH is plenty.

### Deploy the contract

```bash
python -m blockchain.deploy
# -> prints: CONTRACT_ADDRESS=0x....   copy that line into .env
```

---

## Running

### Full pipeline (Parts 1-3)

```bash
python pipeline.py            # uses test_images/test7.jpg by default
```

With `.env` pointing at a testnet you get a real on-chain record. With no `RPC_URL`
it runs in single-process LOCAL mode (auto-deploys the contract in-process).

### Part 3 on its own

```bash
# hash -> upload -> lookup -> verify for one match
python -m blockchain.verify demo --image test_images/test7.jpg --url "https://example.com/the-post"

# re-verify later from the saved record (needs a persistent chain: testnet)
python -m blockchain.verify verify --record-file results/_manual/blockchain_record.json

# demonstrate NOT VERIFIED
python -m blockchain.verify verify --record-file results/_manual/blockchain_record.json --tamper-url "https://example.com/different"
```

### Offline demo (no testnet, no config)

```bash
python -m blockchain.demo_local
```

Deploys in-process, records a real `test_images/` picture, re-verifies (VERIFIED),
then re-verifies a 1-byte-changed copy (NOT VERIFIED) - all in one run.

---

## Expected output (shape)

```
MATCH FOUND
URL: https://.../the-post

IMAGE HASH / FINGERPRINT (SHA-256):
  ec9c7ba7c8b2710f13d0cd3d4323fe744583788b9b1c325930a18c733c340228

UPLOADING TO BLOCKCHAIN...
TRANSACTION CONFIRMED
  Transaction Hash: 0x....
  Record id       : 0

LOOKING UP ON-CHAIN RECORD...
ON-CHAIN FINGERPRINT:
  ec9c7ba7c8b2710f13d0cd3d4323fe744583788b9b1c325930a18c733c340228
LOCAL FINGERPRINT:
  ec9c7ba7c8b2710f13d0cd3d4323fe744583788b9b1c325930a18c733c340228

STATUS: VERIFIED
```

---

## Tests

```bash
python -m blockchain.tests.test_hashing        # determinism: same->same, image/url/timestamp->different
python -m blockchain.tests.test_chain_local    # connect / upload / confirm / lookup / verify / tamper (in-process EVM)
python -m blockchain.demo_local                # full Part 3 flow incl. VERIFIED + NOT VERIFIED
```

(They also run under `pytest blockchain/tests/` if pytest is installed.)

---

## Known limitations

- **LOCAL mode is single-process.** The `eth-tester` chain lives inside one Python
  process, so a record made by one command is gone in the next. Same-process
  re-verification works (`demo_local.py`, one `pipeline.py` run). Cross-process
  `blockchain.verify verify` needs a persistent chain - use a testnet (or your own
  local node) via `RPC_URL`.
- **Re-verification needs the original image bytes.** `blockchain_record.json`
  stores the local `image_path`; if that file is gone, pass `--tamper-image`/an
  explicit path, or re-run the search. Re-encoding the image (different bytes)
  correctly yields NOT VERIFIED.
- **Testnet only** - no mainnet, no real value. Sepolia/Amoy state and faucets are
  best-effort and can reset.
- **URL normalization is conservative.** Different-looking but equivalent URLs
  (tracking params, `www.` vs not) are treated as different. That is deliberate -
  the fingerprint records exactly what was discovered.
- **Part 2 requires external credentials** (`SERPAPI_API_KEY`, Google Cloud auth);
  without them the full `pipeline.py` cannot run, but Part 3 can be exercised via
  `blockchain.demo_local` / `blockchain.verify demo`.
- Gas price uses a single `eth_gas_price` reading with no bump/retry; on a
  congested testnet a transaction may need to be re-sent.
