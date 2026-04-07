import spacy
from spacy.matcher import Matcher
from spacy.util import filter_spans


class PlaneCrashClassifier:
    def __init__(self, model_name: str = "ru_core_news_lg"):
        self._model_name = model_name
        self._nlp = None
        self._matcher = None

    def _ensure_loaded(self):
        if self._nlp is not None:
            return

        self._nlp = spacy.load(self._model_name)
        self._matcher = Matcher(self._nlp.vocab)
        self._setup_default_patterns()

    def _setup_default_patterns(self):
        aircraft_terms = [
            "самол[её]т", "авиалайнер", "вертол[её]т", "истребитель",
            "ту-", "ан-", "ил-", "ми-", "миг-", "cy-", "як-", "superjet", "боинг", "airbus",
        ]
        crash_verbs = ["разбиться", "рухнуть", "упасть", "потерпеть"]
        crash_nouns = ["крушение", "столкновение", "авария", "катастрофа"]

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
        self._matcher.add("PLANE_CRASH_EVENT", [pattern_verb, pattern_verb_reversed])

        # === Само по себе слово авиакатастрофа автоматически сигнализирует о матче ===
        self._matcher.add("PLANE_CRASH_EVENT", [[{"LEMMA": {"IN": ["авиакатастрофа"]}}]])

        # === существительные случаи (крушение самолета) ===
        pattern_noun = [
            {"LEMMA": {"IN": crash_nouns}},
            {"TEXT": {"REGEX": ".+"}, "OP": "*"},
            {"LOWER": {"REGEX": "|".join(aircraft_terms)}}
        ]
        # (самолет потерпел крушение)
        pattern_noun_reversed = [
            {"LOWER": {"REGEX": "|".join(aircraft_terms)}},
            {"TEXT": {"REGEX": ".+"}, "OP": "*"},
            {"LEMMA": {"IN": crash_nouns}}
        ]
        self._matcher.add("PLANE_CRASH_EVENT", [pattern_noun, pattern_noun_reversed])

        # === аварийная посадка ===
        pattern_emergency = [
            {"LEMMA": "аварийный"},
            {"LEMMA": "посадка"},
            {"LOWER": {"REGEX": "|".join(aircraft_terms)}, "OP": "?"}
        ]
        self._matcher.add("PLANE_CRASH_EVENT", [pattern_emergency])

    def add_pattern(self, name: str, patterns: list):
        """Добавить пользовательский паттерн к матчеру."""
        self._ensure_loaded()
        self._matcher.add(name, patterns)

    def find_matches(self, text: str) -> list[tuple[str, object]]:
        """
        Найти совпадения в тексте.
        Возвращает список (label, span) — по одному самому длинному спану на предложение.
        """
        self._ensure_loaded()
        doc = self._nlp(text)
        matches = self._matcher(doc)

        spans_with_labels = [
            (self._nlp.vocab.strings[match_id], doc[start:end])
            for match_id, start, end in matches
        ]

        # убираем вложенные/дублирующиеся спаны
        filtered_keys = {(s.start, s.end) for s in filter_spans([s for _, s in spans_with_labels])}
        filtered = [(l, s) for l, s in spans_with_labels if (s.start, s.end) in filtered_keys]

        # берём самый длинный спан на каждое предложение
        final = []
        for sent in doc.sents:
            sent_spans = [(l, s) for l, s in filtered if s.start >= sent.start and s.end <= sent.end]
            if sent_spans:
                final.append(max(sent_spans, key=lambda ls: ls[1].end - ls[1].start))
        return final

    def is_plane_crash(self, text: str) -> bool:
        """Вернуть True, если текст описывает авиакатастрофу."""
        return bool(self.find_matches(text))

    def classify_series(self, texts) -> list[bool]:
        """
        Классифицировать список текстов.
        Использует nlp.pipe() для батч-обработки — быстрее, чем is_plane_crash по одному.
        """
        self._ensure_loaded()
        return [
            bool(self._matcher(doc))
            for doc in self._nlp.pipe(texts)
        ]
