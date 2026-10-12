"""Assemblage des 17 indicateurs de la fiche en thèmes affichables.

Chaque thème s'ouvre sur un bandeau de KPI (chiffres clés, dont les
indicateurs de la fiche qui se résument à un nombre), suivi de graphiques
présentés par paires de même hauteur.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.reporting import charts
from src.reporting import indicateurs as ind
from src.reporting.data import SidData
from src.reporting.formatting import format_compact, format_date, format_number

CHART_HEIGHT = 300


@dataclass(frozen=True)
class Kpi:
    code: str
    label: str
    value: str
    unit: str = ""
    detail: str = ""
    delta: str = ""


@dataclass
class Carte:
    code: str
    titre: str
    definition: str
    chart_html: str
    table_html: str = ""
    notes: list[str] = field(default_factory=list)
    csv_export: bool = False
    table_visible: bool = False
    wide: bool = False


@dataclass
class Theme:
    id: str
    titre: str
    question: str
    kpis: list[Kpi]
    cartes: list[Carte]
    definitions: list[tuple[str, str, str]]
    exclus: list[str] = field(default_factory=list)


HYPOTHESES = [
    "Pêcheur = capitaine de la carte (hypothèse à confirmer).",
    "Pêcheur actif : carte de l'année de la date de référence, délivrée avant "
    "cette date, sans aucun statut d'autorisation renseigné (règle DAX "
    "ISBLANK de la fiche : tout statut non vide exclut la carte).",
    "Âge = année de référence − année de naissance (DATEDIFF … YEAR en DAX).",
    "Tranches d'âge (moins de 30, 30-44, 45-59, 60 et plus) et seuil de 1950 "
    "pour l'année de construction : à valider.",
    "Le poids est exprimé dans l'unité de la source (à confirmer) ; la quantité "
    "et la valeur en XPF sont sous réserve de validation.",
    "Axes navire (carburant, type de bateau) indicatifs : navire autorisé sur la "
    "carte, pas forcément celui de la campagne.",
    "Montants recopiés de la source, jamais recalculés ; les écarts sont signalés.",
    "Comparaisons « vs N-1 » : même période de l'année précédente (du 1er janvier "
    "à la même date), pour ne pas comparer une année partielle à une année entière.",
]


def _table(df: pd.DataFrame, decimals: dict[str, int] | None = None,
           date_format: str = "%m/%Y") -> str:
    """Vue tableau agrégée d'un graphique, nombres et dates à la française."""
    decimals = decimals or {}
    out = df.copy()
    for column in out.columns:
        series = out[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            out[column] = series.map(
                lambda v: "–" if pd.isna(v) else v.strftime(date_format)
            )
        elif pd.api.types.is_numeric_dtype(series) and column != "Année":
            d = decimals.get(column, 1 if "%" in column or "moyen" in column.lower() else 0)
            out[column] = series.map(lambda v, d=d: format_number(v, d))
    return out.to_html(index=False, border=0, classes="data-table", na_rep="–")


def _pct(value: float) -> str:
    return "–" if pd.isna(value) else f"{format_number(value, 1)} %"


def _share(part: float, total: float) -> str:
    return _pct(100 * part / total) if total else "–"


def _delta(actuel: float, precedent: float, ref: pd.Timestamp) -> str:
    """« ▲ 5,2 % vs 12/10/2025 » : tendance neutre, ni bonne ni mauvaise en soi."""
    v = ind.variation(actuel, precedent)
    if pd.isna(v):
        return ""
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "=")
    return f"{arrow} {format_number(abs(v), 1)} % vs {format_date(ind.meme_date_annee_precedente(ref))}"


def _chart(fig, div_id: str) -> str:
    return charts.to_html(fig, div_id)


# ---------------------------------------------------------------------------
# Thèmes
# ---------------------------------------------------------------------------

