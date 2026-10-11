from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

GO_SEPARATOR = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)
SUPPORTED_ENGINES = {"postgresql", "sqlserver"}


def split_sqlserver_batches(script: str) -> list[str]:
    """Découpe un script uniquement sur les lignes constituées de GO."""
    # GO est compris par les clients SQL Server, mais pas par pyodbc. Une ligne
    # contenant ce texte dans une chaîne ou un commentaire ne doit pas couper le SQL.
    return [batch.strip() for batch in GO_SEPARATOR.split(script) if batch.strip()]


def consume_result_sets(cursor: Any) -> None:
    """Consomme les jeux de résultats et journalise les contrôles SQL."""
    while True:
        # Les SELECT de contrôle restent informatifs : seule une erreur SQL
        # interrompt le pipeline. Leurs résultats sont toutefois journalisés,
        # sans quoi une anomalie détectée par le script passerait inaperçue.
        description = getattr(cursor, "description", None)
        if description is not None:
            columns = [column[0] for column in description]
            for row in cursor.fetchall():
                logging.info(
                    "Contrôle SQL : %s",
                    ", ".join(f"{name}={value}" for name, value in zip(columns, row)),
                )
        nextset = getattr(cursor, "nextset", None)
        if nextset is None or not nextset():
            return


def execute_sql_script(connection: Any, db_engine: str, script_path: Path) -> None:
    """Exécute et valide un script SQL complet pour le moteur demandé."""
    engine = db_engine.strip().lower()
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Moteur SQL non pris en charge : {db_engine}")

    script = script_path.read_text(encoding="utf-8")
    try:
        with connection.cursor() as cursor:
            if engine == "postgresql":
                cursor.execute(script)
                consume_result_sets(cursor)
            else:
                for batch_number, batch in enumerate(
                    split_sqlserver_batches(script), start=1
                ):
                    try:
                        cursor.execute(batch)
                        consume_result_sets(cursor)
                    except Exception:
                        logging.exception(
                            "Échec du batch SQL Server n°%d (%s)",
                            batch_number,
                            script_path,
                        )
                        raise
        # Les scripts DTM gèrent leur transaction métier eux-mêmes. Pour eux,
        # ce commit clôt seulement une éventuelle transaction de pilote encore
        # ouverte après les SELECT de contrôle ; il conserve le comportement
        # transactionnel historique du runner DWH.
        connection.commit()
    except Exception:
        connection.rollback()
        raise
