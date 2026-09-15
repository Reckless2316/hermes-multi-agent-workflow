"""Deterministic trading desk — LLMs analyze; this code authorizes.

This package is a *mechanism* (market data, defined-risk options scanner,
portfolio/BP checks, paper fills, position management). It is not the generic
Hermes triage engine. Do not import this from `engine/`.

Strategy numbers live in `desk/strategy.yaml`.
"""
from .types import ScanResult, SetupStatus, Spread

__all__ = ["ScanResult", "SetupStatus", "Spread"]
