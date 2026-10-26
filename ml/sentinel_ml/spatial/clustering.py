"""Spatial hotspot detection with DBSCAN / HDBSCAN on haversine distance.

Input is a set of geocoded (census-tract centroid) case points over a recent
window, optionally with a baseline window. Each cluster is scored with a
relative risk = observed / expected, where expected comes from the baseline
point density in the same footprint. Clusters with relative risk above the
threshold are reported as hotspots.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, HDBSCAN

EARTH_RADIUS_KM = 6371.0


@dataclass
class Hotspot:
    cluster_id: int
    disease: str | None
    case_count: int
    centroid_lat: float
    centroid_lon: float
    radius_km: float
    relative_risk: float | None
    method: str

    def as_dict(self) -> dict:
        return asdict(self)


def _haversine_to(lat: np.ndarray, lon: np.ndarray, clat: float, clon: float) -> np.ndarray:
    p1, p2 = np.radians(lat), np.radians(clat)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(clon - lon) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def detect_hotspots(
    points: pd.DataFrame,
    baseline: pd.DataFrame | None = None,
    method: str = "hdbscan",
    eps_km: float = 15.0,
    min_samples: int = 25,
    min_relative_risk: float = 1.5,
    window_ratio: float = 1.0,
    min_membership: float = 0.5,
) -> list[Hotspot]:
    """Cluster ``points`` (columns ``lat``, ``lon``, optional ``disease``).

    ``window_ratio`` = length of the baseline window / length of the current
    window, used to scale baseline counts into expected counts.
    """
    if len(points) < min_samples:
        return []
    coords = np.radians(points[["lat", "lon"]].to_numpy())
    if method == "dbscan":
        labels = DBSCAN(eps=eps_km / EARTH_RADIUS_KM, min_samples=min_samples, metric="haversine",
                        algorithm="ball_tree").fit_predict(coords)
    elif method == "hdbscan":
        model = HDBSCAN(min_cluster_size=min_samples, min_samples=min_samples, metric="haversine",
                        cluster_selection_method="leaf", copy=True).fit(coords)
        # Fringe points absorbed from sparse background get low membership strength; treat them as noise
        # so the reported centroid/radius describe the dense core.
        labels = np.where(model.probabilities_ >= min_membership, model.labels_, -1)
    else:
        raise ValueError("method must be 'dbscan' or 'hdbscan'")

    disease = points["disease"].mode().iat[0] if "disease" in points and len(points) else None
    hotspots: list[Hotspot] = []
    for cid in sorted(set(labels) - {-1}):
        member = points[labels == cid]
        clat, clon = float(member["lat"].mean()), float(member["lon"].mean())
        dist = _haversine_to(member["lat"].to_numpy(), member["lon"].to_numpy(), clat, clon)
        radius = float(np.quantile(dist, 0.9)) if len(dist) else 0.0
        rr = None
        if baseline is not None and len(baseline):
            bd = _haversine_to(baseline["lat"].to_numpy(), baseline["lon"].to_numpy(), clat, clon)
            expected = (bd <= max(radius, 1.0)).sum() / max(window_ratio, 1e-9)
            rr = round(float((len(member) + 1) / (expected + 1)), 2)
            if rr < min_relative_risk:
                continue
        hotspots.append(Hotspot(int(cid), disease, int(len(member)), round(clat, 4), round(clon, 4),
                                round(radius, 2), rr, method))
    return sorted(hotspots, key=lambda h: -(h.relative_risk or h.case_count))
