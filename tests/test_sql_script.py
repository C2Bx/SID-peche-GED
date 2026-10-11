import logging
import re
from pathlib import Path

import pytest

from src.database.sql_script import consume_result_sets

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_PAIRS = [
    "dwh/init_dwh.sql",
    "dtm/performance_campagnes/init.sql",
]


class ResultCursor:
    def __init__(self, result_sets: list[tuple[list[str], list[tuple]]]) -> None:
        self.result_sets = result_sets
        self.index = 0

    @property
    def description(self):
        columns, _rows = self.result_sets[self.index]
        return [(name,) for name in columns]

    def fetchall(self):
        return self.result_sets[self.index][1]

    def nextset(self):
        self.index += 1
        return self.index < len(self.result_sets)


def test_control_results_are_logged(caplog) -> None:
    cursor = ResultCursor(
        [
            (["personnes_en_double"], [(0,)]),
            (["frais_dtm", "frais_dwh"], [(10.0, 12.0)]),
        ]
    )
    with caplog.at_level(logging.INFO):
        consume_result_sets(cursor)
    assert "personnes_en_double=0" in caplog.text
    assert "frais_dtm=10.0, frais_dwh=12.0" in caplog.text


def _created_tables(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    names = re.findall(r"CREATE TABLE\s+([\w.]+)", text, flags=re.IGNORECASE)
    return {name.split(".")[-1].upper() for name in names}


@pytest.mark.parametrize("relative", SQL_PAIRS)
def test_postgresql_and_sqlserver_scripts_create_same_tables(relative: str) -> None:
    postgresql = _created_tables(PROJECT_ROOT / "sql/postgresql" / relative)
    sqlserver = _created_tables(PROJECT_ROOT / "sql/sqlserver" / relative)
    assert postgresql
    assert postgresql == sqlserver


@pytest.mark.parametrize("engine", ["postgresql", "sqlserver"])
def test_calendar_covers_every_accepted_fact_date(engine: str) -> None:
    # Une date de fait acceptée hors du calendrier produirait une clé
    # temps_key sans ligne correspondante dans DIM_TEMPS.
    text = (PROJECT_ROOT / "sql" / engine / "dwh/init_dwh.sql").read_text(
        encoding="utf-8"
    )
    last_day = re.search(r"'(\d{4})-12-31'", text)
    assert last_day is not None
    bounds = set(re.findall(r"BETWEEN 1990 AND (\d{4})", text))
    assert bounds == {last_day.group(1)}


def test_sqlserver_dtm_does_not_force_database() -> None:
    text = (
        PROJECT_ROOT / "sql/sqlserver/dtm/performance_campagnes/init.sql"
    ).read_text(encoding="utf-8")
    assert not re.search(r"^\s*USE\s", text, flags=re.IGNORECASE | re.MULTILINE)
