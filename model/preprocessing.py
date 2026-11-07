"""Validate canonical measurements and construct target-independent features."""
import math
import numpy as np
import pandas as pd
from .config import TARGETS, NUMERIC, CATEGORICAL


def normalize(row, training=False):
    row = dict(row)
    for key, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
        value = float(row[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Invalid {key}")
        row[key] = value
    for key in ("network_id", "wifi_band"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"{key} is required and must be a nonempty string")
        row[key] = row[key].strip()
    hour = row.get("hour")
    if hour is None and row.get("timestamp") is not None:
        stamp = pd.Timestamp(row["timestamp"])
        if pd.isna(stamp) or stamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone; or supply local hour")
        stamp = stamp.tz_convert("America/Los_Angeles")
        hour = stamp.hour + stamp.minute / 60
    if hour is not None:
        hour = float(hour)
        if not math.isfinite(hour) or not 0 <= hour < 24:
            raise ValueError("hour must be in [0, 24)")
    row["hour_sin"] = math.sin(2 * math.pi * hour / 24) if hour is not None else np.nan
    row["hour_cos"] = math.cos(2 * math.pi * hour / 24) if hour is not None else np.nan
    row["device_type"] = str(row["device_type"]) if row.get("device_type") is not None else "unknown"
    if training:
        for target in TARGETS:
            value = row.get(target)
            if value is None or pd.isna(value):
                row[target] = np.nan
                continue
            value = float(value)
            if not math.isfinite(value) or (value < 0 if target != "rssi_dbm" else not -150 <= value <= 0):
                raise ValueError(f"Invalid {target}")
            row[target] = value
        if row.get("data_source") not in ("real", "synthetic"):
            raise ValueError("Each training row needs data_source: real or synthetic")
    return row


def measurements(rows):
    frame = pd.DataFrame([normalize(row, training=True) for row in rows])
    if frame.empty:
        raise ValueError("At least one measurement is required")
    return frame


def features(frame):
    return frame[list(NUMERIC + CATEGORICAL)]


def distances(frame, latitude, longitude):
    """Haversine great-circle distances in meters."""
    lat = np.radians(frame.latitude.to_numpy(dtype=float))
    lon = np.radians(frame.longitude.to_numpy(dtype=float))
    qlat, qlon = np.radians([latitude, longitude])
    a = np.sin((lat - qlat) / 2) ** 2 + np.cos(lat) * np.cos(qlat) * np.sin((lon - qlon) / 2) ** 2
    return 6371000 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
