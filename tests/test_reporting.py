import re
from datetime import date

import pandas as pd
import pytest

from src.reporting import build_report
from src.reporting import indicateurs as ind
from src.reporting.data import QUERIES, SidData, demo_data, fingerprint, load
from src.reporting.formatting import format_compact, format_number

REF = pd.Timestamp(2026, 6, 30)
CODES = ["3.1.1", "3.1.2", "3.1.3", "3.1.4", "3.2.1", "3.2.2", "3.2.4", "3.3.1",
         "3.3.2", "3.3.3", "3.4.1", "3.4.2", "3.4.3", "3.4.4", "3.5.1", "3.5.2", "3.5.3"]


def _d(value):
    return pd.Timestamp(value) if value else pd.NaT


def _data() -> SidData:
    carte = ["carte_id", "capitaine_key", "patron_key", "carte_annee",
             "carte_autorisation_statut", "date_delivrance", "commune"]
    cartes = pd.DataFrame([
        ("K1", 1, 1, "2026", None, _d("2026-01-10"), "Nouméa"),     # active, propre patron
        ("K2", 1, 9, "2026", None, _d("2026-02-01"), "Thio"),       # même pêcheur, autre patron
        ("K3", 2, 2, "2026", "Vente", _d("2026-01-01"), "Thio"),    # statut renseigné
        ("K4", 3, 3, "2026", None, _d("2026-08-01"), "Thio"),       # délivrée après la date
        ("K5", 4, 4, "2025", None, _d("2025-01-01"), "Thio"),       # autre année
        ("K6", -1, -1, "2026", None, _d("2026-01-01"), "Thio"),     # capitaine inconnu
        ("K7", 5, 5, "2026", None, pd.NaT, "Thio"),                 # sans date
        ("K8", 6, -1, "2026", None, _d("2026-03-01"), None),        # active, patron inconnu
        ("K9", 1, 1, "2024", None, _d("2024-01-01"), "Nouméa"),     # expérience : compte
        ("K10", 1, 1, "2023", "Vente", _d("2023-01-01"), "Nouméa"),  # expérience : statut
        ("K11", 1, 1, "2027", None, _d("2027-01-01"), "Nouméa"),    # expérience : futur
    ], columns=carte)
    personnes = pd.DataFrame({
        "personne_key": [-1, 1, 6],
        "date_naissance": [pd.NaT, _d("1980-12-31"), pd.NaT],
        "sexe": ["Inconnu", "Masculin", "Inconnu"],
    })
    navires = pd.DataFrame({
        "navire_key": [-1, 1, 2, 3, 4],
        "navire_id": [None, "N1", "N2", "N3", "N4"],
        "annee_construction": pd.array([None, 2000, 1900, None, 2030], dtype="Int64"),
        "nb_moteurs": [0, 1, 2, 0, 1],
    })
    moteurs = pd.DataFrame({"moteur_key": [1, 2, 3, 4, 5], "navire_key": [1, 2, 2, 4, -1]})
    captures = pd.DataFrame({
        "capture_id": ["A", "B", "C"],
        "date_id": [_d("2026-01-05"), _d("2026-02-10"), pd.NaT],
        "categorie_nom": ["Thons", "Loches", None],
        "produit": ["Thon entier", "Loche", None],
        "capture_nombre": [0.0, 2.0, 0.0],
        "capture_poids_entier_total": [10.0, 30.0, 60.0],
        "capture_valeurxpf": [100.0, 300.0, 600.0],
    })
    zones = pd.DataFrame({"capture_id": ["A", "A", "B"], "facteur": [0.5, 0.5, 1.0],
                          "label": ["Z1", "Z2", "Z1"]})
    campagnes = pd.DataFrame([
        ("C1", 2026, 6, _d("2026-06-28"), _d("2026-07-02"), "P1", 4, 5.0, 4.0, 100.0, 60.0, 40.0),
        ("C2", 2026, 6, _d("2026-06-30"), _d("2026-06-30"), "P1", 0, 1.0, 1.0, 50.0, 70.0, -20.0),
        ("C3", 2026, 6, _d("2026-06-01"), _d("2026-06-29"), "P2", 28, 3.0, 2.0, 80.0, 30.0, 50.0),
        ("C4", 2026, 6, _d("2026-06-15"), pd.NaT, "P2", None, 2.0, 2.0, None, None, None),
        ("C5", 2025, 6, _d("2025-06-10"), _d("2025-06-05"), None, None, 1.0, 1.0, 10.0, 5.0, 5.0),
    ], columns=["campagne_id", "annee", "mois", "date_debut", "date_fin", "capitaine_id",
                "duree_jours", "jours_mer", "jours_peche", "campagne_recette",
                "campagne_depense", "campagne_benefice"])
    captures_campagne = pd.DataFrame({
        "campagne_id": ["C1", "C1", "C2"], "categorie_nom": ["Thons", "Loches", "Thons"],
        "annee": [2026, 2026, 2026], "nombre_captures": [1, 2, 1],
        "poids_capture": [10.0, 20.0, 5.0],
    })
    frais = pd.DataFrame({
        "campagne_id": ["C1", "C1", "C2"], "nature_frais": ["Carburant", "Glace", "Carburant"],
        "montant": [30.0, 10.0, 20.0], "annee": [2026, 2026, 2026], "mois": [6, 6, 6],
        "jours_mer": [5.0, 5.0, 1.0],
        "navire_categorie_navigation": ["Côtière", "Côtière", None],
        "carburant_moteur_principal": ["Essence", "Essence", "Gazole"],
    })
    return SidData(cartes, personnes, navires, moteurs, captures, zones, campagnes,
                   captures_campagne, frais)


