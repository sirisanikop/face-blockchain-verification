import os
import shutil
import requests
import json
import re
import cv2

from concurrent.futures import ThreadPoolExecutor, as_completed

from face_id import (
    get_embedding,
    get_all_faces,
    compare_faces
)

from combined_search import get_all_results


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url, save_path):

    try:

        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        content_type = response.headers.get(
            "Content-Type",
            ""
        )

        if (
            response.status_code == 200
            and "image" in content_type
        ):

            with open(
                save_path,
                "wb"
            ) as f:

                f.write(
                    response.content
                )

            return True

        return False

    except requests.RequestException:

        return False


# ============================================================
# EXTRACT OG IMAGE
# ============================================================

def extract_og_image(page_url):

    try:

        response = requests.get(
            page_url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if response.status_code != 200:

            return None

        html = response.text

        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE
        )

        if match:

            return match.group(1)

        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            html,
            re.IGNORECASE
        )

        if match:

            return match.group(1)

        return None

    except requests.RequestException:

        return None


# ============================================================
# CHECK CANDIDATE
# ============================================================

def check_candidate(
    index,
    candidate,
    scan_embedding,
    download_dir,
    via_og_fallback=False
):

    """
    Download a candidate image and compare the selected
    input face against ALL faces in the candidate.

    Candidate contains:

        image_url
        source_url
        title
        source
        category
    """

    image_url = candidate.get(
        "image_url",
        ""
    )

    source_url = candidate.get(
        "source_url",
        ""
    )

    save_path = os.path.join(
        download_dir,
        f"candidate_{index}.jpg"
    )

    # ---------------------------------------------------------
    # Download image
    # ---------------------------------------------------------

    download_url = image_url

    if via_og_fallback:

        # For Phase 2, the candidate's image URL may actually
        # be a webpage that needs its og:image extracted.

        page_url = image_url

        og_image_url = extract_og_image(
            page_url
        )

        if not og_image_url:

            return {
                **candidate,
                "url": image_url,
                "status": "og_fallback_failed",
                "score": None,
                "match": False,
                "path": None,
                "matched_face": None,
                "faces_detected": 0
            }

        download_url = og_image_url

    success = download_image(
        download_url,
        save_path
    )

    if not success:

        status = (
            "og_fallback_failed"
            if via_og_fallback
            else "skipped"
        )

        return {
            **candidate,
            "url": image_url,
            "status": status,
            "score": None,
            "match": False,
            "path": None,
            "matched_face": None,
            "faces_detected": 0
        }

    # ---------------------------------------------------------
    # Detect ALL faces
    # ---------------------------------------------------------

    candidate_faces = get_all_faces(
        save_path
    )

    if len(candidate_faces) == 0:

        return {
            **candidate,
            "url": image_url,
            "status": "no_face",
            "score": None,
            "match": False,
            "path": save_path,
            "matched_face": None,
            "faces_detected": 0
        }

    # ---------------------------------------------------------
    # Compare against EVERY face
    # ---------------------------------------------------------

    best_score = -1.0
    best_face_index = None
    best_match = False

    for face_index, candidate_face in enumerate(
        candidate_faces
    ):

        is_match, score = compare_faces(
            scan_embedding,
            candidate_face["embedding"]
        )

        if score > best_score:

            best_score = score

            best_face_index = (
                face_index + 1
            )

            best_match = is_match

    status = (
        "checked_via_og_image"
        if via_og_fallback
        else "checked"
    )

    return {
        **candidate,
        "url": image_url,
        "status": status,
        "score": best_score,
        "match": best_match,
        "path": save_path,
        "matched_face": best_face_index,
        "faces_detected": len(candidate_faces)
    }


# ============================================================
# RUN CANDIDATE PASS
# ============================================================

def run_candidates_pass(
    candidates,
    scan_embedding,
    download_dir,
    max_workers,
    via_og_fallback=False
):

    all_results = []

    confirmed_match = None

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {

            executor.submit(
                check_candidate,
                i,
                candidate,
                scan_embedding,
                download_dir,
                via_og_fallback
            ): (i, candidate)

            for i, candidate in enumerate(
                candidates
            )
        }

        for future in as_completed(
            futures
        ):

            i, candidate = futures[
                future
            ]

            image_url = candidate.get(
                "image_url",
                ""
            )

            try:

                result = future.result()

            except Exception as e:

                print(
                    f"[{i+1}] {image_url}\n"
                    f"     -> Error: {e}\n"
                )

                continue

            all_results.append(
                result
            )

            tag = (
                " (via og:image)"
                if via_og_fallback
                else ""
            )

            if result["status"] in (
                "checked",
                "checked_via_og_image"
            ):

                print(
                    f"[{i+1}] {image_url}{tag}\n"
                    f"     -> Faces detected: "
                    f"{result['faces_detected']}\n"
                    f"     -> Best score: "
                    f"{result['score']:.4f}\n"
                    f"     -> Match: "
                    f"{result['match']}\n"
                    f"     -> Best matching face: "
                    f"{result['matched_face']}\n"
                )

                if (
                    result["match"]
                    and confirmed_match is None
                ):

                    confirmed_match = result

                    print(
                        f"CONFIRMED MATCH FOUND: "
                        f"{image_url} "
                        f"(score: "
                        f"{result['score']:.4f})"
                    )

                    for f in futures:

                        f.cancel()

                    break

            elif result["status"] == "no_face":

                print(
                    f"[{i+1}] {image_url}{tag}\n"
                    f"     -> No face detected, skipped\n"
                )

            else:

                print(
                    f"[{i+1}] {image_url}{tag}\n"
                    f"     -> Skipped\n"
                )

    return (
        all_results,
        confirmed_match
    )


