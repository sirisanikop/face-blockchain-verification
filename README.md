# Face Identification, Web Search & Blockchain Verification

**HH Goa 2026 — Shortlisting Task 3: Face Identification & Blockchain Verification**

This project takes an input face image, searches the web for posts containing the same person, verifies candidate matches using face embeddings, and records the verified result on an Ethereum-compatible blockchain using a tamper-evident SHA-256 fingerprint.

---

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

## Part 1: Face Identification — `face_id.py`

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
