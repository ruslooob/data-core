import pymorphy3

morph = pymorphy3.MorphAnalyzer()

def normalize_country(text: str) -> str:
    """
    Приводит название страны в именительный падеж.
    Учитывает число прилагательного перед существительным
    (например, "Коморских Островах" -> "Коморские Острова").
    """
    words = text.strip().split()
    parsed = [morph.parse(w)[0] for w in words]
    result = []

    # Пройдём по словам, определяя ближайшее согласование
    for i, p in enumerate(parsed):
        w_nom = p.normal_form

        # --- Существительное ---
        if 'NOUN' in p.tag:
            number = p.tag.number
            gender = p.tag.gender

            # проверим прилагательное слева
            if i > 0 and 'ADJF' in parsed[i - 1].tag:
                adj = parsed[i - 1]
                if adj.tag.number == 'plur':
                    number = 'plur'  # переопределяем число на множественное

            features = {'nomn'}
            if number:
                features.add(number)
            if gender and number != 'plur':
                features.add(gender)

            inflected = p.inflect(features)
            if inflected:
                w_nom = inflected.word

        # --- Прилагательное ---
        elif 'ADJF' in p.tag:
            # ищем ближайшее существительное справа
            noun = None
            for j in range(i + 1, len(parsed)):
                if 'NOUN' in parsed[j].tag:
                    noun = parsed[j]
                    break

            features = {'nomn'}
            if noun:
                number = noun.tag.number
                gender = noun.tag.gender

                # если существительное ошибочно sing,gent, но прилагательное plur
                if p.tag.number == 'plur':
                    number = 'plur'

                if number:
                    features.add(number)
                if gender and number != 'plur':
                    features.add(gender)

            inflected = p.inflect(features)
            if inflected:
                w_nom = inflected.word

        else:
            inflected = p.inflect({'nomn'})
            if inflected:
                w_nom = inflected.word

        # сохраняем регистр
        orig = words[i]
        if orig and orig[0].isupper():
            w_nom = w_nom.capitalize()
        result.append(w_nom)

    return " ".join(result)


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
