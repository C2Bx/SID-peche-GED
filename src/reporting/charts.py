from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import plotly.graph_objects as go

# Palette catégorielle validée, dans son ordre fixe (jamais cyclée). Le thème
# sombre est appliqué côté navigateur à partir de la table de correspondance.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]
SERIES_DARK = dict(zip(PALETTE, PALETTE_DARK))
GRIS = "#8f8e86"  # série « Autres » : regroupement, pas une identité
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

PLOTLY_CONFIG = {"displaylogo": False, "responsive": True,
                 "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


def _layout(fig: go.Figure, *, height: int = 320, **kwargs) -> go.Figure:
    """Charte commune : fond transparent, grille discrète, un seul axe Y."""
    fig.update_layout(
        height=height, autosize=True,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 12, "color": TEXT_SECONDARY},
        hoverlabel={"font": {"family": FONT}},
        separators=", ",
        legend={"orientation": "h", "y": 1.12, "x": 0},
        **kwargs,
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, automargin=True)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, automargin=True)
    return fig


def lines(x: Sequence, series: dict[str, Sequence], *, unit: str = "",
          x_is_month: bool = False, height: int = 300) -> go.Figure:
    """Évolution d'une à six séries sur un axe unique."""
    fig = go.Figure()
    for i, (name, values) in enumerate(series.items()):
        color = GRIS if name.startswith("Autres") else PALETTE[i % len(PALETTE)]
        fig.add_trace(go.Scatter(
            x=list(x), y=list(values), name=name, mode="lines+markers",
            line={"color": color, "width": 2},
            marker={"size": 5 if x_is_month else 8, "color": color},
            hovertemplate=f"%{{y:,.0f}}{(' ' + unit) if unit else ''}<extra>{name}</extra>",
        ))
    _layout(fig, height=height, hovermode="x unified", showlegend=len(series) > 1)
    if x_is_month:
        fig.update_xaxes(tickformat="%m/%Y", showgrid=False)
    else:
        fig.update_xaxes(dtick=1, tickformat="d", showgrid=False)
    fig.update_yaxes(tickformat="~s", rangemode="tozero")
    return fig


def bars(labels: Sequence, values: Sequence, *, horizontal: bool = False,
         unit: str = "", height: int | None = None, decimals: int = 0) -> go.Figure:
    """Une série, une couleur ; valeurs affichées au bout des barres."""
    labels, values = [str(v) for v in labels], list(values)
    texts = [f"{v:,.{decimals}f}".replace(",", " ").replace(".", ",") for v in values]
    value_axis, label_axis = ("x", "y") if horizontal else ("y", "x")
    hover = f"%{{{label_axis}}} : %{{{value_axis}:,.{decimals}f}}" + (f" {unit}" if unit else "")
    fig = go.Figure(go.Bar(
        x=values if horizontal else labels, y=labels if horizontal else values,
        orientation="h" if horizontal else "v",
        marker={"color": PALETTE[0], "cornerradius": 4},
        text=texts, textposition="outside", cliponaxis=False,
        hovertemplate=hover + "<extra></extra>",
    ))
    finite = [v for v in values if pd.notna(v)]
    high, low = max([0, *finite]), min([0, *finite])
    span = (high - low) or 1
    if horizontal:
        _layout(fig, bargap=0.3, height=height or max(200, 30 * len(labels) + 40))
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_xaxes(showticklabels=False, showgrid=False,
                         range=[low - 0.25 * span * (low < 0), high + 0.25 * span])
    else:
        _layout(fig, bargap=0.3, height=height or 280)
        fig.update_xaxes(showgrid=False, type="category")
        fig.update_yaxes(showticklabels=False, showgrid=False,
                         range=[low - 0.2 * span * (low < 0), high + 0.2 * span])
    return fig


def box_by_year(df: pd.DataFrame, x: str, y: str, *, height: int = 300) -> go.Figure:
    """Distribution d'une mesure par année, sans montrer les valeurs individuelles."""
    fig = go.Figure(go.Box(
        x=df[x].astype(str), y=df[y], marker={"color": PALETTE[0]},
        line={"width": 1.5}, boxpoints=False, name=y,
        hoverinfo="skip",
    ))
    _layout(fig, height=height, showlegend=False)
    fig.update_xaxes(showgrid=False, type="category")
    fig.update_yaxes(tickformat="~s", zeroline=True, zerolinewidth=1.5)
    return fig


def to_html(fig: go.Figure, div_id: str) -> str:
    """Fragment HTML d'une figure, Plotly.js étant chargé une fois par la page."""
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       div_id=div_id, config=PLOTLY_CONFIG)
