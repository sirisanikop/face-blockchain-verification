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
# GET IMAGE URL FROM SERPAPI RESULT
# ============================================================

def get_serpapi_image_url(item):
    """
    Get the actual image URL returned by SerpAPI.

    Priority:
        1. image      -> full image URL
        2. thumbnail  -> fallback if full image is unavailable
    """

    return (
        item.get("image")
        or item.get("thumbnail")
        or ""
    )


# ============================================================
# EXTRACT SERPAPI IMAGE URLS
# ============================================================

def extract_serpapi_urls(results):
    """
    Extract actual image URLs from SerpAPI results.

    These are used for the combined image-search output.
    The webpage/source URL is NOT used unless an image URL
    is unavailable.
    """

    urls = []

    # -------------------------
    # Exact matches
    # -------------------------

    for item in results.get("exact_matches", []):

        image_url = get_serpapi_image_url(item)

        if image_url:
            urls.append(image_url)

    # -------------------------
    # Visual matches
    # -------------------------

    for item in results.get("visual_matches", []):

        image_url = get_serpapi_image_url(item)

        if image_url:
            urls.append(image_url)

    # Remove duplicates while preserving order
    return list(dict.fromkeys(urls))


# ============================================================
# GOOGLE VISION
# ============================================================

def get_vision_results(image_path):
    """
    Run the existing Google Vision pipeline.

    The existing get_candidate_urls() function is preserved.
    """

    urls = get_candidate_urls(image_path)

    return {
        "candidate_urls": urls
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

        # Google Vision
        vision_future = executor.submit(
            get_vision_results,
            image_path
        )

        # SerpAPI Google Lens
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

                    serpapi_urls = extract_serpapi_urls(result)

                    print(
                        f"[SerpAPI Google Lens] completed: "
                        f"{len(serpapi_urls)} candidate image URLs"
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
    # GET RESULTS
    # ========================================================

    vision_urls = vision_result["candidate_urls"]

    serpapi_urls = extract_serpapi_urls(
        serpapi_result
    )

    # ========================================================
    # COMBINE AND DEDUPLICATE
    # ========================================================

    combined = list(
        dict.fromkeys(
            vision_urls + serpapi_urls
        )
    )

    return {
        "google_vision": vision_result,

        "serpapi_google_lens": serpapi_result,

        "combined_candidate_urls": combined,

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

    combined = results["combined_candidate_urls"]

    # ========================================================
    # HEADER
    # ========================================================

    print("\n")
    print("========================================")
    print("        COMBINED IMAGE SEARCH")
    print("========================================")

    print(f"\nImage: {image_path}")

    # ========================================================
    # GOOGLE VISION SUMMARY
    # ========================================================

    print("\n[Google Vision]")

    print(
        f"Candidate URLs: "
        f"{len(vision['candidate_urls'])}"
    )

    # ========================================================
    # SERPAPI SUMMARY
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

    print(
        f"Candidate Image URLs: "
        f"{len(extract_serpapi_urls(serpapi))}"
    )

    # ========================================================
    # RESULT SUMMARY
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
        f"{len(extract_serpapi_urls(serpapi))}"
    )

    print(
        f"Combined unique URLs: "
        f"{len(combined)}"
    )

    # ========================================================
    # SERPAPI GOOGLE LENS RESULTS
    # ========================================================

    print("\n")
    print("========================================")
    print("       SERPAPI GOOGLE LENS RESULTS")
    print("========================================")

    # ========================================================
    # VISUAL MATCHES
    # ========================================================

    print("\n--- Visual Matches ---")

    if serpapi["visual_matches"]:

        for i, item in enumerate(
            serpapi["visual_matches"],
            1
        ):

            title = item.get(
                "title",
                "No title"
            )

            source = item.get(
                "source",
                "Unknown source"
            )

            # IMPORTANT:
            # Get the actual image URL,
            # NOT the webpage URL.
            image_url = get_serpapi_image_url(
                item
            )

            # Keep webpage URL separately
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

            else:

                print(
                    "   Image: Not available"
                )

            if website_url:

                print(
                    f"   Website: {website_url}"
                )

    else:

        print(
            "No visual matches found."
        )

    # ========================================================
    # EXACT MATCHES
    # ========================================================

    print("\n--- Exact Matches ---")

    if serpapi["exact_matches"]:

        for i, item in enumerate(
            serpapi["exact_matches"],
            1
        ):

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

            else:

                print(
                    "   Image: Not available"
                )

            if website_url:

                print(
                    f"   Website: {website_url}"
                )

    else:

        print(
            "No exact matches found."
        )

    # ========================================================
    # GOOGLE VISION RESULTS
    # ========================================================

    print("\n")
    print("========================================")
    print("       GOOGLE VISION RESULTS")
    print("========================================")

    print("\n--- Candidate URLs ---")

    for i, url in enumerate(
        vision["candidate_urls"],
        1
    ):

        print(
            f"{i}. {url}"
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

        "combined_candidate_urls":
            results["combined_candidate_urls"],

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

    # Run both Google Vision and SerpAPI
    results = get_all_results(
        image_path
    )

    # Print results
    print_results(
        image_path,
        results
    )

    # Save JSON
    save_results(
        results,
        image_path
    )