from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.api.province_sud_client import ProvinceSudClient
from src.database.repository import count_rows, insert_page
from src.extraction.normalization import normalize_page
from src.extraction.progress import ProgressDisplay

ARCHIVE_RETENTION = 5


@dataclass(frozen=True)
class DownloadResult:
    table: str
    pages: int
    rows: int
    bytes_written: int = 0
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class ExtractionResult:
    table: str
    pages: int
    api_rows: int
    database_rows: int
    child_table: str | None = None
    child_rows: int = 0
    elapsed_seconds: float = 0.0


def _write_json_item(handle: object, row: dict[str, object], first: bool) -> bool:
    """Écrit un objet dans un tableau JSON en gérant son séparateur."""
    if not first:
        # Le séparateur est écrit avant tout objet sauf le premier afin de
        # produire progressivement un unique tableau JSON valide.
        handle.write(",\n")  # type: ignore[attr-defined]
    serialized = json.dumps(row, ensure_ascii=False, indent=2)
    handle.write("  " + serialized.replace("\n", "\n  "))  # type: ignore[attr-defined]
    return False


def _download_table(
    client: ProvinceSudClient, table_name: str, target: Path
) -> DownloadResult:
    """Télécharge une table vers un fichier JSON et mesure l'opération."""
    pages = rows_count = 0
    first = True
    progress = ProgressDisplay(f"Téléchargement {table_name}")
    try:
        # Les pages sont sérialisées au fil de l'eau : la mémoire ne contient
        # jamais l'intégralité d'une table volumineuse.
        with target.open("w", encoding="utf-8") as handle:
            handle.write("[\n")
            for pages, rows in enumerate(client.fetch_pages(table_name), start=1):
                for row in rows:
                    first = _write_json_item(handle, row, first)
                rows_count += len(rows)
                progress.update(len(rows))
            handle.write("\n]\n")
    except Exception:
        # On termine proprement la ligne de progression avant de laisser
        # download_tables supprimer la zone temporaire incomplète.
        progress.abort()
        raise
    elapsed = progress.finish()
    return DownloadResult(
        table_name, pages, rows_count, target.stat().st_size, elapsed
    )


def _rotate_archives(archive_dir: Path, retention: int) -> None:
    """Supprime les instantanés dépassant la durée de rétention demandée."""
    # Le nom horodaté se trie chronologiquement : l'ordre inverse place donc les
    # instantanés les plus récents avant ceux à supprimer.
    snapshots = (
        sorted((path for path in archive_dir.iterdir() if path.is_dir()), reverse=True)
        if archive_dir.exists()
        else []
    )
    for expired in snapshots[retention:]:
        shutil.rmtree(expired)


def download_tables(
    client: ProvinceSudClient,
    table_names: list[str],
    raw_data_dir: Path,
    archive_retention: int = ARCHIVE_RETENTION,
) -> list[DownloadResult]:
    """Télécharge tout l'instantané avant de remplacer les JSON courants."""
    if archive_retention < 0:
        raise ValueError("archive_retention doit être positif ou nul")
    raw_data_dir.mkdir(parents=True, exist_ok=True)
    # Chaque exécution télécharge toutes les tables dans une zone temporaire.
    # Les JSON courants restent ainsi inchangés tant que le téléchargement complet
    # n'est pas terminé.
    staging = raw_data_dir / f".staging-{uuid4().hex}"
    staging.mkdir()
    results: list[DownloadResult] = []
    try:
        for table_name in table_names:
            logging.info("[%s] téléchargement en cours", table_name)
            results.append(
                _download_table(client, table_name, staging / f"{table_name}.json")
            )
            result = results[-1]
            logging.info(
                "[%s] téléchargé : %d pages, %d lignes, %.2f Mio en %.2f s",
                table_name,
                result.pages,
                result.rows,
                result.bytes_written / 1024 / 1024,
                result.elapsed_seconds,
            )

        # Une fois tous les téléchargements terminés, les fichiers courants sont
        # déplacés successivement dans un même répertoire d'archive.
        current_files = [
            raw_data_dir / f"{table_name}.json"
            for table_name in table_names
            if (raw_data_dir / f"{table_name}.json").exists()
        ]
        if current_files:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            snapshot = raw_data_dir / "archive" / timestamp
            snapshot.mkdir(parents=True)
            for current in current_files:
                current.replace(snapshot / current.name)

        # Les nouveaux fichiers sont ensuite publiés successivement avec replace().
        # Chaque déplacement est individuel : l'archivage et la publication de
        # l'instantané complet ne constituent donc pas une opération atomique.
        for table_name in table_names:
            (staging / f"{table_name}.json").replace(
                raw_data_dir / f"{table_name}.json"
            )
        _rotate_archives(raw_data_dir / "archive", archive_retention)
        return results
    finally:
        # La zone de travail est nettoyée aussi bien après succès qu'après une
        # erreur réseau ou de sérialisation.
        shutil.rmtree(staging, ignore_errors=True)


def import_table(
    connection: Any,
    table_name: str,
    raw_data_dir: Path,
    pages: int = 0,
) -> ExtractionResult:
    """Charge le moteur configuré exclusivement depuis le JSON local courant."""
    started_at = time.monotonic()
    source = raw_data_dir / f"{table_name}.json"
    logging.info(
        "[%s] lecture de %s (%.2f Mio)",
        table_name,
        source.name,
        source.stat().st_size / 1024 / 1024,
    )
    with source.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    # Le fichier doit représenter la collection d'objets attendue par le schéma ;
    # cette validation précède toute insertion.
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"[{table_name}] le fichier JSON doit contenir une liste d'objets")

    # Les tableaux imbriqués sont extraits vers leurs tables enfants et les
    # objets principaux sont limités aux colonnes relationnelles connues.
    parents, child_table, children = normalize_page(table_name, rows)
    logging.info(
        "[%s] insertion : %d lignes principales%s",
        table_name,
        len(parents),
        f", {len(children)} lignes dans {child_table}" if child_table else "",
    )
    insert_page(connection, table_name, parents, child_table, children)

    # Après validation transactionnelle du lot, les comptages signalent un écart
    # entre les nombres de lignes attendus et chargés, pour le parent et l'enfant.
    database_rows = count_rows(connection, table_name)
    if database_rows != len(rows):
        raise RuntimeError(
            f"[{table_name}] vérification : JSON={len(rows)}, base={database_rows}."
        )
    child_rows = count_rows(connection, child_table) if child_table else 0
    if child_rows != len(children):
        raise RuntimeError(
            f"[{table_name}] vérification enfants : "
            f"JSON={len(children)}, base={child_rows}."
        )
    result = ExtractionResult(
        table_name, pages, len(rows), database_rows, child_table, child_rows,
        time.monotonic() - started_at,
    )
    logging.info(
        "[%s] import terminé : %d lignes principales, %d enfants en %.2f s",
        table_name,
        result.database_rows,
        result.child_rows,
        result.elapsed_seconds,
    )
    return result