def sociologique(d: SidData, ref: pd.Timestamp) -> Theme:
    actifs = ind.pecheurs_actifs(d, ref)
    actifs_n1 = ind.pecheurs_actifs(d, ind.meme_date_annee_precedente(ref))
    evolution = ind.evolution_pecheurs(d, ref)
    ages = ind.repartition_age(d, ref)
    genre = ind.repartition_genre(d, ref)
    communes = ind.repartition_commune(d, ref)
    patrons = ind.capitaines_patrons(d, ref).set_index("Situation")["Capitaines"]
    experience = ind.repartition_experience(d, ref)
    age = ind.age_moyen(d, ref)
    age_n1 = ind.age_moyen(d, ind.meme_date_annee_precedente(ref))
    sans_age = int(ages.loc[ages["Tranche d'âge"] == ind.NON_RENSEIGNE, "Pêcheurs"].iloc[0])

    kpis = [
        Kpi("3.1.1", "Pêcheurs actifs", format_number(actifs), detail=f"au {format_date(ref)}",
            delta=_delta(actifs, actifs_n1, ref)),
        Kpi("3.1.2", "Âge moyen", format_number(age, 1), "ans",
            detail=f"{format_number(age_n1, 1)} ans un an plus tôt"),
        Kpi("3.1.2", "Part de femmes", _pct(ind.part_femmes(d, ref)),
            detail="parmi les pêcheurs actifs"),
        Kpi("3.1.2", "Communes représentées", format_number(
            int((communes["Commune"] != "Non renseignée").sum())), detail="commune de la carte"),
        Kpi("3.1.3", "Expérience moyenne", format_number(ind.experience_moyenne(d, ref), 1), "ans",
            detail="années avec une carte active"),
        Kpi("3.1.2", "Nouveaux pêcheurs", format_number(ind.nouveaux_pecheurs(d, ref)),
            detail=f"1re carte en {ref.year}"),
        Kpi("3.1.4", "Capitaine = patron", format_number(patrons["Capitaine = patron"]),
            detail=_share(patrons["Capitaine = patron"], actifs)),
        Kpi("3.1.4", "Patron différent", format_number(patrons["Patron différent"]),
            detail=_share(patrons["Patron différent"], actifs)),
        Kpi("3.1.4", "Patron non renseigné", format_number(patrons["Patron non renseigné"]),
            detail=_share(patrons["Patron non renseigné"], actifs)),
    ]
    cartes = [
        Carte("3.1.2", "Évolution du nombre de pêcheurs actifs",
              "Pêcheurs actifs année par année (31 décembre, ou date de référence pour "
              "l'année en cours).",
              _chart(charts.lines(evolution["Année"],
                                  {"Pêcheurs actifs": evolution["Pêcheurs actifs"]},
                                  height=CHART_HEIGHT), "c-312-evolution"),
              _table(evolution, {"Âge moyen": 1}), wide=True),
        Carte("3.1.2", "Répartition par tranche d'âge",
              "Pêcheurs actifs à la date de référence, par tranche d'âge.",
              _chart(charts.bars(ages["Tranche d'âge"], ages["Pêcheurs"], height=CHART_HEIGHT),
                     "c-312-ages"),
              _table(ages),
              notes=[f"{sans_age} pêcheur(s) sans date de naissance, exclu(s) de l'âge moyen.",
                     "Tranches proposées par la fiche, à valider."]),
        Carte("3.1.2", "Répartition par commune",
              "Pêcheurs actifs par commune de la carte (10 premières).",
              _chart(charts.bars(communes["Commune"].head(10), communes["Pêcheurs"].head(10),
                                 horizontal=True, height=CHART_HEIGHT), "c-312-communes"),
              _table(communes) + "<h4>Par genre</h4>" + _table(genre),
              notes=["Un pêcheur titulaire de cartes dans deux communes compte dans chacune."]),
        Carte("3.1.3", "Expérience cumulée",
              "Pêcheurs actifs selon leur nombre d'années avec au moins une carte active.",
              _chart(charts.bars(experience["Expérience"], experience["Pêcheurs"],
                                 height=CHART_HEIGHT), "c-313"),
              _table(experience), notes=["Règle V1 de la fiche, à valider."]),
        Carte("3.1.4", "Capitaines et patrons",
              "Capitaines actifs selon leur patron.",
              _chart(charts.bars(patrons.index, patrons.values, height=CHART_HEIGHT), "c-314"),
              _table(patrons.reset_index()),
              notes=["Avant 2021, le patron est souvent vide : catégorie « non renseigné »."]),
    ]
    return Theme("sociologique", "Sociologique", "Qui sont les pêcheurs ?", kpis, cartes, [
        ("3.1.1", "Nombre de pêcheurs actifs",
         "Pêcheurs ayant une carte valable à la date choisie."),
        ("3.1.2", "Évolution du nombre de pêcheurs",
         "Évolution annuelle des pêcheurs actifs, âge moyen, répartition par âge, genre et commune."),
        ("3.1.3", "Expérience cumulée",
         "Nombre moyen d'années où le pêcheur a eu au moins une carte active."),
        ("3.1.4", "Capitaines et patrons",
         "Capitaines actifs qui sont leur propre patron, ou qui ont un patron différent."),
    ])


