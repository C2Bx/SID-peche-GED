import pandas as pd
import pytest

from reporting import build_report, kpis
from reporting.data import COLUMNS, DtmData, demo_data, load_dtm


def _data() -> DtmData:
    campagnes = pd.DataFrame({
        "campagne_id": ["A", "B", "C"],
        "annee": [2023, 2023, 2024],
        "mois": [1, 2, 3],
        "capitaine_id": ["P1", None, "P2"],
        "capitaine_commune": ["Nouméa", "Nouméa", "Thio"],
        "duree_jours": [1, 2, 3],
        "jours_mer": [1.0, 2.0, 3.0],
        "jours_peche": [1.0, 2.0, 3.0],
        "nombre_captures": [1, 0, 2],
        "poids_capture_total": [10.0, None, 30.0],
        "valeur_captures_total": [100.0, None, 300.0],
        "campagne_benefice": [50.0, 10.0, 100.0],
        "campagne_depense": [50.0, 100.0, 200.0],
        "campagne_recette": [100.0, 100.0, 300.0],
        "campagne_rendement": [1.0, 2.0, 3.0],
    })
    captures = pd.DataFrame({
        "campagne_id": ["A", "C", "C"],
        "categorie_nom": ["Thons", "Thons", "Loches"],
        "annee": [2023, 2024, 2024],
        "nombre_captures": [1, 1, 1],
        "poids_capture": [10.0, 5.0, 25.0],
        "valeur_captures": [100.0, 50.0, 250.0],
    })
    frais = pd.DataFrame({
        "campagne_id": ["A", "C"],
        "nature_frais": ["Carburant", "Glace"],
        "montant": [30.0, 10.0],
        "annee": [2023, 2024],
    })
    return DtmData(campagnes, captures, frais)


def test_format_number_uses_french_separators() -> None:
    assert kpis.format_number(1234567.891, 2) == "1 234 567,89"
    assert kpis.format_number(float("nan")) == "–"
    assert kpis.format_compact(104_400_000) == "104,4 M"


def test_kpis_use_campaign_grain() -> None:
    values = {kpi.label: kpi for kpi in kpis.compute_kpis(_data())}
    assert values["Campagnes"].value == "3"
    assert values["Recette"].value == "500"
    assert values["Bénéfice"].value == "160"


def test_quality_flags_inconsistent_profit_and_missing_captain() -> None:
    checks = {check.label: check for check in kpis.compute_quality(_data())}
    # B : 100 - 100 = 0, bénéfice déclaré 10.
    assert checks["Bénéfice ≠ recette − dépense"].count == 1
    assert checks["Campagnes sans capitaine"].count == 1
    assert checks["Campagnes sans capture"].count == 1
    assert checks["Campagnes sans date de début"].ok


def test_aggregations() -> None:
    data = _data()
    finance = kpis.yearly_finance(data)
    assert finance.set_index("Année").loc[2023, "Recette"] == 200
    especes = kpis.top_especes(data)
    assert list(especes["Espèce"]) == ["Loches", "Thons"]
    frais = kpis.frais_par_nature(data)
    assert frais["Part (%)"].sum() == pytest.approx(100)


def test_filter_years_applies_to_all_tables() -> None:
    filtered = _data().filter_years([2024])
    assert list(filtered.campagnes["campagne_id"]) == ["C"]
    assert set(filtered.captures["campagne_id"]) == {"C"}
    assert list(filtered.frais["campagne_id"]) == ["C"]


def test_load_dtm_reads_the_three_tables() -> None:
    class Cursor:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement):
            self.statements.append(statement)
            self.table = statement.rsplit(".", 1)[1]

        def fetchall(self):
            return [tuple(range(len(COLUMNS[self.table])))]

    cursor = Cursor()
    connection = type("Connection", (), {"cursor": lambda self: cursor})()
    data = load_dtm(connection)
    assert len(data.campagnes) == len(data.captures) == len(data.frais) == 1
    assert all("dtm_performance_campagnes." in s for s in cursor.statements)


def test_render_report_contains_kpis_and_charts() -> None:
    html = build_report.render_report(_data(), source="test")
    assert html.startswith("<!doctype html>")
    assert "Performance des campagnes de pêche" in html
    for chart_id in ("chart-finance", "chart-saison", "chart-especes",
                     "chart-frais", "chart-communes"):
        assert f'id="{chart_id}"' in html
    assert "cdn.plot.ly" in html


def test_demo_build_writes_file(tmp_path) -> None:
    output = tmp_path / "index.html"
    assert build_report.run(["--demo", "--output", str(output)]) == 0
    assert output.stat().st_size > 10_000


def test_demo_data_matches_dtm_contract() -> None:
    data = demo_data(campagnes=20)
    for frame, table in ((data.campagnes, "DTM_PERFORMANCE_CAMPAGNE"),
                         (data.captures, "DTM_CAPTURE_CAMPAGNE"),
                         (data.frais, "DTM_FRAIS_CAMPAGNE")):
        assert list(frame.columns) == COLUMNS[table]
