from __future__ import annotations

import argparse
import logging
import sys
import time

from src.api.province_sud_client import ProvinceSudClient
from src.config import TABLES, load_settings
from src.database.connection import check_connection, connect
from src.database.repository import find_json_columns, relation_statistics
from src.database.schema import reset_tables, validate_reset_scope
from src.dtm.runner import run_dtms
from src.dwh.runner import ensure_env_mer_exists, run_dwh
from src.extraction.peche_extractor import (
    DownloadResult,
    ExtractionResult,
    download_tables,
    import_table,
)
from src.extraction.progress import format_count, format_duration


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse et valide les arguments fournis sur la ligne de commande."""
    # Le mode par défaut enchaîne le téléchargement, la reconstruction de
    # l'ODS, du DWH puis des DTM. Les options permettent de reprendre le pipeline
    # à une étape précise ou depuis les JSON locaux.
    parser = argparse.ArgumentParser(description="Import des données de pêche Province Sud")
    parser.add_argument(
        "--depuis-json",
        "--from-json",
        action="store_true",
        help="saute le téléchargement et charge la base depuis data/raw",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--ods-only", action="store_true", help="construit uniquement l'ODS env_mer"
    )
    modes.add_argument(
        "--dwh-only",
        action="store_true",
        help="reconstruit le DWH depuis l'ODS existant, puis les DTM",
    )
    modes.add_argument(
        "--dtm-only",
        action="store_true",
        help="construit uniquement les DTM depuis le DWH existant",
    )
    parser.add_argument(
        "--sans-rapport",
        action="store_true",
        help="ne régénère pas la restitution HTML après les DTM",
    )
    args = parser.parse_args(argv)
    # Les modes DWH et DTM ne lisent aucun fichier source : leur associer le
    # mode JSON serait contradictoire.
    if (args.dwh_only or args.dtm_only) and args.depuis_json:
        mode = "--dwh-only" if args.dwh_only else "--dtm-only"
        parser.error(f"{mode} est incompatible avec --depuis-json/--from-json")
    return args


def print_summary(
    downloads: list[DownloadResult],
    results: list[ExtractionResult],
    total_elapsed: float,
) -> None:
    """Affiche le bilan des téléchargements et des imports réalisés."""
    print("\nExtraction terminée\n")
    print(f"{'Table':<34} | {'Pages':>7} | {'JSON':>12} | {'Base':>12} | {'Temps':>8}")
    print("-" * 84)
    # Ce rapprochement associe les mesures réseau aux contrôles en base,
    # produits à deux moments différents du pipeline.
    downloads_by_table = {result.table: result for result in downloads}
    for result in results:
        download = downloads_by_table[result.table]
        pages = format_count(download.pages, 7) if download.pages else f"{'-':>7}"
        print(
            f"{result.table:<34} | {pages} | "
            f"{format_count(download.rows, 12)} | "
            f"{format_count(result.database_rows, 12)} | "
            f"{format_duration(download.elapsed_seconds + result.elapsed_seconds)}"
        )
        if result.child_table:
            print(
                f"{result.child_table:<34} | {'':>7} | {'':>12} | "
                f"{format_count(result.child_rows, 12)} | {'':>8}"
            )
    print("-" * 84)
    print(
        f"{'Temps global':<34} | {'':>7} | {'':>12} | {'':>12} | "
        f"{format_duration(total_elapsed)}"
    )
    print("\nToutes les tables ont été récupérées correctement.")


def run_ods(settings: object, args: argparse.Namespace, connection: object) -> tuple[
    list[DownloadResult], list[ExtractionResult]
]:
    """Construit et contrôle l'ODS avec la connexion déjà ouverte."""
    # L'ODS est reconstruit dans son ensemble et dans l'ordre de TABLES, qui
    # place les lignes référencées avant celles portant les clés étrangères.
    selected_tables = list(TABLES)
    validate_reset_scope(selected_tables)
    if args.depuis_json:
        # Tous les fichiers sont contrôlés avant de détruire les tables afin
        # qu'une source locale manquante ne laisse pas un ODS vide.
        logging.info("Mode JSON local : aucun appel à la source")
        missing = [
            settings.raw_data_dir / f"{table_name}.json"
            for table_name in selected_tables
            if not (settings.raw_data_dir / f"{table_name}.json").is_file()
        ]
        if missing:
            names = ", ".join(path.name for path in missing)
            raise FileNotFoundError(f"Fichiers JSON absents : {names}")
        downloads = [
            DownloadResult(
                table_name,
                0,
                0,
                (settings.raw_data_dir / f"{table_name}.json").stat().st_size,
            )
            for table_name in selected_tables
        ]
    else:
        # L'instantané complet est publié sur disque avant toute modification
        # de la base ; un échec réseau préserve ainsi l'ODS actuel.
        logging.info("Téléchargement de l'instantané JSON")
        with ProvinceSudClient(settings.api_key, settings.http_timeout) as client:
            downloads = download_tables(client, selected_tables, settings.raw_data_dir)
    # En mode local, ce nombre vaut zéro car le fichier ne permet pas de
    # retrouver la pagination d'origine ; il sert uniquement au bilan.
    pages_by_table = {result.table: result.pages for result in downloads}

    database_label = (
        "PostgreSQL" if settings.db_engine == "postgresql" else "SQL Server"
    )
    logging.info("Reconstruction et chargement de %s depuis les JSON", database_label)
    check_connection(connection)
    # Cette opération destructive n'intervient qu'après validation des sources.
    # reset_tables regroupe uniquement la reconstruction du schéma dans une
    # transaction ; les imports suivants possèdent chacun leur propre transaction.
    reset_tables(connection, selected_tables)
    results = []
    # L'ordre de chargement respecte les dépendances référentielles de l'ODS.
    for table_name in selected_tables:
        results.append(
            import_table(
                connection,
                table_name,
                settings.raw_data_dir,
                pages_by_table[table_name],
            )
        )
        if args.depuis_json:
            # Faute de réponse API, le nombre d'objets du JSON devient la mesure
            # source affichée dans le bilan final.
            imported = results[-1]
            index = selected_tables.index(table_name)
            downloads[index] = DownloadResult(
                table_name, 0, imported.api_rows, downloads[index].bytes_written
            )
    # La présence d'une colonne JSON résiduelle interrompt le traitement. Les
    # statistiques relationnelles suivantes sont seulement calculées et journalisées :
    # leurs nombres d'orphelins ne déterminent pas le succès du pipeline.
    json_columns = find_json_columns(connection, selected_tables)
    if json_columns:
        raise RuntimeError(f"Colonnes JSON/JSONB encore présentes : {json_columns}")
    logging.info("Analyse des relations principales :")
    for relation, non_null, valid, orphans in relation_statistics(connection):
        logging.info(
            "%s — non nulles : %d, valides : %d, orphelines : %d",
            relation,
            non_null,
            valid,
            orphans,
        )
    logging.info("ODS env_mer construit avec succès.")
    return downloads, results