def materiel(d: SidData, ref: pd.Timestamp) -> Theme:
    age = ind.age_flotte(d, ref)
    stats = ind.stats_navires(d, ref)
    ages = ind.ages_navires(d, ref)
    moto = ind.motorisation(d).set_index("Motorisation")["Navires"]
    navires = ind.nb_navires(d)
    kpis = [
        Kpi("3.2.1", "Navires recensés", format_number(navires), detail="au dernier chargement"),
        Kpi("3.2.2", "Âge moyen de la flotte", format_number(age["age_moyen"], 1), "ans",
            detail=f"{age['retenus']} navires retenus"),
        Kpi("3.2.2", "Âge médian", format_number(stats["age_median"], 0), "ans"),
        Kpi("3.2.2", "Navires de 30 ans et plus", _pct(stats["part_30_ans"])),
        Kpi("3.2.4", "Un moteur", format_number(moto["Un moteur"]),
            detail=_share(moto["Un moteur"], navires)),
        Kpi("3.2.4", "Double motorisation", format_number(moto["Deux moteurs ou plus"]),
            detail=_share(moto["Deux moteurs ou plus"], navires)),
        Kpi("3.2.4", "Motorisation non renseignée", format_number(moto["Motorisation non renseignée"]),
            detail=_share(moto["Motorisation non renseignée"], navires)),
    ]
    cartes = [
        Carte("3.2.2", "Âge de la flotte",
              "Navires par tranche d'âge (année de référence − année de construction).",
              _chart(charts.bars(ages["Âge"], ages["Navires"], height=CHART_HEIGHT), "c-322"),
              _table(ages),
              notes=[f"Exclus : {age['sans_annee']} sans année de construction, "
                     f"{age['ecartes']} avant {ind.SEUIL_ANNEE_CONSTRUCTION} ou après l'année "
                     "de référence (seuil à valider)."]),
        Carte("3.2.4", "Répartition par type de motorisation",
              "Navires à un moteur, à plusieurs moteurs, ou sans information moteur.",
              _chart(charts.bars(moto.index, moto.values, height=CHART_HEIGHT), "c-324"),
              _table(moto.reset_index()),
              notes=[f"Navires avec au moins un moteur dans DIM_MOTEUR : "
                     f"{format_number(ind.navires_avec_moteur(d))}.",
                     "La source n'indique pas si un navire est encore actif : tous comptent."]),
    ]
    return Theme("materiel", "Matériel", "Quelle est la flotte ?", kpis, cartes, [
        ("3.2.1", "Nombre de navires recensés",
         "Navires connus au dernier chargement, actifs ou non (la source ne le dit pas)."),
        ("3.2.2", "Âge de la flotte",
         "Âge moyen des navires, hors années manquantes ou aberrantes."),
        ("3.2.4", "Répartition par type de motorisation",
         "Navires à un moteur, à plusieurs moteurs, ou sans information moteur."),
    ], exclus=["3.2.3", "3.2.5"])


