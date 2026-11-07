"""Held-out evaluation: split sessions or spatial blocks before fitting."""
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from .config import TARGETS, SPATIAL_BLOCK_M
from .preprocessing import measurements
from .training import train
from .prediction import Predictor


def evaluate(rows, method="random_forest"):
    frame = measurements(rows)
    if set(frame.data_source) != {"real"}:
        raise ValueError("Evaluation reports require exclusively real measurements")
    sessions = frame.get("session_id")
    if sessions is not None and sessions.notna().all():
        groups = sessions.astype(str).to_numpy()
        split = "collection_session"
    else:
        # Fixed grid at San Diego's approximate latitude, in meters.
        x = np.floor(frame.longitude * 111320 * np.cos(np.radians(32.8)) / SPATIAL_BLOCK_M)
        y = np.floor(frame.latitude * 111320 / SPATIAL_BLOCK_M)
        groups = (x.astype(str) + ":" + y.astype(str)).to_numpy()
        split = "spatial_block_1000m"
    if len(set(groups)) < 2:
        raise ValueError("Need at least two independent sessions or spatial blocks")
    train_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=42).split(frame, groups=groups))
    predictor = Predictor(train(frame.iloc[train_idx].to_dict("records")))
    errors = {target: [] for target in TARGETS}
    eligible = {target: 0 for target in TARGETS}
    for row in frame.iloc[test_idx].to_dict("records"):
        result = predictor.predict(row, method)
        for target in TARGETS:
            if not np.isnan(row[target]):
                eligible[target] += 1
                if result[target] is not None:
                    errors[target].append(result[target] - row[target])
    return {"split": split, "method": method, "train_rows": len(train_idx), "test_rows": len(test_idx),
            "targets": {t: {"mae": float(np.mean(np.abs(e))) if e else None,
                            "rmse": float(np.sqrt(np.mean(np.square(e)))) if e else None,
                            "predicted_count": len(e), "eligible_count": eligible[t],
                            "coverage": len(e) / eligible[t] if eligible[t] else None}
                        for t, e in errors.items()}}
