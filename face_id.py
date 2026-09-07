#face_id
import cv2
import numpy as np
from insightface.app import FaceAnalysis

# Initialize once, reused by all functions
_app = FaceAnalysis(name="buffalo_l")
_app.prepare(ctx_id=0, det_size=(640, 640))


def get_embedding(image_path):
    """
    Takes an image path, returns the embedding of the largest detected face.
    Returns None if no face is found.
    """
    img = cv2.imread(image_path)
    faces = _app.get(img)

    if len(faces) == 0:
        return None

    # if multiple faces, pick the largest bounding box (closest/most prominent face)
    largest_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
    return largest_face.embedding


def compare_faces(embedding1, embedding2, threshold=0.5):
    """
    Compares two embeddings using cosine similarity.
    Returns (is_match: bool, similarity_score: float)
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