def environnemental(d: SidData, ref: pd.Timestamp) -> Theme:
    mois = ind.captures_par_mois(d)
    especes = ind.captures_par_espece(d)
    produits = ind.captures_par_espece(d, "produit").head(10)
    zones = ind.poids_par_zone(d)
    s = ind.stats_captures(d)
    kpis = [
        Kpi("3.3.1", "Captures", format_number(s["captures"]),
            detail=f"poids moyen {format_number(s['poids_moyen'], 1)} par capture"),
        Kpi("3.3.1", "Poids capturé", format_compact(s["poids"]), detail="unité de la source"),
        Kpi("3.3.1", "Quantité", format_compact(d.captures["capture_nombre"].sum()),
            detail="souvent à 0, à valider"),
        Kpi("3.3.2", "Valeur des captures", format_compact(s["valeur"]), "XPF",
            detail="sous réserve de validation"),
        Kpi("3.3.2", "Prix moyen", format_number(s["prix_moyen"], 0), "XPF",
            detail="par unité de poids"),
        Kpi("3.3.2", "Espèce principale", str(s["espece_principale"]),
            detail=f"{_pct(s['part_espece_principale'])} du poids"),
        Kpi("3.3.2", "Catégories d'espèces", format_number(s["nb_especes"])),
        Kpi("3.3.3", "Captures localisées", _pct(ind.part_captures_avec_zone(d)),
            detail=f"{s['nb_zones']} zones, 1re : {s['zone_principale']}"),
    ]
    cartes = [
        Carte("3.3.1", "Évolution de l'activité de capture",
              "Poids capturé par mois (date de début de la campagne).",
              _chart(charts.lines(mois["Mois"], {"Poids": mois["Poids"]}, x_is_month=True,
                                  height=CHART_HEIGHT), "c-331"),
              _table(mois),
              notes=[f"{ind.captures_sans_date(d)} capture(s) sans date, absentes du graphique."],
              wide=True),
        Carte("3.3.2", "Répartition par espèce",
              "Part du poids capturé par catégorie d'espèce (10 premières).",
              _chart(charts.bars(especes["Espèce"].head(10), especes["Part du poids (%)"].head(10),
                                 horizontal=True, unit="%", decimals=1, height=CHART_HEIGHT),
                     "c-332"),
              _table(especes) + "<h4>10 premiers produits</h4>" + _table(produits),
              notes=["Valeur en XPF sous réserve de validation de sa cohérence."]),
        Carte("3.3.3", "Répartition géographique",
              "Poids pêché par zone (10 premières), réparti entre les zones d'une même capture.",
              _chart(charts.bars(zones["Zone"].head(10), zones["Poids"].head(10),
                                 horizontal=True, height=CHART_HEIGHT), "c-333"),
              _table(zones),
              notes=["Histogramme : le DWH ne contient aucun contour géographique.",
                     "« Captures touchant la zone » ne s'additionne pas d'une zone à l'autre."]),
    ]
    return Theme("environnemental", "Environnemental", "Qu'est-ce qui est pêché ?", kpis, cartes, [
        ("3.3.1", "Évolution de l'activité de capture",
         "Nombre de captures, poids et quantité pêchés, mois par mois."),
        ("3.3.2", "Répartition des captures par espèce",
         "Part du poids, du nombre de captures et de la valeur par espèce, puis par produit."),
        ("3.3.3", "Répartition géographique des captures",
         "Poids par zone, réparti avec le facteur 1 ÷ nombre de zones de la capture."),
    ])