# --- 3.1 -------------------------------------------------------------------

def test_pecheurs_actifs_applies_every_rule_of_the_base_measure() -> None:
    assert set(ind.cartes_actives(_data().cartes, REF)["carte_id"]) == {"K1", "K2", "K8"}
    assert ind.pecheurs_actifs(_data(), REF) == 2


def test_age_uses_dax_datediff_year_semantics() -> None:
    # Né le 31/12/1980 : 45 ans révolus au 30/06/2026, mais DATEDIFF YEAR donne 46.
    assert ind.age_moyen(_data(), REF) == 46
    ages = ind.repartition_age(_data(), REF).set_index("Tranche d'âge")["Pêcheurs"]
    assert ages["45 à 59 ans"] == 1 and ages[ind.NON_RENSEIGNE] == 1


def test_genre_and_commune_breakdowns() -> None:
    genre = ind.repartition_genre(_data(), REF).set_index("Genre")["Pêcheurs"]
    assert genre.to_dict() == {"Masculin": 1, ind.NON_RENSEIGNE: 1}
    communes = ind.repartition_commune(_data(), REF).set_index("Commune")["Pêcheurs"]
    # Le pêcheur 1 a une carte à Nouméa et une à Thio : il compte dans les deux.
    assert communes.to_dict() == {"Nouméa": 1, "Thio": 1, "Non renseignée": 1}


def test_experience_counts_distinct_valid_years_up_to_reference() -> None:
    # Pêcheur 1 : 2024 et 2026 (2023 a un statut, 2027 est future) ; pêcheur 6 : 2026.
    assert ind.experience_moyenne(_data(), REF) == pytest.approx(1.5)


def test_capitaines_patrons_three_categories() -> None:
    out = ind.capitaines_patrons(_data(), REF).set_index("Situation")["Capitaines"]
    assert out.to_dict() == {"Capitaine = patron": 1, "Patron différent": 1,
                             "Patron non renseigné": 1}


def test_evolution_uses_end_of_year_for_past_years() -> None:
    evo = ind.evolution_pecheurs(_data(), REF).set_index("Année")["Pêcheurs actifs"]
    assert evo[2025] == 1 and evo[2026] == 2 and 2027 not in evo


# --- 3.2 -------------------------------------------------------------------

def test_fleet_indicators() -> None:
    d = _data()
    assert ind.nb_navires(d) == 4
    age = ind.age_flotte(d, REF)
    assert age == {"age_moyen": 26.0, "retenus": 1, "sans_annee": 1, "ecartes": 2}
    moto = ind.motorisation(d).set_index("Motorisation")["Navires"]
    assert moto.to_dict() == {"Un moteur": 2, "Deux moteurs ou plus": 1,
                              "Motorisation non renseignée": 1}
    assert ind.navires_avec_moteur(d) == 3


# --- 3.3 -------------------------------------------------------------------

def test_capture_activity_and_species_share() -> None:
    d = _data()
    mois = ind.captures_par_mois(d)
    assert mois["Captures"].sum() == 2 and ind.captures_sans_date(d) == 1
    especes = ind.captures_par_espece(d).set_index("Espèce")
    assert especes.loc["Inconnue", "Part du poids (%)"] == pytest.approx(60)
    assert especes["Part du poids (%)"].sum() == pytest.approx(100)