def run_report(connection: object, settings: object, args: argparse.Namespace) -> None:
    """Régénère la restitution HTML depuis les DTM et le DWH tout juste construits."""
    if args.sans_rapport:
        return
    # Import différé : Plotly et pandas ne sont chargés que si le rapport est
    # produit, ce qui garde l'ETL seul utilisable sans ces dépendances.
    from src.reporting.build_report import generate_from_connection

    generate_from_connection(connection, settings.db_engine)


def run(argv: list[str] | None = None) -> int:
    """Exécute l'ETL complet et renvoie son code de sortie."""
    started_at = time.monotonic()
    args = parse_args(argv)
    try:
        # La clé API n'est exigée que lorsqu'un téléchargement est prévu.
        settings = load_settings(
            require_api_key=not (
                args.depuis_json or args.dwh_only or args.dtm_only
            )
        )
    except ValueError as exc:
        logging.error("Configuration invalide : %s", exc)
        return 2
    try:
        with connect(settings) as connection:
            if args.dtm_only:
                # Les scripts vérifient eux-mêmes les tables DWH détaillées dont
                # ils dépendent ; aucune reconstruction amont n'est déclenchée.
                check_connection(connection)
                run_dtms(connection, settings.db_engine)
                run_report(connection, settings, args)
                return 0

            if args.dwh_only:
                # Le DWH repose sur un ODS existant, contrôlé avant le lancement
                # du script SQL sans relire les sources.
                check_connection(connection)
                ensure_env_mer_exists(connection, settings.db_engine)
                run_dwh(connection, settings.db_engine)
                # Les DTM lisent le DWH : les laisser en l'état les rendrait
                # incohérents avec le DWH tout juste reconstruit.
                run_dtms(connection, settings.db_engine)
                run_report(connection, settings, args)
                return 0

            downloads, results = run_ods(settings, args, connection)
            if not args.ods_only:
                # En mode normal ou JSON local, le DWH n'est construit qu'après
                # la reconstruction et l'exécution des contrôles prévus sur l'ODS.
                ensure_env_mer_exists(connection, settings.db_engine)
                run_dwh(connection, settings.db_engine)
                run_dtms(connection, settings.db_engine)
                run_report(connection, settings, args)
    except Exception as exc:
        # Toute erreur bloque les étapes suivantes et renvoie un code non nul
        # exploitable par un ordonnanceur ou un outil d'intégration.
        logging.error("Pipeline interrompu : %s", exc)
        return 1

    print_summary(downloads, results, time.monotonic() - started_at)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run())
