"""Reference data: monitored diseases and surveillance regions.

Disease parameters are illustrative epidemiological priors used to drive the
synthetic generator and to convert forecasted cases into hospitalization and
mortality risk. They are not clinical reference values.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np


@dataclass(frozen=True)
class DiseaseProfile:
    code: str
    name: str
    category: str
    icd10: str
    base_rate_per_100k: float  # expected daily incident cases per 100k population
    seasonal_amplitude: float  # 0 = flat, 1 = strongly seasonal
    peak_day_of_year: int
    hospitalization_rate: float
    case_fatality_rate: float
    outbreaks_per_region_year: float
    additive_outbreaks: bool = False  # rare diseases: outbreaks add cases rather than multiply
    tropical: bool = False  # incidence scales with lower latitude
    severity_weight: float = 1.0  # used by the alert risk model


DISEASES: dict[str, DiseaseProfile] = {
    p.code: p
    for p in [
        DiseaseProfile("INFLUENZA", "Influenza", "respiratory", "J11", 6.0, 0.9, 30, 0.020, 0.0010, 0.6),
        DiseaseProfile("CLI", "COVID-like illness", "respiratory", "U07.1", 5.0, 0.5, 15, 0.040, 0.0030, 0.5),
        DiseaseProfile("RSV", "Respiratory syncytial virus", "respiratory", "J21.0", 2.0, 0.8, 350, 0.030, 0.0005, 0.4),
        DiseaseProfile("MEASLES", "Measles", "vaccine-preventable", "B05", 0.02, 0.1, 90, 0.100, 0.0020, 0.15,
                       additive_outbreaks=True, severity_weight=1.6),
        DiseaseProfile("DENGUE", "Dengue", "vector-borne", "A90", 0.3, 0.9, 220, 0.050, 0.0010, 0.3,
                       tropical=True, severity_weight=1.2),
        DiseaseProfile("FOODBORNE", "Foodborne illness", "enteric", "A05.9", 0.8, 0.4, 200, 0.010, 0.0002, 0.5,
                       severity_weight=0.9),
    ]
}


@dataclass(frozen=True)
class Region:
    region_id: str  # FIPS-style code
    name: str
    state: str
    lat: float
    lon: float
    population: int


REGIONS: list[Region] = [
    Region("36061", "New York City", "NY", 40.71, -74.01, 8_300_000),
    Region("06037", "Los Angeles", "CA", 34.05, -118.24, 3_900_000),
    Region("17031", "Chicago", "IL", 41.88, -87.63, 2_700_000),
    Region("48201", "Houston", "TX", 29.76, -95.37, 2_300_000),
    Region("04013", "Phoenix", "AZ", 33.45, -112.07, 1_600_000),
    Region("42101", "Philadelphia", "PA", 39.95, -75.17, 1_600_000),
    Region("48029", "San Antonio", "TX", 29.42, -98.49, 1_450_000),
    Region("06073", "San Diego", "CA", 32.72, -117.16, 1_390_000),
    Region("48113", "Dallas", "TX", 32.78, -96.80, 1_300_000),
    Region("12086", "Miami", "FL", 25.76, -80.19, 450_000),
    Region("12057", "Tampa", "FL", 27.95, -82.46, 400_000),
    Region("13121", "Atlanta", "GA", 33.75, -84.39, 500_000),
    Region("53033", "Seattle", "WA", 47.61, -122.33, 750_000),
    Region("08031", "Denver", "CO", 39.74, -104.99, 715_000),
    Region("25025", "Boston", "MA", 42.36, -71.06, 675_000),
    Region("11001", "Washington", "DC", 38.91, -77.04, 690_000),
    Region("47157", "Memphis", "TN", 35.15, -90.05, 630_000),
    Region("22071", "New Orleans", "LA", 29.95, -90.07, 380_000),
    Region("26163", "Detroit", "MI", 42.33, -83.05, 640_000),
    Region("27053", "Minneapolis", "MN", 44.98, -93.27, 430_000),
    Region("41051", "Portland", "OR", 45.52, -122.68, 650_000),
    Region("32003", "Las Vegas", "NV", 36.17, -115.14, 650_000),
    Region("37119", "Charlotte", "NC", 35.23, -80.84, 880_000),
    Region("39049", "Columbus", "OH", 39.96, -83.00, 900_000),
    Region("72127", "San Juan", "PR", 18.47, -66.11, 340_000),
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(a)))


@lru_cache(maxsize=4)
def neighbor_map(radius_km: float = 900.0) -> dict[str, tuple[str, ...]]:
    """Regions within ``radius_km`` of each other (excluding self)."""
    out: dict[str, tuple[str, ...]] = {}
    for a in REGIONS:
        out[a.region_id] = tuple(
            b.region_id
            for b in REGIONS
            if b.region_id != a.region_id and haversine_km(a.lat, a.lon, b.lat, b.lon) <= radius_km
        )
    return out
