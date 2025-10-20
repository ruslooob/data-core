import pytest

from events_data_core.country_normalization import normalize_country, normalize_list
from events_data_core.country_recognition import extract_loc


def test_bert_country_ner(text, expected):
    assert extract_loc(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Хорватии", "Хорватия"),
    ("Союзной Республики Югославии", "Союзная Республика Югославия"),
    ("Гусиное Озеро", "Гусиное Озеро"),
    ("Коморские Острова", "Коморские Острова"),
    ("Российской Федерации", "Российская Федерация"),
    ("Республике Сербской", "Республика Сербская"),
    ("Республики Кыргызстан", "Республика Кыргызстан"),
    ("Демократической Республики Конго", "Демократическая Республика Конго"),
    ("Кыргызстане", "Кыргызстан"),

])
def test_normalize_sentence(text, expected):
    assert normalize_country(text) == expected


@pytest.mark.parametrize("list_text,expected", [
    ("['Российской Федерации', 'Беларуси', 'Москве']", "['Российская Федерация', 'Беларусь', 'Москва']"),
    ("['Боснии и Герцеговине', 'Республике Сербской']", "['Босния и Герцеговина', 'Республика Сербская']"),
    ("['Шотландии', 'Великобритании']", "['Шотландия', 'Великобритания']"),
    ("['Астане', 'Казахстан', 'Беларуси', 'Казахстана', 'Кыргызстана', 'России', 'Таджикистана']",
     "['Астана', 'Казахстан', 'Беларусь', 'Кыргызстан', 'Россия', 'Таджикистан']"),
])
def test_normalize_list(list_text, expected):
    assert normalize_list(list_text) == expected
