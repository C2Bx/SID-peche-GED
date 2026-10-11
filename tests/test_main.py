import sys
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from main import parse_args
from src.config import TABLES
from src.extraction.peche_extractor import ExtractionResult


def test_from_json_option_has_french_and_english_names(monkeypatch) -> None:
    """Vérifie les deux alias de l'option de chargement JSON local."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--depuis-json"])
    assert parse_args().depuis_json is True

    monkeypatch.setattr(sys, "argv", ["main.py", "--from-json"])
    assert parse_args().depuis_json is True


@pytest.mark.parametrize(
    "options",
    [
        ["--ods-only", "--dwh-only"],
        ["--ods-only", "--dtm-only"],
        ["--dwh-only", "--dtm-only"],
    ],
)
def test_pipeline_only_modes_are_mutually_exclusive(options: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(options)


def test_dwh_only_and_from_json_are_incompatible() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--dwh-only", "--depuis-json"])


def test_dtm_only_and_from_json_are_incompatible() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--dtm-only", "--depuis-json"])


def test_dtm_only_option_is_parsed() -> None:
    assert parse_args(["--dtm-only"]).dtm_only is True


def test_positional_table_is_no_longer_accepted() -> None:
    with pytest.raises(SystemExit):
        parse_args(["capture_peche"])


def _mock_pipeline(monkeypatch):
    events: list[str] = []
    settings = SimpleNamespace(db_engine="postgresql")
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(main, "load_settings", Mock(return_value=settings))
    monkeypatch.setattr(main, "connect", Mock(return_value=connection))
    monkeypatch.setattr(main, "check_connection", Mock())
    monkeypatch.setattr(main, "ensure_env_mer_exists", Mock())
    run_ods = Mock(side_effect=lambda *_args: (events.append("ods") or ([], [])))
    monkeypatch.setattr(main, "run_ods", run_ods)
    monkeypatch.setattr(
        main, "run_dwh", Mock(side_effect=lambda *_args: events.append("dwh"))
    )
    monkeypatch.setattr(
        main, "run_dtms", Mock(side_effect=lambda *_args: events.append("dtm"))
    )
    monkeypatch.setattr(main, "print_summary", Mock())
    return events


def test_dwh_only_skips_ods_and_does_not_require_api_key(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    assert main.run(["--dwh-only"]) == 0
    assert events == ["dwh", "dtm"]
    main.load_settings.assert_called_once_with(require_api_key=False)


def test_dtm_only_skips_ods_and_dwh_and_does_not_require_api_key(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    assert main.run(["--dtm-only"]) == 0
    assert events == ["dtm"]
    main.run_dwh.assert_not_called()
    main.run_ods.assert_not_called()
    main.load_settings.assert_called_once_with(require_api_key=False)


def test_ods_only_skips_dwh(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    assert main.run(["--ods-only"]) == 0
    assert events == ["ods"]
    main.run_dtms.assert_not_called()


def test_default_mode_runs_ods_then_dwh_then_dtms(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    assert main.run([]) == 0
    assert events == ["ods", "dwh", "dtm"]


def test_from_json_runs_ods_then_dwh_then_dtms(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    assert main.run(["--depuis-json"]) == 0
    assert events == ["ods", "dwh", "dtm"]
    assert main.run_ods.call_args.args[1].depuis_json is True


def test_from_json_with_ods_only_skips_dwh(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    assert main.run(["--depuis-json", "--ods-only"]) == 0
    assert events == ["ods"]
    main.run_dtms.assert_not_called()


def test_run_ods_always_rebuilds_all_tables(monkeypatch, tmp_path) -> None:
    for table_name in TABLES:
        (tmp_path / f"{table_name}.json").write_text("[]", encoding="utf-8")
    settings = SimpleNamespace(
        raw_data_dir=tmp_path,
        db_engine="postgresql",
        api_key="",
        http_timeout=30,
    )
    args = Namespace(depuis_json=True, ods_only=False, dwh_only=False)
    reset_tables = Mock()
    monkeypatch.setattr(main, "check_connection", Mock())
    monkeypatch.setattr(main, "reset_tables", reset_tables)
    monkeypatch.setattr(
        main,
        "import_table",
        Mock(
            side_effect=lambda _connection, table_name, *_args: ExtractionResult(
                table_name, 0, 0, 0
            )
        ),
    )
    monkeypatch.setattr(main, "find_json_columns", Mock(return_value=[]))
    monkeypatch.setattr(main, "relation_statistics", Mock(return_value=[]))

    downloads, results = main.run_ods(settings, args, Mock())

    reset_tables.assert_called_once_with(reset_tables.call_args.args[0], list(TABLES))
    assert [result.table for result in downloads] == TABLES
    assert [result.table for result in results] == TABLES


def test_ods_failure_prevents_dwh(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    main.run_ods.side_effect = RuntimeError("ODS en erreur")
    assert main.run([]) == 1
    assert events == []
    main.run_dwh.assert_not_called()
    main.run_dtms.assert_not_called()


def test_dwh_failure_prevents_dtms(monkeypatch) -> None:
    events = _mock_pipeline(monkeypatch)
    main.run_dwh.side_effect = RuntimeError("DWH en erreur")
    assert main.run([]) == 1
    assert events == ["ods"]
    main.run_dtms.assert_not_called()
