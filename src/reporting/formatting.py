from __future__ import annotations

import math

import pandas as pd


def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT


def format_number(value, decimals: int = 0) -> str:
    """Nombre à la française : espace fine entre milliers, virgule décimale."""
    if is_missing(value):
        return "–"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def format_compact(value) -> str:
    """Montant abrégé en k / M pour les tuiles."""
    if is_missing(value):
        return "–"
    if abs(value) >= 1_000_000:
        return f"{format_number(value / 1_000_000, 1)} M"
    if abs(value) >= 10_000:
        return f"{format_number(value / 1_000, 0)} k"
    return format_number(value)


def format_date(value) -> str:
    return "–" if is_missing(value) else pd.Timestamp(value).strftime("%d/%m/%Y")
