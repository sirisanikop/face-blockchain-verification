import os
import sys
import serpapi


def search_google_lens(image_path):
    """
    Upload a local image to SerpAPI and search it using Google Lens.
    """

    api_key = os.getenv("SERPAPI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "SERPAPI_API_KEY environment variable is not set."
        )

    if not os.path.isfile(image_path):
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    print(f"Uploading image to SerpAPI: {image_path}")

    client = serpapi.Client(api_key=api_key)

    upload = client.upload_image(image_path)

    image_id = upload.get("image_id")

    if not image_id:
        raise RuntimeError(
            "SerpAPI image upload did not return an image_id."
        )

    print("Image uploaded successfully.")
    print("Running Google Lens search...")

    results = client.search({
        "engine": "google_lens",
        "image_id": image_id
    })

    print("Google Lens search completed.")

    return results


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:")
        print("python serpapi_search.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]

    try:
        results = search_google_lens(image_path)

        print("\n========================================")
        print("SERPAPI GOOGLE LENS SEARCH")
        print("========================================")

        print(f"\nVisual matches: {len(results.get('visual_matches', []))}")
        print(f"Exact matches: {len(results.get('exact_matches', []))}")

        print("\nResults received successfully.")

    except Exception as e:
        print(f"\nSerpAPI Google Lens failed: {e}")
        sys.exit(1)
