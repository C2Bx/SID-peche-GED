from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

DTM = "dtm_performance_campagnes"

# Chaque requête aplatit déjà les jointures nécessaires aux indicateurs : le
# calcul Python travaille ensuite sur des tables simples, comme Power BI sur
# son modèle. Les noms viennent de ce dictionnaire, jamais d'une saisie.
QUERIES = {
    # FAIT_CARTE porte le capitaine, le patron et la date de délivrance ; la
    # commune est celle de la carte (relation FAIT_CARTE -> DIM_COMMUNE).
    "cartes": """
        SELECT fc.carte_id, fc.capitaine_key, fc.patron_key,
               dc.carte_annee, dc.carte_autorisation_statut,
               t.date_id AS date_delivrance, com.commune
        FROM dwh.FAIT_CARTE fc
        LEFT JOIN dwh.DIM_CARTE dc    ON dc.carte_key = fc.carte_key
        LEFT JOIN dwh.DIM_TEMPS t     ON t.temps_key = fc.temps_key
        LEFT JOIN dwh.DIM_COMMUNE com ON com.commune_key = fc.commune_key
    """,
    "personnes": """
        SELECT personne_key, date_naissance, sexe FROM dwh.DIM_PERSONNE
    """,
    "navires": """
        SELECT navire_key, navire_id, annee_construction, nb_moteurs
        FROM dwh.DIM_NAVIRE
    """,
    "moteurs": "SELECT moteur_key, navire_key FROM dwh.DIM_MOTEUR",
    "captures": """
        SELECT f.capture_id, t.date_id, e.categorie_nom, e.produit,
               f.capture_nombre, f.capture_poids_entier_total, f.capture_valeurxpf
        FROM dwh.FAIT_CAPTURE f
        LEFT JOIN dwh.DIM_TEMPS t  ON t.temps_key = f.temps_key
        LEFT JOIN dwh.DIM_ESPECE e ON e.espece_key = f.espece_key
    """,
    "zones": """
        SELECT p.capture_id, p.facteur, z.label
        FROM dwh.PONT_CAPTURE_ZONE p
        LEFT JOIN dwh.DIM_ZONE_PECHE z ON z.zone_key = p.zone_key
    """,
    "campagnes": f"""
        SELECT campagne_id, annee, mois, date_debut, date_fin, capitaine_id,
               duree_jours, jours_mer, jours_peche, campagne_recette,
               campagne_depense, campagne_benefice
        FROM {DTM}.DTM_PERFORMANCE_CAMPAGNE
    """,
    "captures_campagne": f"""
        SELECT campagne_id, categorie_nom, annee, nombre_captures, poids_capture
        FROM {DTM}.DTM_CAPTURE_CAMPAGNE
    """,
    "frais": f"""
        SELECT campagne_id, nature_frais, montant, annee, mois, jours_mer,
               navire_categorie_navigation, carburant_moteur_principal
        FROM {DTM}.DTM_FRAIS_CAMPAGNE
    """,
}

DATE_COLUMNS = {
    "cartes": ["date_delivrance"],
    "personnes": ["date_naissance"],
    "captures": ["date_id"],
    "campagnes": ["date_debut", "date_fin"],
}

# Empreinte de la base : nombre de lignes de chaque table lue. Une ligne
# ajoutée ou supprimée la modifie, ce qui déclenche la régénération en --watch.
FINGERPRINT_TABLES = [
    "dwh.FAIT_CARTE", "dwh.DIM_PERSONNE", "dwh.DIM_NAVIRE", "dwh.DIM_MOTEUR",
    "dwh.FAIT_CAPTURE", "dwh.PONT_CAPTURE_ZONE",
    f"{DTM}.DTM_PERFORMANCE_CAMPAGNE", f"{DTM}.DTM_CAPTURE_CAMPAGNE",
    f"{DTM}.DTM_FRAIS_CAMPAGNE",
]


@dataclass(frozen=True)
class SidData:
    cartes: pd.DataFrame
    personnes: pd.DataFrame
    navires: pd.DataFrame
    moteurs: pd.DataFrame
    captures: pd.DataFrame
    zones: pd.DataFrame
    campagnes: pd.DataFrame
    captures_campagne: pd.DataFrame
    frais: pd.DataFrame


def _query(connection: Any, statement: str) -> pd.DataFrame:
    """Exécute une requête et renvoie un DataFrame, quel que soit le pilote."""
    with connection.cursor() as cursor:
        cursor.execute(statement)
        columns = [column[0].lower() for column in cursor.description]
        # pyodbc renvoie des objets Row : tuple() les rend utilisables par pandas.
        rows = [tuple(row) for row in cursor.fetchall()]
    return pd.DataFrame.from_records(rows, columns=columns)


