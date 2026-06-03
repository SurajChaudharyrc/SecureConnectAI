from __future__ import annotations

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two lat/lon points."""
    if not all(isinstance(v, (int, float)) for v in (lat1, lon1, lat2, lon2)):
        raise ValueError("coords must be numeric")
    if math.isnan(lat1) or math.isnan(lon1) or math.isnan(lat2) or math.isnan(lon2):
        raise ValueError("coords must not be NaN")

    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))
