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

import plotly.graph_objects as go

from dash import Dash, dcc, html, Input, Output


def plot_2d_events(x, y, events, xlabel=None, ylabel=None, title=None):
    # === Основная функция построения графика ===
    def make_figure(highlight_event=None):
        fig = go.Figure()

        # 🔹 1. Основная синяя линия — всегда видна
        fig.add_trace(go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name="Цена акции",
            line=dict(color="steelblue", width=2),
            hoverinfo="skip",
            showlegend=True
        ))

        # 🔹 2. Красная линия (подсветка) — всегда существует, просто пустая, если нет выбранного события
        highlight_x, highlight_y = [], []
        if highlight_event:
            row = events.loc[events["event"] == highlight_event].iloc[0]
            start, end = row["date_start"], row["date_end"]
            if pd.notnull(end):
                mask = (x >= start) & (x <= end)
                highlight_x = events.loc[mask, "DATE"]
                highlight_y = events.loc[mask, "CLOSE"]

        # добавляем трассу в любом случае
        fig.add_trace(go.Scatter(
            x=highlight_x if len(highlight_x) > 0 else [None],
            y=highlight_y if len(highlight_y) > 0 else [None],
            mode="lines",
            name="Период санкций",
            line=dict(color="red", width=4),
            hoverinfo="skip",
            showlegend=True
        ))

        # 🔹 3. Точки событий (hover-интерактив)
        for _, row in events.iterrows():
            start = row["date_start"]
            idx = (x - start).abs().idxmin()
            y_value = y
            label = row["event"]

            fig.add_trace(go.Scatter(
                x=[start],
                y=[y_value],
                mode="markers",
                marker=dict(size=10, color="red", line=dict(color="black", width=1)),
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    f"Период: {start.date()} – "
                    f"{row['date_end'].date() if pd.notnull(row['date_end']) else 'N/A'}"
                    "<extra></extra>"
                ),
                customdata=[label],
                showlegend=False
            ))

        # 🔹 4. Настройки оформления
        fig.update_layout(
            title="Подсветка линии графика в период санкций",
            xaxis_title="Дата",
            yaxis_title="Цена закрытия (₽)",
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

    # === Dash-приложение ===
    app = Dash(__name__)

    app.layout = html.Div([
        html.H3("Подсветка линии графика при наведении на событие", style={"textAlign": "center"}),
        dcc.Graph(id="sanctions-graph", figure=make_figure(), clear_on_unhover=True)
    ])

    @app.callback(
        Output("sanctions-graph", "figure"),
        Input("sanctions-graph", "hoverData")
    )
    def highlight_interval(hoverData):
        if hoverData and "points" in hoverData and hoverData["points"]:
            label = hoverData["points"][0].get("customdata")
            if isinstance(label, str):
                return make_figure(highlight_event=label)
        return make_figure()

    return app
