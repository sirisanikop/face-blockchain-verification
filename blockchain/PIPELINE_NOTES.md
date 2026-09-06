# Pipeline walkthrough (for reference)

What happens, step by step, when you run:

```
python pipeline.py test_images\test3.jpg
```

Full chain:

```
input image
  -> [1] face detection + embedding            (face_id.py)
  -> [2] reverse image / web search            (combined_search.py -> web_detect.py + serpapi)
  -> [3] candidate download + face compare     (pipeline.py)
  -> [4] first confirmed match                 (pipeline.py)
  -> [5] SHA-256 fingerprint of the match      (blockchain/hashing.py)
  -> [6] upload fingerprint to blockchain      (blockchain/verify.py + contract.sol)
  -> [7] read it back + recompute + compare    (blockchain/verify.py)
  -> VERIFIED / NOT VERIFIED
```

Outputs land in `results\test3\`:
`match_result.json`, `blockchain_record.json`, `candidates\candidate_*.jpg`.

---

## Step 0 - entry point

**File:** `pipeline.py` (`__main__` -> `run_pipeline_fast()`)

- `sys.argv[1]` is the scan image path (default `test_images/test7.jpg` if omitted).
- Checks the file exists, then calls `run_pipeline_fast(scan_image)`.
- Creates a clean output dir `results\<image-name>\` and `results\<image-name>\candidates\`
  (any previous run for that image is deleted first).

---

## Step 1 - face detection + embedding

**File:** `face_id.py` — `get_embedding(image_path)`

**What:** turn the scan image into one 512-number vector ("embedding") that represents the face.

**How:**
- `cv2.imread()` loads the image as a pixel array (BGR).
- InsightFace's `FaceAnalysis(name="buffalo_l")` runs a set of pre-trained **ONNX** neural-network models on CPU:
  - `det_10g.onnx` - face **detection** (finds face bounding boxes).
  - `w600k_r50.onnx` - face **recognition** (turns the aligned face crop into the 512-d embedding).
  - (others do landmarks / age-gender; not used here.)
- If several faces are found, it keeps the one with the **largest bounding box** (closest / most prominent).
- Returns the embedding, or `None` if no face was detected -> pipeline aborts with
  `No face detected in the scan image. Aborting.`

**Comparing two faces:** `compare_faces(e1, e2, threshold=0.5)`
- Computes **cosine similarity** = `dot(e1,e2) / (|e1| * |e2|)` -> a number roughly in `[-1, 1]`.
- `>= 0.5` is treated as "same person". Higher = more confident (0.97 = near-certain, 0.55 = borderline).

---

## Step 2 - web / reverse-image search

**File:** `combined_search.py` — `get_all_results(image_path)`

**What:** given the scan image, get a list of URLs on the web that might contain the same face.

**How:** runs two engines concurrently (`ThreadPoolExecutor`), then merges + de-duplicates their URLs:

1. **Google Vision Web Detection** — `web_detect.py`
   - Base64-encodes the image, POSTs it to `https://vision.googleapis.com/v1/images:annotate`
     with feature `WEB_DETECTION`.
   - Auth: a short-lived token from `gcloud auth print-access-token` (the `gcloud` CLI must be
     installed and logged in to the `face-search-demo-2026` GCP project).
   - Returns pages/images with matching or visually-similar images.
   - **On this machine `gcloud` is not installed**, so this call raises, is caught in
     `combined_search.py`, and contributes **0 URLs**. The pipeline continues on SerpAPI alone.

2. **SerpAPI Google Lens** — `serpapi` package
   - `client.upload_image(image_path)` uploads the picture to SerpAPI, which returns an `image_id`.
   - `client.search({engine: "google_lens", image_id, type: "all"})` runs Google Lens and returns
     `visual_matches` + `exact_matches`, each with a `link`.
   - Needs `SERPAPI_API_KEY` in the environment.

**Result:** `combined_candidate_urls` — Vision URLs first, then SerpAPI URLs, duplicates removed.
Typically 40-60 URLs. These are mostly **web pages** (news articles, Instagram/X posts, YouTube,
LinkedIn), not direct image files.

---

## Step 3 - download candidates and face-compare each

