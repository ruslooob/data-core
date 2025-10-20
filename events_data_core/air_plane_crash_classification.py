import spacy
from spacy.matcher import Matcher
from spacy.util import filter_spans

nlp = spacy.load("ru_core_news_lg")

matcher = Matcher(nlp.vocab)

# --- списки слов ---
aircraft_terms = [
    "самол[её]т", "авиалайнер", "вертол[её]т", "истребитель",
    "ту-", "ан-", "ил-", "ми-", "миг-", "cy-", "як-", "superjet", "боинг", "airbus",
]
crash_verbs = ["разбиться", "рухнуть", "упасть", "потерпеть"]

# === глагольные случаи (самолет разбился) ===
pattern_verb = [
    {"LOWER": {"REGEX": "|".join(aircraft_terms)}},
    {"TEXT": {"REGEX": ".+"}, "OP": "*"},
    {"LEMMA": {"IN": crash_verbs}}
]
# (разбился самолет)
pattern_verb_reversed = [
    {"LEMMA": {"IN": crash_verbs}},
    {"TEXT": {"REGEX": ".+"}, "OP": "*"},
    {"LOWER": {"REGEX": "|".join(aircraft_terms)}}
]
matcher.add("PLANE_CRASH_EVENT", [pattern_verb, pattern_verb_reversed])

# === Само по себе слово авиакатастрофа автоматически сигнализирует о матче ===
plane_crash_pattern = [[{"LEMMA": {"IN": ["авиакатастрофа"]}}]]
matcher.add("CRASH_EVENT", plane_crash_pattern)

# === существительные случаи (крушение) ===
crash_nouns = ["крушение", "столкновение", "авария", "катастрофа"]
# (крушение самолета)
pattern_noun = [
    {"LEMMA": {"IN": crash_nouns}},
    {"TEXT": {"REGEX": ".+"}, "OP": "*"},
    {"LOWER": {"REGEX": "|".join(aircraft_terms)}}
]
# (самолет совершил столкновение)
pattern_noun_reversed = [
    {"LOWER": {"REGEX": "|".join(aircraft_terms)}},
    {"TEXT": {"REGEX": ".+"}, "OP": "*"},
    {"LEMMA": {"IN": crash_nouns}}
]
matcher.add("PLANE_CRASH_EVENT", [pattern_noun, pattern_noun_reversed])

# === отдельного внимания заслуживает аварийная посадка
pattern_emergency = [
    {"LEMMA": "аварийный"},
    {"LEMMA": "посадка"},
    {"LOWER": {"REGEX": "|".join(aircraft_terms)}, "OP": "?"}
]
matcher.add("PLANE_CRASH_EVENT", [pattern_emergency])


def find_matches(text):
    doc = nlp(text)

    # === поиск ===
    matches = matcher(doc)

    # --- собираем спаны с метками ---
    spans = []
    for match_id, start, end in matches:
        label = nlp.vocab.strings[match_id]
        span = doc[start:end]
        spans.append((label, span))

    # --- убираем дубликаты и вложенные спаны ---
    unique_spans = filter_spans([s for _, s in spans])

    final_spans = []
    for sent in doc.sents:
        sent_spans = [s for s in unique_spans if s.start >= sent.start and s.end <= sent.end]
        if sent_spans:
            # берём самый длинный (по количеству токенов)
            longest = max(sent_spans, key=lambda s: s.end - s.start)
            final_spans.append(longest)
    return final_spans


def is_plane_crash(text):
    return bool(find_matches(text))
