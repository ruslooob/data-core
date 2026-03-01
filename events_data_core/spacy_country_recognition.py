import ast
from collections import OrderedDict
from typing import Optional

import spacy
from spacy.matcher import Matcher


class CountryRecognizer:
    """Распознаватель стран и городов в тексте на русском языке."""

    def __init__(self, model_name: str = "ru_core_news_lg"):
        self._model_name = model_name
        self._nlp = None
        self._matcher = None
        self._pattern_names: list[str] = []

    def _ensure_loaded(self):
        if self._nlp is None:
            self._nlp = spacy.load(self._model_name, disable=["parser", "ner"])
            self._matcher = Matcher(self._nlp.vocab)
            self._pattern_names = []
            self._register_patterns()

    def _add(self, name: str, patterns: list):
        self._matcher.add(name, patterns)
        self._pattern_names.append(name)

    def _register_patterns(self):
        # === Австралия ===
        self._add("AUSTRALIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(австрали|сидне|канберр).*"}}],
            [
                {"LOWER": {"REGEX": r"^содружеств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^австрали.{0,5}$"}}
            ]
        ])

        # === Австрия ===
        self._add("AUSTRIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(австри|вена).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^австри.{0,5}$"}}
            ]
        ])

        # === Азербайджан ===
        self._add("AZERBAIJAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(азербайджан|баку|бакинск).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^азербайджан.{0,5}"}}
            ]
        ])

        # === Албания ===
        self._add("ALBANIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(албан|тиран).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^албан.{0,5}$"}}
            ]
        ])

        # === Аргентина ===
        self._add("ARGENTINA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(аргентин).*"}}],
            [
                {"LOWER": {"REGEX": r"^аргентин.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^буэнос.{0,5}$"}},
                {"LOWER": {"REGEX": r"^айрес.{0,5}$"}}
            ],
        ])

        # === Армения ===
        self._add("ARMENIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(армени|ереван).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^армени.{0,5}"}}
            ]
        ])

        # === Афганистан ===
        self._add("AFGHANISTAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(афган|кабул).*"}}],
            [
                {"LOWER": {"REGEX": r"^исламск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^афган.{0,5}$"}}
            ]
        ])

        # === Беларусь ===
        self._add("BELARUS_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(беларус|белорус|минск).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^беларус.{0,5}"}}
            ]
        ])

        # === Бельгия ===
        self._add("BELGIUM_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(бельги|брюссел).*"}}],
            [
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^бельги.{0,5}$"}}
            ]
        ])

        # === Болгария ===
        self._add("BULGARIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(болгар|софия).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^болгар.{0,5}$"}}
            ]
        ])

        # === Босния и Герцеговина ===
        self._add("BOSNIA-HERZEGOVINA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(босни|герцеговин|сараев).*"}}],
            [
                {"LOWER": {"REGEX": r"^босни.{0,5}$"}},
                {"LOWER": {"REGEX": r"^и.{0,5}$"}},
                {"LOWER": {"REGEX": r"^герцеговин.{0,5}$"}}
            ]
        ])

        # === Бразилия ===
        self._add("BRAZIL_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(бразил).*"}}],
            [
                {"LOWER": {"REGEX": r"^федеративн.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^бразил.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^рио.*$"}},
                {"ORTH": "-"},
                {"LOWER": {"REGEX": r"^де$"}},
                {"ORTH": "-"},
                {"LOWER": {"REGEX": r"^жанейр.*$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^сан.{0,5}$"}},
                {"LOWER": {"REGEX": r"^паул.{0,5}$"}}
            ],
        ])

        # === Великобритания ===
        self._add("UK_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(великобрит|британи|англи|лондон).*"}}],
            [
                {"LOWER": {"REGEX": r"^объединен.{0,5}$"}},
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}}
            ]
        ])

        # === Венгрия ===
        self._add("HUNGARY_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(венгр|будапешт).*"}}],
            [
                {"LOWER": {"REGEX": r"^венгерск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
            ]
        ])

        # === Венесуэла ===
        self._add("VENEZUELA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(венесуэл|каракас).*"}}],
            [
                {"LOWER": {"REGEX": r"^боливариан.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^венесуэл.{0,5}$"}}
            ]
        ])

        # === Германия ===
        self._add("GERMANY_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(берлин|герман|к[её]льн|немец|фрг).*"}}],
            [
                {"LOWER": {"REGEX": r"^федеративн.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^германи.{0,5}$"}}
            ]
        ])

        # === Греция ===
        self._add("GREECE_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(греци|афин).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^греци.{0,5}$"}}
            ]
        ])

        # === Грузия ===
        self._add("GEORGIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(грузин|грузия|тбилис).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^груз.{0,5}"}}
            ]
        ])

        # === Дания ===
        self._add("DENMARK_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(дания|датск|копенгаген).*"}}],
            [
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^дания.{0,5}$"}}
            ]
        ])

        # === Демократическая республика Конго ===
        self._add("DR-CONGO_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(конг|дкр).*"}}],
            [
                {"LOWER": {"REGEX": r"^демократ.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^конг.{0,5}$"}}
            ]
        ])

        # === Египет ===
        self._add("EGYPT_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(египт|египет|каир).*"}}],
            [
                {"LOWER": {"REGEX": r"^арабск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^египт.{0,5}$"}}
            ]
        ])

        # === Зимбабве ===
        self._add("ZIMBABWE_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(зимбабв|харар).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^зимбабв.{0,5}$"}}
            ]
        ])

        # === Израиль ===
        self._add("ISRAEL_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(израил|иерусалим).*"}}],
            [
                {"LOWER": {"REGEX": r"^государств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^израил.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^тель.{0,5}$"}},
                {"LOWER": {"REGEX": r"^авив.{0,5}$"}}
            ],
        ])

        # === Индия ===
        self._add("INDIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(индия|индий|дели|мумба|бенгалур).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^инд.{0,5}$"}}
            ]
        ])

        # === Иран ===
        self._add("IRAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(иран|тегеран).*"}}],
            [
                {"LOWER": {"REGEX": r"^исламск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^иран.{0,5}$"}}
            ]
        ])

        # === Ирак ===
        self._add("IRAQ_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(ирак|багдад).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^ирак.{0,5}$"}}
            ]
        ])

        # === Ирландия ===
        self._add("IRELAND_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(ирланд|дублин).*"}}],
            [
                {"LOWER": {"REGEX": r"^ирландск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
            ]
        ])

        # === Исландия ===
        self._add("ICELAND_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(исланди|рекьявик).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^исланди.{0,5}$"}}
            ]
        ])

        # === Испания ===
        self._add("SPAIN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(испани|мадрид).*"}}]
        ])

        # === Италия ===
        self._add("ITALY_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(итал|рим).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^итал.{0,5}$"}}
            ]
        ])

        # === Казахстан ===
        self._add("KAZAKHSTAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(казахстан|астан|алма-ат|алматы).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^казахстан.{0,5}$"}}
            ]
        ])

        # === Камбоджа ===
        self._add("CAMBODIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(камбодж|пномпень).*"}}],
            [
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^камбодж.{0,5}$"}}
            ]
        ])

        # === Канада ===
        self._add("CANADA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(канад|оттав|торонт|монреал).*"}}],
            [
                {"LOWER": {"REGEX": r"^канад.{0,5}$"}},
                {"LOWER": {"REGEX": r"^государств.{0,5}$"}}
            ]
        ])

        # === Кипр ===
        self._add("CYPRUS_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(кипр|никоси).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^кипр.{0,5}$"}}
            ]
        ])

        # === Китай ===
        self._add("CHINA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(гонконг|кита|кнр|пекин|пхеньян|шанхай).*"}}],
            [
                {"LOWER": {"REGEX": r"^китайск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^народн.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
            ]
        ])

        # === Колумбия ===
        self._add("COLOMBIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(колумб|богот).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^колумб.{0,5}$"}}
            ]
        ])

        # === Кыргызстан ===
        self._add("KYRGYZSTAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(киргиз|кыргыз|бишкек).*"}}],
            [
                {"LOWER": {"REGEX": r"^кыргызск.{0,5}"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}"}}
            ]
        ])

        # === Латвия ===
        self._add("LATVIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(латви|рига).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^латви.{0,5}$"}}
            ]
        ])

        # === Ливия ===
        self._add("LIBYA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(ливи|трипол).*"}}],
            [
                {"LOWER": {"REGEX": r"^государств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^ливи.{0,5}$"}}
            ]
        ])

        # === Литва ===
        self._add("LITHUANIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(литв|вильнюс).?"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^литв.{0,5}$"}}
            ]
        ])

        # === Люксембург ===
        self._add("LUXEMBOURG_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(люксембург).*"}}],
        ])

        # === Македония ===
        self._add("MACEDONIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(македон).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^македон.{0,5}$"}}
            ]
        ])

        # === Мальта ===
        self._add("MALTA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(мальт|валлетт).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^мальт.{0,5}$"}}
            ]
        ])

        # === Мексика ===
        self._add("MEXICO_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(мексик|мехик).*"}}]
        ])

        # === Молдова ===
        self._add("MOLDOVA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(молдов|кишинев).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^молдов.{0,5}"}}
            ]
        ])

        # === Нидерланды ===
        self._add("NETHERLANDS_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(нидерланд|голланд|амстердам).*"}}],
        ])

        # === Норвегия ===
        self._add("NORWAY_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(норвег|осло).*"}}],
            [
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^норвег.{0,5}$"}}
            ]
        ])

        # === Пакистан ===
        self._add("PAKISTAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(пакист|исламабад|карач).*"}}],
            [
                {"LOWER": {"REGEX": r"^исламск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^пакист.{0,5}$"}}
            ]
        ])

        # === Перу ===
        self._add("PERU_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(перу).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^перу.{0,5}$"}}
            ]
        ])

        # === Польша ===
        self._add("POLAND_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(польш|варшав).*"}}],
        ])

        # === Объединённые Арабские Эмираты (ОАЭ) ===
        self._add("UAE_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(оае|эмират|дуба).*"}}],
            [
                {"LOWER": {"REGEX": r"^объедин.{0,5}$"}},
                {"LOWER": {"REGEX": r"^араб.{0,5}$"}},
                {"LOWER": {"REGEX": r"^эмират.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^абу.{0,5}$"}},
                {"LOWER": {"REGEX": r"^даби.{0,5}$"}}
            ],
        ])

        # === Португалия ===
        self._add("PORTUGAL_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(португал|лиссабон).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^португал.{0,5}$"}}
            ]
        ])

        # === Россия ===
        self._add("RUSSIA_COUNTRY", [
            [{"LEMMA": {"IN": ["россия", "рф", "российский", "русский", "русь", "ссср"]}}],
            [
                {"LEMMA": "российский"},
                {"LEMMA": "федерация"}
            ],
        ])

        # === Россия: города и регионы ===
        self._add("RUSSIA_CITY", [
            [{"LOWER": {
                "REGEX": r"^(астрахан|брянск|волгоград|владикавказ|воронеж|дагестан|иркутск|калининград|казан|киров|магадан|новосибирск|москв|москов|перм|петербург|ростов|татарстан|твер|тульск|хабаровск|чечен|чечн).*"
            }}],
            [{"LOWER": {"IN": ["уфа", "уфе", "уфы", "чита", "чите", "самара", "самаре", "самары"]}}],
            # todo для самары сделать исключение остров самар и все
        ])

        # === Румыния ===
        self._add("ROMANIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(румын|бухарест).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^румын.{0,5}$"}}
            ]
        ])

        # === Саудовская Аравия ===
        self._add("SAUDI-ARABIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(саудов|арави).*"}}],
            [
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^арави.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^эр.{0,5}$"}},
                {"ORTH": "-"},
                {"LOWER": {"REGEX": r"^рияд.{0,5}$"}}
            ],
        ])

        # === Северная Корея (КНДР) ===
        self._add("NORTH-KOREA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(кндр|коре|пхеньян).*"}}],
            [
                {"LOWER": {"REGEX": r"^коре.{0,5}$"}},
                {"LOWER": {"REGEX": r"^народн.{0,5}$"}},
                {"LOWER": {"REGEX": r"^демократич.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
            ]
        ])

        # === Сербия ===
        self._add("SERBIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(серб|белград).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^серб.{0,5}$"}}
            ]
        ])

        # === Сингапур ===
        self._add("SINGAPORE_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(сингапур).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^сингапур.{0,5}$"}}
            ]
        ])

        # === Сирия ===
        self._add("SYRIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(сири|дамаск).*"}}],
            [
                {"LOWER": {"REGEX": r"^арабск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^сири.{0,5}$"}}
            ]
        ])

        # === Словакия ===
        self._add("SLOVAKIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(словак|братислав).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^словак.{0,5}$"}}
            ]
        ])

        # === Словения ===
        self._add("SLOVENIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(словен|люблян).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^словен.{0,5}$"}}
            ]
        ])

        # === США ===
        self._add("USA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(сша|(?<!северн)(?<!южн)(?<!латин).{0,3}америк).*"}}],
            [
                {"LOWER": {"REGEX": r"^соедин[её]н.{0,5}$"}},
                {"LOWER": {"REGEX": r"^штат.*"}}
            ],
        ])

        # === США: города и штаты ===
        self._add("USA_CITY", [
            [{"LOWER": {
                "REGEX": r"^(аляск|бостон|вашингтон|вирджин|джорджия|калифорн|майам|манхэтт|огайо|сиэтл|хьюстон|филадельф|чикаг).*"
            }}],
            [
                {"LOWER": {"REGEX": r"^лас.{0,5}$"}},
                {"ORTH": "-"},
                {"LOWER": {"REGEX": r"^вегас.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^лос.{0,5}$"}},
                {"ORTH": "-"},
                {"LOWER": {"REGEX": r"^анджелес.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^нью.{0,5}$"}},
                {"ORTH": "-"},
                {"LOWER": {"REGEX": r"^йорк.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^сан.{0,5}$"}},
                {"ORTH": "-"},
                {"LOWER": {"REGEX": r"^франциск.{0,5}$"}}
            ],
        ])

        # === Таджикистан ===
        self._add("TAJIKISTAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(таджик|душанб).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^таджик.{0,5}"}}
            ]
        ])

        # === Таиланд ===
        self._add("THAILAND_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(тайланд|бангкок).*"}}],
            [
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^тайланд.{0,5}$"}}
            ]
        ])

        # === Тайвань ===
        self._add("TAIWAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(тайван|тайпей).*"}}],
            [
                {"LOWER": {"REGEX": r"^кита.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^тайван.{0,5}$"}}
            ]
        ])

        # === Туркменистан ===
        self._add("TURKMENISTAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(туркмен|ашхабад).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^туркмен.{0,5}"}}
            ]
        ])

        # === Турция ===
        self._add("TURKEY_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(турци|анкар|стамб).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^турци.{0,5}$"}}
            ]
        ])

        # === Украина ===
        self._add("UKRAINE_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(украин|киев).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^украин.{0,5}"}}
            ]
        ])

        # === Узбекистан ===
        self._add("UZBEKISTAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(узбек|ташкент).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}"}},
                {"LOWER": {"REGEX": r"^узбек.{0,5}"}}
            ]
        ])

        # === Финляндия ===
        self._add("FINLAND_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(финлянд|хельсинк).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^финлянд.{0,5}$"}}
            ]
        ])

        # === Франция ===
        self._add("FRANCE_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(франц(?!иск)|француз|париж).*"}}],
        ])

        # === Хорватия ===
        self._add("CROATIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(хорват|загреб).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^хорват.{0,5}$"}}
            ]
        ])

        # === Черногория ===
        self._add("MONTENEGRO_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(черногор|подгориц).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^черногор.{0,5}$"}}
            ]
        ])

        # === Чехия ===
        self._add("CZECHIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(чех|прага|чешск).*"}}],
            [
                {"LOWER": {"REGEX": r"^чешск.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
            ]
        ])

        # === Чили ===
        self._add("CHILE_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(чили|сантьяго).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^чили.{0,5}$"}}
            ]
        ])

        # === Швейцария ===
        self._add("SWITZERLAND_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(швейцар|берн|цюрих|женев).*"}}],
            [
                {"LOWER": {"REGEX": r"^конфедерац.{0,5}$"}},
                {"LOWER": {"REGEX": r"^швейцар.{0,5}$"}}
            ]
        ])

        # === Швеция ===
        self._add("SWEDEN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(швед|швеци|стокгольм).*"}}],
            [
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
                {"LOWER": {"REGEX": r"^швед.{0,5}$"}}
            ]
        ])

        # === Шотландия ===
        self._add("SCOTLAND_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(шотланд|эдинбург).*"}}],
            [
                {"LOWER": {"REGEX": r"^шотланд.{0,5}$"}},
                {"LOWER": {"REGEX": r"^королевств.{0,5}$"}}
            ]
        ])

        # === Эквадор ===
        self._add("ECUADOR_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(эквадор|кито).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^эквадор.{0,5}$"}}
            ]
        ])

        # === Эстония ===
        self._add("ESTONIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(эстони|таллин).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^эстони.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^эстон.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
            ]
        ])

        # === Югославия (историческая) ===
        self._add("YUGOSLAVIA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(югослав|белград).*"}}],
            [
                {"LOWER": {"REGEX": r"^федерац.{0,5}$"}},
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^югослав.{0,5}$"}}
            ]
        ])

        # === Южная Корея ===
        self._add("SOUTH-KOREA_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(сеул|южнокорейск).*"}}],
            [
                {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
                {"LOWER": {"REGEX": r"^коре.{0,5}$"}}
            ],
            [
                {"LOWER": {"REGEX": r"^южн.{0,5}$"}},
                {"LOWER": {"REGEX": r"^коре.{0,5}$"}}
            ],
        ])

        # === Япония ===
        self._add("JAPAN_COUNTRY", [
            [{"LOWER": {"REGEX": r"^(япон|токио|киот).*"}}],
            [
                {"LOWER": {"REGEX": r"^япон.{0,5}$"}},
                {"LOWER": {"REGEX": r"^государств.{0,5}$"}}
            ]
        ])

        # todo заменить все .* на ограничитель
        # ливан

    def match_locations(self, text: str) -> Optional[list[str]]:
        """Определяет страны в тексте."""
        self._ensure_loaded()
        doc = self._nlp(text)
        matches = self._matcher(doc)

        countries = []
        for match_id, start, end in matches:
            rule_name = self._nlp.vocab.strings[match_id]
            country = rule_name.split("_")[0]
            countries.append(country)

        ordered_unique = list(OrderedDict.fromkeys(countries).keys())
        return ordered_unique if ordered_unique else None

    def match_locations_series(self, series: "pd.Series", batch_size: int = 64) -> "pd.Series":
        """Батчевая обработка колонки локаций через nlp.pipe() — быстрее, чем apply()."""
        import pandas as pd
        self._ensure_loaded()

        texts = list(series)

        results = []
        for doc in self._nlp.pipe(texts, batch_size=batch_size):
            matches = self._matcher(doc)
            countries = []
            for match_id, start, end in matches:
                rule_name = self._nlp.vocab.strings[match_id]
                country = rule_name.split("_")[0]
                countries.append(country)
            ordered_unique = list(OrderedDict.fromkeys(countries).keys())
            results.append(ordered_unique if ordered_unique else None)

        return pd.Series(results, index=series.index)

    def list_patterns(self) -> list[str]:
        """Возвращает список зарегистрированных паттернов."""
        self._ensure_loaded()
        return list(self._pattern_names)
