"""
face_auth.py - JARVIS recognizes your face. Only responds when it's you.
Uses InsightFace — CPU-capable, Apache 2.0 license.
"""
import logging
import numpy as np

logger = logging.getLogger(__name__)


class FaceAuthenticator:
    """
    JARVIS recognizes your face. Only responds when it's you.
    Uses InsightFace — CPU-capable, Apache 2.0.
    """

    def __init__(self, enroll_file: str = "memory/known_faces.json"):
        self._app = None
        self._known_faces: dict[str, np.ndarray] = {}
        self._enroll_file = enroll_file
        self._enabled = False

    def initialize(self):
        """Load InsightFace and known faces."""
        try:
            from insightface.app import FaceAnalysis
            self._app = FaceAnalysis()
            self._app.prepare(ctx_id=0, det_size=(640, 640))
            self._load_known_faces()
            logger.info(f"[FaceAuth] Loaded {len(self._known_faces)} known faces")
        except ImportError:
            logger.warning("[FaceAuth] insightface not installed. Run: pip install insightface")
            self._app = None

    def _load_known_faces(self):
        """Load known face embeddings from disk."""
        import json
        import os
        if not os.path.exists(self._enroll_file):
            return
        try:
            with open(self._enroll_file) as f:
                data = json.load(f)
                for name, emb_list in data.items():
                    self._known_faces[name] = np.array(emb_list)
        except Exception as e:
            logger.debug(f"[FaceAuth] Load failed: {e}")

    def _save_known_faces(self):
        """Save known face embeddings to disk."""
        import json
        data = {name: emb.tolist() for name, emb in self._known_faces.items()}
        with open(self._enroll_file, "w") as f:
            json.dump(data, f)

    def _similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Cosine similarity between two embeddings."""
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(emb1, emb2) / (norm1 * norm2))

    def enroll_user(self, screenshot: np.ndarray, name: str = "user") -> bool:
        """Enroll a face from screenshot. 'JARVIS, learn my face.'"""
        if self._app is None:
            self.initialize()
        if self._app is None:
            return False

        try:
            faces = self._app.get(screenshot)
            if faces:
                self._known_faces[name] = faces[0].embedding
                self._save_known_faces()
                logger.info(f"[FaceAuth] Enrolled face: {name}")
                return True
        except Exception as e:
            logger.error(f"[FaceAuth] Enroll failed: {e}")
        return False

    def is_user_present(self, screenshot: np.ndarray, threshold: float = 0.7) -> bool | str:
        """Check if the user is in frame. Returns name if recognized, False if not."""
        if self._app is None or not self._known_faces:
            return False

        try:
            faces = self._app.get(screenshot)
            if not faces:
                return False
            for face in faces:
                for name, embedding in self._known_faces.items():
                    sim = self._similarity(face.embedding, embedding)
                    if sim > threshold:
                        return name
            return False
        except Exception as e:
            logger.debug(f"[FaceAuth] Check failed: {e}")
            return False

    def remove_user(self, name: str) -> bool:
        """Remove a known face."""
        if name in self._known_faces:
            del self._known_faces[name]
            self._save_known_faces()
            return True
        return False

    @property
    def is_enabled(self) -> bool:
        return self._app is not None and self._enabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        self._enabled = value
