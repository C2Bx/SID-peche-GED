from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from reporting.data import DtmData

# Tolérance reprise du contrôle de fin de script du DTM.
TOLERANCE_BENEFICE = 1


def format_number(value: float | None, decimals: int = 0) -> str:
    """Formate un nombre à la française : espaces fines entre milliers."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", " ").replace(".", ",")


def format_compact(value: float | None) -> str:
    """Formate un montant en k / M pour les tuiles."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{format_number(value / 1_000_000, 1)} M"
    if absolute >= 10_000:
        return f"{format_number(value / 1_000, 0)} k"
    return format_number(value)


@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    unit: str = ""
    detail: str = ""


@dataclass(frozen=True)
class QualityCheck:
    label: str
    count: int
    total: int
    explanation: str

    @property
    def ok(self) -> bool:
        return self.count == 0

    @property
    def share(self) -> str:
        if not self.total:
            return "–"
        return f"{format_number(100 * self.count / self.total, 1)} %"


def compute_kpis(data: DtmData) -> list[Kpi]:
    """Calcule les indicateurs de tête à partir du grain campagne."""
    c = data.campagnes
    # Les montants viennent exclusivement du grain campagne : les sommer depuis
    # FAIT_CARTE ou depuis le détail des frais compterait autre chose.
    recette = c["campagne_recette"].sum(min_count=1)
    depense = c["campagne_depense"].sum(min_count=1)
    benefice = c["campagne_benefice"].sum(min_count=1)
    marge = benefice / recette if recette else float("nan")
    jours_mer = c["jours_mer"].sum(min_count=1)
    return [
        Kpi("Campagnes", format_number(len(c)),
            detail=f"{format_number(c['capitaine_id'].nunique())} capitaines"),
        Kpi("Recette", format_compact(recette), "XPF"),
        Kpi("Dépense", format_compact(depense), "XPF"),
        Kpi("Bénéfice", format_compact(benefice), "XPF",
            detail=f"marge {format_number(100 * marge, 1)} %"),
        Kpi("Poids capturé", format_compact(c["poids_capture_total"].sum(min_count=1)),
            detail="poids entier, unité de la source"),
        Kpi("Jours en mer", format_number(jours_mer),
            detail=f"{format_number(c['jours_mer'].mean(), 1)} j par campagne"),
        Kpi("Rendement moyen", format_number(c["campagne_rendement"].mean(), 2),
            detail="moyenne simple des campagnes"),
    ]


def compute_quality(data: DtmData) -> list[QualityCheck]:
    """Reprend les contrôles du DTM sous une forme lisible dans le rapport."""
    c = data.campagnes
    total = len(c)
    complets = c.dropna(subset=["campagne_benefice", "campagne_recette", "campagne_depense"])
    ecart = (
        complets["campagne_benefice"]
        - (complets["campagne_recette"] - complets["campagne_depense"])
    ).abs() > TOLERANCE_BENEFICE
    return [
        QualityCheck("Campagnes sans capitaine", int(c["capitaine_id"].isna().sum()), total,
                     "Jointure carte → capitaine impossible en amont."),
        QualityCheck("Campagnes sans date de début", int(c["annee"].isna().sum()), total,
                     "Absentes des graphiques par année."),
        QualityCheck("Bénéfice ≠ recette − dépense", int(ecart.sum()), total,
                     "Valeur de la source conservée, écart signalé aux métiers."),
        QualityCheck("Campagnes sans capture", int((c["nombre_captures"] == 0).sum()), total,
                     "Campagne déclarée sans aucune espèce."),
    ]


def yearly_finance(data: DtmData) -> pd.DataFrame:
    """Recette, dépense et bénéfice par année de début de campagne."""
    c = data.campagnes.dropna(subset=["annee"])
    out = (
        c.groupby("annee")[["campagne_recette", "campagne_depense", "campagne_benefice"]]
        .sum(min_count=1)
        .reset_index()
    )
    out["annee"] = out["annee"].astype(int)
    return out.rename(columns={
        "annee": "Année", "campagne_recette": "Recette",
        "campagne_depense": "Dépense", "campagne_benefice": "Bénéfice",
    })


def top_especes(data: DtmData, n: int = 10) -> pd.DataFrame:
    """Les n catégories d'espèces les plus pêchées en poids."""
    out = (
        data.captures.groupby("categorie_nom")[["poids_capture", "valeur_captures"]]
        .sum(min_count=1)
        .sort_values("poids_capture", ascending=False)
        .head(n)
        .reset_index()
    )
    return out.rename(columns={
        "categorie_nom": "Espèce", "poids_capture": "Poids",
        "valeur_captures": "Valeur (XPF)",
    })


def frais_par_nature(data: DtmData) -> pd.DataFrame:
    """Total et part de chaque poste de frais."""
    out = (
        data.frais.groupby("nature_frais")["montant"].sum(min_count=1)
        .sort_values(ascending=False)
        .reset_index()
    )
    total = out["montant"].sum()
    out["part"] = out["montant"] / total * 100 if total else float("nan")
    return out.rename(columns={
        "nature_frais": "Poste", "montant": "Montant (XPF)", "part": "Part (%)",
    })


def benefice_par_commune(data: DtmData, n: int = 10) -> pd.DataFrame:
    """Bénéfice moyen par campagne selon la commune du capitaine."""
    out = (
        data.campagnes.groupby("capitaine_commune")
        .agg(campagnes=("campagne_id", "count"),
             benefice_moyen=("campagne_benefice", "mean"))
        .sort_values("campagnes", ascending=False)
        .head(n)
        .sort_values("benefice_moyen", ascending=False)
        .reset_index()
    )
    return out.rename(columns={
        "capitaine_commune": "Commune", "campagnes": "Campagnes",
        "benefice_moyen": "Bénéfice moyen (XPF)",
    })
