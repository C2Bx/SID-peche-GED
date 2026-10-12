from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from main import parse_args
from src.config import TABLES
from src.extraction.peche_extractor import ExtractionResult


@pytest.mark.parametrize(
    "options",
    [
        ["--from-json", "--from-ods"],
        ["--from-json", "--from-dwh"],
        ["--from-json", "--from-dtm"],
        ["--from-ods", "--from-dwh"],
        ["--from-ods", "--from-dtm"],
        ["--from-dwh", "--from-dtm"],
    ],
)
def test_pipeline_starting_points_are_mutually_exclusive(options: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(options)


def test_from_dtm_and_no_report_are_incompatible(capsys) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--from-dtm", "--no-report"])
    assert "aucune étape ne resterait à exécuter" in capsys.readouterr().err


@pytest.mark.parametrize("legacy_option", [
    "--sans-rapport", "--ods-only", "--dwh-only", "--dtm-only", "--depuis-json",
])
def test_legacy_options_are_rejected(legacy_option: str) -> None:
    with pytest.raises(SystemExit):
        parse_args([legacy_option])


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
    def fake_ods(_settings, args, _connection):
        events.append("ods_json" if args.from_json else "ods")
        return [], []

    run_ods = Mock(side_effect=fake_ods)
    monkeypatch.setattr(main, "run_ods", run_ods)
    monkeypatch.setattr(
        main, "run_dwh", Mock(side_effect=lambda *_args: events.append("dwh"))
    )
    monkeypatch.setattr(
        main, "run_dtms", Mock(side_effect=lambda *_args: events.append("dtm"))
    )
    monkeypatch.setattr(
        main,
        "run_report",
        Mock(side_effect=lambda _c, _s, args: None if args.no_report else events.append("rapport")),
    )
    monkeypatch.setattr(main, "print_summary", Mock())
    return events


@pytest.mark.parametrize(("options", "expected"), [
    ([], ["ods", "dwh", "dtm", "rapport"]),
    (["--from-json"], ["ods_json", "dwh", "dtm", "rapport"]),
    (["--from-ods"], ["dwh", "dtm", "rapport"]),
    (["--from-dwh"], ["dtm", "rapport"]),
    (["--from-dtm"], ["rapport"]),
    (["--no-report"], ["ods", "dwh", "dtm"]),
    (["--from-json", "--no-report"], ["ods_json", "dwh", "dtm"]),
    (["--from-ods", "--no-report"], ["dwh", "dtm"]),
    (["--from-dwh", "--no-report"], ["dtm"]),
])
def test_pipeline_sequence(monkeypatch, options: list[str], expected: list[str]) -> None:
    events = _mock_pipeline(monkeypatch)
    assert main.run(options) == 0
    assert events == expected


@pytest.mark.parametrize("option", ["--from-json", "--from-ods", "--from-dwh", "--from-dtm"])
def test_starting_from_existing_data_does_not_require_api_key(monkeypatch, option: str) -> None:
    _mock_pipeline(monkeypatch)
    assert main.run([option]) == 0
    main.load_settings.assert_called_once_with(require_api_key=False)


def test_default_mode_requires_api_key(monkeypatch) -> None:
    _mock_pipeline(monkeypatch)
    assert main.run([]) == 0
    main.load_settings.assert_called_once_with(require_api_key=True)


def test_run_ods_always_rebuilds_all_tables(monkeypatch, tmp_path) -> None:
    for table_name in TABLES:
        (tmp_path / f"{table_name}.json").write_text("[]", encoding="utf-8")
    settings = SimpleNamespace(
        raw_data_dir=tmp_path,
        db_engine="postgresql",
        api_key="",
        http_timeout=30,
    )
    args = Namespace(from_json=True)
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