**File:** `pipeline.py` — `run_candidates_pass()` / `check_candidate()`

**What:** for each candidate URL, get an image from it and check whether its face matches the scan.

**How:** URLs are processed in parallel (`ThreadPoolExecutor`, 5 workers). For each URL:

**Phase 1 - treat the URL as a direct image**
- `download_image(url)` does `requests.get()` and only accepts it if the response
  `Content-Type` is an image. Saves it as `results\<name>\candidates\candidate_<i>.jpg`.
- `get_embedding()` on that file. If no face -> status `no_face`.
- `compare_faces(scan_embedding, candidate_embedding)`.
- If a page URL isn't a direct image, the download is rejected -> status `skipped`.

**Phase 2 - `og:image` fallback for the skipped ones**
- `extract_og_image(page_url)` fetches the HTML and regex-scrapes
  `<meta property="og:image" content="...">` — the preview image a site advertises for
  social sharing (usually the main photo on the page).
- Downloads that image, then embeds + compares as above.

**First hit wins:** the first candidate with `cosine >= 0.5` becomes `confirmed_match` and the
remaining work is cancelled. If nothing matches after both phases ->
`No confirmed match found` and Part 3 does not run.

---

## Step 4 - the confirmed match

**File:** `pipeline.py` — `run_pipeline_fast()`

At this point the pipeline has:

```python
result = {
    "url":        confirmed_match["url"],   # the page URL the match came from
    "score":      confirmed_match["score"], # cosine similarity, e.g. 0.9744
    "image_path": confirmed_match["path"],  # results\<name>\candidates\candidate_<i>.jpg
}
```

