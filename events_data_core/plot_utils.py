import json
from typing import List, Optional

from matplotlib import pyplot as plt


def plot_2d_static(
        x: List,
        y: List,
        xlabel: Optional[str] = None,
        ylabel: Optional[str] = None,
        title: Optional[str] = None,
        color: str = "tab:blue", linewidth: float = 1.8,
        grid: bool = True,
        show: bool = True
):
    """
    Простая функция для построения 2D-графика.

    Параметры:
        x: список или массив значений по оси X
        y: список или массив значений по оси Y
        xlabel: подпись оси X (опционально)
        ylabel: подпись оси Y (опционально)
        title: заголовок графика (опционально)
        color: цвет линии (по умолчанию "tab:blue")
        linewidth: толщина линии
        grid: показывать ли сетку
        show: если True, вызывает plt.show()
    """
    if len(x) != len(y):
        raise ValueError("Длины массивов X и Y должны совпадать")

    plt.figure(figsize=(12, 6))
    plt.plot(x, y, color=color, linewidth=linewidth)

    if xlabel:
        plt.xlabel(xlabel)
    if ylabel:
        plt.ylabel(ylabel)
    if title:
        plt.title(title)

    if grid:
        plt.grid(True, linestyle="--", alpha=0.6)

    plt.tight_layout()

    if show:
        plt.show()


def plot_2d_interactive(x, y, xlabel=None, ylabel=None, title=None):
    """
    Строит интерактивный 2D-график с возможностью наведения на точки.
    """
    fig = go.Figure()

    # Добавляем линию
    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode="lines",
        line=dict(width=2, color="royalblue"),
        hovertemplate="Дата: %{x}<br>Значение: %{y:.4f} <extra></extra>"
    ))

    # Настраиваем внешний вид
    fig.update_layout(
        title=title,
        xaxis_title=xlabel,
        yaxis_title=ylabel,
        hovermode="x unified",
        template="plotly_white",
        width=1100,
        height=600
    )

    fig.show()


def plot_2d(x, y, xlabel=None, ylabel=None, title=None, type='interactive'):
    if type == 'interactive':
        plot_2d_interactive(x, y, xlabel, ylabel, title)
    elif type == 'plain':
        plot_2d_static(x, y, xlabel, ylabel, title)
    elif type == 'interactive_event_interval':
        plot_2d_interactive(x, y, xlabel, ylabel, title)


import pandas as pd

from dash import Dash, html, dcc, Input, Output
import plotly.graph_objects as go


def plot_2d_events(x, y, events, xlabel=None, ylabel=None, title=None):
    # --- normalize types ---
    x = pd.to_datetime(pd.Series(x))
    y = pd.Series(y)

    events = events.copy()
    events["date_start"] = pd.to_datetime(events["date_start"])
    events["date_end"] = pd.to_datetime(events["date_end"])

    # будем использовать уникальный id события (надежнее, чем текст)
    if "id" not in events.columns:
        raise ValueError("events must contain column 'id'")

    # --- figure builder ---
    def make_figure(highlight_event_id=None):
        fig = go.Figure()

        # 1) основная синяя линия — НЕ участвует в hover, чтобы не перехватывать hoverData
        fig.add_trace(go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name="Цена акции",
            line=dict(color="steelblue", width=2),
            hoverinfo="none",          # важно
            hovertemplate=None,
            showlegend=True
        ))

        # 2) красная подсветка интервала (одна трасса)
        highlight_x, highlight_y = [None], [None]
        if highlight_event_id is not None:
            row = events.loc[events["id"] == highlight_event_id].iloc[0]
            start, end = row["date_start"], row["date_end"]

            if pd.notnull(end):
                mask = (x >= start) & (x <= end)
            else:
                mask = (x >= start)

            hx = x[mask]
            hy = y[mask]
            if len(hx) > 0:
                highlight_x, highlight_y = hx, hy

        fig.add_trace(go.Scatter(
            x=highlight_x,
            y=highlight_y,
            mode="lines",
            name="Период санкций",
            line=dict(color="red", width=4),
            hoverinfo="none",
            hovertemplate=None,
            showlegend=True
        ))

        # 3) маркеры событий (hover по ним)
        for _, row in events.iterrows():
            start = row["date_start"]
            end = row["date_end"]
            label = row["event"]
            event_id = row["id"]

            # ближайшая точка цены к start
            idx = (x - start).abs().idxmin()
            y_value = y.loc[idx]

            fig.add_trace(go.Scatter(
                x=[start],
                y=[y_value],
                mode="markers",
                marker=dict(size=12, color="red", line=dict(color="black", width=1)),
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    f"Период: {start.date()} – {end.date() if pd.notnull(end) else 'N/A'}"
                    "<extra></extra>"
                ),
                customdata=[event_id],   # важно: именно id
                showlegend=False
            ))

        fig.update_layout(
            title=title or "Подсветка линии в период санкций",
            xaxis_title=xlabel or "Дата",
            yaxis_title=ylabel or "Цена закрытия",
            template="plotly_white",
            height=600,
            hovermode="closest",
            margin=dict(l=40, r=40, t=70, b=40),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.08,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="lightgray",
                borderwidth=1,
                font=dict(size=12)
            )
        )

        return fig

    app = Dash(__name__)
    app.layout = html.Div([
        html.H3("Подсветка линии при наведении на событие", style={"textAlign": "center"}),
        dcc.Graph(id="sanctions-graph", figure=make_figure(), clear_on_unhover=True)
    ])

    @app.callback(
        Output("sanctions-graph", "figure"),
        Input("sanctions-graph", "hoverData")
    )
    def highlight_interval(hoverData):
        if hoverData and hoverData.get("points"):
            cd = hoverData["points"][0].get("customdata")
            # customdata обычно приходит как скаляр или как список из 1 элемента
            if isinstance(cd, (list, tuple)):
                cd = cd[0] if cd else None
            return make_figure(highlight_event_id=cd)
        return make_figure()

    return app