"""JSON-compatible API with target-specific geographic coverage checks."""
import math
import joblib
import numpy as np
import pandas as pd
from .config import TARGETS, MAX_DISTANCE_M, MIN_NEIGHBORS
from .preprocessing import normalize, distances, features


class Predictor:
    def __init__(self, artifact, max_distance_m=MAX_DISTANCE_M, min_neighbors=MIN_NEIGHBORS):
        if not math.isfinite(max_distance_m) or max_distance_m <= 0 or min_neighbors < 3:
            raise ValueError("Require a positive radius and at least three neighbors")
        if artifact.get("version") != 1:
            raise ValueError("Unsupported model artifact")
        self.artifact = artifact
        self.radius = max_distance_m
        self.minimum = min_neighbors

    @classmethod
    def load(cls, path, **kwargs):
        # joblib uses pickle: load only artifacts produced by trusted teammates.
        return cls(joblib.load(path), **kwargs)

    def predict(self, request, method="baseline"):
        if method not in ("baseline", "random_forest"):
            raise ValueError("method must be baseline or random_forest")
        query = normalize(request)
        frame = self.artifact["measurements"]
        group = frame[(frame.network_id == query["network_id"]) & (frame.wifi_band == query["wifi_band"])]
        group = group.assign(distance_m=distances(group, query["latitude"], query["longitude"]))
        near = group[group.distance_m <= self.radius]
        response = {"is_estimate": True, "method": method, "data_sources": self.artifact["data_sources"],
                    "synthetic_data_used": "synthetic" in self.artifact["data_sources"],
                    "reliability": "unavailable", "targets": {}}
        for target in TARGETS:
            usable = near.dropna(subset=[target])
            value, reason = None, "insufficient_nearby_measurements"
            if len(usable) >= self.minimum:
                if method == "baseline":
                    value = float(np.average(usable[target], weights=1 / np.maximum(usable.distance_m, 1) ** 2))
                else:
                    model = self.artifact["models"].get((query["network_id"], query["wifi_band"], target))
                    if model is not None:
                        value = float(model.predict(features(pd.DataFrame([query])))[0])
                    else:
                        reason = "no_trained_model"
            response[target] = value
            response["targets"][target] = {"nearby_count": len(usable),
                "nearest_distance_m": float(usable.distance_m.min()) if len(usable) else None,
                "reliability": "low" if value is not None else "unavailable",
                "reason": "uncalibrated_estimate" if value is not None else reason}
        available = sum(response[t] is not None for t in TARGETS)
        response["status"] = "available" if available == 3 else "partial" if available else "unavailable"
        response["reliability"] = "low" if available else "unavailable"
        return response
