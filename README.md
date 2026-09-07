# Face Identification & Web Verification Pipeline

## Face Identification & Verification

- **Multi-face detection:** Detects and generates embeddings for all faces using InsightFace.
- **Target face selection:** Supports explicit face selection when multiple faces are present.
- **Embedding-based verification:** Uses 512-D face embeddings with **cosine similarity** for identity matching.
- **Multi-face candidate matching:** Compares the target embedding against every face in each candidate image and selects the highest similarity.
- **Face localization:** Stores bounding boxes and face areas for each detected face.
- **Configurable threshold:** Uses a tunable similarity threshold (`0.5` by default).
- **Structured output:** Records match score, matched face, detected face count, source URL, and output path for downstream verification.

## Reverse Image / Web Search

- Two engines run **in parallel** on the same input image — Google Cloud Vision and SerpAPI Google Lens — since neither alone has full web/social coverage; results are merged and deduplicated by URL.
- Output is a **candidate pool only**, not a confirmed identity — matches get verified later against face embeddings before being trusted.
- If one engine fails or returns zero results, the pipeline continues with the other rather than halting (known gap: Instagram/private accounts are inconsistently indexed by both).

| **Engine** | **Provides** |
|---|---|
| **Google Cloud Vision — Web Detection** | Pages with matching images, full/partial matches, visually similar images |
| **SerpAPI — Google Lens** | Visual matches, exact matches |

```text
                         SAME INPUT IMAGE
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
          Google Vision                  SerpAPI
          Web Detection               Google Lens
                   │                         │
                   ▼                         ▼
          Vision candidates            Lens candidates
                   │                         │
                   └────────────┬────────────┘
                                ▼
                       Deduplicate by URL
                                ▼
                       Combined candidate pool
                                ▼
                 Handoff to face-embedding verification
```

## Person C — Blockchain Verification

- **Blockchain:** Sepolia testnet using a wallet and RPC provider such as Alchemy/Infura.
- **Hashing:** Generate a **SHA-256 hash** from the discovered post’s image bytes + URL + timestamp.
- **On-chain upload:** Store the generated hash and relevant metadata on the blockchain through a transaction.
- **Re-verification:** Recalculate the hash later and compare it with the **on-chain record** to demonstrate that the discovered data has not been tampered with.

---

# Technical Overview: Face Identification Module (`face_id.py`)

This module serves as the primary **biometric encoding and feature-extraction engine** for the pipeline. It processes input images, detects face boundaries, generates high-dimensional facial embeddings, and performs cosine similarity matching to identify faces across source targets.

- **InsightFace (`buffalo_l` Model Zoo) Integration:** Leverages the ONNX-backed InsightFace framework to perform combined face detection and 512-dimensional feature vector extraction in a single forward pass, optimized for high variance in pose and lighting across web images.
- **Global Model Initialization Pattern:** Initializes `FaceAnalysis` once into memory (`_app`) to avoid runtime model loading overhead, providing fast inference across multiple downstream search requests.
- **Area-Based Dominant Face Selection (`get_embedding`):** Rather than blindly selecting the first detected face, `get_all_faces()` dynamically calculates spatial bounding-box areas using `A = (x2 - x1) × (y2 - y1)` to target and extract the principal subject from crowded or background-cluttered images.
- **Cosine Similarity Matching Core (`compare_faces`):** Computes normalized dot products between embedding vectors against a tunable decision threshold (`0.5`), returning scalar similarity scores for downstream identification and blockchain verification payload creation.

---

# 8-Point Face Identification Breakdown

## 1. `_app = FaceAnalysis(...)`

Loads the **InsightFace** toolkit and uses the **`buffalo_l`** model.

The model is initialized once and kept in memory so that repeated inference does not require loading the model for every request.

---

## 2. `get_all_faces()`

This is the main **face detection + embedding extraction** function.

### Pipeline

```text
Image path
    ↓
cv2.imread()
    ↓
InsightFace detects faces
    ↓
For every detected face:
    ├── embedding
    ├── bounding box
    └── face area
    ↓
Return list of faces
```

For each detected face:

```text
x1, y1, x2, y2 = face.bbox
```

The bounding-box area is calculated as:

```text
area = (x2 - x1) * (y2 - y1)
```

