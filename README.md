# Face Identification, Web Search & Blockchain Verification

**HH Goa 2026 — Shortlisting Task 3: Face Identification & Blockchain Verification**

This project takes an input face image, searches the web for posts containing the same person, verifies candidate matches using face embeddings, and records the verified result on an Ethereum-compatible blockchain using a tamper-evident SHA-256 fingerprint.

## What the Project Does

The pipeline:

1. Detects and encodes the target face using **InsightFace**.
2. Searches the web using **Google Cloud Vision** and **SerpAPI Google Lens** in parallel.
3. Combines and deduplicates candidate results.
4. Downloads candidate images and detects all faces within them.
5. Compares every candidate face against the target embedding using **cosine similarity**.
6. Confirms a match when the similarity exceeds the configured threshold.
7. Generates a SHA-256 fingerprint of the matched image, URL, and timestamp.
8. Stores the fingerprint and metadata on-chain.
9. Recomputes and compares the fingerprint during verification to detect tampering.

---

# Part 1: Face Identification — `face_id.py`

- **Model:** InsightFace `buffalo_l`, ONNX-based, running through ONNX Runtime on CPU.
- **Embeddings:** Generates 512-dimensional facial embeddings.
- **Multi-face detection:** `get_all_faces()` detects and embeds every face in an image while storing its bounding box and area.
- **Input face selection:** When multiple faces are present in the input image, `select_input_face()` lets the user choose the target face. A single detected face is selected automatically.
- **Face comparison:** `compare_faces()` uses cosine similarity with a configurable threshold of `0.5`.
- **Candidate-side matching:** Every face in a candidate image is compared against the target embedding, and the highest similarity score is retained.

The threshold was empirically tested on sample pairs, with same-person pairs scoring approximately **0.55–0.97** and different-person pairs approximately **-0.13–0.26**.

### Face Matching Flow

```text
Input Image
    ↓
Detect All Faces
    ↓
Select Target Face
    ↓
Generate 512-D Embedding
    ↓
Compare with Candidate Faces
    ↓
Cosine Similarity
    ↓
Threshold Check
    ↓
MATCH / NO MATCH

```

---

# Part 2: Web / Social Media Search

**Files:** `combined_search.py`, `web_detect.py`, `serpapi_search.py`

Two search engines run concurrently using `ThreadPoolExecutor`:

### Google Cloud Vision — Web Detection

Uses the Google Cloud Vision Web Detection API to retrieve:

- Pages containing matching images
- Full and partial image matches
- Visually similar images
- Best-guess labels

Authentication uses a short-lived `gcloud` OAuth token.

### SerpAPI — Google Lens

Uses the SerpAPI Google Lens endpoint to retrieve:

- Visual matches
- Exact matches
- Source pages
- Direct candidate image URLs

When available, the pipeline prefers SerpAPI's direct `image` URL over the source `link`, since some platforms restrict direct webpage scraping.

### Candidate Processing

Results from both engines are merged and deduplicated by URL.

For webpage candidates that do not directly provide an image:

```text
Webpage URL
    ↓
Fetch HTML
    ↓
Extract <meta property="og:image">
    ↓
Download Candidate Image

```

If one search engine fails, the pipeline continues using results from the other engine.

---

# Part 3: Blockchain Verification — `blockchain/`

The blockchain component uses an **Ethereum-compatible network**.

It supports:

- **Sepolia testnet** — chain ID `11155111`, using an RPC provider such as Infura or Alchemy.
- **Local/offline chain** — `eth-tester` / `py-evm`, enabled automatically when `RPC_URL` is empty.

### Hashing

The SHA-256 fingerprint is generated from:

```text
raw_image_bytes
      +
normalized_url
      +
canonical_timestamp

```

The fields are separated using the ASCII Unit Separator (`0x1F`) to prevent boundary collisions.

The timestamp is generated once when the match is recorded and then persisted for later verification.

### What Is Stored On-Chain

Only the following are stored:

- 32-byte SHA-256 fingerprint
- Source URL
- Timestamp
- Uploader address

**The image itself is never stored on-chain.**

### Smart Contract

`contract.sol` defines the `FaceVerification` contract.

The main operation is:

```text
storeRecord(fingerprint, url, timestamp)

```

This stores the record and emits a `RecordStored` event containing the record ID.

### Re-Verification

`verify_discovered_data()`:

1. Reads the original record from the blockchain.
2. Re-fetches the discovered image/data.
3. Recomputes the SHA-256 fingerprint.
4. Compares it byte-for-byte with the on-chain fingerprint.
5. Returns `VERIFIED` or `NOT VERIFIED`.

The CLI can also demonstrate tamper detection by intentionally verifying a different image.

---

# Part 4: Pipeline Orchestration — `pipeline.py`

