import os
import shutil
import requests
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from face_id import get_embedding, compare_faces
from combined_search import get_all_results


def download_image(url, save_path):
    try:
        response = requests.get(url, timeout=10)
        content_type = response.headers.get("Content-Type", "")
        if response.status_code == 200 and "image" in content_type:
            with open(save_path, "wb") as f:
                f.write(response.content)
            return True
        return False
    except requests.RequestException:
        return False


def extract_og_image(page_url):
    try:
        response = requests.get(page_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code != 200:
            return None
        html = response.text
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if match:
            return match.group(1)
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            html, re.IGNORECASE
        )
        if match:
            return match.group(1)
        return None
    except requests.RequestException:
        return None


def check_candidate(index, url, scan_embedding, download_dir, via_og_fallback=False):
    save_path = os.path.join(download_dir, f"candidate_{index}.jpg")

    if via_og_fallback:
        og_image_url = extract_og_image(url)
        if not og_image_url:
            return {"url": url, "status": "og_fallback_failed", "score": None, "match": False, "path": None}
        success = download_image(og_image_url, save_path)
    else:
        success = download_image(url, save_path)

    if not success:
        status = "og_fallback_failed" if via_og_fallback else "skipped"
        return {"url": url, "status": status, "score": None, "match": False, "path": None}

    candidate_embedding = get_embedding(save_path)
    if candidate_embedding is None:
        return {"url": url, "status": "no_face", "score": None, "match": False, "path": save_path}

    is_match, score = compare_faces(scan_embedding, candidate_embedding)
    status = "checked_via_og_image" if via_og_fallback else "checked"
    return {"url": url, "status": status, "score": score, "match": is_match, "path": save_path}


def run_candidates_pass(candidate_urls, scan_embedding, download_dir, max_workers, via_og_fallback=False):
    all_results = []
    confirmed_match = None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(check_candidate, i, url, scan_embedding, download_dir, via_og_fallback): (i, url)
            for i, url in enumerate(candidate_urls)
        }

        for future in as_completed(futures):
            i, url = futures[future]
            result = future.result()
            all_results.append(result)

            tag = " (via og:image)" if via_og_fallback else ""
            if result["status"] in ("checked", "checked_via_og_image"):
                print(f"[{i+1}] {url}{tag}\n     -> Score: {result['score']:.4f} | Match: {result['match']}\n")
                if result["match"] and confirmed_match is None:
                    confirmed_match = result
                    print(f"CONFIRMED MATCH FOUND: {url} (score: {result['score']:.4f})")
                    for f in futures:
                        f.cancel()
                    break
            elif result["status"] == "no_face":
                print(f"[{i+1}] {url}{tag}\n     -> No face detected, skipped\n")
            else:
                print(f"[{i+1}] {url}{tag}\n     -> Skipped\n")

    return all_results, confirmed_match


def run_pipeline_fast(scan_image_path, max_workers=5):
    # Derive a clean label from the scan filename, e.g. "test5.jpg" -> "test5"
    scan_name = os.path.splitext(os.path.basename(scan_image_path))[0]

    output_dir = os.path.join("results", scan_name)
    download_dir = os.path.join(output_dir, "candidates")

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(download_dir, exist_ok=True)

    scan_embedding = get_embedding(scan_image_path)
    if scan_embedding is None:
        print("No face detected in the scan image. Aborting.")
        return None

    print(f"Searching for matching content (Google Vision + SerpAPI)...")
    search_results = get_all_results(scan_image_path)
    candidate_urls = search_results["combined_candidate_urls"]
    print(f"Found {len(candidate_urls)} combined candidate URL(s).\n")

    print("=== Phase 1: checking direct image URLs ===\n")
    all_checked, confirmed_match = run_candidates_pass(
        candidate_urls, scan_embedding, download_dir, max_workers, via_og_fallback=False
    )

    if confirmed_match is None:
        skipped_urls = [r["url"] for r in all_checked if r["status"] == "skipped"]
        print(f"\n=== Phase 1 found no match. Phase 2: retrying {len(skipped_urls)} skipped URLs via og:image ===\n")
        phase2_checked, confirmed_match = run_candidates_pass(
            skipped_urls, scan_embedding, download_dir, max_workers, via_og_fallback=True
        )
        all_checked.extend(phase2_checked)

    print("\n" + "=" * 40)
    print("SUMMARY")
    print("=" * 40)
    print(f"Scan image: {scan_image_path}")
    print(f"Total candidates: {len(candidate_urls)}")
    print(f"Total checked (both phases): {len(all_checked)}")

    result = None
    if confirmed_match:
        result = {"url": confirmed_match["url"], "score": confirmed_match["score"], "image_path": confirmed_match["path"]}
        print(f"Match: {result['url']} (score: {result['score']:.4f})")

        # --- Part 3: blockchain verification of the confirmed match ---
        # Hash (matched image bytes + URL + timestamp) -> upload to chain -> look it
        # back up -> recompute locally -> report VERIFIED / NOT VERIFIED.
        # Non-fatal: if the chain/config is unavailable, Parts 1-2 output is unaffected.
        # Set ENABLE_BLOCKCHAIN=0 to skip this step entirely.
        if os.getenv("ENABLE_BLOCKCHAIN", "1").strip().lower() not in ("0", "false", "no"):
            try:
                from blockchain.verify import record_and_verify
                result["blockchain"] = record_and_verify(
                    image_path=result["image_path"],
                    url=result["url"],
                    output_dir=output_dir,
                )
            except Exception as e:
                print(f"[blockchain] Part 3 step failed (pipeline continues): {e}")
                result["blockchain"] = {"status": "error", "error": str(e)}
    else:
        print("No confirmed match found, even after og:image fallback.")

    result_path = os.path.join(output_dir, "match_result.json")
    with open(result_path, "w") as f:
        json.dump({
            "scan_image": scan_image_path,
            "best_match": result,
            "all_checked_results": all_checked
        }, f, indent=2)
    print(f"\nSaved result to {result_path}")

    return result


if __name__ == "__main__":
    import sys

    # Usage:  python pipeline.py [path/to/scan_image.jpg]
    # Defaults to the bundled sample if no path is given.
    scan_image = sys.argv[1] if len(sys.argv) > 1 else "test_images/test7.jpg"

    if not os.path.isfile(scan_image):
        print(f"Image not found: {scan_image}")
        sys.exit(1)

    result = run_pipeline_fast(scan_image)
    print("\nFinal result:", result)