def normalize(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Uniformise les types renvoyés par psycopg, pyodbc ou le jeu de démo."""
    frame = frame.copy()
    for column in DATE_COLUMNS.get(name, []):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    if "carte_annee" in frame:
        # La colonne est textuelle dans le DWH : on la garde en texte, comme
        # la comparaison FORMAT(YEAR(...), "0") de la fiche.
        frame["carte_annee"] = frame["carte_annee"].map(
            lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip())
    for column in frame.columns:
        if frame[column].dtype == object and column.endswith(("_key", "_total", "_xpf")):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def load(connection: Any) -> SidData:
    """Lit le DWH et le DTM nécessaires aux 17 indicateurs de la restitution."""
    return SidData(**{
        name: normalize(name, _query(connection, statement))
        for name, statement in QUERIES.items()
    })


def fingerprint(connection: Any) -> str:
    """Empreinte courte du contenu de la base, comparée entre deux lectures."""
    counts = []
    with connection.cursor() as cursor:
        for table in FINGERPRINT_TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts.append(f"{table}={cursor.fetchone()[0]}")
    # Libère la transaction ouverte par les SELECT : la lecture suivante voit
    # ainsi les données validées entre-temps par un autre processus.
    connection.commit()
    return hashlib.sha1(";".join(counts).encode()).hexdigest()[:12]


def demo_data(seed: int = 7, today: date | None = None) -> SidData:
    """Produit un jeu fictif cohérent au format du DWH et du DTM."""
    rng = np.random.default_rng(seed)
    today = today or date.today()
    years = list(range(today.year - 5, today.year + 1))
    communes = ["Nouméa", "Dumbéa", "Mont-Dore", "Païta", "Bourail", "La Foa",
                "Thio", "Yaté", "Île des Pins", "Poya"]

    # Personnes -------------------------------------------------------------
    n_personnes = 160
    # La première ligne est le membre inconnu (-1) de DIM_PERSONNE.
    naissance = [None] + [
        None if rng.random() < 0.06 else
        date(int(rng.integers(1950, 2003)), int(rng.integers(1, 13)), int(rng.integers(1, 28)))
        for _ in range(n_personnes)]
    personnes = pd.DataFrame({
        "personne_key": [-1, *range(1, n_personnes + 1)],
        "date_naissance": naissance,
        "sexe": ["Inconnu", *rng.choice(["Masculin", "Féminin", "Inconnu"], n_personnes,
                                        p=[0.82, 0.14, 0.04])],
    })
    commune_personne = {k: rng.choice(communes) for k in range(1, n_personnes + 1)}

    # Cartes : un capitaine a une carte certaines années, pas toutes ----------
    cartes = []
    debut = {k: int(rng.integers(years[0] - 8, years[-1] + 1)) for k in commune_personne}
    for key in commune_personne:
        for year in years:
            if year < debut[key] or rng.random() < 0.15:
                continue
            delivrance = date(year, int(rng.integers(1, 10)), int(rng.integers(1, 28)))
            if year == today.year and delivrance > today:
                delivrance = date(year, 1, 15)
            patron = key if rng.random() < 0.6 else (
                -1 if rng.random() < (0.6 if year < 2021 else 0.15)
                else int(rng.integers(1, n_personnes + 1)))
            statut = rng.choice([None, "Cessation d'activité", "Vente"], p=[0.9, 0.06, 0.04])
            cartes.append({
                "carte_id": f"C{key:03d}-{year}", "capitaine_key": key, "patron_key": patron,
                "carte_annee": str(year), "carte_autorisation_statut": statut,
                "date_delivrance": None if rng.random() < 0.02 else delivrance,
                "commune": commune_personne[key],
            })
    cartes = pd.DataFrame(cartes)

    # Navires et moteurs ------------------------------------------------------
    n_navires = 130
    nb_moteurs = rng.choice([0, 1, 2], n_navires, p=[0.12, 0.7, 0.18])
    annees = [None if rng.random() < 0.08 else (1900 if rng.random() < 0.02
              else int(rng.integers(1965, today.year))) for _ in range(n_navires)]
    navires = pd.DataFrame({
        "navire_key": range(1, n_navires + 1),
        "navire_id": [f"N{i:04d}" for i in range(1, n_navires + 1)],
        "annee_construction": pd.array(annees, dtype="Int64"),
        "nb_moteurs": nb_moteurs,
    })
    navires = pd.concat([pd.DataFrame({"navire_key": [-1], "navire_id": [None],
                                       "annee_construction": pd.array([None], dtype="Int64"),
                                       "nb_moteurs": [0]}), navires], ignore_index=True)
    moteurs = pd.DataFrame([
        {"moteur_key": len(navires) * 3 + i, "navire_key": row.navire_key}
        for row in navires.itertuples() if row.navire_key != -1
        for i in range(row.nb_moteurs)
    ])
    moteurs["moteur_key"] = range(1, len(moteurs) + 1)

    # Campagnes (DTM) ---------------------------------------------------------
    especes = ["Vivaneaux", "Loches", "Thons", "Bec de cane", "Crabes", "Langoustes",
               "Picots", "Mulets", "Bossus", "Holothuries", "Poulpes", "Dawas"]
    produits = {e: [f"{e} entier", f"{e} vidé"] for e in especes}
    natures = ["Carburant", "Glace", "Vivres", "Appâts", "Matériel", "Petit matériel",
               "Lubrifiant", "Entretien du bateau", "Entretien du moteur", "Divers"]
    categories = ["Côtière 1re catégorie", "Côtière 2e catégorie", "Hauturière"]
    carburants = ["Essence", "Gazole", "Non renseigné"]

    campagnes, captures_dwh, frais = [], [], []
    capture_id = 0
    actives_cartes = cartes[cartes["carte_autorisation_statut"].isna()]
    for i in range(900):
        carte = actives_cartes.iloc[int(rng.integers(len(actives_cartes)))]
        year = int(carte["carte_annee"])
        start = date(year, 1, 1) + timedelta(days=int(rng.integers(0, 365)))
        if start > today:
            start = today - timedelta(days=int(rng.integers(0, 60)))
        jours = int(rng.integers(1, 8))
        end = start + timedelta(days=jours - 1)
        anomalie = rng.random()
        date_fin = None if anomalie < 0.02 else (start - timedelta(days=2) if anomalie < 0.03 else end)
        duree = None if date_fin is None or date_fin < start else (date_fin - start).days
        recette = round(float(rng.gamma(2.2, 60_000)) * jours / 3, -2)
        depense = round(recette * float(rng.uniform(0.45, 1.2)), -2)
        benefice = recette - depense + (5_000 if rng.random() < 0.015 else 0)
        cid = f"CAMP-{i:05d}"
        campagnes.append({
            "campagne_id": cid, "annee": start.year, "mois": start.month,
            "date_debut": start, "date_fin": date_fin,
            "capitaine_id": f"P{int(carte['capitaine_key']):03d}",
            "duree_jours": duree, "jours_mer": float(jours),
            "jours_peche": float(max(jours - int(rng.integers(0, 2)), 0)),
            "campagne_recette": recette, "campagne_depense": depense,
            "campagne_benefice": benefice,
        })
        weights = np.linspace(3, 0.4, len(especes))
        weights /= weights.sum()
        for espece in rng.choice(especes, int(rng.integers(1, 5)), replace=False, p=weights):
            capture_id += 1
            poids = round(float(rng.gamma(2, 25)) * jours, 1)
            captures_dwh.append({
                "capture_id": f"CAP-{capture_id:06d}", "campagne_id": cid,
                "date_id": start, "categorie_nom": espece,
                "produit": str(rng.choice(produits[espece])),
                "capture_nombre": 0.0 if rng.random() < 0.85 else float(rng.integers(1, 40)),
                "capture_poids_entier_total": poids,
                "capture_valeurxpf": round(poids * float(rng.uniform(700, 1500)), -1),
            })
        parts = rng.dirichlet(np.linspace(6, 0.5, len(natures)))
        categorie = str(rng.choice(categories))
        carburant = str(rng.choice(carburants, p=[0.55, 0.35, 0.10]))
        for nature, part in zip(natures, parts):
            frais.append({
                "campagne_id": cid, "nature_frais": nature,
                "montant": round(depense * 0.7 * float(part), -1),
                "annee": start.year, "mois": start.month, "jours_mer": float(jours),
                "navire_categorie_navigation": categorie,
                "carburant_moteur_principal": carburant,
            })

    captures_dwh = pd.DataFrame(captures_dwh)
    captures_campagne = (
        captures_dwh.assign(annee=captures_dwh["date_id"].map(lambda d: d.year))
        .groupby(["campagne_id", "categorie_nom", "annee"], as_index=False)
        .agg(nombre_captures=("capture_id", "nunique"),
             poids_capture=("capture_poids_entier_total", "sum"))
    )
    zone_labels = [f"Zone {c}" for c in "ABCDEFGHIJ"]
    zones = []
    for cap in captures_dwh["capture_id"]:
        if rng.random() < 0.35:
            n = int(rng.integers(1, 4))
            for label in rng.choice(zone_labels, n, replace=False):
                zones.append({"capture_id": cap, "facteur": 1.0 / n, "label": str(label)})

    frames = {
        "cartes": cartes, "personnes": personnes, "navires": navires, "moteurs": moteurs,
        "captures": captures_dwh.drop(columns="campagne_id"), "zones": pd.DataFrame(zones),
        "campagnes": pd.DataFrame(campagnes), "captures_campagne": captures_campagne,
        "frais": pd.DataFrame(frais),
    }
    return SidData(**{f.name: normalize(f.name, frames[f.name]) for f in fields(SidData)})