The function stores:

```text
{
    "embedding": face.embedding,
    "bbox": [x1, y1, x2, y2],
    "area": area
}
```

This allows the system to handle:

```text
Person A + Person B + Person C
            ↓
       Detect A, B, C
            ↓
   Generate embeddings
```

---

## 3. `get_embedding()`

This is a **backwards-compatible helper**.

It calls:

```text
faces = get_all_faces(image_path)
```

Then selects the face with the largest bounding-box area:

```text
largest_face = max(faces, key=lambda f: f["area"])
```

Finally:

```text
return largest_face["embedding"]
```

So the flow is:

```text
Image
  ↓
Detect all faces
  ↓
Find largest face
  ↓
Return largest face's embedding
```

It is useful for older code that expects:

```text
get_embedding(image)
```

to return a single embedding. It is redundant in the final multi-face pipeline and is mainly useful for testing/backwards compatibility.

---

## 4. `compare_faces()`

This is the actual **face verification function**.

```text
Embedding 1
     +
Embedding 2
     ↓
Cosine similarity
     ↓
Similarity score
     ↓
Compare with threshold = 0.5
     ↓
MATCH / NO MATCH
```

The similarity calculation uses NumPy and produces a scalar score that determines whether the two embeddings are sufficiently similar.

---

## 5. `if __name__ == "__main__"`

This is a **test/demo section**, not the actual reverse-image-search pipeline.

It takes:

```text
test5.jpg
test7.jpg
```

and performs:

```text
test5.jpg
   ↓
get_embedding()
   ↓
embedding 1

test7.jpg
   ↓
get_embedding()
   ↓
embedding 2

embedding 1 + embedding 2
   ↓
compare_faces()
   ↓
score + match
```

Example output:

```text
Similarity score: 0.9432
Match: True
```

This allows `face_id.py` to be run directly to test whether the face-recognition component works.

---

## 6. Overall `face_id.py` Pipeline

```text
                         IMAGE
                           │
                           ▼
                  ┌─────────────────┐
                  │ InsightFace     │
                  │ Face Detection  │
                  └────────┬────────┘
                           │
                    All detected faces
                           │
                  ┌────────▼────────┐
                  │ For each face   │
                  │ • Embedding     │
                  │ • Bounding box  │
                  │ • Area          │
                  └────────┬────────┘
                           │
                           ▼
                    get_all_faces()
                           │
                 ┌─────────┴─────────┐
                 │                   │
             Multiple            Single/
              faces              largest
                 │                   │
                 ▼                   ▼
          Select target        get_embedding()
              face
                 │
                 └─────────┬─────────┘
                           ▼
                    Face Embedding
                           │
                           ▼
                    compare_faces()
                           │
                    Cosine Similarity
                           │
                     Threshold Check
                           │
                           ▼
                     MATCH / NO MATCH
```

---

## 7. How `face_id.py` Fits into the Larger Project

The face module acts as the **face verification engine** inside the larger system:

```text
INPUT PERSON IMAGE
        ↓
Detect faces
        ↓
Select target face
        ↓
Generate embedding
        ↓
Reverse image search
        ↓
Candidate images
        ↓
Detect ALL faces in each candidate
        ↓
Generate candidate embeddings
        ↓
Compare target ↔ every candidate face
        ↓
Best similarity score
        ↓
MATCH / NO MATCH
        ↓
Blockchain verification
```

The important technical feature is that candidate images are **not treated as single-person images**. Every face in a candidate image is detected and compared against the selected target face.

---

## 8. Multi-Face Handling

Two separate multi-face cases are handled:

### Multiple faces in the input image

`select_input_face()` identifies all faces and lets the user choose the target when multiple people are present.

### Multiple faces in a candidate image

`check_candidate()` detects every face in the candidate image and compares each one with the target embedding.

For example:

```text
Input face
    ↓
Candidate #7
    ├── Face 1 → 0.31
    ├── Face 2 → 0.47
    ├── Face 3 → 0.82  ← highest
    └── Face 4 → 0.29
```

The highest similarity score is retained.

---

# 6-Point Search & Verification Pipeline

## 1. `download_image(url, save_path)`

**Job:** Download a candidate image from a URL.

