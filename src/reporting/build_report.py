"""Génère la restitution HTML des 17 indicateurs depuis le DWH et le DTM.

    python -m src.reporting.build_report                     # lit la base du .env
    python -m src.reporting.build_report --date-ref 2025-12-31
    python -m src.reporting.build_report --watch             # se régénère à chaque ajout en base
    python -m src.reporting.build_report --demo              # données fictives, sans base
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.offline
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.reporting import charts
from src.reporting.data import SidData, demo_data, fingerprint, load
from src.reporting.formatting import format_date
from src.reporting.restitution import HYPOTHESES, build_themes

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_OUTPUT = PROJECT_ROOT / "reporting" / "performance_campagnes" / "index.html"


def plotly_script_tag(mode: str) -> str:
    """Balise de chargement de Plotly.js, par CDN ou intégrée au fichier."""
    if mode == "inline":
        return f"<script>{plotly.offline.get_plotlyjs()}</script>"
    version = plotly.offline.get_plotlyjs_version()
    return (f'<script src="https://cdn.plot.ly/plotly-{version}.min.js" '
            'charset="utf-8"></script>')


def render(d: SidData, *, source: str, date_ref: pd.Timestamp, plotly_mode: str = "cdn",
           refresh_seconds: int = 0) -> str:
    """Produit la page HTML complète de la restitution."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR),
                      autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    return env.get_template("restitution.html.j2").render(
        title="Restitution — SID Pêche Province Sud",
        generated_at=datetime.now().strftime("%d/%m/%Y à %H:%M"),
        date_ref=format_date(date_ref),
        date_ref_iso=date_ref.strftime("%Y-%m-%d"),
        source=source,
        hypotheses=HYPOTHESES,
        themes=build_themes(d, date_ref),
        plotly_script=plotly_script_tag(plotly_mode),
        series_dark=charts.SERIES_DARK,
        refresh_seconds=refresh_seconds,
    )


def write_report(d: SidData, output: Path, *, source: str, date_ref: pd.Timestamp,
                 plotly_mode: str = "cdn", refresh_seconds: int = 0) -> Path:
    """Écrit l'unique artefact de restitution : la page HTML."""
    output.parent.mkdir(parents=True, exist_ok=True)
    html = render(d, source=source, date_ref=date_ref, plotly_mode=plotly_mode,
                  refresh_seconds=refresh_seconds)
    output.write_text(html, encoding="utf-8")
    logging.info("Restitution générée : %s", output)
    return output


def generate_from_connection(connection: Any, db_engine: str, *, output: Path = DEFAULT_OUTPUT,
                             date_ref: date | None = None, plotly_mode: str = "cdn",
                             refresh_seconds: int = 0) -> Path:
    """Point d'entrée du pipeline : lit la base ouverte et écrit la restitution."""
    data = load(connection)
    connection.commit()
    engine = "PostgreSQL" if db_engine == "postgresql" else "SQL Server"
    return write_report(data, output, source=f"DWH dwh et DTM ({engine})",
                        date_ref=pd.Timestamp(date_ref or date.today()),
                        plotly_mode=plotly_mode, refresh_seconds=refresh_seconds)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère la restitution HTML des indicateurs")
    parser.add_argument("--demo", action="store_true",
                        help="utilise un jeu de données fictif au lieu de la base")
    parser.add_argument("--date-ref", type=date.fromisoformat, default=None,
                        help="date de référence AAAA-MM-JJ (défaut : aujourd'hui)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="fichier HTML généré")
    parser.add_argument("--plotly", choices=("cdn", "inline"), default="cdn",
                        help="inline intègre Plotly.js (~4 Mo) pour un usage hors ligne")
    parser.add_argument("--watch", nargs="?", type=int, const=30, default=0, metavar="SECONDES",
                        help="surveille la base et régénère dès qu'une donnée change "
                             "(vérification toutes les 30 s par défaut)")
    args = parser.parse_args(argv)
    if args.watch and args.demo:
        parser.error("--watch lit la base : il est incompatible avec --demo")
    return args


def watch(args: argparse.Namespace) -> int:
    """Régénère la restitution à chaque changement du DWH ou du DTM."""
    from src.config import load_settings
    from src.database.connection import connect

    settings = load_settings(require_api_key=False)
    last = None
    logging.info("Surveillance de la base toutes les %d s (Ctrl+C pour arrêter)", args.watch)
    try:
        while True:
            try:
                with connect(settings) as connection:
                    current = fingerprint(connection)
                    # La date du jour fait aussi partie de l'état : à minuit, les
                    # indicateurs « à une date » changent sans nouvelle donnée.
                    state = (current, args.date_ref or date.today())
                    if state != last:
                        logging.info("Changement détecté (%s) : régénération", current)
                        generate_from_connection(
                            connection, settings.db_engine, output=args.output,
                            date_ref=args.date_ref, plotly_mode=args.plotly,
                            refresh_seconds=args.watch)
                        last = state
            except Exception as exc:  # la surveillance survit à une base indisponible
                logging.error("Lecture impossible, nouvel essai dans %d s : %s", args.watch, exc)
            time.sleep(args.watch)
    except KeyboardInterrupt:
        logging.info("Surveillance arrêtée.")
        return 0


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.watch:
        return watch(args)
    if args.demo:
        date_ref = pd.Timestamp(args.date_ref or date.today())
        write_report(demo_data(today=date_ref.date()), args.output,
                     source="Jeu de démonstration (données fictives)",
                     date_ref=date_ref, plotly_mode=args.plotly)
        return 0

    # Import différé : le mode démo fonctionne sans pilote ni .env.
    from src.config import load_settings
    from src.database.connection import connect

    try:
        settings = load_settings(require_api_key=False)
        with connect(settings) as connection:
            generate_from_connection(connection, settings.db_engine, output=args.output,
                                     date_ref=args.date_ref, plotly_mode=args.plotly)
    except Exception as exc:
        logging.error("Génération de la restitution impossible : %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run())
