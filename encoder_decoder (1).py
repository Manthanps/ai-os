"""Encoder/decoder (PCA-style) anomaly detector for workflow metrics."""

from typing import List, Optional, Tuple

try:
    import numpy as np  # type: ignore
except Exception:
    np = None


class EncoderDecoderAnomaly:
    """Lightweight encoder/decoder anomaly detector using PCA reconstruction."""

    def __init__(
        self,
        window: int = 60,
        min_train: int = 30,
        components: int = 2,
        z_threshold: float = 3.0,
    ):
        self.window = max(10, window)
        self.min_train = max(10, min_train)
        self.components = max(1, components)
        self.z_threshold = z_threshold
        self.buffer: List[List[float]] = []
        self.mean = None
        self.comp = None
        self.threshold = None
        self.available = np is not None

    def update_and_check(self, vector: List[float]) -> Tuple[bool, float, Optional[float]]:
        """Update model with a vector and return (is_anomaly, score, threshold)."""
        if not self.available:
            return False, 0.0, None

        self.buffer.append(vector)
        if len(self.buffer) > self.window:
            self.buffer.pop(0)

        if len(self.buffer) >= self.min_train:
            self._fit()

        if self.comp is None or self.mean is None or self.threshold is None:
            return False, 0.0, self.threshold

        score = self._reconstruction_error(vector)
        return score > self.threshold, score, self.threshold

    def _fit(self) -> None:
        X = np.array(self.buffer, dtype=float)
        self.mean = X.mean(axis=0)
        Xc = X - self.mean

        # PCA via SVD
        try:
            _, _, vt = np.linalg.svd(Xc, full_matrices=False)
        except Exception:
            self.comp = None
            return

        k = min(self.components, vt.shape[0], vt.shape[1])
        self.comp = vt[:k]

        # Set threshold from reconstruction errors
        errors = [self._reconstruction_error(x.tolist()) for x in X]
        mu = float(np.mean(errors))
        sigma = float(np.std(errors))
        self.threshold = mu + self.z_threshold * (sigma if sigma > 1e-9 else 1e-9)

    def _reconstruction_error(self, vector: List[float]) -> float:
        x = np.array(vector, dtype=float)
        x_c = x - self.mean
        enc = self.comp @ x_c
        dec = (self.comp.T @ enc) + self.mean
        return float(np.mean((x - dec) ** 2))
