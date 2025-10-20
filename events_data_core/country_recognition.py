import re

from transformers import pipeline

ner_pipe = pipeline("ner", model="Gherman/bert-base-NER-Russian", aggregation_strategy="simple")

geo_groups = {"REGION", "CITY", "COUNTRY", "DISTRICT"}


def _left_word_index(text, pos):
    """Найти индекс начала слова, идущего до позиции pos."""
    i = pos - 1
    while i >= 0 and (text[i].isalpha() or text[i] in "-–—"):
        i -= 1
    return i + 1


def extract_loc_spans(text):
    """Возвращает обнаруженное слово и его начальные и конечные индексы. Сцепляет очевидные разделенные моделью токены"""
    entities = ner_pipe(text)
    result = []

    for i, entity in enumerate(entities):
        if entity['entity_group'] not in geo_groups:
            continue

        word = entity["word"]
        start, end = entity["start"], entity["end"]

        if word.startswith("##"):
            # находим индекс начала слова
            left_index = _left_word_index(text, start)
            full_word = text[left_index:end]

            if result:
                last_word, last_start, last_end = result[-1]

                # если предыдущая сущность пересекается — обновляем
                if last_end >= left_index:
                    result[-1] = (text[last_start:end], last_start, end)
                else:
                    result.append((full_word, left_index, end))
            else:
                result.append((full_word, left_index, end))
        elif i > 0 and entities[i - 1]['end'] == start and result:
            # слипающиеся токены (например дефис)
            last = result.pop()
            last_word, last_start, last_end = last
            new_word = last_word + word
            result.append((new_word, last_start, end))
        elif i > 0 and start - entities[i - 1]['end'] == 1 and result:
            # токены разделены пробелом — соединяем с пробелом
            last = result.pop()
            last_word, last_start, last_end = last
            new_word = last_word + " " + word
            result.append((new_word, last_start, end))
        else:
            result.append((word, start, end))

    return result


def get_original_word(text: str, start: int, end: int) -> str:
    """
    Возвращает оригинальное слово из текста, расширяя диапазон (start, end)
    до ближайших границ слова.
    """
    left = start
    while left > 0 and re.match(r"[A-Za-zА-Яа-яЁё\-–—]", text[left - 1]):
        left -= 1

    right = end
    while right < len(text) and re.match(r"[A-Za-zА-Яа-яЁё\-–—]", text[right]):
        right += 1

    return text[left:right].strip(" ,.;:!?()[]{}«»\"'—–")


def get_original_loc(text, loc_spans):
    '''Достает по индексам начала и конца токена из массива locations оригинальные сущности'''
    return [get_original_word(text, start, end) for _, start, end in loc_spans]


def extract_loc(text) -> list[str]:
    return get_original_loc(text, extract_loc_spans(text))
