import base64
import json
import subprocess
import sys
import requests


PROJECT_ID = "face-search-demo-2026"
VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


def get_access_token():
    """Get a temporary OAuth access token from gcloud."""
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        check=True
    )

    return result.stdout.strip()


def web_detect(image_path):
    """Send an image to Google Cloud Vision Web Detection."""

    # Read image
    with open(image_path, "rb") as f:
        image_content = base64.b64encode(f.read()).decode("utf-8")

    # Get Google Cloud OAuth token
    access_token = get_access_token()

    # Request body
    payload = {
        "requests": [
            {
                "image": {
                    "content": image_content
                },
                "features": [
                    {
                        "type": "WEB_DETECTION",
                        "maxResults": 20
                    }
                ]
            }
        ]
    }

    # Authentication headers
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-goog-user-project": PROJECT_ID,
        "Content-Type": "application/json"
    }

    # Send request
    response = requests.post(
        VISION_URL,
        headers=headers,
        json=payload
    )

    print("HTTP status:", response.status_code)

    # Show useful error if request failed
    if not response.ok:
        print("\nGoogle Cloud returned an error:")
        print(response.text)
        response.raise_for_status()

    data = response.json()

    # Extract Web Detection results
    web = data["responses"][0].get("webDetection", {})

    print("\n========================================")
    print("GOOGLE VISION WEB DETECTION RESULTS")
    print("========================================")

    # Pages containing matching images
    print("\n--- Pages with matching images ---")

    pages = web.get("pagesWithMatchingImages", [])

    if pages:
        for page in pages:
            print(page.get("url"))
    else:
        print("No matching pages found.")

    # Exact/full image matches
    print("\n--- Full matching images ---")

    full_matches = web.get("fullMatchingImages", [])

    if full_matches:
        for image in full_matches:
            print(image.get("url"))
    else:
        print("No full matches found.")

    # Partial matches
    print("\n--- Partial matching images ---")

    partial_matches = web.get("partialMatchingImages", [])

    if partial_matches:
        for image in partial_matches:
            print(image.get("url"))
    else:
        print("No partial matches found.")

    # Visually similar images
    print("\n--- Visually similar images ---")

    similar = web.get("visuallySimilarImages", [])

    if similar:
        for image in similar:
            print(image.get("url"))
    else:
        print("No visually similar images found.")

    # Best guess labels
    print("\n--- Best guess labels ---")

    labels = web.get("bestGuessLabels", [])

    if labels:
        for label in labels:
            print(label.get("label"))
    else:
        print("No labels found.")

    return web


def get_candidate_urls(image_path):
    """
    Assignment-friendly interface:

    image -> list of candidate URLs
    """

    web = web_detect(image_path)

    urls = []

    # Pages containing matching images
    for page in web.get("pagesWithMatchingImages", []):
        url = page.get("url")
        if url:
            urls.append(url)

    # Full matches
    for image in web.get("fullMatchingImages", []):
        url = image.get("url")
        if url:
            urls.append(url)

    # Partial matches
    for image in web.get("partialMatchingImages", []):
        url = image.get("url")
        if url:
            urls.append(url)

    # Visually similar images
    for image in web.get("visuallySimilarImages", []):
        url = image.get("url")
        if url:
            urls.append(url)

    # Remove duplicates while preserving order
    return list(dict.fromkeys(urls))


if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Usage:")
        print("python3 web_detect.py test.jpeg")
        sys.exit(1)

    image_path = sys.argv[1]

    print("Image:", image_path)
    print("Project:", PROJECT_ID)

    result = web_detect(image_path)

    # Save raw result for debugging/demo purposes
    with open("result.json", "w") as f:
        json.dump(result, f, indent=2)

    print("\n========================================")
    print("Results saved to result.json")
    print("========================================")
