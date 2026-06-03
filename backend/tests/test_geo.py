import math

import pytest

from backend.app.services.geo import haversine_km


def test_zero_distance():
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0


def test_known_distance_paris_to_delhi():
    # Approximate great-circle distance ~6595 km. Allow a small tolerance.
    d = haversine_km(48.8566, 2.3522, 28.6139, 77.2090)
    assert 6500 < d < 6700


def test_short_distance():
    # Two points ~1 km apart in Lucknow.
    d = haversine_km(26.8467, 80.9462, 26.8557, 80.9462)
    assert 0.9 < d < 1.1


def test_rejects_nan():
    with pytest.raises(ValueError):
        haversine_km(math.nan, 0.0, 0.0, 0.0)