def activite(d: SidData, ref: pd.Timestamp) -> Theme:
    mois = ind.campagnes_par_mois(d)
    duree = ind.duree_campagnes(d)
    durees = ind.repartition_durees(d)
    par_campagne = ind.captures_par_campagne(d)
    especes = ind.captures_par_campagne_espece(d)
    actives = ind.campagnes_actives(d, ref)
    sans_fin = ind.campagnes_sans_fin_ouvertes(d, ref)
    s, s1 = ind.stats_campagnes(d, ref), ind.stats_campagnes(d, ref, 1)
    poids_campagne = par_campagne.set_index("Année")["Poids par campagne"]
    kpis = [
        Kpi("3.4.1", f"Campagnes {ref.year}", format_number(s["campagnes"]),
            detail=f"du 01/01 au {format_date(ref)}", delta=_delta(s["campagnes"], s1["campagnes"], ref)),
        Kpi("3.4.1", "Campagnes au total", format_number(d.campagnes["campagne_id"].nunique()),
            detail="depuis le début des données"),
        Kpi("3.4.2", "Durée moyenne", format_number(duree["duree_moyenne"], 1), "jours",
            detail=f"médiane {format_number(ind.duree_mediane(d), 0)} jour(s)"),
        Kpi("3.4.2", f"Jours en mer {ref.year}", format_number(s["jours_mer"]),
            delta=_delta(s["jours_mer"], s1["jours_mer"], ref)),
        Kpi("3.4.2", "Jours de pêche / jours en mer", _pct(s["part_jours_peche"]),
            detail=f"en {ref.year}"),
        Kpi("3.4.3", "Poids par campagne", format_number(poids_campagne.get(ref.year), 0),
            detail=f"en {ref.year}"),
        Kpi("3.4.4", "Campagnes actives", format_number(len(actives)),
            detail=f"au {format_date(ref)}"),
    ]
    cartes = [
        Carte("3.4.1", "Évolution du nombre de campagnes",
              "Nombre de sorties de pêche par mois de début.",
              _chart(charts.lines(mois["Mois"], {"Campagnes": mois["Campagnes"]}, x_is_month=True,
                                  height=CHART_HEIGHT), "c-341"),
              _table(mois), wide=True),
        Carte("3.4.2", "Durée des campagnes",
              "Campagnes selon leur durée (date de fin − date de début).",
              _chart(charts.bars(durees["Durée"], durees["Campagnes"], height=CHART_HEIGHT), "c-342"),
              _table(durees),
              notes=[f"Signalé, non corrigé : {duree['date_manquante']} campagne(s) avec une date "
                     f"manquante, {duree['fin_avant_debut']} avec une fin avant le début."]),
        Carte("3.4.3", "Poids des captures par campagne",
              "Poids capturé moyen par campagne, année par année.",
              _chart(charts.lines(par_campagne["Année"],
                                  {"Poids par campagne": par_campagne["Poids par campagne"]},
                                  height=CHART_HEIGHT), "c-343"),
              _table(par_campagne, {"Captures par campagne": 2, "Poids par campagne": 1})
              + "<h4>Par espèce (10 premières en poids)</h4>" + _table(especes)),
        Carte("3.4.4", "Campagnes actives à une date",
              f"Sorties en cours au {format_date(ref)} : début au plus tard ce jour-là, "
              "fin au plus tôt.",
              "",
              _table(actives.rename(columns={
                  "Campagne": "Identifiant de campagne", "Début": "Date de début",
                  "Fin": "Date de fin", "Durée (j)": "Durée"}), date_format="%d/%m/%Y"),
              notes=[f"{sans_fin} campagne(s) commencée(s) sans date de fin : exclues, à vérifier."],
              csv_export=True, table_visible=True, wide=True),
    ]
    return Theme("activite", "Activité", "Quelles sorties en mer ?", kpis, cartes, [
        ("3.4.1", "Évolution du nombre de campagnes",
         "Nombre de sorties de pêche par mois, filtrable par pêcheur."),
        ("3.4.2", "Durée d'une campagne",
         "Jours entre début et fin ; vide si une date manque ou si la fin précède le début."),
        ("3.4.3", "Nombre et poids des captures par campagne",
         "Ce que rapporte chaque sortie, par espèce et dans le temps."),
        ("3.4.4", "Campagnes actives à une date",
         "Sorties commencées au plus tard et finies au plus tôt à la date choisie (export CSV)."),
    ])


