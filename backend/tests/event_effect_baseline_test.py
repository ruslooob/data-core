"""Baseline-функции event_effect: знаковый vs абсолютный percentile rank.

Демонстрируют суть фикса шума: на асимметричном распределении псевдо-CAR
знаковый rank ловит направленную аномалию короткого хвоста, а абсолютный — нет.
"""
from core.event_effect import _percentile_rank, _signed_rank


def test_signed_rank_basic():
    dist = [-5.0, -3.0, -1.0, 0.0, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0]  # n=10
    assert _signed_rank(11.0, dist) == 1.0   # выше всех
    assert _signed_rank(-6.0, dist) == 0.0   # ниже всех
    assert _signed_rank(0.5, dist) == 0.4    # 4 значения строго меньше 0.5


def test_signed_rank_catches_short_tail_anomaly():
    # Длинный нижний хвост, короткий верхний — типичная асимметрия.
    dist = [-10.0, -8.0, -6.0, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0, 3.0]
    # +5% аномален вверх относительно собственного верхнего хвоста.
    assert _signed_rank(5.0, dist) > 0.95
    # Абсолютный baseline берёт большую (нижнюю) сторону и аномалию НЕ видит —
    # это и есть баг, который чинит знаковый rank.
    assert _percentile_rank(5.0, dist) < 0.95


def test_empty_distribution():
    assert _signed_rank(1.0, []) == 0.0
    assert _percentile_rank(1.0, []) == 0.0
