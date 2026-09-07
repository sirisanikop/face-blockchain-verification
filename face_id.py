#face_id
import cv2
import numpy as np
from insightface.app import FaceAnalysis

# Initialize once, reused by all functions
_app = FaceAnalysis(name="buffalo_l")
_app.prepare(ctx_id=0, det_size=(640, 640))



def get_all_faces(image_path):
    """
    Detect all faces in an image.

    Returns a list of dictionaries containing:
        - embedding
        - bbox
        - area

    Returns [] if no faces are detected.
    """
    img = cv2.imread(image_path)

    if img is None:
        print(f"Could not read image: {image_path}")
        return []

    faces = _app.get(img)

    results = []

    for face in faces:
        x1, y1, x2, y2 = face.bbox

        area = (x2 - x1) * (y2 - y1)

        results.append({
            "embedding": face.embedding,
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "area": float(area)
        })

    return results


def get_embedding(image_path):
    """
    Backwards-compatible function.

    Returns the embedding of the largest detected face.
    Returns None if no face is found.
    """
    faces = get_all_faces(image_path)

    if len(faces) == 0:
        return None

    largest_face = max(faces, key=lambda f: f["area"])

    return largest_face["embedding"]


def compare_faces(embedding1, embedding2, threshold=0.5):
    """
    Compares two embeddings using cosine similarity.

    Returns:
        (is_match, similarity_score)
    """
    cosine_sim = np.dot(embedding1, embedding2) / (
        np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
    )

    is_match = bool(cosine_sim >= threshold)

    return is_match, float(cosine_sim)


if __name__ == "__main__":

    emb1 = get_embedding("test_images/test5.jpg")
    emb2 = get_embedding("test_images/test7.jpg")

    if emb1 is None or emb2 is None:
        print("Could not detect a face in one or both images.")
    else:
        is_match, score = compare_faces(emb1, emb2)

        print(f"Similarity score: {score:.4f}")
        print(f"Match: {is_match}")