FROM postgres:16

# plpython3u — untrusted PL/Python: позволяет писать UDF на Python внутри
# Postgres. Нужно для CAR/vol_ratio/volume_ratio + TA-функций бэктеста,
# которые используют pandas/numpy.
#
# pandas/numpy/scipy ставим apt'ом (системные пакеты), а не через pip —
# образ debian-12 идёт с Python 3.11, но pip-пакеты numpy/pandas/scipy
# для него не имеют готовых wheel'ов в pypi и пытаются компилировать
# из исходников (нужен gcc + build-essential, +500MB образа). Системные
# debian-пакеты уже скомпилированы; версии чуть старее (numpy 1.24,
# pandas 1.5.3, scipy 1.10), но для CAR/vol_ratio это нормально —
# алгоритмы используют общеупотребительные API.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        postgresql-plpython3-16 \
        python3-numpy \
        python3-pandas \
        python3-scipy \
 && rm -rf /var/lib/apt/lists/*