```text
URL
 ↓
requests.get()
 ↓
Check HTTP 200 + Content-Type = image
 ↓
Save image locally
 ↓
True / False
```

This is the image downloader used when a candidate URL points directly to an image.

---

## 2. `extract_og_image(page_url)`

**Job:** Handle candidate URLs that point to webpages rather than directly to image files.

```text
Webpage URL
    ↓
Download HTML
    ↓
Search for <meta property="og:image">
    ↓
Extract image URL
```

This provides the **webpage → image URL fallback**.

---

## 3. `check_candidate(...)`

This is the core **candidate face-matching function**.

```text
Candidate URL
      ↓
Is OG fallback needed?
   ↙          ↘
 No           Yes
 ↓             ↓
Download    Extract og:image
directly        ↓
            Download image
      ↓
Detect ALL faces
      ↓
Compare input face
against EVERY face
      ↓
Keep highest similarity
      ↓
Return result
```

If a candidate contains four people, the function compares the input against all four and keeps the highest similarity score.

---

## 4. `run_candidates_pass(...)`

**Job:** Run `check_candidate()` on many candidate URLs simultaneously.

Instead of:

```text
Candidate 1 → wait
Candidate 2 → wait
Candidate 3 → wait
...
```

the pipeline uses parallel workers through **`ThreadPoolExecutor`**:

```text
Candidate 1 ─┐
Candidate 2 ─┤
Candidate 3 ─┼──→ Parallel workers
Candidate 4 ─┤
Candidate 5 ─┘
```

If a result crosses the similarity threshold:

```text
MATCH FOUND
    ↓
confirmed_match = result
    ↓
Stop / cancel remaining work
```

This provides **parallel candidate processing + early stopping**.

---

## 5. User-Facing Face Selection Helpers

### `describe_face_position(...)`

Converts a bounding box into a human-readable location.

```text
bbox
 ↓
center_x / center_y
 ↓
left / center / right
+
upper / middle / lower
```

Examples:

```text
Face → "left, upper"
Face → "center, middle"
Face → "right, lower"
```

This helps the user identify which face they want to search.

### `describe_face_size(...)`

Compares the size of detected faces and returns:

```text
large
medium
small
```

These helpers are for **UI/user-selection assistance**, not the actual face-matching calculation.

---

## 6. `select_input_face(...)` + `run_pipeline_fast(...)`

### `select_input_face(...)`

Handles multiple people in the **original input image**.

```text
Input scan
    ↓
get_all_faces()
    ↓
How many faces?
```

If there is one face:

```text
Automatically select it
```

If there are multiple faces:

```text
Face 1 → left, upper, large
Face 2 → center, middle, medium
Face 3 → right, lower, small
        ↓
Ask user: Which face?
        ↓
Return selected face's embedding
```

### `run_pipeline_fast(...)`

This is the **master function** that brings the entire pipeline together:

```text
INPUT IMAGE
     ↓
select_input_face()
     ↓
Selected embedding
     ↓
get_all_results()
     ↓
Google Vision + SerpAPI
     ↓
Candidate URLs
     ↓
┌──────────────────────┐
│       PHASE 1        │
│    Direct download   │
└──────────┬───────────┘
           ↓
   Detect candidate faces
           ↓
   Compare against input
           ↓
      MATCH FOUND?
       ↙        ↘
     YES         NO
      ↓           ↓
    STOP       PHASE 2
                  ↓
            OG:image fallback
                  ↓
             Detect faces
                  ↓
               Compare
                  ↓
            MATCH / NO MATCH
                  ↓
           Blockchain verify
                  ↓
              Save JSON
```

The master function therefore:

1. Selects the input face.
2. Gets reverse-search candidates from Google Vision + SerpAPI.
3. Runs the direct-download candidate pass.
4. Uses the `og:image` fallback when necessary.
5. Sends a confirmed match for blockchain verification.
6. Saves the resulting JSON payload.

---

# Complete Person A Flow

> **Input face → detect/select target face → obtain reverse-search candidates → download candidate images → detect all faces → compare embeddings → select highest similarity → confirm match → send verified result to blockchain.**

Importantly, `select_input_face()` handles **multiple faces in the input**, while `check_candidate()` handles **multiple faces in each candidate image**.
