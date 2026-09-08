import sys
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from web_detect import get_candidate_urls
from serpapi import Client


# ============================================================
# SERPAPI GOOGLE LENS
# ============================================================

def get_serpapi_results(image_path):
    """Run Google Lens through SerpAPI and preserve result categories."""

    print("[SerpAPI] Uploading image...")

    api_key = os.getenv("SERPAPI_API_KEY")

    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is not set")

    client = Client(api_key=api_key)

    upload = client.upload_image(image_path)
    image_id = upload["image_id"]

    print("[SerpAPI] Running Google Lens...")

    results = client.search({
        "engine": "google_lens",
        "image_id": image_id,
        "type": "all"
    })

    print("HTTP status: 200")

    return {
        "visual_matches": results.get("visual_matches", []),
        "exact_matches": results.get("exact_matches", [])
    }


# ============================================================
# GET IMAGE URL
# ============================================================

def get_serpapi_image_url(item):
    """
    Get the actual image URL returned by SerpAPI.

    Priority:
        1. image
        2. thumbnail
    """

    return (
        item.get("image")
        or item.get("thumbnail")
        or ""
    )


# ============================================================
# EXTRACT SERPAPI CANDIDATES
# ============================================================

def extract_serpapi_candidates(results):
    """
    Extract BOTH:

        image_url  -> image that will be downloaded/verified
        source_url -> webpage containing/source of the image

    This prevents the source webpage from being lost.
    """

    candidates = []

    # --------------------------------------------------------
    # Exact matches
    # --------------------------------------------------------

    for item in results.get("exact_matches", []):

        image_url = get_serpapi_image_url(item)
        source_url = item.get("link", "")

        if image_url:

            candidates.append({
                "image_url": image_url,
                "source_url": source_url,
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "category": "exact_match"
            })

    # --------------------------------------------------------
    # Visual matches
    # --------------------------------------------------------

    for item in results.get("visual_matches", []):

        image_url = get_serpapi_image_url(item)
        source_url = item.get("link", "")

        if image_url:

            candidates.append({
                "image_url": image_url,
                "source_url": source_url,
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "category": "visual_match"
            })

    # --------------------------------------------------------
    # Deduplicate using image URL
    # --------------------------------------------------------

    unique = {}

    for candidate in candidates:

        image_url = candidate["image_url"]

        if image_url not in unique:
            unique[image_url] = candidate

    return list(unique.values())


# ============================================================
# GOOGLE VISION
# ============================================================

def get_vision_results(image_path):
    """
    Run the existing Google Vision pipeline.

    Google Vision currently returns URLs only.
    """

    urls = get_candidate_urls(image_path)

    candidates = []

    for url in urls:

        candidates.append({
            "image_url": url,
            "source_url": "",
            "title": "",
            "source": "Google Vision",
            "category": "google_vision"
        })

    return {
        "candidate_urls": candidates
    }


# ============================================================
# RUN BOTH SEARCH ENGINES
# ============================================================

def get_all_results(image_path):
    """Run Google Vision and SerpAPI concurrently."""

    vision_result = None
    serpapi_result = None

    vision_error = None
    serpapi_error = None

    with ThreadPoolExecutor(max_workers=2) as executor:

        vision_future = executor.submit(
            get_vision_results,
            image_path
        )

        serpapi_future = executor.submit(
            get_serpapi_results,
            image_path
        )

        futures = {
            vision_future: "Google Vision",
            serpapi_future: "SerpAPI Google Lens"
        }

        for future in as_completed(futures):

            source = futures[future]

            try:

                result = future.result()

                if source == "Google Vision":

                    vision_result = result

                    print(
                        f"[Google Vision] completed: "
                        f"{len(result['candidate_urls'])} candidate URLs"
                    )

                else:

                    serpapi_result = result

                    candidates = extract_serpapi_candidates(
                        result
                    )

                    print(
                        f"[SerpAPI Google Lens] completed: "
                        f"{len(candidates)} candidate image URLs"
                    )

            except Exception as e:

                if source == "Google Vision":

                    vision_error = str(e)

                    print(
                        f"[Google Vision] failed: {e}"
                    )

                else:

                    serpapi_error = str(e)

                    print(
                        f"[SerpAPI Google Lens] failed: {e}"
                    )

    # ========================================================
    # SAFETY FALLBACKS
    # ========================================================

    if vision_result is None:

        vision_result = {
            "candidate_urls": []
        }

    if serpapi_result is None:

        serpapi_result = {
            "visual_matches": [],
            "exact_matches": []
        }

    # ========================================================
    # GET CANDIDATES
    # ========================================================

    vision_candidates = vision_result["candidate_urls"]

    serpapi_candidates = extract_serpapi_candidates(
        serpapi_result
    )

    # ========================================================
    # COMBINE + DEDUPLICATE
    # ========================================================

    combined = []

    seen_images = set()

    for candidate in (
        vision_candidates + serpapi_candidates
    ):

        image_url = candidate["image_url"]

        if image_url not in seen_images:

            seen_images.add(image_url)

            combined.append(candidate)

    return {

        "google_vision": vision_result,

        "serpapi_google_lens": serpapi_result,

        "combined_candidates": combined,

        "errors": {
            "google_vision": vision_error,
            "serpapi_google_lens": serpapi_error
        }
    }