def test_zone_weight_is_split_by_factor() -> None:
    zones = ind.poids_par_zone(_data()).set_index("Zone")
    assert zones.loc["Z1", "Poids"] == pytest.approx(35)   # 10 × 0,5 + 30 × 1
    assert zones.loc["Z2", "Poids"] == pytest.approx(5)
    assert zones.loc["Z1", "Captures touchant la zone"] == 2


# --- 3.4 -------------------------------------------------------------------

def test_active_campaigns_include_bounds_and_report_missing_end() -> None:
    d = _data()
    assert list(ind.campagnes_actives(d, REF)["Campagne"]) == ["C1", "C2"]
    assert ind.campagnes_sans_fin_ouvertes(d, REF) == 1


def test_duration_anomalies_are_counted_not_fixed() -> None:
    duree = ind.duree_campagnes(_data())
    assert duree["duree_moyenne"] == pytest.approx((4 + 0 + 28) / 3)
    assert duree["date_manquante"] == 1 and duree["fin_avant_debut"] == 1


def test_captures_per_campaign() -> None:
    out = ind.captures_par_campagne(_data()).set_index("Année")
    assert out.loc[2026, "Poids par campagne"] == pytest.approx(35 / 4)


# --- 3.5 -------------------------------------------------------------------

def test_profitability_uses_source_amounts_and_flags_gaps() -> None:
    d = _data()
    par_pecheur = ind.rentabilite_par_pecheur(d).set_index(["Année", "Capitaine"])
    assert par_pecheur.loc[(2026, "P1"), "Bénéfice"] == 20
    resume = ind.rentabilite_par_campagne(d)
    # C5 : 10 − 5 = 5 = bénéfice ; C2 : 50 − 70 = −20 = bénéfice ; aucun écart.
    assert resume["ecarts"] == 0
    d.campagnes.loc[0, "campagne_benefice"] = 99
    assert ind.rentabilite_par_campagne(d)["ecarts"] == 1


def test_costs() -> None:
    d = _data()
    natures = ind.frais_par_nature(d).set_index("Nature")
    assert natures.loc["Carburant", "Montant (XPF)"] == 50
    assert ind.montant_moyen_par_campagne(d) == pytest.approx(30)
    carburant = ind.montant_moyen_par_campagne(d, "carburant_moteur_principal")
    assert carburant.set_index("carburant_moteur_principal")["Montant moyen par campagne"].to_dict() \
        == {"Essence": 40, "Gazole": 20}


# --- Lecture, rendu --------------------------------------------------------

class FakeCursor:
    def __init__(self, tables):
        self.tables = tables

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement):
        self.statement = statement

    @property
    def description(self):
        return [(c,) for c in self._frame().columns]

    def _frame(self):
        for name, frame in self.tables.items():
            if QUERIES[name] == self.statement:
                return frame
        raise AssertionError(self.statement)

    def fetchall(self):
        return list(self._frame().itertuples(index=False, name=None))

    def fetchone(self):
        return (3,)


class FakeConnection:
    def __init__(self, tables):
        self.fake = FakeCursor(tables)
        self.commits = 0

    def cursor(self):
        return self.fake

    def commit(self):
        self.commits += 1


def test_load_reads_every_query_and_normalizes_dates() -> None:
    d = _data()
    connection = FakeConnection({name: getattr(d, name) for name in QUERIES})
    loaded = load(connection)
    assert ind.pecheurs_actifs(loaded, REF) == 2
    assert pd.api.types.is_datetime64_any_dtype(loaded.campagnes["date_debut"])


def test_fingerprint_changes_with_counts() -> None:
    connection = FakeConnection({})
    first = fingerprint(connection)
    connection.fake.fetchone = lambda: (4,)
    assert fingerprint(connection) != first
    assert connection.commits == 2


