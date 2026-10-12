"""Calcul des indicateurs de la fiche « Indicateurs de la restitution ».

Chaque fonction reproduit la mesure DAX de référence de la fiche ; le numéro
de l'indicateur figure dans sa docstring. Les fonctions sont pures : elles ne
lisent que les tables de SidData et la date de référence.
"""
from __future__ import annotations

import pandas as pd

from src.reporting.data import SidData

# Hypothèses de la fiche « à valider », regroupées pour être affichées.
SEUIL_ANNEE_CONSTRUCTION = 1950
TRANCHES_AGE = [(0, 29, "Moins de 30 ans"), (30, 44, "30 à 44 ans"),
                (45, 59, "45 à 59 ans"), (60, 200, "60 ans et plus")]
NON_RENSEIGNE = "Non renseigné"
TOLERANCE_BENEFICE = 1


# ---------------------------------------------------------------------------
# Mesures de base
# ---------------------------------------------------------------------------

def cartes_actives(cartes: pd.DataFrame, date_ref: pd.Timestamp) -> pd.DataFrame:
    """Cartes qui rendent un pêcheur actif à la date de référence.

    DAX : capitaine_key <> -1, carte_annee = FORMAT(YEAR(DateRef), "0"),
    ISBLANK(carte_autorisation_statut), DIM_TEMPS[date_id] <= DateRef.
    """
    mask = (
        (cartes["capitaine_key"] != -1)
        & (cartes["carte_annee"] == str(date_ref.year))
        & cartes["carte_autorisation_statut"].isna()
        & (cartes["date_delivrance"] <= date_ref)  # NaT -> False, comme -1
    )
    return cartes[mask]


def pecheurs_actifs(d: SidData, date_ref: pd.Timestamp) -> int:
    """3.1.1 Nombre de pêcheurs actifs (DISTINCTCOUNT capitaine_key)."""
    return int(cartes_actives(d.cartes, date_ref)["capitaine_key"].nunique())


def _cles_actives(d: SidData, date_ref: pd.Timestamp) -> pd.Index:
    return pd.Index(cartes_actives(d.cartes, date_ref)["capitaine_key"].unique())


def age_dax(naissance: pd.Series, date_ref: pd.Timestamp) -> pd.Series:
    """DATEDIFF(naissance, DateRef, YEAR) : écart d'années civiles, pas l'âge exact."""
    return date_ref.year - naissance.dt.year


# ---------------------------------------------------------------------------
# 3.1 Sociologique
# ---------------------------------------------------------------------------

def ages_pecheurs_actifs(d: SidData, date_ref: pd.Timestamp) -> pd.Series:
    """Âges des pêcheurs actifs dont la date de naissance est connue et passée."""
    p = d.personnes[d.personnes["personne_key"].isin(_cles_actives(d, date_ref))]
    p = p[p["date_naissance"].notna() & (p["date_naissance"] <= date_ref)]
    return age_dax(p["date_naissance"], date_ref)


def age_moyen(d: SidData, date_ref: pd.Timestamp) -> float:
    """3.1.2 Âge moyen des pêcheurs actifs, âges manquants exclus."""
    ages = ages_pecheurs_actifs(d, date_ref)
    return float(ages.mean()) if len(ages) else float("nan")


def tranche_age(age: float) -> str:
    for low, high, label in TRANCHES_AGE:
        if low <= age <= high:
            return label
    return NON_RENSEIGNE


