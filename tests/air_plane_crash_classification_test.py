import pytest

from events_data_core.air_plane_crash_classification import is_plane_crash

test_in_out = [
    ("Крушение авиалайнера «Saab 340» авиакомпании «Crossair» у деревни Нассенвиль.", True),
    ("Самолёт потерпел крушение в районе вулкана Опала на Камчатке.", True),
    ("Рухнула стена склада в Петербурге.", False),
    ("Вертолёт Ми-8 разбился при взлёте из аэропорта города Таманрассет.", True),
    ('SuperJet совершил аварийную посадку.', True),
    ('Произошла аварийная посадка самолета.', True),
    ('Авиакатастрофа в индонезии. Самолет superjet 100.', True),
    ('Крушение самолета в Израиле.', True),
    ('Самолёт «Fokker F28-1000 Fellowship» перуанской авиакомпании TANS Perú потерпел катастрофу на подлёте к аэропорту вблизи Чачапояс.',
     True),
    ('Самолет потерпел крушение в Израиле.', True),
    ('реактивный истребитель ВВС Нигерии F-7 потерпел крушение.', True),
]


@pytest.mark.parametrize("text,expected", test_in_out)
def test_normalize_sentence(text, expected):
    assert is_plane_crash(text) == expected