# ============================================================
# FACE POSITION
# ============================================================

def describe_face_position(
    bbox,
    image_width,
    image_height
):

    x1, y1, x2, y2 = bbox

    center_x = (
        x1 + x2
    ) / 2

    center_y = (
        y1 + y2
    ) / 2

    if center_x < image_width / 3:

        horizontal = "left"

    elif center_x < (
        2 * image_width / 3
    ):

        horizontal = "center"

    else:

        horizontal = "right"

    if center_y < image_height / 3:

        vertical = "upper"

    elif center_y < (
        2 * image_height / 3
    ):

        vertical = "middle"

    else:

        vertical = "lower"

    return horizontal, vertical


# ============================================================
# FACE SIZE
# ============================================================

def describe_face_size(
    face_area,
    all_faces
):

    areas = [
        face["area"]
        for face in all_faces
    ]

    largest_area = max(
        areas
    )

    smallest_area = min(
        areas
    )

    if largest_area == smallest_area:

        return "medium"

    if face_area == largest_area:

        return "large"

    if face_area == smallest_area:

        return "small"

    return "medium"


# ============================================================
# SELECT INPUT FACE
# ============================================================

def select_input_face(
    scan_image_path
):

    faces = get_all_faces(
        scan_image_path
    )

    if len(faces) == 0:

        print(
            "No faces detected in the input image."
        )

        return None

    if len(faces) == 1:

        print(
            "One face detected in the input image."
        )

        return faces[0]["embedding"]

    image = cv2.imread(
        scan_image_path
    )

    if image is None:

        print(
            "Could not read the input image."
        )

        return None

    image_height, image_width = (
        image.shape[:2]
    )

    print()

    print("=" * 55)

    print(
        f"{len(faces)} faces detected "
        "in the input image."
    )

    print("=" * 55)

    print()

    for i, face in enumerate(
        faces
    ):

        horizontal, vertical = (
            describe_face_position(
                face["bbox"],
                image_width,
                image_height
            )
        )

        size = describe_face_size(
            face["area"],
            faces
        )

        print(
            f"Face {i + 1} → "
            f"{horizontal}, "
            f"{vertical}, "
            f"{size}"
        )

    print()

    largest_index = max(
        range(len(faces)),
        key=lambda i: faces[i]["area"]
    )

    print(
        f"Tip: Face {largest_index + 1} "
        "appears to be the largest/"
        "most prominent face."
    )

    print()

    while True:

        choice = input(
            f"Which face do you want to search? "
            f"[1-{len(faces)}]: "
        ).strip()

        try:

            choice = int(
                choice
            )

            if 1 <= choice <= len(faces):

                break

            print(
                f"Please enter a number between "
                f"1 and {len(faces)}."
            )

        except ValueError:

            print(
                "Please enter a valid number."
            )

    selected_face = faces[
        choice - 1
    ]

    print()

    print(
        f"Selected Face {choice}."
    )

    print()

    return selected_face[
        "embedding"
    ]


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline_fast(
    scan_image_path,
    max_workers=5
):

    # ---------------------------------------------------------
    # Output directories
    # ---------------------------------------------------------

    scan_name = os.path.splitext(
        os.path.basename(
            scan_image_path
        )
    )[0]

    output_dir = os.path.join(
        "results",
        scan_name
    )

    download_dir = os.path.join(
        output_dir,
        "candidates"
    )

    if os.path.exists(
        output_dir
    ):

        shutil.rmtree(
            output_dir
        )

    os.makedirs(
        download_dir,
        exist_ok=True
    )

    # ---------------------------------------------------------
    # Select face
    # ---------------------------------------------------------

    scan_embedding = select_input_face(
        scan_image_path
    )

    if scan_embedding is None:

        print(
            "Could not select a face. Aborting."
        )

        return None

    # ---------------------------------------------------------
    # Search
    # ---------------------------------------------------------

    print(
        "Searching for matching content "
        "(Google Vision + SerpAPI)..."
    )

    search_results = get_all_results(
        scan_image_path
    )

    candidates = search_results[
        "combined_candidates"
    ]

    print(
        f"Found {len(candidates)} "
        f"combined candidate(s).\n"
    )

    # ---------------------------------------------------------
    # Phase 1
    # ---------------------------------------------------------

    print(
        "=== Phase 1: checking direct "
        "image URLs ===\n"
    )

    all_checked, confirmed_match = (
        run_candidates_pass(
            candidates,
            scan_embedding,
            download_dir,
            max_workers,
            via_og_fallback=False
        )
    )

    # ---------------------------------------------------------
    # Phase 2
    # ---------------------------------------------------------

    if confirmed_match is None:

        skipped_candidates = [

            r

            for r in all_checked

            if r["status"] == "skipped"
        ]

        print(
            f"\n=== Phase 1 found no match. "
            f"Phase 2: retrying "
            f"{len(skipped_candidates)} "
            f"skipped URLs via og:image ===\n"
        )

        phase2_checked, confirmed_match = (
            run_candidates_pass(
                skipped_candidates,
                scan_embedding,
                download_dir,
                max_workers,
                via_og_fallback=True
            )
        )

        all_checked.extend(
            phase2_checked
        )

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    print()

    print("=" * 60)

    print(
        "              FACE VERIFICATION RESULT"
    )

    print("=" * 60)

    print()

    print(
        f"Input image        : "
        f"{scan_image_path}"
    )

    print(
        f"Candidates found   : "
        f"{len(candidates)}"
    )

    print(
        f"Candidates checked : "
        f"{len(all_checked)}"
    )

    print()

    if confirmed_match:

        result = {

            "url":
                confirmed_match["url"],

            "source_page":
                confirmed_match.get(
                    "source_url",
                    ""
                ),

            "title":
                confirmed_match.get(
                    "title",
                    ""
                ),

            "source":
                confirmed_match.get(
                    "source",
                    ""
                ),

            "category":
                confirmed_match.get(
                    "category",
                    ""
                ),

            "score":
                confirmed_match["score"],

            "image_path":
                confirmed_match["path"],

            "matched_face":
                confirmed_match[
                    "matched_face"
                ],

            "faces_detected":
                confirmed_match[
                    "faces_detected"
                ]
        }

        print(
            "STATUS             : MATCH FOUND"
        )

        print()

        print(
            f"Similarity score   : "
            f"{result['score']:.4f}"
        )

        print(
            f"Matched face       : "
            f"Face {result['matched_face']}"
        )

        print(
            f"Faces in candidate : "
            f"{result['faces_detected']}"
        )

        print()

        print(
            f"Source image       : "
            f"{result['url']}"
        )

        if result["source_page"]:

            print(
                f"Source website     : "
                f"{result['source_page']}"
            )

        # -----------------------------------------------------
        # Blockchain
        # -----------------------------------------------------

        if os.getenv(
            "ENABLE_BLOCKCHAIN",
            "1"
        ).strip().lower() not in (
            "0",
            "false",
            "no"
        ):

            try:

                from blockchain.verify import (
                    record_and_verify
                )

                result["blockchain"] = (
                    record_and_verify(
                        image_path=result[
                            "image_path"
                        ],
                        url=result[
                            "url"
                        ],
                        output_dir=output_dir
                    )
                )

                print()

                print(
                    "BLOCKCHAIN         : VERIFIED"
                )

            except Exception as e:

                print()

                print(
                    "BLOCKCHAIN         : "
                    "VERIFICATION FAILED"
                )

                print(
                    f"Reason             : {e}"
                )

                result["blockchain"] = {

                    "status": "error",

                    "error": str(e)
                }

    else:

        result = None

        print(
            "STATUS             : "
            "NO MATCH FOUND"
        )

        print()

        print(
            "No candidate image crossed the"
        )

        print(
            "required similarity threshold."
        )

    # ========================================================
    # SAVE FINAL RESULTS
    # ========================================================

    result_path = os.path.join(
        output_dir,
        "match_result.json"
    )

    with open(
        result_path,
        "w"
    ) as f:

        json.dump(
            {
                "scan_image":
                    scan_image_path,

                "best_match":
                    result,

                "all_checked_results":
                    all_checked
            },
            f,
            indent=2
        )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    print()

    print("=" * 60)

    print(
        "                 OUTPUT FILES"
    )

    print("=" * 60)

    if result and result.get(
        "image_path"
    ):

        print()

        print(
            f"Final matched image : "
            f"{result['image_path']}"
        )

    if result and result.get(
        "source_page"
    ):

        print(
            f"Source website     : "
            f"{result['source_page']}"
        )

    print(
        f"JSON results        : "
        f"{result_path}"
    )

    print()

    print("=" * 60)

    print()

    return result


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    import sys

    scan_image = (

        sys.argv[1]

        if len(sys.argv) > 1

        else "test_images/test2.jpg"
    )

    if not os.path.isfile(
        scan_image
    ):

        print(
            f"Image not found: "
            f"{scan_image}"
        )

        sys.exit(1)

    result = run_pipeline_fast(
        scan_image
    )