`image_path` points at the **exact image bytes** that were face-matched (either the direct
image or the page's `og:image`). That file is the thing Part 3 fingerprints.

---

## Step 5 - SHA-256 fingerprint of the discovered data

**Files:** `blockchain/verify.py` (`hash_discovered_data`) -> `blockchain/image_source.py` +
`blockchain/hashing.py`

**What:** produce one 32-byte number that uniquely identifies (matched image + its URL + a timestamp).

**How:**
1. `resolve_image_bytes()` gets the raw bytes. Order of preference: caller-supplied bytes ->
   local `image_path` (the normal case) -> direct image URL -> page URL -> page's `og:image`.
   If every source fails it raises (it never fingerprints an unrelated image).
2. A timestamp is generated **once**: `int(time.time())` (Unix seconds). It is stored and reused
   later for re-verification - re-verify never uses "now".
3. `compute_fingerprint(image_bytes, url, timestamp)` builds this exact byte string:

   ```
   <raw image bytes>  +  0x1F  +  <normalized URL as UTF-8>  +  0x1F  +  <timestamp as decimal string>
   ```

   - `0x1F` is the ASCII "Unit Separator" - it can't appear in a URL or a number, so the three
     fields can never run together and cause a collision.
   - **normalized URL** (`normalize_url()`): lowercase the scheme + host, drop the default port
     (`:80`/`:443`), drop the `#fragment`, drop a lone trailing `/`. Path and query are kept
     exactly as-is.
   - **timestamp string**: plain integer seconds, e.g. `"1788702796"`.
4. `hashlib.sha256(...)` of that byte string -> the 32-byte fingerprint (shown as 64 hex chars).

Because the timestamp is part of the input, the fingerprint is **different on every run** - that
is expected. Within one run, the value hashed at upload time and at verify time is identical.

---

## Step 6 - upload the fingerprint to the blockchain

**Files:** `blockchain/verify.py` (`upload_verification_record`) + `blockchain/chain.py` +
`blockchain/contract.sol`

**Connect to a chain** (`chain.py`):
- If `.env` has no `RPC_URL` -> **LOCAL mode**: `Web3(EthereumTesterProvider())`, a complete
  Ethereum Virtual Machine running **inside the Python process** (`eth-tester` / `py-evm`).
  No node, no internet, no keys, no gas cost.
- `get_account()` - the wallet that signs. In LOCAL mode it's eth-tester's built-in test account.
- `get_contract()` - in LOCAL mode, if the `FaceVerification` contract isn't deployed yet, it is
  **compiled** (`py-solc-x`, solc 0.8.26) and **deployed** automatically, then cached for the run.
  (`[chain] LOCAL mode: auto-deployed FaceVerification at 0x...` in the output.)

**The smart contract** (`contract.sol`, `FaceVerification`):
- Stores an array of `Record { bytes32 fingerprint; string url; uint256 timestamp; address uploader; }`.
- `storeRecord(fingerprint, url, timestamp)` - appends a record, emits `RecordStored(id, ...)`,
  returns the new id.
- `getRecord(id)` - returns that record.
- The **image is never stored on-chain** - only the 32-byte hash + metadata.

**Send the transaction** (`chain.py::send_tx`):
1. Build a transaction calling `storeRecord(...)` (`build_transaction`) with `from`, `nonce`,
   `chainId`, `gasPrice`.
2. **Sign it locally** with the account's private key (`account.sign_transaction`).
3. Broadcast the signed bytes (`w3.eth.send_raw_transaction`).
4. **Wait for the receipt** (`w3.eth.wait_for_transaction_receipt`) - i.e. wait until the
   transaction is included in a block. `receipt.status == 1` means success.
5. Read the `RecordStored` event from the receipt to get the numeric `record_id`.

Returns: `tx_hash`, `block_number`, `record_id`, `contract_address`, `chain_id`, `uploader`.

---

## Step 7 - read it back, recompute, compare

**File:** `blockchain/verify.py` (`lookup_verification_record`, `verify_discovered_data`,
`record_and_verify`)

1. `lookup_verification_record(record_id)` - calls `getRecord(id)` on the contract (a read-only
   call, no transaction) and returns the stored `fingerprint`, `url`, `timestamp`, `uploader`.
2. **Recompute** the fingerprint locally from the discovered data (same `compute_fingerprint`,
   re-reading the image, re-normalizing the URL, using the stored timestamp).
3. Compare the two hex strings:
   - equal  -> `STATUS: VERIFIED`  (the on-chain record matches the real data)
   - differ -> `STATUS: NOT VERIFIED` (image, URL, or timestamp changed since it was recorded)
4. `record_and_verify()` (the function `pipeline.py` calls) does steps 5-7 in sequence, prints
   the `MATCH FOUND / UPLOADING / LOOKING UP / STATUS` block, and writes
   `results\<name>\blockchain_record.json`:

   ```json
   {
     "status": "VERIFIED",
     "url": "...",
     "url_normalized": "...",
     "timestamp": 1788702796,
     "image_path": "results\\test3\\candidates\\candidate_N.jpg",
     "image_bytes_len": 247752,
     "fingerprint_hex": "....",
     "onchain_fingerprint_hex": "....",
     "tx_hash": "0x....",
     "block_number": 2,
     "record_id": 0,
     "contract_address": "0x....",
     "chain_id": ...,
     "uploader": "0x...."
   }
   ```

`pipeline.py` attaches this dict to its result as `result["blockchain"]` and also writes
`match_result.json` with the whole thing. Parts 1 & 2 output is unchanged; Part 3 is added and
is non-fatal (if the chain step errors, the pipeline still reports the face match).

---

## LOCAL mode caveat

The `eth-tester` chain lives inside one Python process. A record created by `python pipeline.py`
does not exist in a later, separate `python -m blockchain.verify verify ...` process. To watch
verification in one process, use the printed output of the pipeline run itself, or:

```
python -m blockchain.demo_local          # record + re-verify + tamper, all in one run
```

For cross-process re-verification you need a persistent chain (set `RPC_URL` to a testnet like
Sepolia in `.env`).

---

## Files by step

| Step | Files |
|---|---|
| entry / orchestration | `pipeline.py` |
| face embedding + compare | `face_id.py` |
| web search | `combined_search.py`, `web_detect.py`, `serpapi` package |
| candidate download / match | `pipeline.py` (`download_image`, `extract_og_image`, `check_candidate`) |
| fingerprint | `blockchain/hashing.py`, `blockchain/image_source.py` |
| chain connection / deploy | `blockchain/chain.py`, `blockchain/deploy.py`, `blockchain/contract.sol` |
| upload / lookup / verify | `blockchain/verify.py` |
| contract ABI (Python <-> contract) | `blockchain/FaceVerification_abi.json` |
