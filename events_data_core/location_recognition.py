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
        entity_group = entity['entity_group']
        if entity_group not in geo_groups:
            continue

        word = entity["word"]
        start, end = entity["start"], entity["end"]

        if word.startswith("##"):
            # находим индекс начала слова
            left_index = _left_word_index(text, start)
            full_word = text[left_index:end]

            if result:
                last_word, last_start, last_end, last_type = result[-1]

                # если предыдущая сущность пересекается — обновляем
                if last_end >= left_index and last_type == entity_group:
                    result[-1] = (text[last_start:end], last_start, end, last_type)
                else:
                    result.append((full_word, left_index, end, entity_group))
            else:
                result.append((full_word, left_index, end, entity_group))
        elif i > 0 and entities[i - 1]['end'] == start:
            # слипающиеся токены (например дефис)
            prev_type = entities[i - 1]['entity_group']
            if result and prev_type == entity_group:
                last_word, last_start, last_end, last_type = result.pop()
                new_word = last_word + word
                result.append((new_word, last_start, end, last_type))
            else:
                result.append((word, start, end, entity_group))
        elif i > 0 and start - entities[i - 1]['end'] == 1:
            # токены разделены пробелом — соединяем с пробелом
            prev_type = entities[i - 1]['entity_group']
            if result and prev_type == entity_group:
                last_word, last_start, last_end, last_type = result.pop()
                new_word = last_word + " " + word
                result.append((new_word, last_start, end, last_type))
            else:
                result.append((word, start, end, entity_group))
        else:
            result.append((word, start, end, entity_group))

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


def merge_overlapping_spans(spans):
    """
    Убирает перекрывающиеся спаны, оставляя самый длинный.
    spans: список кортежей (word, start, end, label)
    """
    if not spans:
        return []

    # сортируем по началу, затем по длине (длинные вперёд при равных start)
    spans = sorted(spans, key=lambda x: (x[1], -(x[2] - x[1])))

    merged = []
    for span in spans:
        word, start, end, label = span
        if not merged:
            merged.append(span)
            continue

        last_word, last_start, last_end, last_label = merged[-1]

        # Проверка на перекрытие
        if start < last_end:
            # Если перекрываются — оставляем самый длинный
            last_len = last_end - last_start
            cur_len = end - start
            if cur_len > last_len:
                merged[-1] = span  # заменяем
            # если равные — можно оставить первый (ничего не делаем)
        else:
            merged.append(span)

    return merged


def get_original_loc(text, loc_spans):
    '''Достает по индексам начала и конца токена из массива locations оригинальные сущности'''
    clean_spans = merge_overlapping_spans(loc_spans)
    return [get_original_word(text, start, end) for _, start, end, _ in clean_spans]


def extract_loc(text) -> list[str]:
    return get_original_loc(text, extract_loc_spans(text))