`run_pipeline_fast(scan_image_path)` is the main end-to-end entry point.

### Input Face Selection

`select_input_face()`:

- Automatically selects the face if exactly one is detected.
- Displays approximate position and size when multiple faces are detected.
- Lets the user explicitly choose which face to search for.

### Candidate Matching

`check_candidate()`:

- Downloads the candidate image.
- Detects every face in the image.
- Compares every detected face with the selected target embedding.
- Keeps the highest similarity score.
- Records the matched face index and total number of detected faces.

This allows the system to handle group photos and other multi-person candidate images.

### Two-Phase Candidate Checking

**Phase 1 — Direct download**

Attempts to download every candidate's direct `image_url`.

**Phase 2 —** **`og:image`** **fallback**

If Phase 1 finds no match, candidates that could not be directly downloaded are retried by extracting their `og:image` URL.

### Concurrency

Each phase uses:

```text
ThreadPoolExecutor(max_workers=5)

```

Five candidates can therefore be downloaded, processed, and compared concurrently.

### Match Selection

The pipeline uses **first confirmed match** logic. The first candidate whose best-face similarity reaches the `0.5` threshold is accepted, and remaining work is cancelled where possible.

This avoids unnecessary processing once the task requirement of finding at least one verified matching post has been satisfied.

### Blockchain Handoff

Once a face match is confirmed:

```text
pipeline.py
    ↓
blockchain.verify.record_and_verify()
    ↓
Hash
    ↓
Store on-chain
    ↓
Read record
    ↓
Recompute hash
    ↓
Verify

```

Blockchain execution is controlled by `ENABLE_BLOCKCHAIN` and is isolated from the face-search result. If blockchain configuration fails, the confirmed face match and search results are still saved.

### Output

Results are stored per input image:

```text
results/
└── <scan-image-name>/
    └── match_result.json

```

The JSON contains the checked candidates, match information, similarity score, source URL, and blockchain status.

---

# End-to-End Pipeline

```text
                 INPUT FACE IMAGE
                         ↓
                 Select Target Face
                         ↓
                  Face Embedding
                         ↓
             ┌───────────┴───────────┐
             ↓                       ↓
       Google Vision            SerpAPI Lens
             ↓                       ↓
        Candidates              Candidates
             └───────────┬───────────┘
                         ↓
                Deduplicate URLs
                         ↓
                Candidate Pool
                         ↓
             Download Candidate Images
                         ↓
                 Detect ALL Faces
                         ↓
              Compare Face Embeddings
                         ↓
               Best Face / Score
                         ↓
                 Score ≥ 0.5?
                    ↙       ↘
                  YES        NO
                   ↓          ↓
             Confirm Match   Continue
                   ↓
             Blockchain Hash
                   ↓
              Store On-Chain
                   ↓
             Recompute + Compare
                   ↓
              VERIFIED / NOT VERIFIED

```

---

# Known Limitations

- **Index-dependent search:** Google Vision and Google Lens can only find content that has already been crawled/indexed. They are not general-purpose face-recognition systems.
- **Platform restrictions:** Public content on platforms such as Instagram and LinkedIn may be inconsistently indexed or inaccessible.
- **Shared underlying data:** Google Vision and Google Lens rely substantially on the same Google-crawled web data. Running both improves result diversity and ranking, but does not provide completely independent web coverage.
- **`og:image`** **fallback:** Some platforms prevent webpage scraping, so `og:image` extraction is not guaranteed. SerpAPI's direct image URLs recover some of these cases.
- **First-match strategy:** The pipeline stops at the first candidate above the threshold rather than exhaustively finding the globally highest-scoring candidate.

---

# Team

| MemberResponsibility |                                |
| -------------------- | ------------------------------ |
| **Prachi Jalan**     | Face Verification & Comparison |
| **Siri Sanikop**     | Web Search                     |
| **Tanishk Gowda**    | Blockchain Verification        |

---

# Setup & Usage

## 1. Install Dependencies

```bash
pip install -r requirements.txt

```

## 2. Configure Environment

```bash
cp .env.example .env

```

Configure the required values:

```text
SERPAPI_API_KEY=
RPC_URL=
PRIVATE_KEY=
CONTRACT_ADDRESS=

```

Google Vision authentication is configured separately through `gcloud`.

## 3. Run the Pipeline

```bash
python pipeline.py path/to/scan_image.jpg

```

## 4. Re-Verify a Blockchain Record

```bash
python -m blockchain.verify verify \
  --record-file results/<image-name>/blockchain_record.json

```

To demonstrate tamper detection:

```bash
python -m blockchain.verify verify \
  --record-file results/<image-name>/blockchain_record.json \
  --tamper-image some_other_photo.jpg

```

## 5. Run Fully Offline

No testnet or external keys are required:

```bash
python -m blockchain.demo_local
```
