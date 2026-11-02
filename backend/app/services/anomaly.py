"""Statistical anomaly detection.

A lightweight, dependency-free z-score detector: a sample is flagged when it
sits more than ``k`` standard deviations from the window mean. This is the
Fase-4 "statistical anomaly detection" building block; it runs over any metric
series returned by the time-series store.
"""
from __future__ import annotations

from statistics import fmean, pstdev

MIN_SAMPLES = 8


def zscores(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = fmean(values)
    sd = pstdev(values)
    if sd == 0:
        return [0.0] * len(values)
    return [round((v - mean) / sd, 2) for v in values]


def detect(values: list[float], k: float = 3.0, min_samples: int = MIN_SAMPLES) -> list[int]:
    """Indices of anomalous samples (|z| > k). Needs enough data and spread."""
    n = len(values)
    if n < min_samples:
        return []
    mean = fmean(values)
    sd = pstdev(values)
    if sd == 0:
        return []
    return [i for i, v in enumerate(values) if abs(v - mean) > k * sd]