def repartition_age(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.1.2 Pêcheurs actifs par tranche d'âge, âge inconnu compris."""
    keys = _cles_actives(d, date_ref)
    ages = ages_pecheurs_actifs(d, date_ref)
    labels = ages.map(tranche_age).value_counts()
    labels[NON_RENSEIGNE] = len(keys) - len(ages)
    order = [label for _, _, label in TRANCHES_AGE] + [NON_RENSEIGNE]
    return pd.DataFrame({"Tranche d'âge": order,
                         "Pêcheurs": [int(labels.get(o, 0)) for o in order]})


def repartition_genre(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.1.2 [Pêcheurs actifs] découpé par DIM_PERSONNE[sexe]."""
    p = d.personnes[d.personnes["personne_key"].isin(_cles_actives(d, date_ref))]
    sexe = p["sexe"].where(p["sexe"].notna() & (p["sexe"] != "Inconnu"), NON_RENSEIGNE)
    out = sexe.value_counts().rename_axis("Genre").reset_index(name="Pêcheurs")
    return out


def repartition_commune(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.1.2 [Pêcheurs actifs] découpé par DIM_COMMUNE[commune] (commune de la carte).

    Un pêcheur titulaire de cartes dans deux communes compte dans chacune,
    comme le DISTINCTCOUNT par commune en DAX.
    """
    c = cartes_actives(d.cartes, date_ref)
    commune = c["commune"].fillna("Non renseignée")
    out = (c.assign(Commune=commune).groupby("Commune")["capitaine_key"].nunique()
           .sort_values(ascending=False).reset_index(name="Pêcheurs"))
    return out


def evolution_pecheurs(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.1.2 Pêcheurs actifs et âge moyen, année par année.

    Pour une année passée, la date de référence est le 31 décembre ; pour
    l'année en cours, c'est la date de référence choisie.
    """
    annees = sorted({int(a) for a in d.cartes["carte_annee"].dropna() if str(a).isdigit()})
    rows = []
    for annee in annees:
        if annee > date_ref.year:
            continue
        ref = min(date_ref, pd.Timestamp(annee, 12, 31))
        rows.append({"Année": annee, "Pêcheurs actifs": pecheurs_actifs(d, ref),
                     "Âge moyen": age_moyen(d, ref)})
    return pd.DataFrame(rows, columns=["Année", "Pêcheurs actifs", "Âge moyen"])


def experience_moyenne(d: SidData, date_ref: pd.Timestamp) -> float:
    """3.1.3 Nombre moyen d'années avec au moins une carte sans statut.

    DAX : DISTINCTCOUNT(carte_annee) des cartes du pêcheur, statut vide et
    carte_annee <= FORMAT(YEAR(DateRef), "0") (comparaison de texte).
    """
    keys = _cles_actives(d, date_ref)
    if not len(keys):
        return float("nan")
    c = d.cartes[d.cartes["capitaine_key"].isin(keys)
                 & d.cartes["carte_autorisation_statut"].isna()
                 & d.cartes["carte_annee"].notna()]
    c = c[c["carte_annee"] <= str(date_ref.year)]
    return float(c.groupby("capitaine_key")["carte_annee"].nunique().reindex(keys).mean())


def capitaines_patrons(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.1.4 Capitaines actifs : leur propre patron, patron différent, non renseigné."""
    c = cartes_actives(d.cartes, date_ref)
    propre = c[c["capitaine_key"] == c["patron_key"]]
    autre = c[(c["capitaine_key"] != c["patron_key"]) & (c["patron_key"] != -1)]
    inconnu = c[c["patron_key"] == -1]
    return pd.DataFrame({
        "Situation": ["Capitaine = patron", "Patron différent", "Patron non renseigné"],
        "Capitaines": [int(x["capitaine_key"].nunique()) for x in (propre, autre, inconnu)],
    })


# ---------------------------------------------------------------------------
# 3.2 Matériel
# ---------------------------------------------------------------------------

def nb_navires(d: SidData) -> int:
    """3.2.1 DISTINCTCOUNTNOBLANK(DIM_NAVIRE[navire_id])."""
    return int(d.navires["navire_id"].dropna().nunique())


def age_flotte(d: SidData, date_ref: pd.Timestamp) -> dict[str, float]:
    """3.2.2 Âge moyen des navires construits entre le seuil et l'année de référence."""
    annee_ref = date_ref.year
    n = d.navires[d.navires["navire_id"].notna()]
    annee = pd.to_numeric(n["annee_construction"], errors="coerce")
    valides = annee[(annee >= SEUIL_ANNEE_CONSTRUCTION) & (annee <= annee_ref)]
    return {
        "age_moyen": float((annee_ref - valides).mean()) if len(valides) else float("nan"),
        "retenus": int(len(valides)),
        "sans_annee": int(annee.isna().sum()),
        "ecartes": int(len(annee) - annee.isna().sum() - len(valides)),
    }


def ages_navires(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.2.2 Répartition des navires retenus par tranche d'âge de 10 ans."""
    annee = pd.to_numeric(d.navires.loc[d.navires["navire_id"].notna(), "annee_construction"],
                          errors="coerce")
    annee = annee[(annee >= SEUIL_ANNEE_CONSTRUCTION) & (annee <= date_ref.year)]
    age = (date_ref.year - annee).astype(int)
    bins = list(range(0, int(age.max()) + 11, 10)) if len(age) else [0, 10]
    labels = [f"{b} à {b + 9} ans" for b in bins[:-1]]
    counts = pd.cut(age, bins=bins, right=False, labels=labels).value_counts().reindex(labels)
    return pd.DataFrame({"Âge": labels, "Navires": counts.fillna(0).astype(int).values})


def motorisation(d: SidData) -> pd.DataFrame:
    """3.2.4 Navires à un moteur, à plusieurs moteurs, sans moteur renseigné."""
    n = d.navires[d.navires["navire_id"].notna()]
    return pd.DataFrame({
        "Motorisation": ["Un moteur", "Deux moteurs ou plus", "Motorisation non renseignée"],
        "Navires": [int(n.loc[n["nb_moteurs"] == 1, "navire_id"].nunique()),
                    int(n.loc[n["nb_moteurs"] >= 2, "navire_id"].nunique()),
                    int(n.loc[n["nb_moteurs"] == 0, "navire_id"].nunique())],
    })


def navires_avec_moteur(d: SidData) -> int:
    """3.2.4 DISTINCTCOUNT(DIM_MOTEUR[navire_key]), navire inconnu exclu."""
    return int(d.moteurs.loc[d.moteurs["navire_key"] != -1, "navire_key"].nunique())


# ---------------------------------------------------------------------------
# 3.3 Environnemental
# ---------------------------------------------------------------------------

def captures_par_mois(d: SidData) -> pd.DataFrame:
    """3.3.1 Nombre, poids et quantité des captures par mois de début de campagne."""
    c = d.captures[d.captures["date_id"].notna()]
    out = (c.assign(Mois=c["date_id"].dt.to_period("M").dt.to_timestamp())
           .groupby("Mois")
           .agg(**{"Captures": ("capture_id", "nunique"),
                   "Poids": ("capture_poids_entier_total", "sum"),
                   "Quantité": ("capture_nombre", "sum")})
           .reset_index())
    return out


def captures_sans_date(d: SidData) -> int:
    return int(d.captures["date_id"].isna().sum())


def captures_par_espece(d: SidData, axe: str = "categorie_nom") -> pd.DataFrame:
    """3.3.2 Poids, nombre, valeur et part du poids par espèce (ou produit)."""
    c = d.captures.assign(**{axe: d.captures[axe].fillna("Inconnue")})
    total = c["capture_poids_entier_total"].sum()
    out = (c.groupby(axe)
           .agg(Poids=("capture_poids_entier_total", "sum"),
                Captures=("capture_id", "nunique"),
                Valeur=("capture_valeurxpf", "sum"))
           .sort_values("Poids", ascending=False).reset_index())
    out["Part du poids (%)"] = out["Poids"] / total * 100 if total else float("nan")
    return out.rename(columns={axe: "Espèce" if axe == "categorie_nom" else "Produit",
                               "Valeur": "Valeur (XPF)"})


def poids_par_zone(d: SidData) -> pd.DataFrame:
    """3.3.3 SUMX(PONT_CAPTURE_ZONE, facteur * poids) et captures touchant la zone."""
    if d.zones.empty:
        return pd.DataFrame(columns=["Zone", "Poids", "Captures touchant la zone"])
    z = d.zones.merge(d.captures[["capture_id", "capture_poids_entier_total"]],
                      on="capture_id", how="left")
    z["poids_reparti"] = z["facteur"] * z["capture_poids_entier_total"]
    out = (z.assign(label=z["label"].fillna("Zone inconnue")).groupby("label")
           .agg(Poids=("poids_reparti", "sum"),
                **{"Captures touchant la zone": ("capture_id", "nunique")})
           .sort_values("Poids", ascending=False).reset_index()
           .rename(columns={"label": "Zone"}))
    return out


def part_captures_avec_zone(d: SidData) -> float:
    total = d.captures["capture_id"].nunique()
    return d.zones["capture_id"].nunique() / total * 100 if total else float("nan")


# ---------------------------------------------------------------------------
# 3.4 Activité
# ---------------------------------------------------------------------------

def campagnes_par_mois(d: SidData) -> pd.DataFrame:
    """3.4.1 DISTINCTCOUNT(campagne_id) par mois de début."""
    c = d.campagnes[d.campagnes["date_debut"].notna()]
    return (c.assign(Mois=c["date_debut"].dt.to_period("M").dt.to_timestamp())
            .groupby("Mois")["campagne_id"].nunique().reset_index(name="Campagnes"))


def duree_campagnes(d: SidData) -> dict[str, float]:
    """3.4.2 Durée moyenne ; les durées vides sont signalées, pas corrigées."""
    c = d.campagnes
    date_manquante = c["date_debut"].isna() | c["date_fin"].isna()
    fin_avant_debut = ~date_manquante & (c["date_fin"] < c["date_debut"])
    return {
        "duree_moyenne": float(c["duree_jours"].mean()),
        "date_manquante": int(date_manquante.sum()),
        "fin_avant_debut": int(fin_avant_debut.sum()),
        "total": int(len(c)),
    }


def repartition_durees(d: SidData) -> pd.DataFrame:
    """3.4.2 Campagnes par durée (fin − début, 0 = retour le jour même)."""
    duree = d.campagnes["duree_jours"].dropna().astype(int)
    labels = {0: "Même jour", 1: "1 jour", 2: "2 jours", 3: "3 jours"}
    tranche = duree.map(lambda j: labels.get(j, "4 à 6 jours" if j <= 6 else "7 jours et plus"))
    order = list(labels.values()) + ["4 à 6 jours", "7 jours et plus"]
    counts = tranche.value_counts().reindex(order, fill_value=0)
    return pd.DataFrame({"Durée": order, "Campagnes": counts.values})


def captures_par_campagne(d: SidData) -> pd.DataFrame:
    """3.4.3 Nombre et poids des captures, ramenés au nombre de campagnes, par année."""
    cc = d.captures_campagne.groupby("annee")[["nombre_captures", "poids_capture"]].sum()
    nb = d.campagnes.dropna(subset=["annee"]).groupby("annee")["campagne_id"].nunique()
    out = cc.join(nb.rename("campagnes"), how="outer").fillna(0).reset_index()
    out["annee"] = out["annee"].astype(int)
    out["Captures par campagne"] = out["nombre_captures"] / out["campagnes"].where(out["campagnes"] > 0)
    out["Poids par campagne"] = out["poids_capture"] / out["campagnes"].where(out["campagnes"] > 0)
    return out.rename(columns={"annee": "Année", "nombre_captures": "Captures",
                               "poids_capture": "Poids", "campagnes": "Campagnes"})


def captures_par_campagne_espece(d: SidData, n: int = 10) -> pd.DataFrame:
    """3.4.3 Nombre de captures et poids par espèce (DTM_CAPTURE_CAMPAGNE)."""
    return (d.captures_campagne.assign(categorie_nom=d.captures_campagne["categorie_nom"].fillna(NON_RENSEIGNE))
            .groupby("categorie_nom")[["nombre_captures", "poids_capture"]].sum()
            .sort_values("poids_capture", ascending=False).head(n).reset_index()
            .rename(columns={"categorie_nom": "Espèce", "nombre_captures": "Captures",
                             "poids_capture": "Poids"}))


COLONNES_CAMPAGNES_ACTIVES = {
    "campagne_id": "Campagne", "capitaine_id": "Capitaine", "date_debut": "Début",
    "date_fin": "Fin", "duree_jours": "Durée (j)", "jours_mer": "Jours en mer",
    "jours_peche": "Jours de pêche",
}


def campagnes_actives(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.4.4 Campagnes commencées au plus tard et finies au plus tôt à la date."""
    c = d.campagnes
    actives = c[(c["date_debut"] <= date_ref) & (c["date_fin"] >= date_ref)]
    return (actives[list(COLONNES_CAMPAGNES_ACTIVES)].sort_values("date_debut")
            .rename(columns=COLONNES_CAMPAGNES_ACTIVES).reset_index(drop=True))


def campagnes_sans_fin_ouvertes(d: SidData, date_ref: pd.Timestamp) -> int:
    """Campagnes commencées avant la date sans date de fin : exclues, signalées."""
    c = d.campagnes
    return int(((c["date_debut"] <= date_ref) & c["date_fin"].isna()).sum())


# ---------------------------------------------------------------------------
# 3.5 Économique
# ---------------------------------------------------------------------------

MONTANTS = {"campagne_recette": "Recette", "campagne_depense": "Dépense",
            "campagne_benefice": "Bénéfice"}


def finances_par_annee(d: SidData) -> pd.DataFrame:
    """3.5.1 Recette, dépense et bénéfice cumulés par année (montants source)."""
    c = d.campagnes.dropna(subset=["annee"])
    out = c.groupby("annee")[list(MONTANTS)].sum(min_count=1).reset_index()
    out["annee"] = out["annee"].astype(int)
    return out.rename(columns={"annee": "Année", **MONTANTS})


def rentabilite_par_pecheur(d: SidData) -> pd.DataFrame:
    """3.5.1 Recette, dépense et bénéfice par année et par capitaine_id."""
    c = d.campagnes.dropna(subset=["annee"])
    out = (c.groupby(["annee", "capitaine_id"], dropna=False)[list(MONTANTS)]
           .sum(min_count=1).reset_index())
    out["annee"] = out["annee"].astype(int)
    return out.rename(columns={"annee": "Année", "capitaine_id": "Capitaine", **MONTANTS})


def synthese_par_pecheur(d: SidData) -> pd.DataFrame:
    """3.5.1 Résumé annuel de la distribution du bénéfice par pêcheur."""
    r = rentabilite_par_pecheur(d)
    g = r.groupby("Année")["Bénéfice"]
    return pd.DataFrame({
        "Pêcheurs": r.groupby("Année")["Capitaine"].nunique(),
        "Bénéfice médian": g.median(),
        "Bénéfice moyen": g.mean(),
        "Pêcheurs déficitaires (%)": g.apply(lambda s: (s < 0).mean() * 100),
    }).reset_index()


def rentabilite_par_campagne(d: SidData) -> dict[str, float]:
    """3.5.2 Résumé des montants par campagne et écarts bénéfice ≠ recette − dépense."""
    c = d.campagnes
    complets = c.dropna(subset=list(MONTANTS))
    ecart = (complets["campagne_benefice"]
             - (complets["campagne_recette"] - complets["campagne_depense"])).abs() > TOLERANCE_BENEFICE
    return {
        "recette_moyenne": float(c["campagne_recette"].mean()),
        "depense_moyenne": float(c["campagne_depense"].mean()),
        "benefice_moyen": float(c["campagne_benefice"].mean()),
        "benefice_median": float(c["campagne_benefice"].median()),
        "deficitaires_pct": float((c["campagne_benefice"] < 0).mean() * 100),
        "ecarts": int(ecart.sum()),
    }


def frais_par_nature(d: SidData) -> pd.DataFrame:
    """3.5.3 Montant et part de chaque nature de frais."""
    f = d.frais.assign(nature_frais=d.frais["nature_frais"].fillna(NON_RENSEIGNE))
    out = (f.groupby("nature_frais")["montant"].sum(min_count=1)
           .sort_values(ascending=False).reset_index())
    total = out["montant"].sum()
    out["part"] = out["montant"] / total * 100 if total else float("nan")
    return out.rename(columns={"nature_frais": "Nature", "montant": "Montant (XPF)",
                               "part": "Part (%)"})


def frais_par_annee_nature(d: SidData) -> pd.DataFrame:
    """3.5.3 Montant des frais par année et par nature."""
    f = d.frais.dropna(subset=["annee"])
    out = f.pivot_table(index="annee", columns="nature_frais", values="montant",
                        aggfunc="sum").reset_index()
    out["annee"] = out["annee"].astype(int)
    return out.rename(columns={"annee": "Année"})


def montant_moyen_par_campagne(d: SidData, axe: str | None = None) -> pd.DataFrame | float:
    """3.5.3 DIVIDE([Montant frais], DISTINCTCOUNT(campagne_id)), éventuellement par axe."""
    f = d.frais
    if axe is None:
        n = f["campagne_id"].nunique()
        return float(f["montant"].sum() / n) if n else float("nan")
    if axe == "jours_mer":
        f = f.assign(jours_mer=f["jours_mer"].map(_tranche_jours_mer))
    else:
        f = f.assign(**{axe: f[axe].fillna(NON_RENSEIGNE)})
    g = f.groupby(axe)
    out = (g["montant"].sum() / g["campagne_id"].nunique()).reset_index(name="Montant moyen par campagne")
    if axe == "jours_mer":
        order = ["1 jour", "2 jours", "3 à 4 jours", "5 jours et plus", NON_RENSEIGNE]
        out[axe] = pd.Categorical(out[axe], categories=order, ordered=True)
        return out.sort_values(axe).reset_index(drop=True)
    return out.sort_values("Montant moyen par campagne", ascending=False).reset_index(drop=True)


def _tranche_jours_mer(j: float) -> str:
    if pd.isna(j):
        return NON_RENSEIGNE
    if j <= 1:
        return "1 jour"
    if j <= 2:
        return "2 jours"
    if j <= 4:
        return "3 à 4 jours"
    return "5 jours et plus"


# ---------------------------------------------------------------------------
# Indicateurs complémentaires des bandeaux de KPI
# ---------------------------------------------------------------------------
# Ils dérivent des mesures de la fiche (mêmes tables, mêmes règles) et servent
# à les situer : comparaison à la même période de l'année précédente, parts,
# médianes. Aucun ne remplace une mesure de la fiche.

def meme_date_annee_precedente(date_ref: pd.Timestamp) -> pd.Timestamp:
    return date_ref - pd.DateOffset(years=1)


def periode(date_ref: pd.Timestamp, decalage: int = 0) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Du 1er janvier à la date de référence, décalé de `decalage` années."""
    fin = date_ref - pd.DateOffset(years=decalage)
    return pd.Timestamp(fin.year, 1, 1), fin


def variation(actuel: float, precedent: float) -> float:
    """Variation relative en %, NaN si la base est nulle ou absente."""
    if precedent is None or pd.isna(precedent) or precedent == 0 or pd.isna(actuel):
        return float("nan")
    return (actuel - precedent) / abs(precedent) * 100


def est_femme(sexe: pd.Series) -> pd.Series:
    """Libellés commençant par F (« F », « Féminin »…), insensible à la casse."""
    return sexe.fillna("").astype(str).str.strip().str.upper().str.startswith("F")


def part_femmes(d: SidData, date_ref: pd.Timestamp) -> float:
    """Part des femmes parmi les pêcheurs actifs (3.1.2, découpage par genre)."""
    keys = _cles_actives(d, date_ref)
    if not len(keys):
        return float("nan")
    p = d.personnes[d.personnes["personne_key"].isin(keys)]
    return float(est_femme(p["sexe"]).sum() / len(keys) * 100)


def nouveaux_pecheurs(d: SidData, date_ref: pd.Timestamp) -> int:
    """Pêcheurs actifs dont la première carte sans statut est de l'année de référence."""
    keys = _cles_actives(d, date_ref)
    valides = d.cartes[d.cartes["capitaine_key"].isin(keys)
                       & d.cartes["carte_autorisation_statut"].isna()
                       & d.cartes["carte_annee"].notna()]
    premiere = valides.groupby("capitaine_key")["carte_annee"].min()
    return int((premiere == str(date_ref.year)).sum())


def repartition_experience(d: SidData, date_ref: pd.Timestamp) -> pd.DataFrame:
    """3.1.3 Pêcheurs actifs par nombre d'années d'activité (même règle que la moyenne)."""
    keys = _cles_actives(d, date_ref)
    c = d.cartes[d.cartes["capitaine_key"].isin(keys)
                 & d.cartes["carte_autorisation_statut"].isna()
                 & d.cartes["carte_annee"].notna()]
    annees = c[c["carte_annee"] <= str(date_ref.year)].groupby("capitaine_key")["carte_annee"].nunique()
    tranche = annees.map(lambda n: f"{n} an" if n == 1 else (f"{n} ans" if n < 5 else "5 ans et plus"))
    order = ["1 an", "2 ans", "3 ans", "4 ans", "5 ans et plus"]
    counts = tranche.value_counts().reindex(order, fill_value=0)
    return pd.DataFrame({"Expérience": order, "Pêcheurs": counts.values})


def stats_navires(d: SidData, date_ref: pd.Timestamp) -> dict[str, float]:
    """3.2.2 compléments : âge médian et part des navires de 30 ans et plus."""
    annee = pd.to_numeric(d.navires.loc[d.navires["navire_id"].notna(), "annee_construction"],
                          errors="coerce")
    annee = annee[(annee >= SEUIL_ANNEE_CONSTRUCTION) & (annee <= date_ref.year)]
    age = date_ref.year - annee
    return {"age_median": float(age.median()) if len(age) else float("nan"),
            "part_30_ans": float((age >= 30).mean() * 100) if len(age) else float("nan")}


def stats_captures(d: SidData) -> dict[str, float | str]:
    """3.3 compléments : valeur, prix moyen, espèce et zone principales."""
    c = d.captures
    poids = c["capture_poids_entier_total"].sum()
    valeur = c["capture_valeurxpf"].sum()
    especes = captures_par_espece(d)
    connues = especes[especes["Espèce"] != "Inconnue"]
    zones = poids_par_zone(d)
    return {
        "captures": int(c["capture_id"].nunique()),
        "poids": float(poids), "valeur": float(valeur),
        "prix_moyen": float(valeur / poids) if poids else float("nan"),
        "poids_moyen": float(c["capture_poids_entier_total"].mean()),
        "nb_especes": int(connues["Espèce"].nunique()),
        "espece_principale": connues["Espèce"].iloc[0] if len(connues) else "–",
        "part_espece_principale": float(connues["Part du poids (%)"].iloc[0]) if len(connues) else float("nan"),
        "zone_principale": zones["Zone"].iloc[0] if len(zones) else "–",
        "nb_zones": int(len(zones)),
    }


def stats_campagnes(d: SidData, date_ref: pd.Timestamp, decalage: int = 0) -> dict[str, float]:
    """3.4 et 3.5 sur la période du 1er janvier à la date de référence (ou N-1)."""
    debut, fin = periode(date_ref, decalage)
    c = d.campagnes[(d.campagnes["date_debut"] >= debut) & (d.campagnes["date_debut"] <= fin)]
    recette = c["campagne_recette"].sum(min_count=1)
    benefice = c["campagne_benefice"].sum(min_count=1)
    par_pecheur = c.groupby("capitaine_id")["campagne_benefice"].sum(min_count=1).dropna()
    jours_mer = c["jours_mer"].sum(min_count=1)
    return {
        "campagnes": int(c["campagne_id"].nunique()),
        "jours_mer": float(jours_mer) if pd.notna(jours_mer) else float("nan"),
        "part_jours_peche": float(c["jours_peche"].sum() / jours_mer * 100) if jours_mer else float("nan"),
        "recette": float(recette) if pd.notna(recette) else float("nan"),
        "depense": float(c["campagne_depense"].sum(min_count=1)),
        "benefice": float(benefice) if pd.notna(benefice) else float("nan"),
        "marge": float(benefice / recette * 100) if recette else float("nan"),
        "benefice_median_pecheur": float(par_pecheur.median()) if len(par_pecheur) else float("nan"),
        "pecheurs_deficitaires": float((par_pecheur < 0).mean() * 100) if len(par_pecheur) else float("nan"),
    }


def repartition_benefice_campagne(d: SidData) -> pd.DataFrame:
    """3.5.2 Campagnes par tranche de bénéfice (agrégat, pas de campagne isolée)."""
    b = d.campagnes["campagne_benefice"].dropna()
    bornes = [-float("inf"), -50_000, 0, 50_000, 100_000, 200_000, float("inf")]
    labels = ["Perte > 50 k", "Perte ≤ 50 k", "0 à 50 k", "50 à 100 k", "100 à 200 k", "Plus de 200 k"]
    counts = pd.cut(b, bornes, right=False, labels=labels).value_counts().reindex(labels, fill_value=0)
    return pd.DataFrame({"Bénéfice (XPF)": labels, "Campagnes": counts.values})


def duree_mediane(d: SidData) -> float:
    return float(d.campagnes["duree_jours"].median())
