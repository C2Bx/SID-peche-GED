from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

SCHEMA = "dtm_performance_campagnes"

# Seules les colonnes exploitées par le rapport sont lues : le rapport ne
# dépend ainsi que d'une partie stable du contrat du DTM.
COLUMNS = {
    "DTM_PERFORMANCE_CAMPAGNE": [
        "campagne_id", "annee", "mois", "capitaine_id", "capitaine_commune",
        "duree_jours", "jours_mer", "jours_peche", "nombre_captures",
        "poids_capture_total", "valeur_captures_total", "campagne_benefice",
        "campagne_depense", "campagne_recette", "campagne_rendement",
    ],
    "DTM_CAPTURE_CAMPAGNE": [
        "campagne_id", "categorie_nom", "annee", "nombre_captures",
        "poids_capture", "valeur_captures",
    ],
    "DTM_FRAIS_CAMPAGNE": [
        "campagne_id", "nature_frais", "montant", "annee",
    ],
}


@dataclass(frozen=True)
class DtmData:
    campagnes: pd.DataFrame
    captures: pd.DataFrame
    frais: pd.DataFrame

    def filter_years(self, years: list[int] | None) -> "DtmData":
        """Restreint les trois tables aux années demandées."""
        if not years:
            return self
        return DtmData(
            *(df[df["annee"].isin(years)].reset_index(drop=True)
              for df in (self.campagnes, self.captures, self.frais))
        )


def _read_table(connection: Any, table: str) -> pd.DataFrame:
    """Lit une table du DTM dans un DataFrame, quel que soit le pilote."""
    columns = COLUMNS[table]
    # Les noms viennent du dictionnaire interne, jamais d'une saisie libre.
    statement = f"SELECT {', '.join(columns)} FROM {SCHEMA}.{table}"
    with connection.cursor() as cursor:
        cursor.execute(statement)
        # pyodbc renvoie des objets Row : tuple() les rend utilisables par pandas.
        rows = [tuple(row) for row in cursor.fetchall()]
    return pd.DataFrame.from_records(rows, columns=columns)


def load_dtm(connection: Any) -> DtmData:
    """Charge le DTM performance_campagnes depuis PostgreSQL ou SQL Server."""
    return DtmData(
        campagnes=_read_table(connection, "DTM_PERFORMANCE_CAMPAGNE"),
        captures=_read_table(connection, "DTM_CAPTURE_CAMPAGNE"),
        frais=_read_table(connection, "DTM_FRAIS_CAMPAGNE"),
    )


def demo_data(seed: int = 7, campagnes: int = 600) -> DtmData:
    """Produit un jeu fictif au format du DTM, pour travailler sans base."""
    rng = np.random.default_rng(seed)
    communes = ["Nouméa", "Dumbéa", "Mont-Dore", "Païta", "Bourail",
                "La Foa", "Thio", "Yaté", "Île des Pins", "Poya", "Non renseignée"]
    especes = ["Vivaneaux", "Loches", "Thons", "Bec de cane", "Crabes",
               "Langoustes", "Picots", "Mulets", "Bossus", "Holothuries",
               "Poulpes", "Dawas"]
    natures = ["Carburant", "Glace", "Vivres", "Appâts", "Matériel",
               "Petit matériel", "Lubrifiant", "Entretien du bateau",
               "Entretien du moteur", "Divers"]

    ids = [f"CAMP-{i:05d}" for i in range(campagnes)]
    annees = rng.choice([2021, 2022, 2023, 2024, 2025], size=campagnes)
    jours_mer = rng.integers(1, 8, size=campagnes).astype(float)
    recette = np.round(rng.gamma(2.2, 60_000, size=campagnes) * jours_mer / 3, -2)
    depense = np.round(recette * rng.uniform(0.45, 1.15, size=campagnes), -2)
    poids = np.round(recette / rng.uniform(900, 1_400, size=campagnes), 1)
    df_campagnes = pd.DataFrame({
        "campagne_id": ids,
        "annee": annees,
        "mois": rng.integers(1, 13, size=campagnes),
        "capitaine_id": [None if rng.random() < 0.02 else f"P{rng.integers(1, 120):03d}"
                         for _ in ids],
        "capitaine_commune": rng.choice(communes, size=campagnes),
        "duree_jours": jours_mer.astype(int),
        "jours_mer": jours_mer,
        "jours_peche": np.maximum(jours_mer - rng.integers(0, 2, size=campagnes), 0),
        "nombre_captures": rng.integers(1, 5, size=campagnes),
        "poids_capture_total": poids,
        "valeur_captures_total": recette,
        "campagne_benefice": recette - depense,
        "campagne_depense": depense,
        "campagne_recette": recette,
        "campagne_rendement": np.round(poids / jours_mer, 2),
    })
    # Quelques bénéfices incohérents, pour que le bloc qualité ait du contenu.
    df_campagnes.loc[rng.choice(campagnes, 9, replace=False), "campagne_benefice"] += 5_000

    weights = np.linspace(3, 0.4, len(especes))
    weights /= weights.sum()
    captures = []
    for row in df_campagnes.itertuples():
        for espece in rng.choice(especes, size=row.nombre_captures, replace=False, p=weights):
            share = rng.uniform(0.1, 1)
            captures.append({
                "campagne_id": row.campagne_id, "categorie_nom": espece,
                "annee": row.annee, "nombre_captures": 1,
                "poids_capture": round(row.poids_capture_total * share / row.nombre_captures, 1),
                "valeur_captures": round(row.campagne_recette * share / row.nombre_captures, -2),
            })

    frais = []
    for row in df_campagnes.itertuples():
        parts = rng.dirichlet(np.linspace(6, 0.5, len(natures)))
        for nature, part in zip(natures, parts):
            # Les salaires ne figurent pas dans le détail des frais.
            frais.append({"campagne_id": row.campagne_id, "nature_frais": nature,
                          "montant": round(row.campagne_depense * 0.7 * part, -1),
                          "annee": row.annee})

    return DtmData(df_campagnes, pd.DataFrame(captures), pd.DataFrame(frais))
