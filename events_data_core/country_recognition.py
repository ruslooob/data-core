import ast
from collections import OrderedDict

import spacy
from spacy.matcher import Matcher

nlp = spacy.load("ru_core_news_lg")

matcher = Matcher(nlp.vocab)

# === Австралия ===
pattern_australia = [
    [{"LOWER": {"REGEX": r"^(австрали|сидне|канберр).*"}}],
    [
        {"LOWER": {"REGEX": r"^содружеств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^австрали.{0,5}$"}}
    ]
]
matcher.add("AUSTRALIA_COUNTRY", pattern_australia)

# === Австрия ===
pattern_austria = [
    [{"LOWER": {"REGEX": r"^(австри|вена).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^австри.{0,5}$"}}
    ]
]
matcher.add("AUSTRIA_COUNTRY", pattern_austria)

# === Азербайджан ===
pattern_azerbaijan = [
    [{"LOWER": {"REGEX": r"^(азербайджан|баку|бакинск).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^азербайджан.{0,5}"}}
    ]
]
matcher.add("AZERBAIJAN_COUNTRY", pattern_azerbaijan)

# === Албания ===
pattern_albania = [
    [{"LOWER": {"REGEX": r"^(албан|тиран).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^албан.{0,5}$"}}
    ]
]
matcher.add("ALBANIA_COUNTRY", pattern_albania)

# === Аргентина ===
pattern_argentina = [
    [{"LOWER": {"REGEX": r"^(аргентин).*"}}],
    [
        {"LOWER": {"REGEX": r"^аргентин.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
    ],
    [
        {"LOWER": {"REGEX": r"^буэнос.{0,5}$"}},
        {"LOWER": {"REGEX": r"^айрес.{0,5}$"}}
    ],
]
matcher.add("ARGENTINA_COUNTRY", pattern_argentina)

# === Армения ===
pattern_armenia = [
    [{"LOWER": {"REGEX": r"^(армени|ереван).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^армени.{0,5}"}}
    ]
]
matcher.add("ARMENIA_COUNTRY", pattern_armenia)

# === Афганистан ===
pattern_afghanistan = [
    [{"LOWER": {"REGEX": r"^(афган|кабул).*"}}],
    [
        {"LOWER": {"REGEX": r"^исламск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^афган.{0,5}$"}}
    ]
]
matcher.add("AFGHANISTAN_COUNTRY", pattern_afghanistan)

# === Беларусь ===
pattern_belarus = [
    [{"LOWER": {"REGEX": r"^(беларус|белорус|минск).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^беларус.{0,5}"}}
    ]
]
matcher.add("BELARUS_COUNTRY", pattern_belarus)

# === Бельгия ===
pattern_belgium = [
    [{"LOWER": {"REGEX": r"^(бельги|брюссел).*"}}],
    [
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^бельги.{0,5}$"}}
    ]
]
matcher.add("BELGIUM_COUNTRY", pattern_belgium)

# === Болгария ===
pattern_bulgaria = [
    [{"LOWER": {"REGEX": r"^(болгар|софия).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^болгар.{0,5}$"}}
    ]
]
matcher.add("BULGARIA_COUNTRY", pattern_bulgaria)

# === Босния и Герцеговина ===
pattern_bosnia = [
    [{"LOWER": {"REGEX": r"^(босни|герцеговин|сараев).*"}}],
    [
        {"LOWER": {"REGEX": r"^босни.{0,5}$"}},
        {"LOWER": {"REGEX": r"^и.{0,5}$"}},
        {"LOWER": {"REGEX": r"^герцеговин.{0,5}$"}}
    ]
]
matcher.add("BOSNIA-HERZEGOVINA_COUNTRY", pattern_bosnia)

# === Бразили ===
pattern_brazil = [
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
]
matcher.add("BRAZIL_COUNTRY", pattern_brazil)

# === Великобритания ===
pattern_uk = [
    [{"LOWER": {"REGEX": r"^(великобрит|британи|англи|лондон).*"}}],
    [
        {"LOWER": {"REGEX": r"^объединен.{0,5}$"}},
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}}
    ]
]
matcher.add("UK_COUNTRY", pattern_uk)