def economique(d: SidData, ref: pd.Timestamp) -> Theme:
    finances = ind.finances_par_annee(d)
    pecheurs = ind.rentabilite_par_pecheur(d)
    synthese = ind.synthese_par_pecheur(d)
    campagne = ind.rentabilite_par_campagne(d)
    tranches = ind.repartition_benefice_campagne(d)
    natures = ind.frais_par_nature(d)
    par_annee = ind.frais_par_annee_nature(d)
    top = [n for n in natures["Nature"] if n in par_annee.columns][:5]
    series = {n: par_annee[n] for n in top}
    autres = [c for c in par_annee.columns if c not in top and c != "Année"]
    if autres:
        series["Autres natures"] = par_annee[autres].sum(axis=1)
    carburant = ind.montant_moyen_par_campagne(d, "carburant_moteur_principal")
    bateau = ind.montant_moyen_par_campagne(d, "navire_categorie_navigation")
    jours = ind.montant_moyen_par_campagne(d, "jours_mer")
    s, s1 = ind.stats_campagnes(d, ref), ind.stats_campagnes(d, ref, 1)
    poste = natures.iloc[0] if len(natures) else None
    kpis = [
        Kpi("3.5.1", f"Recette {ref.year}", format_compact(s["recette"]), "XPF",
            delta=_delta(s["recette"], s1["recette"], ref)),
        Kpi("3.5.1", f"Dépense {ref.year}", format_compact(s["depense"]), "XPF",
            delta=_delta(s["depense"], s1["depense"], ref)),
        Kpi("3.5.1", f"Bénéfice {ref.year}", format_compact(s["benefice"]), "XPF",
            delta=_delta(s["benefice"], s1["benefice"], ref)),
        Kpi("3.5.1", "Marge", _pct(s["marge"]), detail=f"bénéfice / recette en {ref.year}"),
        Kpi("3.5.1", "Bénéfice médian par pêcheur", format_compact(s["benefice_median_pecheur"]),
            "XPF", detail=f"{_pct(s['pecheurs_deficitaires'])} de pêcheurs déficitaires"),
        Kpi("3.5.2", "Bénéfice moyen par campagne", format_compact(campagne["benefice_moyen"]), "XPF",
            detail=f"médiane {format_compact(campagne['benefice_median'])} XPF"),
        Kpi("3.5.2", "Campagnes déficitaires", _pct(campagne["deficitaires_pct"]),
            detail=f"{campagne['ecarts']} écart(s) bénéfice ≠ recette − dépense"),
        Kpi("3.5.3", "Frais moyens par campagne",
            format_compact(ind.montant_moyen_par_campagne(d)), "XPF"),
        Kpi("3.5.3", "Premier poste de frais", poste["Nature"] if poste is not None else "–",
            detail=f"{_pct(poste['Part (%)'])} des frais" if poste is not None else ""),
    ]
    cartes = [
        Carte("3.5.1", "Recette, dépense et bénéfice par année",
              "Montants cumulés des campagnes, rattachées à leur année de début.",
              _chart(charts.lines(finances["Année"], {k: finances[k] for k in
                                                      ("Recette", "Dépense", "Bénéfice")},
                                  unit="XPF", height=CHART_HEIGHT), "c-351-annees"),
              _table(finances), wide=True),
        Carte("3.5.1", "Bénéfice annuel par pêcheur",
              "Distribution du bénéfice cumulé par pêcheur et par année (quartiles, médiane).",
              _chart(charts.box_by_year(pecheurs, "Année", "Bénéfice", height=CHART_HEIGHT),
                     "c-351-pecheurs"),
              _table(synthese),
              notes=["Aucun pêcheur n'est affiché individuellement.",
                     "Taux de rentabilité non affiché tant que le métier n'a pas défini sa formule."]),
        Carte("3.5.2", "Bénéfice par campagne",
              "Campagnes par tranche de bénéfice.",
              _chart(charts.bars(tranches["Bénéfice (XPF)"], tranches["Campagnes"],
                                 height=CHART_HEIGHT), "c-352"),
              _table(tranches),
              notes=[f"{campagne['ecarts']} campagne(s) où bénéfice ≠ recette − dépense : "
                     "valeur source conservée, écart signalé."]),
        Carte("3.5.3", "Évolution des coûts par nature",
              "Montant des frais par année pour les 5 premiers postes.",
              _chart(charts.lines(par_annee["Année"], series, unit="XPF", height=CHART_HEIGHT),
                     "c-353-annees"),
              _table(natures)),
        Carte("3.5.3", "Coût d'une campagne selon les jours en mer",
              "Frais moyens par campagne selon la durée en mer.",
              _chart(charts.bars(jours["jours_mer"].astype(str), jours["Montant moyen par campagne"],
                                 height=CHART_HEIGHT), "c-353-jours"),
              _table(jours)
              + "<h4>Selon le carburant du moteur principal</h4>" + _table(carburant)
              + "<h4>Selon le type de bateau</h4>" + _table(bateau),
              notes=["La somme des frais n'égale pas la dépense : les salaires n'y figurent pas.",
                     "Carburant et type de bateau : axes indicatifs (navire autorisé sur la carte)."]),
    ]
    return Theme("economique", "Économique", "Combien gagné, combien dépensé ?", kpis, cartes, [
        ("3.5.1", "Rentabilité annuelle par pêcheur",
         "Recettes, dépenses et bénéfice cumulés des campagnes d'un pêcheur, par année."),
        ("3.5.2", "Rentabilité par campagne",
         "Recette, dépense et bénéfice d'une sortie de pêche."),
        ("3.5.3", "Évolution des coûts",
         "Frais par nature, dans le temps, selon le carburant, le type de bateau et les jours en mer."),
    ], exclus=["3.5.4"])


def build_themes(d: SidData, ref: pd.Timestamp) -> list[Theme]:
    return [sociologique(d, ref), materiel(d, ref), environnemental(d, ref),
            activite(d, ref), economique(d, ref)]
