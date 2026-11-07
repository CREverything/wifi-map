"""Fit separate forests per network, band, and available target."""
import numpy as np
import joblib
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from .config import TARGETS, NUMERIC, CATEGORICAL
from .preprocessing import measurements, features


def train(rows, output=None):
    frame = measurements(rows)
    models = {}
    for (network, band), group in frame.groupby(["network_id", "wifi_band"]):
        for target in TARGETS:
            usable = group.dropna(subset=[target])
            if len(usable) < 3:
                continue
            preprocessing = ColumnTransformer([
                ("numeric", SimpleImputer(strategy="median", keep_empty_features=True), list(NUMERIC)),
                ("category", OneHotEncoder(handle_unknown="ignore"), list(CATEGORICAL)),
            ])
            pipeline = Pipeline([("features", preprocessing), ("forest", RandomForestRegressor(
                n_estimators=100, min_samples_leaf=2, random_state=42, n_jobs=-1))])
            pipeline.fit(features(usable), usable[target])
            models[(network, band, target)] = pipeline
    artifact = {"version": 1, "measurements": frame, "models": models,
                "data_sources": sorted(frame.data_source.unique().tolist())}
    if output is not None:
        joblib.dump(artifact, output)
    return artifact