# === Венгрия ===
pattern_hungary = [
    [{"LOWER": {"REGEX": r"^(венгр|будапешт).*"}}],
    [
        {"LOWER": {"REGEX": r"^венгерск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
    ]
]
matcher.add("HUNGARY_COUNTRY", pattern_hungary)

# === Венесуэла ===
pattern_venezuela = [
    [{"LOWER": {"REGEX": r"^(венесуэл|каракас).*"}}],
    [
        {"LOWER": {"REGEX": r"^боливариан.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^венесуэл.{0,5}$"}}
    ]
]
matcher.add("VENEZUELA_COUNTRY", pattern_venezuela)

# === Германия ===
pattern_germany = [
    [{"LOWER": {"REGEX": r"^(берлин|герман|к[её]льн|немец|фрг).*"}}],
    [
        {"LOWER": {"REGEX": r"^федеративн.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^германи.{0,5}$"}}
    ]
]
matcher.add("GERMANY_COUNTRY", pattern_germany)

# === Греция ===
pattern_greece = [
    [{"LOWER": {"REGEX": r"^(греци|афин).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^греци.{0,5}$"}}
    ]
]
matcher.add("GREECE_COUNTRY", pattern_greece)

# === Грузия ===
pattern_georgia = [
    [{"LOWER": {"REGEX": r"^(грузин|грузия|тбилис).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^груз.{0,5}"}}
    ]
]
matcher.add("GEORGIA_COUNTRY", pattern_georgia)

# === Дания ===
pattern_denmark = [
    [{"LOWER": {"REGEX": r"^(дания|датск|копенгаген).*"}}],
    [
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^дания.{0,5}$"}}
    ]
]
matcher.add("DENMARK_COUNTRY", pattern_denmark)

# === Демократическая республика Конго ===
pattern_drc = [
    [{"LOWER": {"REGEX": r"^(конг|дкр).*"}}],
    [
        {"LOWER": {"REGEX": r"^демократ.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^конг.{0,5}$"}}
    ]
]
matcher.add("DR_CONGO_COUNTRY", pattern_drc)

# === Египет ===
pattern_egypt = [
    [{"LOWER": {"REGEX": r"^(египт|египет|каир).*"}}],
    [
        {"LOWER": {"REGEX": r"^арабск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^египт.{0,5}$"}}
    ]
]
matcher.add("EGYPT_COUNTRY", pattern_egypt)

# === Зимбабве ===
pattern_zimbabwe = [
    [{"LOWER": {"REGEX": r"^(зимбабв|харар).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^зимбабв.{0,5}$"}}
    ]
]
matcher.add("ZIMBABWE_COUNTRY", pattern_zimbabwe)

# === Израиль ===
pattern_israel = [
    [{"LOWER": {"REGEX": r"^(израил|иерусалим).*"}}],
    [
        {"LOWER": {"REGEX": r"^государств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^израил.{0,5}$"}}
    ],
    [
        {"LOWER": {"REGEX": r"^тель.{0,5}$"}},
        {"LOWER": {"REGEX": r"^авив.{0,5}$"}}
    ],
]
matcher.add("ISRAEL_COUNTRY", pattern_israel)

# === Индия ===
pattern_india = [
    [{"LOWER": {"REGEX": r"^(индия|индий|дели|мумба|бенгалур).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^инд.{0,5}$"}}
    ]
]
matcher.add("INDIA_COUNTRY", pattern_india)

# === Иран ===
pattern_iran = [
    [{"LOWER": {"REGEX": r"^(иран|тегеран).*"}}],
    [
        {"LOWER": {"REGEX": r"^исламск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^иран.{0,5}$"}}
    ]
]
matcher.add("IRAN_COUNTRY", pattern_iran)

# === Ирак ===
pattern_iraq = [
    [{"LOWER": {"REGEX": r"^(ирак|багдад).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^ирак.{0,5}$"}}
    ]
]
matcher.add("IRAQ_COUNTRY", pattern_iraq)

# === Ирландия ===
pattern_ireland = [
    [{"LOWER": {"REGEX": r"^(ирланд|дублин).*"}}],
    [
        {"LOWER": {"REGEX": r"^ирландск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
    ]
]
matcher.add("IRELAND_COUNTRY", pattern_ireland)

# === Исландия ===
pattern_iceland = [
    [{"LOWER": {"REGEX": r"^(исланди|рекьявик).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^исланди.{0,5}$"}}
    ]
]
matcher.add("ICELAND_COUNTRY", pattern_iceland)

# === Испания ===
pattern_spain = [
    [{"LOWER": {"REGEX": r"^(испани|мадрид).*"}}]
]
matcher.add("SPAIN_COUNTRY", pattern_spain)

# === Италия ===
pattern_italy = [
    [{"LOWER": {"REGEX": r"^(итал|рим).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^итал.{0,5}$"}}
    ]
]
matcher.add("ITALY_COUNTRY", pattern_italy)

# === Казахстан ===
pattern_kazakhstan = [
    [{"LOWER": {"REGEX": r"^(казахстан|астан|алма-ат|алматы).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^казахстан.{0,5}$"}}
    ]
]
matcher.add("KAZAKHSTAN_COUNTRY", pattern_kazakhstan)

# === Камбоджа ===
pattern_cambodia = [
    [{"LOWER": {"REGEX": r"^(камбодж|пномпень).*"}}],
    [
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^камбодж.{0,5}$"}}
    ]
]
matcher.add("CAMBODIA_COUNTRY", pattern_cambodia)

# === Канада ===
pattern_canada = [
    [{"LOWER": {"REGEX": r"^(канад|оттав|торонт|монреал).*"}}],
    [
        {"LOWER": {"REGEX": r"^канад.{0,5}$"}},
        {"LOWER": {"REGEX": r"^государств.{0,5}$"}}
    ]
]
matcher.add("CANADA_COUNTRY", pattern_canada)

# === Кипр ===
pattern_cyprus = [
    [{"LOWER": {"REGEX": r"^(кипр|никоси).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^кипр.{0,5}$"}}
    ]
]
matcher.add("CYPRUS_COUNTRY", pattern_cyprus)

# === Китай ===
pattern_china = [
    # 1. Простые формы
    [{"LOWER": {"REGEX": r"^(гонконг|кита|кнр|пекин|пхеньян|шанхай).*"}}],

    # 2. Полное официальное название — Китайская Народная Республика
    [
        {"LOWER": {"REGEX": r"^китайск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^народн.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
    ]
]

matcher.add("CHINA_COUNTRY", pattern_china)

# === Колумбия ===
pattern_colombia = [
    [{"LOWER": {"REGEX": r"^(колумб|богот).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^колумб.{0,5}$"}}
    ]
]
matcher.add("COLOMBIA_COUNTRY", pattern_colombia)

# === Кыргызстан ===
pattern_kyrgyzstan = [
    [{"LOWER": {"REGEX": r"^(киргиз|кыргыз|бишкек).*"}}],
    [
        {"LOWER": {"REGEX": r"^кыргызск.{0,5}"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}"}}
    ]
]
matcher.add("KYRGYZSTAN_COUNTRY", pattern_kyrgyzstan)

# === Латвия ===
pattern_latvia = [
    [{"LOWER": {"REGEX": r"^(латви|рига).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^латви.{0,5}$"}}
    ]
]
matcher.add("LATVIA_COUNTRY", pattern_latvia)

# === Ливия ===
pattern_libya = [
    [{"LOWER": {"REGEX": r"^(ливи|трипол).*"}}],
    [
        {"LOWER": {"REGEX": r"^государств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^ливи.{0,5}$"}}
    ]
]
matcher.add("LIBYA_COUNTRY", pattern_libya)

# === Литва ===
pattern_lithuania = [
    [{"LOWER": {"REGEX": r"^(литв|вильнюс).?"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^литв.{0,5}$"}}
    ]
]
matcher.add("LITHUANIA_COUNTRY", pattern_lithuania)

# === Люксембург ===
pattern_luxembourg = [
    [{"LOWER": {"REGEX": r"^(люксембург).*"}}],
]
matcher.add("LUXEMBOURG_COUNTRY", pattern_luxembourg)

# === Македония ===
pattern_macedonia = [
    [{"LOWER": {"REGEX": r"^(македон).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^македон.{0,5}$"}}
    ]
]
matcher.add("MACEDONIA_COUNTRY", pattern_macedonia)

# === Мальта ===
pattern_malta = [
    [{"LOWER": {"REGEX": r"^(мальт|валлетт).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^мальт.{0,5}$"}}
    ]
]
matcher.add("MALTA_COUNTRY", pattern_malta)

# === Мексика ===
pattern_mexico = [
    [{"LOWER": {"REGEX": r"^(мексик|мехик).*"}}]
]
matcher.add("MEXICO_COUNTRY", pattern_mexico)

# === Молдова ===
pattern_moldova = [
    [{"LOWER": {"REGEX": r"^(молдов|кишинев).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^молдов.{0,5}"}}
    ]
]
matcher.add("MOLDOVA_COUNTRY", pattern_moldova)

# === Нидерланды ===
pattern_netherlands = [
    [{"LOWER": {"REGEX": r"^(нидерланд|голланд|амстердам).*"}}],
]
matcher.add("NETHERLANDS_COUNTRY", pattern_netherlands)

# === Норвегия ===
pattern_norway = [
    [{"LOWER": {"REGEX": r"^(норвег|осло).*"}}],
    [
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^норвег.{0,5}$"}}
    ]
]
matcher.add("NORWAY_COUNTRY", pattern_norway)

# === Пакистан ===
pattern_pakistan = [
    [{"LOWER": {"REGEX": r"^(пакист|исламабад|карач).*"}}],
    [
        {"LOWER": {"REGEX": r"^исламск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^пакист.{0,5}$"}}
    ]
]
matcher.add("PAKISTAN_COUNTRY", pattern_pakistan)

# === Перу ===
pattern_peru = [
    [{"LOWER": {"REGEX": r"^(перу).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^перу.{0,5}$"}}
    ]
]
matcher.add("PERU_COUNTRY", pattern_peru)

pattern_poland = [
    [{"LOWER": {"REGEX": r"^(польш|варшав).*"}}],
]
matcher.add("POLAND_COUNTRY", pattern_poland)

# === Объединенные Арабские Эмираты (ОАЭ) ===
pattern_uae = [
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
]
matcher.add("UAE_COUNTRY", pattern_uae)

# === Португалия ===
pattern_portugal = [
    [{"LOWER": {"REGEX": r"^(португал|лиссабон).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^португал.{0,5}$"}}
    ]
]
matcher.add("PORTUGAL_COUNTRY", pattern_portugal)

# === Россия ===
pattern_russia = [
    [{"LEMMA": {"IN": ["россия", "рф", "российский", "русский", "русь", "ссср"]}}],
    [  # вторая форма — "Российской Федерации"
        {"LEMMA": "российский"},
        {"LEMMA": "федерация"}
    ],
]
matcher.add("RUSSIA_COUNTRY", pattern_russia)

# === 2. Названия городов и регионов ===
# Сюда можно добавлять новые регионы по мере надобности
pattern_russia_city = [
    [{"LOWER": {
        "REGEX": r"^(астрахан|брянск|волгоград|владикавказ|воронеж|дагестан|иркутск|калининград|казан|киров|магадан|новосибирск|москв|москов|перм|петербург|ростов|татарстан|твер|тульск|хабаровск|чечен|чечн).*"}}],
    [{"LOWER": {"IN": ["уфа", "уфе", "уфы", "чита", "чите", "самара", "самаре", "самары"]}}],
    # todo для самары сделать исключение остров самар и все
]
matcher.add("RUSSIA_CITY", pattern_russia_city)

# === Румыния ===
pattern_romania = [
    [{"LOWER": {"REGEX": r"^(румын|бухарест).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^румын.{0,5}$"}}
    ]
]
matcher.add("ROMANIA_COUNTRY", pattern_romania)

# === Саудовская Аравия ===
pattern_saudi_arabia = [
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
]
matcher.add("SAUDI_ARABIA_COUNTRY", pattern_saudi_arabia)

# === Северная Корея (КНДР) ===
pattern_north_korea = [
    [{"LOWER": {"REGEX": r"^(кндр|коре|пхеньян).*"}}],
    [
        {"LOWER": {"REGEX": r"^коре.{0,5}$"}},
        {"LOWER": {"REGEX": r"^народн.{0,5}$"}},
        {"LOWER": {"REGEX": r"^демократич.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
    ]
]
matcher.add("NORTH-KOREA_COUNTRY", pattern_north_korea)

# === Сербия ===
pattern_serbia = [
    [{"LOWER": {"REGEX": r"^(серб|белград).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^серб.{0,5}$"}}
    ]
]
matcher.add("SERBIA_COUNTRY", pattern_serbia)

# === Сингапур ===
pattern_singapore = [
    [{"LOWER": {"REGEX": r"^(сингапур).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^сингапур.{0,5}$"}}
    ]
]
matcher.add("SINGAPORE_COUNTRY", pattern_singapore)

# === Сирия ===
pattern_syria = [
    [{"LOWER": {"REGEX": r"^(сири|дамаск).*"}}],
    [
        {"LOWER": {"REGEX": r"^арабск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^сири.{0,5}$"}}
    ]
]
matcher.add("SYRIA_COUNTRY", pattern_syria)

# === Словакия ===
pattern_slovakia = [
    [{"LOWER": {"REGEX": r"^(словак|братислав).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^словак.{0,5}$"}}
    ]
]
matcher.add("SLOVAKIA_COUNTRY", pattern_slovakia)

# === Словения ===
pattern_slovenia = [
    [{"LOWER": {"REGEX": r"^(словен|люблян).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^словен.{0,5}$"}}
    ]
]
matcher.add("SLOVENIA_COUNTRY", pattern_slovenia)

# === США ===
pattern_usa = [
    # однословные формы
    [{"LOWER": {"REGEX": r"^(сша|(?<!северн)(?<!южн)(?<!латин).{0,3}америк).*"}}],
    # двухсловные формы: Соединённые Штаты / Соединенных Штатов
    [
        {"LOWER": {"REGEX": r"^соедин[её]н.{0,5}$"}},
        {"LOWER": {"REGEX": r"^штат.*"}}
    ],
]
matcher.add("USA_COUNTRY", pattern_usa)

# === 2. Города и прилагательные от них ===
pattern_usa_city = [
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
]

matcher.add("USA_CITY", pattern_usa_city)

# === Таджикистан ===
pattern_tajikistan = [
    [{"LOWER": {"REGEX": r"^(таджик|душанб).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^таджик.{0,5}"}}
    ]
]
matcher.add("TAJIKISTAN_COUNTRY", pattern_tajikistan)

# === Таиланд ===
pattern_thailand = [
    [{"LOWER": {"REGEX": r"^(тайланд|бангкок).*"}}],
    [
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^тайланд.{0,5}$"}}
    ]
]
matcher.add("THAILAND_COUNTRY", pattern_thailand)

# === Тайвань ===
pattern_taiwan = [
    [{"LOWER": {"REGEX": r"^(тайван|тайпей).*"}}],
    [
        {"LOWER": {"REGEX": r"^кита.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^тайван.{0,5}$"}}
    ]
]
matcher.add("TAIWAN_COUNTRY", pattern_taiwan)

# === Туркменистан ===
pattern_turkmenistan = [
    [{"LOWER": {"REGEX": r"^(туркмен|ашхабад).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^туркмен.{0,5}"}}
    ]
]
matcher.add("TURKMENISTAN_COUNTRY", pattern_turkmenistan)

# === Туркция ===
pattern_turkey = [
    [{"LOWER": {"REGEX": r"^(турци|анкар|стамб).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^турци.{0,5}$"}}
    ]
]
matcher.add("TURKEY_COUNTRY", pattern_turkey)

# === Украина ===
pattern_ukraine = [
    [{"LOWER": {"REGEX": r"^(украин|киев).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^украин.{0,5}"}}
    ]
]
matcher.add("UKRAINE_COUNTRY", pattern_ukraine)

# === Узбекистан ===
pattern_uzbekistan = [
    [{"LOWER": {"REGEX": r"^(узбек|ташкент).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}"}},
        {"LOWER": {"REGEX": r"^узбек.{0,5}"}}
    ]
]
matcher.add("UZBEKISTAN_COUNTRY", pattern_uzbekistan)

# === Финляндия ===
pattern_finland = [
    [{"LOWER": {"REGEX": r"^(финлянд|хельсинк).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^финлянд.{0,5}$"}}
    ]
]
matcher.add("FINLAND_COUNTRY", pattern_finland)

# === Франция ===
pattern_france = [
    [{"LOWER": {"REGEX": r"^(франц(?!иск)|француз|париж).*"}}],
]
matcher.add("FRANCE_COUNTRY", pattern_france)

# === Хорватия ===
pattern_croatia = [
    [{"LOWER": {"REGEX": r"^(хорват|загреб).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^хорват.{0,5}$"}}
    ]
]
matcher.add("CROATIA_COUNTRY", pattern_croatia)

# === Черногория ===
pattern_montenegro = [
    [{"LOWER": {"REGEX": r"^(черногор|подгориц).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^черногор.{0,5}$"}}
    ]
]
matcher.add("MONTENEGRO_COUNTRY", pattern_montenegro)

# === Чехия ===
pattern_czechia = [
    [{"LOWER": {"REGEX": r"^(чех|прага|чешск).*"}}],
    [
        {"LOWER": {"REGEX": r"^чешск.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}}
    ]
]
matcher.add("CZECHIA_COUNTRY", pattern_czechia)

# === Чили ===
pattern_chile = [
    [{"LOWER": {"REGEX": r"^(чили|сантьяго).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^чили.{0,5}$"}}
    ]
]
matcher.add("CHILE_COUNTRY", pattern_chile)

# === Швейцария ===
pattern_switzerland = [
    [{"LOWER": {"REGEX": r"^(швейцар|берн|цюрих|женев).*"}}],
    [
        {"LOWER": {"REGEX": r"^конфедерац.{0,5}$"}},
        {"LOWER": {"REGEX": r"^швейцар.{0,5}$"}}
    ]
]
matcher.add("SWITZERLAND_COUNTRY", pattern_switzerland)

# === Швеция ===
pattern_sweden = [
    [{"LOWER": {"REGEX": r"^(швед|швеци|стокгольм).*"}}],
    [
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}},
        {"LOWER": {"REGEX": r"^швед.{0,5}$"}}
    ]
]
matcher.add("SWEDEN_COUNTRY", pattern_sweden)

pattern_scotland = [
    [{"LOWER": {"REGEX": r"^(шотланд|эдинбург).*"}}],
    [
        {"LOWER": {"REGEX": r"^шотланд.{0,5}$"}},
        {"LOWER": {"REGEX": r"^королевств.{0,5}$"}}
    ]
]
matcher.add("SCOTLAND_COUNTRY", pattern_scotland)

# === Эквадор ===
pattern_ecuador = [
    [{"LOWER": {"REGEX": r"^(эквадор|кито).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^эквадор.{0,5}$"}}
    ]
]
matcher.add("ECUADOR_COUNTRY", pattern_ecuador)

# === Эстония ===
pattern_estonia = [
    [{"LOWER": {"REGEX": r"^(эстони|таллин).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^эстони.{0,5}$"}}
    ],
    [
        {"LOWER": {"REGEX": r"^эстон.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
    ]
]
matcher.add("ESTONIA_COUNTRY", pattern_estonia)

# === Югославия === (историческая)
pattern_yugoslavia = [
    [{"LOWER": {"REGEX": r"^(югослав|белград).*"}}],
    [
        {"LOWER": {"REGEX": r"^федерац.{0,5}$"}},
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^югослав.{0,5}$"}}
    ]
]
matcher.add("YUGOSLAVIA_COUNTRY", pattern_yugoslavia)

# === Южная корея ===
pattern_south_korea = [
    [{"LOWER": {"REGEX": r"^(сеул|южнокорейск).*"}}],
    [
        {"LOWER": {"REGEX": r"^республик.{0,5}$"}},
        {"LOWER": {"REGEX": r"^коре.{0,5}$"}}
    ],
    [
        {"LOWER": {"REGEX": r"^южн.{0,5}$"}},
        {"LOWER": {"REGEX": r"^коре.{0,5}$"}}
    ],
]

matcher.add("SOUTH-KOREA_COUNTRY", pattern_south_korea)

# === Япония ===
pattern_japan = [
    [{"LOWER": {"REGEX": r"^(япон|токио|киот).*"}}],
    [
        {"LOWER": {"REGEX": r"^япон.{0,5}$"}},
        {"LOWER": {"REGEX": r"^государств.{0,5}$"}}
    ]
]
matcher.add("JAPAN_COUNTRY", pattern_japan)


# todo заменить все .* на ограничитель
# ливан

def match_locations(loc_list, matcher=matcher):
    loc_list = ast.literal_eval(loc_list)
    text = ", ".join(loc_list)
    doc = nlp(text)
    matches = matcher(doc)

    # Извлекаем названия стран из имён правил (до символа "_")
    countries = []
    for match_id, start, end in matches:
        rule_name = nlp.vocab.strings[match_id]
        country = rule_name.split("_")[0]
        countries.append(country)

    # Упорядоченный уникальный набор стран
    ordered_unique = list(OrderedDict.fromkeys(countries).keys())
    return ordered_unique if ordered_unique else None

def get_matchers(matcher=matcher):
    return [nlp.vocab.strings[k] for k in matcher._patterns.keys()]