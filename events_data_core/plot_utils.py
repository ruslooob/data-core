from typing import List, Optional

import pandas as pd
from matplotlib import pyplot as plt
from dash import Dash, html, dcc, Input, Output, Patch
import plotly.graph_objects as go

from events_data_core.cpi_data_provider import load_normalized_ipc_data, IpcType


def plot_2d_static(
        x: List,
        y: List,
        xlabel: Optional[str] = None,
        ylabel: Optional[str] = None,
        title: Optional[str] = None,
        color: str = "tab:blue",
        linewidth: float = 1.8,
        grid: bool = True,
        show: bool = True
):
    """
    Простая функция для построения 2D-графика.
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

    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode="lines",
        line=dict(width=2, color="royalblue"),
        hovertemplate="Дата: %{x}<br>Значение: %{y:.4f} <extra></extra>"
    ))

    fig.update_layout(
        title=title,
        xaxis_title=xlabel,
        yaxis_title=ylabel,
        hovermode="x unified",
        template="plotly_white",
        width=1100,
        height=600
    )

    fig.show(renderer='browser')


def plot_2d(x, y, xlabel=None, ylabel=None, title=None, mode='interactive'):
    if mode == 'interactive':
        plot_2d_interactive(x, y, xlabel, ylabel, title)
    elif mode == 'plain':
        plot_2d_static(x, y, xlabel, ylabel, title)


def plot_price_real(
        stock_data: pd.DataFrame,
        normalize_date: str,
        cpi_normalized: bool = True,
        cpi_base_date: str = '2022-01-01',
        cpi_type: IpcType = IpcType.GOODS_AND_SERVICES,
        events_df: Optional[pd.DataFrame] = None,
        title: Optional[str] = None,
) -> go.Figure:
    """
    Строит нормализованный график цены акции.

    Цена нормируется к normalize_date = 100.
    Если cpi_normalized=True — сначала корректируется на инфляцию
    через real_ruble из load_normalized_ipc_data.

    Параметры:
        stock_data:      DataFrame с колонками DATE и CLOSE
        normalize_date:  дата, относительно которой нормировать (= 100)
        cpi_normalized:  применять поправку на инфляцию
        cpi_base_date:   базовая дата для CPI (только при cpi_normalized=True)
        cpi_type:        тип ИПЦ (только при cpi_normalized=True)
        events_df:       опционально — DataFrame с колонками date_start и event
                         для отрисовки вертикальных меток событий
        title:           заголовок графика
    """
    stock = stock_data.copy()
    stock['DATE'] = pd.to_datetime(stock['DATE'])
    stock = stock.sort_values('DATE').reset_index(drop=True)

    if cpi_normalized:
        cpi_norm = load_normalized_ipc_data(cpi_type, base_year=cpi_base_date)
        cpi_norm['date'] = pd.to_datetime(cpi_norm['date'])
        stock = pd.merge_asof(
            stock, cpi_norm[['date', 'real_ruble']],
            left_on='DATE', right_on='date', direction='backward'
        )
        price_series = stock['CLOSE'] * stock['real_ruble']
    else:
        price_series = stock['CLOSE']

    price_series = price_series.values
    dates = stock['DATE']

    normalize_ts = pd.Timestamp(normalize_date)
    ref_idx = (dates - normalize_ts).abs().idxmin()
    ref_price = price_series[ref_idx]
    if ref_price == 0:
        raise ValueError(f"Цена на дату {normalize_date} равна 0, нормировка невозможна")

    price_norm = price_series / ref_price * 100

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates,
        y=price_norm,
        mode='lines',
        line=dict(color='steelblue', width=2),
        name='Цена акции',
        hovertemplate='%{x|%d.%m.%Y}: %{y:.1f}<extra></extra>',
    ))

    fig.add_hline(
        y=100,
        line_dash='dash', line_color='red', line_width=1.5,
        annotation_text=f'{normalize_date} = 100',
        annotation_position='top left'
    )

    if events_df is not None:
        ev = events_df.copy()
        ev['date_start'] = pd.to_datetime(ev['date_start'])
        for _, row in ev.iterrows():
            ev_date = row['date_start']
            if ev_date >= dates.min():
                fig.add_vline(
                    x=ev_date,
                    line_width=1, line_dash='dot',
                    line_color='rgba(200,50,50,0.5)'
                )

    cpi_label = f', поправка на ИПЦ (база {cpi_base_date})' if cpi_normalized else ''
    fig.update_layout(
        title=title or f'Нормализованная цена акции{cpi_label}, {normalize_date} = 100',
        xaxis_title='Дата',
        yaxis_title=f'Индекс ({normalize_date} = 100)',
        template='plotly_white',
        height=500,
        hovermode='x unified',
    )

    return fig


def plot_2d_events(x, y, events, xlabel=None, ylabel=None, title=None):
    """
    Dash-приложение: график цены акции с маркерами событий.
    При наведении на маркер подсвечивает интервал события.

    events должен содержать колонки: id, date_start, date_end, event
    """
    x = pd.to_datetime(pd.Series(x))
    y = pd.Series(y)

    events = events.copy()
    events["date_start"] = pd.to_datetime(events["date_start"])
    events["date_end"] = pd.to_datetime(events["date_end"])

    if "id" not in events.columns:
        raise ValueError("events must contain column 'id'")

    def make_figure(highlight_event_id=None):
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name="Цена акции",
            line=dict(color="steelblue", width=2),
            hoverinfo="none",
            hovertemplate=None,
            showlegend=True
        ))

        highlight_x, highlight_y = [None], [None]
        if highlight_event_id is not None:
            row = events.loc[events["id"] == highlight_event_id].iloc[0]
            start, end = row["date_start"], row["date_end"]
            mask = (x >= start) & (x <= end) if pd.notnull(end) else (x >= start)
            hx, hy = x[mask], y[mask]
            if len(hx) > 0:
                highlight_x, highlight_y = hx, hy

        fig.add_trace(go.Scatter(
            x=highlight_x,
            y=highlight_y,
            mode="lines",
            name="Период события",
            line=dict(color="red", width=4),
            hoverinfo="none",
            hovertemplate=None,
            showlegend=True
        ))

        for _, row in events.iterrows():
            start = row["date_start"]
            end = row["date_end"]
            label = row["event"]
            event_id = row["id"]

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
                customdata=[event_id],
                showlegend=False
            ))

        fig.update_layout(
            title=title or "График цены с событиями",
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
        html.H3("График цены с событиями", style={"textAlign": "center"}),
        dcc.Graph(id="events-graph", figure=make_figure(), clear_on_unhover=True)
    ])

    @app.callback(
        Output("events-graph", "figure"),
        Input("events-graph", "hoverData")
    )
    def highlight_interval(hoverData):
        highlight_x, highlight_y = [None], [None]

        if hoverData and hoverData.get("points"):
            cd = hoverData["points"][0].get("customdata")
            if isinstance(cd, (list, tuple)):
                cd = cd[0] if cd else None

            if cd is not None:
                row = events.loc[events["id"] == cd].iloc[0]
                start, end = row["date_start"], row["date_end"]
                mask = (x >= start) & (x <= end) if pd.notnull(end) else (x >= start)
                hx, hy = x[mask], y[mask]
                if len(hx) > 0:
                    highlight_x, highlight_y = hx, hy

        patched = Patch()
        patched["data"][1]["x"] = list(highlight_x)
        patched["data"][1]["y"] = list(highlight_y)
        return patched

    return app
