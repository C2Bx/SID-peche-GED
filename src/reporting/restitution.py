"""Assemblage des 17 indicateurs de la fiche en thèmes affichables."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.reporting import charts
from src.reporting import indicateurs as ind
from src.reporting.data import SidData
from src.reporting.formatting import format_compact, format_date, format_number


@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    unit: str = ""
    detail: str = ""


@dataclass
class Indicateur:
    code: str
    titre: str
    definition: str
    kpis: list[Kpi] = field(default_factory=list)
    chart_html: str = ""
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
    indicateurs: list[Indicateur]
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


def _pct(part: float, total: float) -> str:
    return f"{format_number(100 * part / total, 1)} %" if total else "–"


# ---------------------------------------------------------------------------
# Thèmes
# ---------------------------------------------------------------------------

def sociologique(d: SidData, ref: pd.Timestamp) -> Theme:
    actifs = ind.pecheurs_actifs(d, ref)
    evolution = ind.evolution_pecheurs(d, ref)
    ages = ind.repartition_age(d, ref)
    genre = ind.repartition_genre(d, ref)
    communes = ind.repartition_commune(d, ref)
    patrons = ind.capitaines_patrons(d, ref)
    experience = ind.experience_moyenne(d, ref)
    sans_age = int(ages.loc[ages["Tranche d'âge"] == ind.NON_RENSEIGNE, "Pêcheurs"].iloc[0])

    return Theme("sociologique", "Sociologique", "Qui sont les pêcheurs ?", [
        Indicateur(
            "3.1.1", "Nombre de pêcheurs actifs",
            "Combien de pêcheurs ont une carte valable à la date choisie.",
            kpis=[Kpi("Pêcheurs actifs", format_number(actifs),
                      detail=f"au {format_date(ref)}")],
        ),
        Indicateur(
            "3.1.2", "Évolution du nombre de pêcheurs",
            "Évolution annuelle des pêcheurs actifs, avec leur âge moyen et leur "
            "répartition par âge, genre et commune.",
            kpis=[Kpi("Âge moyen", format_number(ind.age_moyen(d, ref), 1), "ans",
                      detail=f"{sans_age} pêcheur(s) sans date de naissance exclu(s)")],
            chart_html=charts.to_html(charts.lines(
                evolution["Année"], {"Pêcheurs actifs": evolution["Pêcheurs actifs"]}),
                "c-312-evolution"),
            table_html=_table(evolution, {"Âge moyen": 1}),
            notes=["Années passées : situation au 31 décembre ; année en cours : à la date de référence."],
            wide=True,
        ),
        Indicateur(
            "3.1.2", "Répartition par tranche d'âge",
            "Pêcheurs actifs à la date de référence, par tranche d'âge.",
            chart_html=charts.to_html(charts.bars(ages["Tranche d'âge"], ages["Pêcheurs"]),
                                      "c-312-ages"),
            table_html=_table(ages),
            notes=["Tranches proposées par la fiche, à valider."],
        ),
        Indicateur(
            "3.1.2", "Répartition par genre et par commune",
            "Pêcheurs actifs par genre, et par commune de la carte.",
            kpis=[Kpi(row["Genre"], format_number(row["Pêcheurs"]),
                      detail=_pct(row["Pêcheurs"], actifs)) for _, row in genre.iterrows()],
            chart_html=charts.to_html(charts.bars(communes["Commune"], communes["Pêcheurs"],
                                                  horizontal=True), "c-312-communes"),
            table_html=_table(communes),
            notes=["Un pêcheur titulaire de cartes dans deux communes compte dans chacune."],
        ),
        Indicateur(
            "3.1.3", "Expérience cumulée",
            "Nombre moyen d'années d'activité des pêcheurs actifs : une année compte "
            "si le pêcheur a au moins une carte active cette année-là.",
            kpis=[Kpi("Expérience moyenne", format_number(experience, 1), "ans")],
            notes=["Règle V1 de la fiche, à valider."],
        ),
        Indicateur(
            "3.1.4", "Capitaines et patrons",
            "Parmi les capitaines actifs, combien sont leur propre patron et combien "
            "ont un patron différent.",
            kpis=[Kpi(row["Situation"], format_number(row["Capitaines"]),
                      detail=_pct(row["Capitaines"], actifs)) for _, row in patrons.iterrows()],
            notes=["Avant 2021, le patron est souvent vide : catégorie « non renseigné »."],
        ),
    ])


def materiel(d: SidData, ref: pd.Timestamp) -> Theme:
    age = ind.age_flotte(d, ref)
    ages = ind.ages_navires(d, ref)
    moto = ind.motorisation(d)
    return Theme("materiel", "Matériel", "Quelle est la flotte ?", [
        Indicateur(
            "3.2.1", "Nombre de navires recensés",
            "Navires connus au dernier chargement ; la source n'indique pas s'ils "
            "sont encore actifs, tous comptent.",
            kpis=[Kpi("Navires", format_number(ind.nb_navires(d)))],
        ),
        Indicateur(
            "3.2.2", "Âge de la flotte",
            "Âge moyen des navires : année de référence moins année de construction.",
            kpis=[Kpi("Âge moyen", format_number(age["age_moyen"], 1), "ans",
                      detail=f"{age['retenus']} navires retenus")],
            chart_html=charts.to_html(charts.bars(ages["Âge"], ages["Navires"]), "c-322"),
            table_html=_table(ages),
            notes=[f"Exclus : {age['sans_annee']} sans année de construction, "
                   f"{age['ecartes']} avec une année antérieure à "
                   f"{ind.SEUIL_ANNEE_CONSTRUCTION} ou postérieure à l'année de référence "
                   "(seuil à valider)."],
        ),
        Indicateur(
            "3.2.4", "Répartition par type de motorisation",
            "Navires à un moteur, à plusieurs moteurs, ou sans information moteur.",
            kpis=[Kpi(row["Motorisation"], format_number(row["Navires"]))
                  for _, row in moto.iterrows()],
            notes=[f"Navires avec au moins un moteur dans DIM_MOTEUR : "
                   f"{format_number(ind.navires_avec_moteur(d))}."],
        ),
    ], exclus=["3.2.3", "3.2.5"])


def environnemental(d: SidData, ref: pd.Timestamp) -> Theme:
    mois = ind.captures_par_mois(d)
    especes = ind.captures_par_espece(d)
    produits = ind.captures_par_espece(d, "produit").head(10)
    zones = ind.poids_par_zone(d)
    total_poids = d.captures["capture_poids_entier_total"].sum()
    return Theme("environnemental", "Environnemental", "Qu'est-ce qui est pêché ?", [
        Indicateur(
            "3.3.1", "Évolution de l'activité de capture",
            "Nombre de captures, poids et quantité pêchés, mois par mois.",
            kpis=[Kpi("Captures", format_number(d.captures["capture_id"].nunique())),
                  Kpi("Poids capturé", format_compact(total_poids)),
                  Kpi("Quantité", format_compact(d.captures["capture_nombre"].sum()),
                      detail="souvent à 0, mesure complémentaire")],
            chart_html=charts.to_html(charts.lines(mois["Mois"], {"Poids": mois["Poids"]},
                                                   x_is_month=True), "c-331"),
            table_html=_table(mois),
            notes=["La date d'une capture est la date de début de sa campagne.",
                   f"{ind.captures_sans_date(d)} capture(s) sans date, absentes du graphique."],
            wide=True,
        ),
        Indicateur(
            "3.3.2", "Répartition des captures par espèce",
            "Part du poids, du nombre de captures et de la valeur par catégorie d'espèce, "
            "puis par produit.",
            chart_html=charts.to_html(charts.bars(especes["Espèce"].head(10),
                                                  especes["Part du poids (%)"].head(10),
                                                  horizontal=True, unit="%", decimals=1),
                                      "c-332"),
            table_html=_table(especes) + "<h4>10 premiers produits</h4>" + _table(produits),
            notes=["Valeur en XPF sous réserve de validation de sa cohérence."],
        ),
        Indicateur(
            "3.3.3", "Répartition géographique des captures",
            "Poids pêché par zone ; une capture sur plusieurs zones voit son poids "
            "réparti (facteur = 1 ÷ nombre de zones).",
            kpis=[Kpi("Captures localisées",
                      f"{format_number(ind.part_captures_avec_zone(d), 1)} %",
                      detail="des captures ont au moins une zone")],
            chart_html=charts.to_html(charts.bars(zones["Zone"].head(15), zones["Poids"].head(15),
                                                  horizontal=True), "c-333"),
            table_html=_table(zones),
            notes=["Histogramme par zone : le DWH ne contient aucun contour géographique.",
                   "« Captures touchant la zone » ne s'additionne pas d'une zone à l'autre."],
        ),
    ])


def activite(d: SidData, ref: pd.Timestamp) -> Theme:
    mois = ind.campagnes_par_mois(d)
    duree = ind.duree_campagnes(d)
    durees = ind.repartition_durees(d)
    par_campagne = ind.captures_par_campagne(d)
    especes = ind.captures_par_campagne_espece(d)
    actives = ind.campagnes_actives(d, ref)
    sans_fin = ind.campagnes_sans_fin_ouvertes(d, ref)
    return Theme("activite", "Activité", "Quelles sorties en mer ?", [
        Indicateur(
            "3.4.1", "Évolution du nombre de campagnes",
            "Nombre de sorties de pêche par mois de début.",
            kpis=[Kpi("Campagnes", format_number(d.campagnes["campagne_id"].nunique()))],
            chart_html=charts.to_html(charts.lines(mois["Mois"], {"Campagnes": mois["Campagnes"]},
                                                   x_is_month=True), "c-341"),
            table_html=_table(mois),
            wide=True,
        ),
        Indicateur(
            "3.4.2", "Durée d'une campagne",
            "Nombre moyen de jours entre la date de début et la date de fin.",
            kpis=[Kpi("Durée moyenne", format_number(duree["duree_moyenne"], 1), "jours")],
            chart_html=charts.to_html(charts.bars(durees["Durée"], durees["Campagnes"]), "c-342"),
            table_html=_table(durees),
            notes=[f"Anomalies signalées, non corrigées : {duree['date_manquante']} campagne(s) "
                   f"avec une date manquante, {duree['fin_avant_debut']} avec une fin "
                   "antérieure au début (durée laissée vide)."],
        ),
        Indicateur(
            "3.4.3", "Nombre et poids des captures par campagne",
            "Ce que rapporte une sortie : captures et poids, par espèce et dans le temps.",
            chart_html=charts.to_html(charts.lines(
                par_campagne["Année"], {"Poids par campagne": par_campagne["Poids par campagne"]}),
                "c-343"),
            table_html=_table(par_campagne, {"Captures par campagne": 2, "Poids par campagne": 1})
            + "<h4>Par espèce (10 premières en poids)</h4>" + _table(especes),
        ),
        Indicateur(
            "3.4.4", "Campagnes actives à une date",
            "Sorties en cours à la date choisie : début au plus tard ce jour-là, fin au plus tôt.",
            kpis=[Kpi("Campagnes actives", format_number(len(actives)),
                      detail=f"au {format_date(ref)}")],
            table_html=_table(
                actives.rename(columns={
                    "Campagne": "Identifiant de campagne",
                    "Début": "Date de début",
                    "Fin": "Date de fin",
                    "Durée (j)": "Durée",
                }),
                date_format="%d/%m/%Y",
            ),
            notes=[f"{sans_fin} campagne(s) commencée(s) sans date de fin : exclues, à vérifier."],
            csv_export=True,
            table_visible=True,
        ),
    ])


def economique(d: SidData, ref: pd.Timestamp) -> Theme:
    finances = ind.finances_par_annee(d)
    pecheurs = ind.rentabilite_par_pecheur(d)
    synthese = ind.synthese_par_pecheur(d)
    campagne = ind.rentabilite_par_campagne(d)
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
    return Theme("economique", "Économique", "Combien gagné, combien dépensé ?", [
        Indicateur(
            "3.5.1", "Rentabilité annuelle par pêcheur",
            "Recettes, dépenses et bénéfice cumulés de toutes les campagnes d'un "
            "pêcheur, par année.",
            chart_html=charts.to_html(charts.box_by_year(pecheurs, "Année", "Bénéfice",
                                                         unit="XPF"), "c-351"),
            table_html=_table(finances) + "<h4>Bénéfice annuel par pêcheur</h4>"
            + _table(synthese),
            notes=["Distribution du bénéfice annuel par pêcheur (boîte : quartiles, "
                   "trait : médiane) ; aucun pêcheur n'est affiché individuellement.",
                   "Taux de rentabilité non affiché tant que le métier n'a pas défini sa formule."],
            wide=True,
        ),
        Indicateur(
            "3.5.2", "Rentabilité par campagne",
            "Recette, dépense et bénéfice d'une sortie de pêche.",
            kpis=[Kpi("Recette moyenne", format_compact(campagne["recette_moyenne"]), "XPF"),
                  Kpi("Dépense moyenne", format_compact(campagne["depense_moyenne"]), "XPF"),
                  Kpi("Bénéfice moyen", format_compact(campagne["benefice_moyen"]), "XPF",
                      detail=f"médiane {format_compact(campagne['benefice_median'])} XPF"),
                  Kpi("Campagnes déficitaires", f"{format_number(campagne['deficitaires_pct'], 1)} %")],
            notes=[f"{campagne['ecarts']} campagne(s) où bénéfice ≠ recette − dépense : "
                   "valeur source conservée, écart signalé."],
        ),
        Indicateur(
            "3.5.3", "Évolution des coûts",
            "Montant des frais par nature, dans le temps, selon le carburant, le type "
            "de bateau et les jours en mer.",
            kpis=[Kpi("Frais moyens par campagne",
                      format_compact(ind.montant_moyen_par_campagne(d)), "XPF")],
            chart_html=charts.to_html(charts.lines(par_annee["Année"], series, unit="XPF"),
                                      "c-353"),
            table_html=_table(natures)
            + "<h4>Montant moyen par campagne selon le carburant du moteur principal</h4>"
            + _table(carburant)
            + "<h4>… selon le type de bateau</h4>" + _table(bateau)
            + "<h4>… selon les jours en mer</h4>" + _table(jours),
            notes=["La somme des frais n'égale pas la dépense : les salaires n'y figurent pas.",
                   "Carburant et type de bateau : axes indicatifs (navire autorisé sur la carte)."],
            wide=True,
        ),
    ], exclus=["3.5.4"])


def build_themes(d: SidData, ref: pd.Timestamp) -> list[Theme]:
    return [sociologique(d, ref), materiel(d, ref), environnemental(d, ref),
            activite(d, ref), economique(d, ref)]