# ============================================================
# PRINT RESULTS
# ============================================================

def print_results(image_path, results):

    vision = results["google_vision"]

    serpapi = results["serpapi_google_lens"]

    combined = results["combined_candidates"]

    print("\n")
    print("========================================")
    print("        COMBINED IMAGE SEARCH")
    print("========================================")

    print(f"\nImage: {image_path}")

    # ========================================================
    # GOOGLE VISION
    # ========================================================

    print("\n[Google Vision]")

    print(
        f"Candidate URLs: "
        f"{len(vision['candidate_urls'])}"
    )

    # ========================================================
    # SERPAPI
    # ========================================================

    print("\n[SerpAPI Google Lens]")

    print(
        f"Visual Matches: "
        f"{len(serpapi['visual_matches'])}"
    )

    print(
        f"Exact Matches: "
        f"{len(serpapi['exact_matches'])}"
    )

    serpapi_candidates = extract_serpapi_candidates(
        serpapi
    )

    print(
        f"Candidate Image URLs: "
        f"{len(serpapi_candidates)}"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n")
    print("========================================")
    print("          RESULT SUMMARY")
    print("========================================")

    print(
        f"\nGoogle Vision URLs: "
        f"{len(vision['candidate_urls'])}"
    )

    print(
        f"SerpAPI Image URLs: "
        f"{len(serpapi_candidates)}"
    )

    print(
        f"Combined unique URLs: "
        f"{len(combined)}"
    )

    # ========================================================
    # SERPAPI RESULTS
    # ========================================================

    print("\n")
    print("========================================")
    print("       SERPAPI GOOGLE LENS RESULTS")
    print("========================================")

    for category in [
        "visual_matches",
        "exact_matches"
    ]:

        print(
            f"\n--- {category.replace('_', ' ').title()} ---"
        )

        items = serpapi.get(category, [])

        if not items:

            print("No results found.")
            continue

        for i, item in enumerate(items, 1):

            title = item.get(
                "title",
                "No title"
            )

            source = item.get(
                "source",
                "Unknown source"
            )

            image_url = get_serpapi_image_url(
                item
            )

            website_url = item.get(
                "link",
                ""
            )

            print(f"\n{i}. {title}")

            print(
                f"   Source: {source}"
            )

            if image_url:

                print(
                    f"   Image: {image_url}"
                )

            if website_url:

                print(
                    f"   Website: {website_url}"
                )

    # ========================================================
    # GOOGLE VISION
    # ========================================================

    print("\n")
    print("========================================")
    print("       GOOGLE VISION RESULTS")
    print("========================================")

    for i, candidate in enumerate(
        vision["candidate_urls"],
        1
    ):

        print(
            f"{i}. {candidate['image_url']}"
        )

    # ========================================================
    # ERRORS
    # ========================================================

    errors = results["errors"]

    if errors["google_vision"]:

        print(
            "\n[WARNING] Google Vision failed:"
        )

        print(
            errors["google_vision"]
        )

    if errors["serpapi_google_lens"]:

        print(
            "\n[WARNING] SerpAPI Google Lens failed:"
        )

        print(
            errors["serpapi_google_lens"]
        )


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(results, image_path):

    output = {

        "image": image_path,

        "google_vision":
            results["google_vision"],

        "serpapi_google_lens":
            results["serpapi_google_lens"],

        "combined_candidates":
            results["combined_candidates"],

        "errors":
            results["errors"]
    }

    with open(
        "result.json",
        "w"
    ) as f:

        json.dump(
            output,
            f,
            indent=2
        )

    print("\n")
    print("========================================")
    print("Results saved to result.json")
    print("========================================")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 2:

        print("Usage:")
        print(
            "python combined_search.py "
            "test_images/test4.jpg"
        )

        sys.exit(1)

    image_path = sys.argv[1]

    if not os.path.isfile(image_path):

        print(
            f"Image not found: {image_path}"
        )

        sys.exit(1)

    results = get_all_results(
        image_path
    )

    print_results(
        image_path,
        results
    )

    save_results(
        results,
        image_path
    )