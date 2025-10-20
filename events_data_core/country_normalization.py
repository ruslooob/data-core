import pymorphy3

morph = pymorphy3.MorphAnalyzer()


def normalize_country(country: str, morph=morph):
    """Приводит каждое слово в предложении к начальной форме. Внимание: функция может неправильно коверкать незнакомые слова (например населенный пункт Шали (несклоняемо), может превратить в Шаль)"""
    # разбиваем по пробелам, но не трогаем твою основную логику
    words = country.strip().replace("ё", "е").split()
    normalized_parts = []
    tags = []

    for word in words:
        parsed = morph.parse(word.lower())[0]
        norm = parsed.normal_form
        tags.append(parsed.tag)
        # сохраняем исходные заглавные буквы
        is_upper = [ch.isupper() for ch in word]
        result = []
        for i, ch in enumerate(norm):
            if i < len(is_upper) and is_upper[i]:
                result.append(ch.upper())
            else:
                result.append(ch)
        normalized_parts.append("".join(result))

    # собираем обратно в одну строку
    normalized_parts = postprocess_geo(normalized_parts, tags)

    # Собираем обратно в строку
    return " ".join(normalized_parts)


def _adj_to_feminine(adj: str) -> str:
    """Муж./общая база → жен. род: -ый/-ий → -ая/-яя (с учётом -ск/-ч/-ш)."""
    if adj.endswith("ый"):
        return adj[:-2] + "ая"
    if adj.endswith("ий"):
        base = adj[:-2]
        return base + ("ая" if base.endswith(("ск", "ч", "ш")) else "яя")
    return adj  # уже ок или не ADJF по форме


def _adj_to_neuter(adj: str) -> str:
    """Муж./общая база → ср. род: -ый/-ий → -ое/-ее."""
    if adj.endswith("ый"):
        return adj[:-2] + "ое"
    if adj.endswith("ий"):
        return adj[:-2] + "ее"
    return adj


def _adj_to_plural(adj: str) -> str:
    """Муж./общая база → мн. число: -ый/-ий → -ые/-ие."""
    if adj.endswith("ый"):
        return adj[:-2] + "ые"
    if adj.endswith("ий"):
        return adj[:-2] + "ие"
    return adj


# Частные «нормальные» формы нарицательных во мн. числе, когда рядом множественное прилагательное
_PLURAL_NOUN_FIX = {
    "штат": "штаты",
    "эмират": "эмираты",
    "остров": "острова",
}

# Фиксированные исключения (двухсловные паттерны), правим только прилагательное
_EXCEPTIONS = {
    ("Российский", "Федерация"): "Российская",
    ("Великий", "Британия"): "Великая",
    ("Соединенный", "Королевство"): "Соединенное",
}


def postprocess_geo(tokens, tags):
    """
    Постобработка геофраз (страны/гео-словосочетания) в начальную форму.
    - Согласует прилагательные с существительными по роду/числу.
    - Исправляет несколько типовых исключений.
    """
    tokens = tokens.copy()

    for i in range(len(tags) - 1):
        t1, t2 = tags[i], tags[i + 1]
        w1, w2 = tokens[i], tokens[i + 1]

        # ---- 0) Исключения-словари (двухсловные шаблоны) ----
        repl = _EXCEPTIONS.get((w1, w2))
        if repl:
            tokens[i] = repl

        # ---- 1) ADJF + NOUN: согласование по роду/числу ----
        if t1.POS == "ADJF" and t2.POS == "NOUN":
            # женский род (Республика, Федерация и т.п.)
            if "femn" in t2:
                tokens[i] = _adj_to_feminine(w1)

            # средний род (Озеро, Море — реже во «странах», но встречается в топонимах)
            elif "neut" in t2:
                tokens[i] = _adj_to_neuter(w1)

            # множественное число (Штаты, Эмираты, Острова, Нидерланды и т.п.)
            if "plur" in t2:
                tokens[i] = _adj_to_plural(tokens[i])
                low2 = w2.lower()
                for base, plural in _PLURAL_NOUN_FIX.items():
                    if low2.startswith(base) and w2.endswith(base[-1]):
                        tokens[i + 1] = plural.capitalize()
                        break

                if t1.POS == "ADJF":
                    if not tokens[i].endswith(("ые", "ие")):
                        tokens[i] = _adj_to_plural(tokens[i])

        # ---- 2) NOUN(femn) + ADJF: прилагательное после жен. сущ. → в жен. род ----
        if t1.POS == "NOUN" and "femn" in t1 and t2.POS == "ADJF":
            tokens[i + 1] = _adj_to_feminine(w2)

        # ---- 3) ADJF + ADJF + NOUN(femn): оба прилагательных → жен. род ----
        if (
                t1.POS == "ADJF" and t2.POS == "ADJF"
                and i + 2 < len(tags) and tags[i + 2].POS == "NOUN" and "femn" in tags[i + 2]
        ):
            tokens[i] = _adj_to_feminine(tokens[i])
            tokens[i + 1] = _adj_to_feminine(tokens[i + 1])

        # ---- 4) Спец-ошибка лемматизации: "Соединить Штат(ы) ..." → "Соединенные Штаты ..." ----
        if i == 0 and tokens[0] == "Соединить" and t2.POS == "NOUN":
            tokens[0] = "Соединенные"
            low2 = w2.lower()
            for base, plural in _PLURAL_NOUN_FIX.items():
                if low2.startswith(base) and w2.endswith(base[-1]):
                    tokens[1] = plural.capitalize()
                    break

    return tokens


def normalize_list(list_text):
    """
    list_text — это строка вроде '[Тикси, Николаев, Камбоджи, Туапсе]'
    """
    if isinstance(list_text, str):
        # удаляем квадратные скобки и разделяем по запятым
        inner = list_text.strip("[]")
        items = [x.strip()[1:-1] for x in inner.split(",") if x.strip()]
    elif isinstance(list_text, (list, tuple)):
        items = list_text
    else:
        return []

    norm_items = [normalize_country(x) for x in items if x]
    return str(list(dict.fromkeys(norm_items)))
