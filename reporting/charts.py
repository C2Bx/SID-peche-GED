from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# Palette catégorielle validée (ordre fixe, jamais cyclé). La variante sombre
# est appliquée côté navigateur par le template, à partir de cette table.
SERIES = {
    "recette": "#2a78d6",
    "depense": "#eb6834",
    "benefice": "#1baf7a",
}
SERIES_DARK = {
    "#2a78d6": "#3987e5",
    "#eb6834": "#d95926",
    "#1baf7a": "#199e70",
}
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
MOIS = ["Janv.", "Févr.", "Mars", "Avr.", "Mai", "Juin",
        "Juil.", "Août", "Sept.", "Oct.", "Nov.", "Déc."]

PLOTLY_CONFIG = {"displaylogo": False, "responsive": True,
                 "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


def _layout(fig: go.Figure, *, height: int = 340, **kwargs) -> go.Figure:
    """Applique la charte commune : fond transparent, grille discrète."""
    fig.update_layout(
        height=height,
        autosize=True,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 13, "color": TEXT_SECONDARY},
        hoverlabel={"font": {"family": FONT}},
        separators=", ",
        **kwargs,
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, automargin=True)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, automargin=True)
    return fig


def finance_by_year(df: pd.DataFrame) -> go.Figure:
    """Évolution annuelle de la recette, de la dépense et du bénéfice."""
    fig = go.Figure()
    for column, key in (("Recette", "recette"), ("Dépense", "depense"),
                        ("Bénéfice", "benefice")):
        fig.add_trace(go.Scatter(
            x=df["Année"], y=df[column], name=column, mode="lines+markers",
            line={"color": SERIES[key], "width": 2},
            marker={"size": 8, "color": SERIES[key],
                    "line": {"width": 2, "color": "rgba(255,255,255,0.9)"}},
            hovertemplate="%{y:,.0f} XPF<extra>" + column + "</extra>",
        ))
        if len(df):
            # Étiquette directe sur le dernier point : l'identité ne repose pas
            # sur la seule couleur.
            fig.add_annotation(
                x=df["Année"].iloc[-1], y=df[column].iloc[-1], text=column,
                xanchor="left", xshift=10, showarrow=False,
            )
    _layout(fig, hovermode="x unified",
            legend={"orientation": "h", "y": 1.08, "x": 0})
    fig.update_xaxes(dtick=1, tickformat="d", showgrid=False)
    fig.update_yaxes(ticksuffix=" ", tickformat="~s", title_text="XPF")
    return fig


def campagnes_by_month(df_campagnes: pd.DataFrame) -> go.Figure:
    """Saisonnalité : nombre de campagnes par mois de début."""
    counts = (
        df_campagnes.dropna(subset=["mois"])["mois"].astype(int)
        .value_counts().reindex(range(1, 13), fill_value=0)
    )
    fig = go.Figure(go.Bar(
        x=MOIS, y=counts.values, marker={"color": SERIES["recette"], "cornerradius": 4},
        hovertemplate="%{x} : %{y} campagnes<extra></extra>",
    ))
    _layout(fig, bargap=0.25, height=300)
    fig.update_xaxes(showgrid=False)
    return fig


def _horizontal_bar(labels, values, *, hover: str, suffix: str = "",
                    height: int | None = None) -> go.Figure:
    """Barres horizontales triées, une seule série donc une seule couleur."""
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker={"color": SERIES["recette"], "cornerradius": 4},
        text=[f"{v:,.0f}{suffix}".replace(",", " ") for v in values],
        textposition="outside", cliponaxis=False,
        hovertemplate=hover,
    ))
    _layout(fig, bargap=0.3, height=height or max(240, 34 * len(labels) + 40))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    # Marge à droite (et à gauche si négatif) pour les étiquettes extérieures.
    values = list(values)
    high = max([0, *values])
    low = min([0, *values])
    span = (high - low) or 1
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=True,
                     range=[low - 0.22 * span * (low < 0), high + 0.22 * span])
    return fig


def top_especes_chart(df: pd.DataFrame) -> go.Figure:
    return _horizontal_bar(
        df["Espèce"], df["Poids"],
        hover="%{y}<br>Poids : %{x:,.0f}<extra></extra>",
    )


def frais_chart(df: pd.DataFrame) -> go.Figure:
    return _horizontal_bar(
        df["Poste"], df["Montant (XPF)"],
        hover="%{y}<br>%{x:,.0f} XPF<extra></extra>",
    )


def commune_chart(df: pd.DataFrame) -> go.Figure:
    return _horizontal_bar(
        df["Commune"], df["Bénéfice moyen (XPF)"],
        hover="%{y}<br>Bénéfice moyen : %{x:,.0f} XPF<extra></extra>",
    )


def to_html(fig: go.Figure, div_id: str) -> str:
    """Fragment HTML d'une figure, Plotly.js étant chargé une fois par la page."""
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       div_id=div_id, config=PLOTLY_CONFIG)
