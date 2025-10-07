from typing import List, Optional

from matplotlib import pyplot as plt


def plot_2d(
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


import plotly.graph_objects as go


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