def test_report_contains_all_indicators_and_browser_csv_export(tmp_path) -> None:
    output = tmp_path / "index.html"
    assert build_report.run(["--demo", "--date-ref", "2026-10-12",
                             "--output", str(output)]) == 0
    html = output.read_text(encoding="utf-8")
    for code in CODES:
        assert f'<span class="code">{code}</span>' in html
    # Seul le détail demandé par le 3.4.4 est affiché ; aucune capture brute.
    assert not re.search(r"CAP-\d", html)
    assert "Exclus par le SFD : 3.2.3, 3.2.5" in html and "3.5.4" in html
    assert "Identifiant de campagne" in html
    assert "Capitaine" in html
    assert "Date de début" in html and "Date de fin" in html
    assert "Durée" in html and "Jours en mer" in html and "Jours de pêche" in html
    assert 'data-csv-filename="campagnes_actives_2026-10-12.csv"' in html
    assert "Exporter en CSV" in html
    assert 'join(";")' in html and "text/csv;charset=utf-8" in html
    assert list(tmp_path.iterdir()) == [output]
    assert not list(tmp_path.glob("*.csv"))


def test_watch_is_incompatible_with_demo() -> None:
    with pytest.raises(SystemExit):
        build_report.parse_args(["--demo", "--watch"])


def test_demo_is_deterministic_and_dated() -> None:
    a, b = demo_data(today=date(2026, 10, 12)), demo_data(today=date(2026, 10, 12))
    assert a.campagnes.equals(b.campagnes)
    assert a.campagnes["date_debut"].max() <= pd.Timestamp(2026, 10, 12)


def test_formatting() -> None:
    assert format_number(1234567.891, 2) == "1 234 567,89"
    assert format_number(float("nan")) == "–"
    assert format_compact(104_400_000) == "104,4 M"


def test_watch_regenerates_only_when_the_database_changes(monkeypatch, tmp_path) -> None:
    import contextlib
    import types

    import src.config
    import src.database.connection

    d = _data()
    connection = FakeConnection({name: getattr(d, name) for name in QUERIES})
    counts = iter([(1,)] * 9 + [(1,)] * 9 + [(2,)] * 9)  # 3 passages, 9 tables chacun
    connection.fake.fetchone = lambda: next(counts)
    monkeypatch.setattr(src.config, "load_settings",
                        lambda **_: types.SimpleNamespace(db_engine="postgresql"))
    monkeypatch.setattr(src.database.connection, "connect",
                        lambda _settings: contextlib.nullcontext(connection))
    writes = []
    monkeypatch.setattr(build_report, "write_report",
                        lambda *a, **k: writes.append(k["refresh_seconds"]))
    ticks = iter([None, None, KeyboardInterrupt])

    def fake_sleep(_seconds):
        tick = next(ticks)
        if tick:
            raise tick()

    monkeypatch.setattr(build_report.time, "sleep", fake_sleep)
    args = build_report.parse_args(["--watch", "5", "--output", str(tmp_path / "i.html")])
    assert build_report.watch(args) == 0
    # 1er passage : génération ; 2e : base inchangée ; 3e : une ligne ajoutée.
    assert writes == [5, 5]


# --- Bandeaux de KPI ---------------------------------------------------------

def test_kpi_band_complements() -> None:
    d = _data()
    assert ind.part_femmes(d, REF) == 0
    # Pêcheur 1 : première carte valide en 2024 ; pêcheur 6 : en 2026.
    assert ind.nouveaux_pecheurs(d, REF) == 1
    exp = ind.repartition_experience(d, REF).set_index("Expérience")["Pêcheurs"]
    assert exp["1 an"] == 1 and exp["2 ans"] == 1


def test_period_comparison_uses_same_period_last_year() -> None:
    d = _data()
    assert ind.periode(REF) == (pd.Timestamp(2026, 1, 1), REF)
    s, s1 = ind.stats_campagnes(d, REF), ind.stats_campagnes(d, REF, 1)
    assert s["campagnes"] == 4 and s1["campagnes"] == 1
    assert s["recette"] == 230
    assert ind.variation(s["campagnes"], s1["campagnes"]) == 300
    assert pd.isna(ind.variation(5, 0))


def test_profit_bands_per_campaign() -> None:
    bands = ind.repartition_benefice_campagne(_data()).set_index("Bénéfice (XPF)")["Campagnes"]
    assert bands["Perte ≤ 50 k"] == 1 and bands["0 à 50 k"] == 3 and bands.sum() == 4


def test_page_opens_in_day_mode_with_toggle(tmp_path) -> None:
    output = tmp_path / "index.html"
    build_report.run(["--demo", "--date-ref", "2026-10-12", "--output", str(output)])
    html = output.read_text(encoding="utf-8")
    assert '<html lang="fr" data-theme="light">' in html
    assert "prefers-color-scheme" not in html  # le système ne force pas le mode nuit
    assert 'data-set-theme="dark"' in html and 'data-set-theme="light"' in html
