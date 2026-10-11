"""Génère reporting/performance_campagnes/index.html depuis le DTM.

    python -m reporting.build_report            # lit la base configurée dans .env
    python -m reporting.build_report --demo     # jeu fictif, sans base
    python -m reporting.build_report --annee 2023 --annee 2024
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.offline
from jinja2 import Environment, FileSystemLoader, select_autoescape

from reporting import charts, kpis
from reporting.data import DtmData, demo_data, load_dtm

REPORTING_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = REPORTING_DIR / "performance_campagnes" / "index.html"


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    subtitle: str
    chart_html: str
    table_html: str
    note: str = ""
    wide: bool = False


def _table(df: pd.DataFrame) -> str:
    """Vue tableau d'un graphique, nombres formatés à la française."""
    formatted = df.copy()
    for column in formatted.columns:
        if pd.api.types.is_float_dtype(formatted[column]):
            decimals = 1 if "%" in column else 0
            formatted[column] = formatted[column].map(
                lambda v, d=decimals: kpis.format_number(v, d))
    return formatted.to_html(index=False, border=0, classes="data-table", na_rep="–")


def build_sections(data: DtmData) -> list[Section]:
    """Assemble les graphiques et leur vue tableau."""
    finance = kpis.yearly_finance(data)
    especes = kpis.top_especes(data)
    frais = kpis.frais_par_nature(data)
    communes = kpis.benefice_par_commune(data)
    mois = (
        data.campagnes.dropna(subset=["mois"])["mois"].astype(int)
        .value_counts().reindex(range(1, 13), fill_value=0)
    )
    return [
        Section("finance", "Recette, dépense et bénéfice par année",
                "Somme des campagnes, rattachées à leur année de début",
                charts.to_html(charts.finance_by_year(finance), "chart-finance"),
                _table(finance), wide=True),
        Section("saison", "Campagnes par mois de début",
                "Saisonnalité de l'activité",
                charts.to_html(charts.campagnes_by_month(data.campagnes), "chart-saison"),
                _table(pd.DataFrame({"Mois": charts.MOIS, "Campagnes": mois.values}))),
        Section("especes", "Top 10 des espèces en poids",
                "Poids entier cumulé par catégorie d'espèce",
                charts.to_html(charts.top_especes_chart(especes), "chart-especes"),
                _table(especes)),
        Section("frais", "Répartition des frais par poste",
                "Montant total par nature de frais, en XPF",
                charts.to_html(charts.frais_chart(frais), "chart-frais"),
                _table(frais),
                note="Les salaires ne figurent pas dans le détail des frais : "
                     "la somme des postes est donc inférieure à la dépense."),
        Section("communes", "Bénéfice moyen par commune du capitaine",
                "Les 10 communes comptant le plus de campagnes, en XPF",
                charts.to_html(charts.commune_chart(communes), "chart-communes"),
                _table(communes)),
    ]


def plotly_script_tag(mode: str) -> str:
    """Balise de chargement de Plotly.js, par CDN ou intégrée au fichier."""
    if mode == "inline":
        return f"<script>{plotly.offline.get_plotlyjs()}</script>"
    version = plotly.offline.get_plotlyjs_version()
    return (f'<script src="https://cdn.plot.ly/plotly-{version}.min.js" '
            'charset="utf-8"></script>')


def render_report(data: DtmData, *, source: str, years: list[int] | None = None,
                  plotly_mode: str = "cdn") -> str:
    """Produit la page HTML complète du rapport."""
    env = Environment(
        loader=FileSystemLoader(REPORTING_DIR / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("performance_campagnes.html.j2")
    available_years = sorted(int(y) for y in data.campagnes["annee"].dropna().unique())
    return template.render(
        title="Performance des campagnes de pêche",
        generated_at=datetime.now().strftime("%d/%m/%Y à %H:%M"),
        source=source,
        years=years or available_years,
        kpis=kpis.compute_kpis(data),
        quality=kpis.compute_quality(data),
        sections=build_sections(data),
        plotly_script=plotly_script_tag(plotly_mode),
        series_dark=charts.SERIES_DARK,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true",
                        help="utilise un jeu de données fictif au lieu de la base")
    parser.add_argument("--annee", type=int, action="append",
                        help="restreint le rapport à une année (option répétable)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"fichier généré (défaut : {DEFAULT_OUTPUT.relative_to(REPORTING_DIR.parent)})")
    parser.add_argument("--plotly", choices=("cdn", "inline"), default="cdn",
                        help="inline intègre Plotly.js (~4 Mo) pour un usage hors ligne")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.demo:
        data, source = demo_data(), "Jeu de démonstration (données fictives)"
    else:
        # Import différé : le mode démo fonctionne sans pilote ni .env.
        from src.config import load_settings
        from src.database.connection import connect

        try:
            settings = load_settings(require_api_key=False)
            with connect(settings) as connection:
                data = load_dtm(connection)
        except Exception as exc:
            logging.error("Lecture du DTM impossible : %s", exc)
            return 1
        engine = "PostgreSQL" if settings.db_engine == "postgresql" else "SQL Server"
        source = f"DTM dtm_performance_campagnes ({engine})"

    data = data.filter_years(args.annee)
    if data.campagnes.empty:
        logging.error("Aucune campagne à présenter pour ce périmètre.")
        return 1

    html = render_report(data, source=source, years=args.annee, plotly_mode=args.plotly)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    logging.info("Rapport généré : %s (%d campagnes)", args.output, len(data.campagnes))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run())
