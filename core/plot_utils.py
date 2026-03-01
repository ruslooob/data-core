import socket
from typing import List, Optional

import pandas as pd
from matplotlib import pyplot as plt
from dash import Dash, html, dcc, Input, Output, Patch
import plotly.graph_objects as go

from core.cpi_data_provider import load_normalized_ipc_data, IpcType


def _find_free_port(min_port: int = 10001) -> int:
    """Находит свободный порт начиная с min_port."""
    port = min_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
        port += 1


class _DashApp:
    """Обёртка над Dash-приложением с автоматически выбранным свободным портом."""

    def __init__(self, app: Dash):
        self._app = app
        self._port = _find_free_port()

    def run(self, **kwargs):
        kwargs.setdefault('port', self._port)
        kwargs.setdefault('jupyter_mode', 'inline')
        self._app.run(**kwargs)


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

    return fig


def plot_2d(x, y, xlabel=None, ylabel=None, title=None, mode='interactive'):
    if mode == 'interactive':
        return plot_2d_interactive(x, y, xlabel, ylabel, title)
    elif mode == 'plain':
        return plot_2d_static(x, y, xlabel, ylabel, title)
    else:
        raise NotImplementedError


def plot_price_real(
        stock_data: pd.DataFrame,
        normalize_date: str,
        cpi_normalized: bool = True,
        cpi_base_date: str = '2022-01-01',
        cpi_type: IpcType = IpcType.GOODS_AND_SERVICES,
        events_df: pd.DataFrame = None,
        title: Optional[str] = None,
):
    """
    Dash-приложение: нормализованный график цены акции с маркерами событий.

    Цена нормируется к normalize_date = 100.
    Если cpi_normalized=True — корректируется на инфляцию через real_ruble.
    Если передан events_df — показываются маркеры событий на цене:
      при наведении отображается текст события и затемняется интервал date_start–date_end.

    Параметры:
        stock_data:      DataFrame с колонками DATE и CLOSE
        normalize_date:  дата, относительно которой нормировать (= 100)
        cpi_normalized:  применять поправку на инфляцию
        cpi_base_date:   базовая дата для CPI (только при cpi_normalized=True)
        cpi_type:        тип ИПЦ (только при cpi_normalized=True)
        events_df:       опционально — DataFrame с колонками id, date_start, date_end, event
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

    x = pd.Series(dates.values)
    y = pd.Series(price_norm)

    cpi_label = f', поправка на ИПЦ (база {cpi_base_date})' if cpi_normalized else ''
    default_title = title or f'Нормализованная цена акции{cpi_label}, {normalize_date} = 100'

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode='lines',
        line=dict(color='steelblue', width=2),
        name='Цена акции',
        hovertemplate='%{x|%d.%m.%Y}: %{y:.2f}<extra></extra>',
        showlegend=True,
    ))

    events = None
    if events_df is not None:
        events = events_df.copy()
        events['date_start'] = pd.to_datetime(events['date_start'])
        events['date_end'] = pd.to_datetime(events['date_end'])

        if 'id' not in events.columns:
            raise ValueError("events_df must contain column 'id'")

        for _, row in events.iterrows():
            start = row['date_start']
            end = row['date_end']
            label = row['event']
            event_id = row['id']

            idx = (x - start).abs().idxmin()
            y_value = y.loc[idx]

            fig.add_trace(go.Scatter(
                x=[start],
                y=[y_value],
                mode='markers',
                marker=dict(size=9, color='crimson', line=dict(color='white', width=1)),
                hovertemplate=(
                    f'<b>{label}</b><br>'
                    f'{start.date()} – {end.date() if pd.notnull(end) else "..."}'
                    '<extra></extra>'
                ),
                customdata=[event_id],
                showlegend=False,
            ))

    fig.update_layout(
        title=default_title,
        xaxis=dict(
            title='Дата',
            showspikes=True,
            spikemode='across',
            spikesnap='cursor',
            spikecolor='rgba(100,100,100,0.4)',
            spikethickness=1,
            spikedash='dot',
        ),
        yaxis_title=f'Индекс ({normalize_date} = 100)',
        template='plotly_white',
        height=500,
        hovermode='closest',
    )

    app = Dash(__name__)
    app.layout = html.Div([
        dcc.Graph(id='price-real-graph', figure=fig, clear_on_unhover=True)
    ])

    @app.callback(
        Output('price-real-graph', 'figure'),
        Input('price-real-graph', 'hoverData')
    )
    def highlight_interval(hoverData):
        patched = Patch()

        if hoverData and hoverData.get('points') and events is not None:
            cd = hoverData['points'][0].get('customdata')
            if isinstance(cd, (list, tuple)):
                cd = cd[0] if cd else None

            if cd is not None:
                row = events.loc[events['id'] == cd].iloc[0]
                patched['layout']['shapes'] = [{
                    'type': 'rect',
                    'x0': str(row['date_start']),
                    'x1': str(row['date_end']),
                    'y0': 0,
                    'y1': 1,
                    'yref': 'paper',
                    'fillcolor': 'rgba(0,0,0,0.10)',
                    'line': {'width': 0},
                    'layer': 'below',
                }]
                return patched

        patched['layout']['shapes'] = []
        return patched

    return _DashApp(app)


def plot_2d_events(x, y, events, xlabel=None, ylabel=None, title=None):
    """
    Dash-приложение: график цены акции с маркерами событий.
    При наведении на маркер показывает текст события и затемняет интервал date_start–date_end.

    events должен содержать колонки: id, date_start, date_end, event
    """
    x = pd.to_datetime(pd.Series(x))
    y = pd.Series(y)

    events = events.copy()
    events["date_start"] = pd.to_datetime(events["date_start"])
    events["date_end"] = pd.to_datetime(events["date_end"])

    if "id" not in events.columns:
        raise ValueError("events must contain column 'id'")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode="lines",
        name="Цена акции",
        line=dict(color="steelblue", width=2),
        hovertemplate='%{x|%d.%m.%Y}: %{y:.2f}<extra></extra>',
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
            marker=dict(size=9, color="crimson", line=dict(color="white", width=1)),
            hovertemplate=(
                f"<b>{label}</b><br>"
                f"{start.date()} – {end.date() if pd.notnull(end) else '...'}"
                "<extra></extra>"
            ),
            customdata=[event_id],
            showlegend=False
        ))

    fig.update_layout(
        title=title or "График цены с событиями",
        xaxis=dict(
            title=xlabel or "Дата",
            showspikes=True,
            spikemode='across',
            spikesnap='cursor',
            spikecolor='rgba(100,100,100,0.4)',
            spikethickness=1,
            spikedash='dot',
        ),
        yaxis_title=ylabel or "Цена закрытия",
        template="plotly_white",
        height=600,
        hovermode="closest",
        margin=dict(l=40, r=40, t=70, b=40),
    )

    app = Dash(__name__)
    app.layout = html.Div([
        dcc.Graph(id="events-graph", figure=fig, clear_on_unhover=True)
    ])

    @app.callback(
        Output("events-graph", "figure"),
        Input("events-graph", "hoverData")
    )
    def highlight_interval(hoverData):
        patched = Patch()

        if hoverData and hoverData.get("points"):
            cd = hoverData["points"][0].get("customdata")
            if isinstance(cd, (list, tuple)):
                cd = cd[0] if cd else None

            if cd is not None:
                row = events.loc[events["id"] == cd].iloc[0]
                patched["layout"]["shapes"] = [{
                    "type": "rect",
                    "x0": str(row["date_start"]),
                    "x1": str(row["date_end"]),
                    "y0": 0,
                    "y1": 1,
                    "yref": "paper",
                    "fillcolor": "rgba(0,0,0,0.10)",
                    "line": {"width": 0},
                    "layer": "below",
                }]
                return patched

        patched["layout"]["shapes"] = []
        return patched

    return _DashApp(app)
