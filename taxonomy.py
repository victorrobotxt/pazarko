"""
Product taxonomy shared by derive.py (classification, families) and server.py (search transliteration).

  classify(name, category_path, slug, kzp_category) -> (kind, dept)
      kind  a product type ('energy_drink', 'chocolate', ...): what the thing *is*, used to roll up
            flavours/variants of one brand into a family
      dept  a department ('napitki', 'igrachki', ...): used for search intent and facets
  BrandIndex   finds the brand in a product name, across Latin/Cyrillic spellings
  translit / skeleton   script-independent forms for matching 'Monster' ~ 'МОНСТЪР', 'Roshen' ~ 'РОШЕН'

Rules are plain data below; extend KINDS when a product type is misclassified.
"""
from __future__ import annotations

import collections
import re

DEPTS = {
    "napitki": "Напитки", "kafe": "Кафе, чай и какао", "alkohol": "Алкохол", "tyutyun": "Тютюн",
    "mlechni": "Мляко, сирена и яйца", "meso": "Месо и риба", "kolbasi": "Колбаси и деликатеси",
    "plodove": "Плодове и зеленчуци", "hlyab": "Хляб и тестени", "sladko": "Сладко",
    "soleno": "Снакс и ядки", "osnovni": "Основни храни", "konservi": "Консерви и сосове",
    "zamrazeni": "Замразени", "bebe": "Бебе и дете", "kozmetika": "Козметика и хигиена",
    "pochistvane": "Почистване и домакинство", "dom": "Дом, кухня и градина", "zoo": "Домашни любимци",
    "zdrave": "Аптека и здраве", "igrachki": "Играчки, книги и парти", "drugi": "Други",
}

# (kind, label, dept, alternatives). Alternatives are regex stems matched at word starts on upper-cased
# text. When several match, the one starting earliest in the name wins ('Шоколад с мляко' is chocolate,
# 'Мляко с шоколад' is milk); at the same position the longest wins ('паста за зъби' over 'паста').
KINDS = [
    # drinks
    ("energy_drink", "Енергийна напитка", "napitki", [r"ЕНЕРГИЙН\w*\s+НАПИТ\w*", r"ЕНЕРГИЙНИ", r"ЕНЕРДЖИ\w*",
                                                       r"ENERGY\s+DRINK", r"ЕНЕРГИЙНА"]),
    ("isotonic", "Изотонична напитка", "napitki", [r"ИЗОТОНИ\w*"]),
    ("water", "Вода", "napitki", [r"МИНЕРАЛН\w*\s+ВОД\w*", r"ИЗВОРН\w*\s+ВОД\w*", r"ТРАПЕЗН\w*\s+ВОД\w*",
                                  r"ГАЗИРАН\w*\s+ВОД\w*", r"ВОДА", r"ВОДИ", r"WATER"]),
    ("iced_tea", "Студен чай", "napitki", [r"СТУДЕН\w*\s+ЧАЙ", r"ICE\w*\s+TEA", r"ЛЕДЕН\w*\s+ЧАЙ"]),
    ("juice", "Сок / нектар", "napitki", [r"СОК", r"СОКОВЕ", r"НЕКТАР\w*", r"ФРЕШ", r"СМУТИ", r"JUICE"]),
    ("soft_drink", "Безалкохолна напитка", "napitki", [r"ГАЗИРАН\w*\s+НАПИТ\w*", r"БЕЗАЛКОХОЛН\w*", r"КОЛА",
                                                        r"COLA", r"ЛИМОНАД\w*", r"ТОНИК", r"ГАЗИРАНИ",
                                                        r"НАПИТКА", r"НАПИТКИ", r"ПЛОДОВИ\s+НАПИТКИ"]),
    ("coffee_instant", "Разтворимо кафе", "kafe", [r"РАЗТВОРИМ\w*\s+КАФЕ", r"КАФЕ\s+3\s*В\s*1", r"3\s*В\s*1",
                                                    r"РАЗТВОРИМ\w*", r"INSTANT\s+COFFEE"]),
    ("coffee_capsules", "Кафе капсули", "kafe", [r"КАФЕ\s+КАПСУЛ\w*", r"КАПСУЛ\w*\s+(?:ЗА\s+)?КАФЕ",
                                                  r"КАПСУЛ\w*\s+(?:NESPRESSO|DOLCE)", r"DOLCEGUSTO\w*",
                                                  r"NESPRESSO\s+СЪВМЕСТИМИ"]),
    ("coffee", "Кафе", "kafe", [r"КАФЕ", r"COFFEE", r"ЕСПРЕСО", r"ESPRESSO", r"МЛЯНО\s+КАФЕ", r"МЛЯНО"]),
    ("tea", "Чай", "kafe", [r"ЧАЙ", r"ЧАЕВЕ", r"ЧАЕНИ", r"TEA"]),
    ("cocoa", "Какао", "kafe", [r"КАКАО", r"ГОРЕЩ\s+ШОКОЛАД", r"ЦИКОРИЯ"]),
    # alcohol
    ("beer", "Бира", "alkohol", [r"БИРА", r"БИРИ", r"ПИВО", r"BEER", r"ЛАГЕР"]),
    ("wine", "Вино", "alkohol", [r"ВИНО", r"ВИНА", r"WINE", r"ПЕНЛИВО\w*", r"ШАМПАНСКО", r"ПРОСЕКО", r"РОЗЕ",
                                 r"PROSECCO"]),
    ("rakia", "Ракия", "alkohol", [r"РАКИЯ", r"РАКИИ", r"ГРОЗДОВА", r"СЛИВОВА"]),
    ("whisky", "Уиски", "alkohol", [r"УИСКИ", r"WHISK\w*", r"БЪРБЪН"]),
    ("vodka", "Водка", "alkohol", [r"ВОДКА", r"VODKA"]),
    ("gin", "Джин", "alkohol", [r"ДЖИН", r"GIN"]),
    ("rum", "Ром", "alkohol", [r"РОМ", r"RUM"]),
    ("liqueur", "Ликьор", "alkohol", [r"ЛИКЬОР\w*", r"LIQUEUR"]),
    ("spirits", "Спиртна напитка", "alkohol", [r"БРЕНДИ", r"КОНЯК", r"МАСТИКА", r"УЗО", r"ТЕКИЛА", r"АНАСОНОВ\w*",
                                               r"АНАСОНОВ\w*\s+НАПИТК\w*",
                                               r"СИДЕР"]),
    ("tobacco", "Тютюневи изделия", "tyutyun", [r"ЦИГАРИ", r"ПУРИ", r"ТЮТЮН\w*", r"HEETS",
                                                 r"TEREA", r"НАГРЯВАН\w*\s+ТЮТЮН"]),
    # dairy & eggs
    ("yogurt", "Кисело мляко", "mlechni", [r"КИСЕЛО\s+МЛЯКО", r"МЛЯКО\s+КИСЕЛО", r"КИСЕЛИ\s+МЛЕКА", r"ЙОГУРТ\w*", r"YOG\w*",
                                           r"КИС\.\s*МЛЯКО", r"ПЛОДОВ\w*\s+КИС\w*"]),
    ("ayran", "Айрян / кефир", "mlechni", [r"АЙРЯН", r"КЕФИР", r"МЛЕЧНИ\s+НАПИТКИ"]),
    ("formula", "Адаптирано мляко", "bebe", [r"АДАПТИРАН\w*", r"МЛЯКО\s+ЗА\s+КЪРМАЧ\w*", r"APTAMIL", r"АПТАМИЛ",
                                             r"HUMANA", r"ХУМАНА", r"FRISO\w*", r"ФРИСО\w*", r"NAN\s+OPTIPRO",
                                             r"БЕБЕЛАК", r"MILUPA", r"ПРЕХОДНО\s+МЛЯКО", r"СУХО\s+МЛЯКО",
                                             r"МЛЯКО\s+СУХО", r"МЛЯКО\s+НА\s+ПРАХ", r"БЕБЕШКО\s+МЛЯКО",
                                             r"ЗА\s+КЪРМАЧ\w*", r"OPTIPRO", r"ОПТИПРО", r"НАН-?\d"]),
    ("body_lotion", "Лосион / мляко за тяло", "kozmetika", [r"МЛЯКО\s+ЗА\s+(?:ТЯЛО|ЛИЦЕ|ДЕМАКИЯЖ)",
                                                            r"ПОЧИСТВАЩО\s+МЛЯКО", r"ЛОСИОН\w*", r"BODY\s+LOTION",
                                                            r"СЛЪНЦЕЗАЩИТ\w*"]),
    ("milk", "Прясно мляко", "mlechni", [r"ПРЯСНО\s+МЛЯКО", r"МЛЯКО", r"UHT", r"МЛЕКА", r"ЯДКОВО\s+МЛЯКО",
                                          r"ЯДКОВИ\s+МЛЕКА", r"ОВЕСЕНА\s+НАПИТКА", r"СОЕВА\s+НАПИТКА",
                                          r"(?:БАДЕМОВ|ОРИЗОВ|КОКОСОВ|ЛЕШНИКОВ|КАШУ|ОВЕСЕН|СОЕВ)\w*\s+НАПИТК\w*",
                                          r"НАПИТК\w*\s+(?:БАДЕМОВ|ОРИЗОВ|КОКОСОВ|ЛЕШНИКОВ|ОВЕСЕН|СОЕВ)\w*"]),
    ("processed_cheese", "Топено сирене", "mlechni", [r"ТОПЕНО\s+СИРЕНЕ", r"КРЕМА\s+СИРЕНЕ", r"ТОПЕНИ\s+СИРЕНА"]),
    ("white_cheese", "Сирене", "mlechni", [r"СИРЕНЕ", r"FETA", r"ФЕТА", r"БЯЛО\s+САЛАМУРЕНО", r"МЕКИ\s+СИРЕНА"]),
    ("yellow_cheese", "Кашкавал", "mlechni", [r"КАШКАВАЛ\w*", r"КАШК\.?"]),
    ("cheese", "Сирена (други)", "mlechni", [r"МОЦАРЕЛ\w*", r"MOZZARELLA", r"ЧЕДЪР", r"CHEDDAR", r"ГАУДА", r"GOUDA",
                                            r"ЕДАМ", r"ПАРМЕЗАН", r"МАСКАРПОНЕ", r"РИКОТА", r"ХАЛУМИ", r"ЕМЕНТАЛ",
                                            r"БРИ", r"КАМАМБЕР", r"ТВЪРДИ\s+СИРЕНА", r"СИРЕНА"]),
    ("butter", "Масло", "mlechni", [r"КРАВЕ\s+МАСЛО", r"МАСЛО", r"BUTTER", r"МАРГАРИН\w*"]),
    ("cottage_cheese", "Извара", "mlechni", [r"ИЗВАРА"]),
    ("cream", "Сметана", "mlechni", [r"СМЕТАНА", r"ЗАКВАСЕНА", r"ГОТВАРСКА\s+СМЕТАНА", r"СМЕТАН\w*"]),
    ("dairy_dessert", "Млечен десерт", "mlechni", [r"МЛЕЧ\w*\s+ДЕСЕРТ\w*", r"ПУДИНГ\w*", r"КРЕМ\s+КАРАМЕЛ",
                                                    r"ДЕСЕРТНИ\s+КРЕМОВЕ"]),
    ("eggs", "Яйца", "mlechni", [r"ЯЙЦА", r"ЯЙЦЕ", r"EGGS"]),
    # meat & fish
    ("chicken", "Пилешко", "meso", [r"ПИЛЕ", r"ПИЛЕШК\w*", r"ПУЕШК\w*", r"ПАТЕШК\w*", r"ПИЛ\.", r"ПИЛЕТА"]),
    ("pork", "Свинско", "meso", [r"СВИНСК\w*", r"СВ\.\s*МЕСО", r"ВРАТ", r"ПЛЕШКА", r"ВЕШАЛИЦА", r"ВЕШЕЛИЦА",
                                  r"СВИНСКА\s+СКАРА"]),
    ("beef", "Телешко / агнешко", "meso", [r"ТЕЛЕШК\w*", r"ГОВЕЖД\w*", r"АГНЕШК\w*", r"ЯРЕШК\w*", r"ШОЛ"]),
    ("mince", "Кайма и кюфтета", "meso", [r"КАЙМА", r"КЮФТЕТА", r"КЮФТЕ", r"КЕБАПЧЕТА", r"КЕБАПЧЕ"]),
    ("canned_fish", "Рибна консерва", "konservi", [r"РИБА\s+ТОН", r"ТОН\s+(?:В|ФИЛЕ|ПАРЧЕТА)", r"САРДИН\w*",
                                                   r"ШПРОТИ", r"РИБН\w*\s+КОНСЕРВ\w*", r"СКУМРИЯ\s+В\s+\w+"]),
    ("fish", "Риба и морски дарове", "meso", [r"РИБА", r"РИБИ", r"СЬОМГ\w*", r"ПЪСТЪРВ\w*", r"СКУМРИЯ", r"ЦИПУРА",
                                              r"ЛАВРАК", r"ХЕК", r"АКУЛА", r"СКАРИДИ", r"МИДИ", r"КАЛМАР\w*",
                                              r"ХАЙВЕР", r"ХЕРИНГА", r"ПАНГАСИУС", r"ФИЛЕ\s+ОТ\s+РИБА"]),
    # deli
    ("sausages", "Кренвирши и наденици", "kolbasi", [r"КРЕНВИРШ\w*", r"НАДЕНИЦ\w*", r"ДЕБРЕЦИН\w*"]),
    ("salami", "Салам / луканка", "kolbasi", [r"САЛАМ\w*", r"ЛУКАНК\w*", r"СУДЖУК\w*", r"ШПЕК\w*", r"КОЛБАС\w*",
                                              r"СТАРЕЦ", r"ЕЛЕНА", r"ФИЛЕ\s+ЕЛЕНА", r"ПАСТЪРМА"]),
    ("ham", "Шунка / бекон", "kolbasi", [r"ШУНК\w*", r"БЕКОН", r"ПРОШУТО", r"ХАМОН"]),
    ("pate", "Пастет", "kolbasi", [r"ПАСТЕТ\w*", r"ПАЙ"]),
    # produce
    ("bananas", "Банани", "plodove", [r"БАНАН\w*"]),
    ("apples", "Ябълки", "plodove", [r"ЯБЪЛК\w*"]),
    ("citrus", "Цитрусови", "plodove", [r"ПОРТОКАЛ\w*", r"ЛИМОН\w*", r"МАНДАРИН\w*", r"ГРЕЙПФРУТ\w*", r"ЦИТРУС\w*"]),
    ("fruit", "Плодове", "plodove", [r"ГРОЗДЕ", r"КРУШ\w*", r"ЯГОДИ", r"КИВИ", r"ПРАСКОВ\w*", r"НЕКТАРИН\w*",
                                     r"ДИНЯ", r"ПЪПЕШ", r"АВОКАДО", r"АНАНАС", r"РАЙСКА\s+ЯБЪЛКА", r"СЛИВИ",
                                     r"ЧЕРЕШИ", r"БОРОВИНК\w*", r"МАЛИНИ", r"НАР", r"ПЛОДОВЕ", r"ЕКЗОТИ\w*"]),
    ("canned_tomatoes", "Доматени консерви", "konservi", [r"ДОМАТИ\s+(?:КУБЧЕТА|ПАСИРАНИ|БЕЛЕНИ|ЦЕЛИ|НАРЯЗАНИ|"
                                                           r"РЕНДОСАНИ|ЧЕРИ\s+В)", r"ПАСИРАНИ\s+ДОМАТИ",
                                                          r"БЕЛЕНИ\s+ДОМАТИ", r"ДОМАТЕН\w*", r"ДОМАТЕНО\s+ПЮРЕ",
                                                          r"ДОМАТЕНО\s+КОНЦЕНТРАТ", r"\*?\*?БЕЛЕНИ\s+ДОМАТИ"]),
    ("tomatoes", "Домати", "plodove", [r"ДОМАТИ", r"ДОМАТ"]),
    ("cucumbers", "Краставици", "plodove", [r"КРАСТАВИЦ\w*"]),
    ("potatoes", "Картофи", "plodove", [r"КАРТОФИ", r"КАРТОФ"]),
    ("onions", "Лук и чесън", "plodove", [r"КРОМИД", r"ЛУК", r"ЧЕСЪН", r"ПРАЗ"]),
    ("vegetables", "Зеленчуци", "plodove", [r"МОРКОВ\w*", r"ЗЕЛЕ", r"ЧУШК\w*", r"ТИКВИЧК\w*", r"ПАТЛАДЖАН\w*",
                                             r"САЛАТА\s+(?:АЙСБЕРГ|ЗЕЛЕНА)", r"МАРУЛ\w*", r"СПАНАК", r"БРОКОЛИ",
                                             r"КАРФИОЛ", r"ЦВЕКЛО", r"ЗЕЛЕНЧУЦИ", r"ЗЕЛЕНОЛИСТНИ",
                                             r"КОРЕНОПЛОДНИ", r"МАГДАНОЗ", r"КОПЪР"]),
    ("mushrooms", "Гъби", "plodove", [r"ГЪБИ", r"ПЕЧУРК\w*"]),
    # bakery
    ("bread", "Хляб", "hlyab", [r"ХЛЯБ", r"ХЛЕБЧЕТА", r"ПИТКА", r"ПИТКИ", r"ПИТА", r"БАГЕТ\w*", r"ТОСТЕРЕН",
                                 r"ЛАВАШ", r"ТОРТИЛ\w*", r"ЖИТЕН\s+ХЛЯБ"]),
    ("pastry", "Баница и закуски", "hlyab", [r"БАНИЦ\w*", r"БАНИЧК\w*", r"КИФЛ\w*", r"ПОГАЧ\w*", r"МЕКИЦ\w*",
                                             r"КОЗУНАК\w*", r"ЗАКУСК\w*\s+(?:СЪС|С)\s", r"ПУРА"]),
    ("croissant", "Кроасан", "sladko", [r"КРОАСАН\w*", r"CROISSANT\w*", r"7\s*DAYS", r"7\s*ДЕЙС"]),
    ("dough", "Кори и тесто", "hlyab", [r"КОРИ", r"ТЕСТО", r"БУТЕРНО"]),
    # sweets
    ("chocolate", "Шоколад", "sladko", [r"ШОКОЛАД\w*", r"CHOCOLATE", r"АЕРОШОКОЛАД", r"ШОК\.",
                                        r"ШОКОЛАДОВ\w*\s+ЯЙ\w*"]),
    ("wafer", "Вафла", "sladko", [r"ВАФЛ\w*", r"WAFER\w*"]),
    ("biscuits", "Бисквити", "sladko", [r"БИСКВИТ\w*", r"КУКИС", r"COOKIE\w*", r"ДЖИНДЖИФИЛОВИ", r"СУХИ\s+ПАСТИ",
                                         r"БИШКОТ\w*"]),
    ("candy", "Бонбони и дъвки", "sladko", [r"БОНБОН\w*", r"ДРАЖЕ\w*", r"ЖЕЛИРАН\w*", r"ЛОКУМ", r"ХАЛВА", r"ДЪВК\w*",
                                            r"БЛИЗАЛК\w*", r"МАРШМЕЛО\w*", r"ДЪВЧ\w*", r"ЗАХАРНИ\s+ИЗДЕЛИЯ"]),
    ("cake", "Торти и сладкиши", "sladko", [r"ТОРТ\w*", r"ПАСТИ", r"КЕКС\w*", r"МЪФИН\w*", r"ЕКЛЕР\w*", r"БАКЛАВ\w*",
                                             r"ПАЛАЧИНК\w*", r"РУЛЦА", r"РУЛО", r"СЛАДКИШ\w*", r"БРАУНИ",
                                             r"ПУРИЧК\w*", r"ВАФЛЕНИ\s+ПУРИЧК\w*"]),
    ("spread", "Мед, сладко и кремове", "sladko", [r"ТАХАН\w*", r"ЛЕШНИКОВ\w*\s+КРЕМ", r"ШОКОЛАДОВ\w*\s+КРЕМ",
                                                   r"NUTELLA", r"НУТЕЛА", r"МЕД", r"СЛАДКО", r"КОНФИТЮР\w*",
                                                   r"МАРМАЛАД\w*", r"ПЕТМЕЗ", r"КРЕМ\s+ЗА\s+МАЗАНЕ",
                                                   r"ПРОТЕИНОВ\w*\s+КРЕМ", r"(?:ФЪСТЪЧЕНО|БАДЕМОВО|ЛЕШНИКОВО|ОРЕХОВО|"
                                                   r"КАШУ)\s+МАСЛО"]),
    ("bar", "Барчета", "sladko", [r"ЗЪРНЕН\w*\s+БАР\w*", r"ПРОТЕИНОВ\w*\s+БАР\w*", r"БАРЧЕ\w*", r"БАРОВЕ",
                                  r"БАР", r"(?:ОВЕСЕН|ОВЕСЕНО|ЗЪРНЕН|ЗЪРНЕНО|ПЛОДОВ|ПЛОДОВО)\s+БЛОКЧ\w*",
                                  r"FLAP\s*JACK"]),
    # salty
    ("chips", "Чипс", "soleno", [r"ЧИПС\w*", r"CHIPS", r"ТОРТИЛА\s+ЧИПС"]),
    ("snack", "Солени снаксове", "soleno", [r"СНАКС\w*", r"SNACK\w*", r"СОЛЕТ\w*", r"КРЕКЕР\w*", r"ПУКАНК\w*",
                                             r"ПРЪЧИЦ\w*", r"ХРУПК\w*", r"ФЛИПС", r"СУХАРИ", r"ГРИСИНИ", r"КРУТОН\w*",
                                             r"БРЕЦЕЛ\w*", r"МУНЧ", r"MUNCH"]),
    ("nuts", "Ядки и семки", "soleno", [r"ЯДКИ", r"ФЪСТЪ\w*", r"БАДЕМ\w*", r"ЛЕШНИ\w*", r"ОРЕХ\w*", r"КАШУ",
                                         r"ШАМ\s+ФЪСТЪК", r"ШАМФЪСТ\w*", r"СЕМКИ", r"СЕМЕНА\s+(?:ОТ\s+)?ТИКВ\w*", r"СТАФИДИ",
                                         r"ФУРМИ", r"СУШЕНИ\s+ПЛОДОВЕ", r"СМЕС\s+ЯДКИ",
                                         r"ЛЕНЕНО\s+СЕМЕ", r"ЧИА", r"СУСАМ"]),
    # staples
    ("flour", "Брашно", "osnovni", [r"БРАШНО"]),
    ("sugar", "Захар", "osnovni", [r"ЗАХАР", r"ПОДСЛАДИТЕЛ\w*", r"СТЕВИЯ"]),
    ("salt", "Сол", "osnovni", [r"СОЛ", r"МОРСКА\s+СОЛ", r"ХИМАЛАЙСКА"]),
    ("oil", "Олио", "osnovni", [r"ОЛИО", r"СЛЪНЧОГЛЕДОВО\s+МАСЛО", r"РАПИЧНО\s+МАСЛО"]),
    ("olive_oil", "Зехтин", "osnovni", [r"ЗЕХТИН", r"МАСЛИНОВО\s+МАСЛО", r"МАСЛ\.\s*МАСЛО", r"OLIVE\s+OIL",
                                         r"EXTRA\s+VIRGIN"]),
    ("vinegar", "Оцет", "osnovni", [r"ОЦЕТ", r"БАЛСАМИКО"]),
    ("rice", "Ориз", "osnovni", [r"ОРИЗ"]),
    ("legumes", "Боб, леща, нахут", "osnovni", [r"БОБ", r"ЛЕЩА", r"НАХУТ", r"ВАРИВА"]),
    ("pasta", "Паста и спагети", "osnovni", [r"СПАГЕТИ", r"МАКАРОН\w*", r"ФУСИЛИ", r"ПЕНЕ", r"ТАЛИАТЕЛ\w*",
                                             r"ТАЛЯТЕЛ\w*", r"ЛАЗАНЯ", r"ПАСТА", r"ФИДЕ", r"ЮФКА", r"НУДЪЛС",
                                             r"НУДЛИ", r"NOODLE\w*", r"КУС-КУС", r"БУЛГУР", r"ЛУМАЧЕ", r"PIPE",
                                             r"FUSILLI", r"PENNE", r"SPAGHETTI"]),
    ("cereal", "Зърнени закуски", "osnovni", [r"ЗЪРНЕН\w*\s+ЗАКУСК\w*", r"МЮСЛИ", r"КОРНФЛЕЙКС", r"ОВЕСЕНИ\s+ЯДКИ",
                                              r"ГРАНОЛА", r"КОРН\s+ФЛЕЙКС"]),
    ("spices", "Подправки", "osnovni", [r"ПОДПРАВК\w*", r"ЧЕРЕН\s+ПИПЕР", r"ЧЕРВЕН\s+ПИПЕР", r"КИМИОН", r"ЧУБРИЦА",
                                         r"ДЖОДЖЕН", r"РИГАН", r"БОСИЛЕК", r"КАНЕЛА", r"ВАНИЛ\w*", r"БАКПУЛВЕР",
                                         r"СОДА\s+БИКАРБОНАТ", r"МАЯ", r"БУЛЬОН\w*", r"КУБЧЕТА\s+БУЛЬОН",
                                         r"ОВКУСИТЕЛ\w*", r"ЧУБРИЦ\w*", r"ВАНИЛОВ\w*\s+ЗАХАР"]),
    # canned & sauces
    ("sauce", "Сосове", "konservi", [r"КЕТЧУП\w*", r"МАЙОНЕЗ\w*", r"ГОРЧИЦ\w*", r"СОС", r"СОСОВЕ", r"ДРЕСИНГ\w*",
                                      r"ПЕСТО", r"KETCHUP"]),
    ("lyutenitsa", "Лютеница", "konservi", [r"ЛЮТЕНИЦ\w*", r"КЬОПООЛУ", r"АЙВАР", r"ЗАЕДЕВК\w*"]),
    ("canned_veg", "Зеленчукови консерви", "konservi", [r"ГРАХ", r"ЦАРЕВИЦ\w*", r"КОНСЕРВ\w*", r"ТУРШИЯ",
                                                        r"КИСЕЛИ\s+КРАСТАВИЧКИ", r"КОРНИШОН\w*", r"ЛЕЧО",
                                                        r"ГЮВЕЧ", r"ПЕЧЕНИ\s+ЧУШКИ", r"КОМПОТ\w*"]),
    ("olives", "Маслини", "konservi", [r"МАСЛИН\w*", r"OLIVES"]),
    ("soup", "Супи и готови ястия", "konservi", [r"СУПА", r"СУПИ", r"ЧОРБА", r"ГОТОВ\w*\s+ЯСТИ\w*", r"САРМИ",
                                                 r"ГОТВЕНИ\s+ЯСТИЯ", r"КУЛИНАРИЯ"]),
    # frozen
    ("ice_cream", "Сладолед", "zamrazeni", [r"СЛАДОЛЕД\w*", r"ICE\s+CREAM"]),
    ("frozen", "Замразени храни", "zamrazeni", [r"ЗАМРАЗЕН\w*", r"ПИЦА", r"ПИЦИ", r"КАРТОФКИ", r"ПЪРЖЕНИ\s+КАРТОФИ"]),
    # baby
    ("baby_food", "Бебешка храна", "bebe", [r"БЕБЕШК\w*\s+(?:ПЮРЕ|КАША|ХРАНА)", r"ПЮРЕ", r"ПЮРЕТА", r"КАША",
                                            r"МЛЕЧНА\s+КАША", r"МЛ\.\s*КАША", r"КАШИ"]),
    ("diapers", "Пелени", "bebe", [r"ПЕЛЕН\w*", r"PAMPERS", r"ПАМПЕРС", r"HUGGIES", r"ГАЩИЧКИ\s+ПЕЛЕН\w*"]),
    # personal care
    ("wet_wipes", "Мокри кърпи", "kozmetika", [r"МОКРИ\s+КЪРПИ", r"ВЛАЖНИ\s+КЪРПИ", r"КЪРПИ\s+МОКРИ"]),
    ("shampoo", "Шампоан", "kozmetika", [r"ШАМПОАН\w*", r"SHAMPOO", r"Ш-Н"]),
    ("conditioner", "Балсам и маска за коса", "kozmetika", [r"БАЛСАМ\s+ЗА\s+КОСА", r"МАСКА\s+ЗА\s+КОСА",
                                                            r"КОНДИЦИОНЕР\w*", r"БАЛСАМИ\s+И\s+МАСКИ"]),
    ("shower_gel", "Душ гел", "kozmetika", [r"ДУШ[\s-]*ГЕЛ\w*", r"SHOWER", r"ПЯНА\s+ЗА\s+ВАНА"]),
    ("soap", "Сапун", "kozmetika", [r"САПУН\w*", r"SOAP", r"С-Н"]),
    ("toothpaste", "Паста за зъби", "kozmetika", [r"ПАСТА\s+ЗА\s+ЗЪБИ", r"TOOTHPASTE", r"ПЗ"]),
    ("toothbrush", "Четка за зъби", "kozmetika", [r"ЧЕТК\w*\s+ЗА\s+ЗЪБИ", r"TOOTHBRUSH", r"ЧЗ",
                                                  r"ЕЛЕКТРИЧЕСКА\s+ЧЕТКА"]),
    ("oral_care", "Грижа за устата", "kozmetika", [r"ВОДА\s+ЗА\s+УСТА", r"ВОДА\s+ЗА\s+УСТНА", r"ЗЪБЕН\s+КОНЕЦ",
                                                   r"КОНЕЦ\s+ЗА\s+ЗЪБИ", r"УСТНА\s+ХИГИЕНА", r"ЗА\s+ДЕТСКИ\s+ЗЪБИ"]),
    ("deodorant", "Дезодорант", "kozmetika", [r"ДЕЗОДОРАНТ\w*", r"АНТИПЕРСПИРАНТ\w*", r"DEO\w*", r"РОЛ-ОН"]),
    ("skin_care", "Кремове и грижа за кожата", "kozmetika", [r"КРЕМ", r"КРЕМОВЕ", r"СЕРУМ\w*", r"ГЕЛ\s+ЗА\s+ЛИЦЕ",
                                                             r"МИЦЕЛАРН\w*", r"ТОНИК\s+ЗА\s+ЛИЦЕ", r"МАСКА\s+ЗА\s+ЛИЦЕ",
                                                             r"БАЛСАМ\s+ЗА\s+УСТНИ", r"МАСЛО\s+ЗА\s+ТЯЛО",
                                                             r"ЗА\s+ЛИЦЕ", r"СКРАБ"]),
    ("hair_dye", "Боя за коса", "kozmetika", [r"БОЯ\s+ЗА\s+КОСА", r"ЦВЯТ\s+ЗА\s+КОСА", r"БОЯ\s+КОСА"]),
    ("hair_styling", "Стилизиране на коса", "kozmetika", [r"ЛАК\s+ЗА\s+КОСА", r"ГЕЛ\s+ЗА\s+КОСА", r"ПЯНА\s+ЗА\s+КОСА",
                                                          r"ВОСЪК\s+ЗА\s+КОСА", r"СТИЛИЗИРАЩ\w*", r"ЗА\s+КОСА"]),
    ("shaving", "Бръснене", "kozmetika", [r"САМОБРЪСН\w*", r"БРЪСНАЧ\w*", r"ПЯНА\s+ЗА\s+БРЪСНЕНЕ",
                                          r"ГЕЛ\s+ЗА\s+БРЪСНЕНЕ", r"АФТЪРШЕЙВ", r"НОЖЧЕТА", r"ДЕПИЛ\w*"]),
    ("feminine", "Дамска хигиена", "kozmetika", [r"ПРЕВРЪЗК\w*", r"ТАМПОН\w*", r"ЕЖЕДНЕВНИ", r"ЕЖЕД\.\s*ПРЕВРЪЗКИ"]),
    ("makeup", "Грим", "kozmetika", [r"СПИРАЛА", r"ЧЕРВИЛО", r"ФОН\s+ДЬО\s+ТЕН", r"ПУДРА", r"ОЧНА\s+ЛИНИЯ",
                                      r"СЕНКИ\s+ЗА\s+ОЧИ", r"ЛАК\s+ЗА\s+НОКТИ", r"ГРИМ", r"КОРЕКТОР", r"MASCARA",
                                      r"МОЛИВ\s+ЗА\s+(?:ОЧИ|УСТНИ|ВЕЖДИ)"]),
    ("perfume", "Парфюм", "kozmetika", [r"ПАРФЮМ\w*", r"ТОАЛЕТНА\s+ВОДА", r"EAU\s+DE", r"ОДЕКОЛОН"]),
    ("cotton", "Клечки, тампони, памук", "kozmetika", [r"КЛЕЧКИ\s+ЗА\s+УШИ", r"ДИСКОВЕ\s+ЗА\s+ГРИМ",
                                                       r"ТАМПОНИ\s+ЗА\s+ГРИМ", r"КЪРПИ\s+ЗА\s+ГРИМ", r"ВАТА"]),
    ("condoms", "Презервативи", "kozmetika", [r"ПРЕЗЕРВАТИВ\w*"]),
    # household
    ("dish", "За съдове", "pochistvane", [r"ПРЕПАРАТ\s+ЗА\s+СЪДОВЕ", r"ЗА\s+СЪДОВЕ", r"СЪДОМИЯЛН\w*",
                                           r"ТАБЛЕТКИ\s+ЗА\s+СЪДОМИЯЛН\w*", r"FAIRY", r"ФЕЪРИ"]),
    ("laundry", "Пране", "pochistvane", [r"ПРАХ\s+ЗА\s+ПРАНЕ", r"ПЕРИЛЕН", r"ПЕРИЛНИ", r"ГЕЛ\s+ЗА\s+ПРАНЕ",
                                          r"КАПСУЛИ\s+ЗА\s+ПРАНЕ", r"ЗА\s+ПРАНЕ", r"ОМЕКОТИТЕЛ\w*", r"ПЕТНОВАДИТЕЛ\w*",
                                          r"ПРОТИВ\s+ПЕТНА", r"ИЗБЕЛВА\w*", r"ТЕЧЕН\s+ПЕРИЛЕН"]),
    ("paper", "Тоалетна хартия и салфетки", "pochistvane", [r"ТОАЛЕТНА\s+ХАРТИЯ", r"КУХНЕНСК\w*\s+РУЛА",
                                                            r"КУХНЕНСКА\s+ХАРТИЯ", r"САЛФЕТКИ", r"НОСНИ\s+КЪРПИЧКИ",
                                                            r"КЪРПИЧКИ", r"ТХ"]),
    ("cleaner", "Почистващи препарати", "pochistvane", [r"ПОЧИСТВА\w*", r"ПРЕПАРАТ\w*", r"ДЕЗИНФЕКТ\w*", r"БЕЛИНА",
                                                        r"ЧИСТАЧ\w*", r"ЗА\s+ПОД", r"ЗА\s+СТЪКЛА", r"ЗА\s+ТОАЛЕТНА",
                                                        r"ОСВЕЖИТЕЛ\w*", r"ВЕРОФОРМ", r"ДОМЕСТОС", r"ДУХАЛО",
                                                        r"СРЕДСТВА", r"ТОАЛЕТН\w*\s+БЛОКЧ\w*", r"WC[\s-]*БЛОКЧ\w*",
                                                        r"Т\.\s*Ч\.\s*БЛОКЧ\w*", r"БЛОКЧ\w*\s+ЗА\s+(?:ТОАЛЕТНА|WC)"]),
    ("cleaning_tools", "Кърпи, гъби и консумативи", "pochistvane", [r"МИКРОФИБ\w*", r"КЪРПА", r"КЪРПИ",
                                                                    r"ГЪБ\w*\s+ЗА\s+\w+", r"ГЪБА", r"ГЪБИЧКИ",
                                                                    r"МОП", r"СТИРК\w*", r"ТОРБИ\s+ЗА\s+СМЕТ",
                                                                    r"ЧУВАЛ\w*", r"РЪКАВИЦ\w*", r"ТЕЛ\s+ЗА\s+СЪДОВЕ"]),
    # home, kitchen, garden
    ("kitchenware", "Кухненски съдове", "dom", [r"ТИГАН\w*", r"ТЕНДЖЕР\w*", r"ТАВА", r"ТАВИ", r"ЧИНИ\w*", r"ЧАШ\w*",
                                                r"ПРИБОР\w*", r"НОЖ", r"НОЖОВЕ", r"ЛЪЖИ\w*", r"ВИЛИЦ\w*",
                                                r"КУТИ\w*\s+ЗА\s+ХРАНА", r"ФОЛИО", r"ХАРТИЯ\s+ЗА\s+ПЕЧЕНЕ",
                                                r"ДЪСКА\s+ЗА\s+РЯЗАНЕ", r"КУПА", r"КУПИ", r"ТЕРМОС\w*", r"БУРКАН\w*\s+ЗА"]),
    ("home", "Дом и декорация", "dom", [r"СВЕЩ\w*", r"КРУШК\w*", r"БАТЕРИ\w*", r"ЛАМП\w*", r"ДЕКОРАЦ\w*",
                                         r"ВЪЗГЛАВНИЦ\w*", r"ЧАРШАФ\w*", r"СПАЛН\w*\s+КОМПЛЕКТ", r"ХАВЛИ\w*",
                                         r"ТЕКСТИЛ", r"КОШ\w*", r"ЗАКАЧАЛК\w*", r"УДЪЛЖИТЕЛ", r"ЗАРЯДНО"]),
    ("garden", "Градина", "dom", [r"СЕМЕНА", r"ТОР", r"ТОРОВЕ", r"ГРАДИН\w*", r"ЦВЕТЯ", r"ПОЧВА", r"ПРЪСТ",
                                   r"САКСИ\w*", r"РАЗСАД\w*", r"БАРБЕКЮ", r"ВЪГЛИЩА"]),
    ("diy", "Ремонт и инструменти", "dom", [r"ИНСТРУМЕНТ\w*", r"БОРМАШИН\w*", r"ОТВЕРТК\w*", r"ЛЕПИЛО", r"СИЛИКОН\w*",
                                            r"ВИНТ\w*", r"ДЮБЕЛ\w*", r"ГРУНД", r"ЛАТЕКС", r"ШПАКЛОВ\w*", r"БОЯ"]),
    ("clothing", "Облекло", "dom", [r"ЧОРАП\w*", r"БЕЛЬО", r"ТЕНИСК\w*", r"ОБЛЕКЛО", r"ЧЕХЛИ", r"ПИЖАМ\w*"]),
    ("car", "За автомобила", "dom", [r"ЗА\s+КОЛА", r"АНТИФРИЗ", r"ЧИСТАЧКИ", r"АВТО"]),
    # pets
    ("pet", "За домашни любимци", "zoo", [r"ИГРАЧК\w*\s+ЗА\s+(?:КУЧЕ|КОТК)\w*", r"ЗА\s+КУЧЕТА", r"ЗА\s+КОТКИ",
                                           r"ЗА\s+КУЧЕ", r"ЗА\s+КОТКА", r"КУЧЕШК\w*", r"КОТЕШК\w*", r"PEDIGREE",
                                           r"WHISKAS", r"FRISKIES", r"ФРИСКИС", r"ПЕДИГРИ", r"УИСКАС", r"ROYAL\s+CANIN",
                                           r"РОЯЛ\s+КАНИН", r"ПЯСЪК\s+ЗА\s+КОТКИ", r"ГРАНУЛИ", r"ПАУЧ"]),
    # health
    ("supplement", "Хранителни добавки", "zdrave", [r"ХРАНИТЕЛН\w*\s+ДОБАВК\w*", r"ВИТАМИН\w*", r"МАГНЕЗИЙ",
                                                    r"ЦИНК", r"ПРОБИОТИ\w*", r"ОМЕГА", r"КОЛАГЕН", r"ЖЕЛЯЗО",
                                                    r"ПРОТЕИН\w*", r"ФИТНЕС\s+ДОБАВКИ"]),
    ("medicine", "Лекарства и медицински", "zdrave", [r"ТАБЛ\w*", r"КАПС\.?", r"КАПСУЛИ", r"САШЕ\w*", r"СИРОП",
                                                      r"СПРЕЙ\s+ЗА\s+(?:НОС|ГЪРЛО)", r"НАЗ\.\s*СПРЕЙ", r"КАПКИ",
                                                      r"АМП\w*", r"СУСП\w*", r"СУПОЗ\w*", r"ЕФ\.\s*ТАБЛ", r"БИНТ\w*",
                                                      r"ПЛАСТИР\w*", r"ТЕРМОМЕТ\w*", r"ТЕСТ\s+ЗА", r"МАЗ",
                                                      r"СПИРТ\s+ЕТИЛОВ", r"ЛЕКАРСТВ\w*"]),
    # toys, books, party
    ("toys", "Играчки", "igrachki", [r"ИГРАЧК\w*", r"HOT\s+WHEELS", r"LEGO", r"ЛЕГО", r"КУКЛ\w*", r"ПЪЗЕЛ\w*",
                                      r"ПЛЮШ\w*", r"КОНСТРУКТОР\w*", r"НАСТОЛН\w*\s+ИГР\w*", r"ТОПКА", r"БАЛОН\w*",
                                      r"КОЛИЧК\w*", r"BARBIE", r"MONSTER\s+TRUCKS?", r"ИГРА"]),
    ("books", "Книги и канцелария", "igrachki", [r"КНИГ\w*", r"КНИЖК\w*", r"ПРИКАЗК\w*", r"ОЦВЕТЯВ\w*",
                                                 r"СПИСАНИ\w*", r"ВЕСТНИК\w*", r"ТЕТРАД\w*", r"ХИМИКАЛ\w*",
                                                 r"МОЛИВ\w*", r"ФЛУМАСТ\w*", r"ЗА\s+УЧИЛИЩЕ", r"СТИКЕР\w*"]),
    ("party", "Парти и празници", "igrachki", [r"ПАРТИ", r"СВЕЩИЧК\w*", r"МАРТЕНИЦ\w*", r"УКРАС\w*", r"ЕЛХ\w*",
                                               r"КОЛЕДН\w*", r"ВЕЛИКДЕН\w*", r"БОЯ\s+ЗА\s+ЯЙЦА", r"ПОДАРЪЧ\w*"]),
]
# Sub-types of a broad kind, found anywhere in the name or category (the earliest-word rule above stops at 'Кафе'
# in 'Кафе Dallmayr Азуро Nespresso Капсули'). Same-brand items of different sub-types are different products, not
# flavours: a 1 kg bag of beans and a 18 g instant sachet must not share a family. The first sub-type wins wherever
# it appears (capsules, disposables); otherwise the earliest mention ('Самобръсначка + 2 ножчета' is a razor,
# 'Ножчета за самобръсначка' are blades).
SUBKINDS = {
    "coffee": [
        ("coffee_capsules", "Кафе капсули", [r"КАПСУЛ\w*", r"CAPSUL\w*", r"NESPRESSO", r"DOLCE\s*GUSTO", r"TASSIMO"]),
        ("coffee_instant", "Разтворимо кафе", [r"РАЗТВОРИМ\w*", r"INSTANT", r"\d\s*В\s*1", r"\d\s*IN\s*1", r"СТИК\w*",
                                               r"САШЕ\w*", r"NESCAFE", r"НЕСКАФЕ", r"КАПУЧИНО", r"CAPPUCCINO"]),
        ("coffee_pods", "Кафе дози", [r"ДОЗИ", r"PADS?", r"ПАДОВЕ", r"SENSEO"]),
        ("coffee_beans", "Кафе на зърна", [r"ЗЪРН\w*", r"BEANS?", r"К\.\s*ЗЪРНА"]),
        ("coffee_ground", "Мляно кафе", [r"МЛЯН\w*", r"GROUND"]),
    ],
    "shaving": [
        ("razor_disposable", "Еднократни самобръсначки", [r"ЕДНОКРАТН\w*", r"DISPOSABLE"]),
        ("razor_blades", "Ножчета и резерви", [r"НОЖЧЕТА", r"РЕЗЕРВ\w*", r"КАРТРИДЖ\w*", r"ГЛАВИ", r"BLADES?",
                                               r"CARTRIDGES?"]),
        ("shaving_prep", "Пяна и гел за бръснене", [r"ПЯНА", r"ГЕЛ", r"АФТЪРШЕЙВ", r"AFTER\s*SHAVE", r"FOAM", r"BALM",
                                                    r"БАЛСАМ", r"ЛОСИОН"]),
        ("depilation", "Депилация", [r"ДЕПИЛ\w*", r"ВОСЪЧН\w*", r"КОЛАНЧ\w*"]),
        ("razor", "Самобръсначки", [r"САМОБРЪСН\w*", r"БРЪСНАЧ\w*", r"RAZOR"]),
    ],
}
# Flavours and varieties: what tells two lines of one product apart, in either script. A word is matched whole
# against these stems ('ЯГОД\w*' = ягода, ягоди, ягодов...). derive.py vetoes a name match when each name has one
# the other lacks (Merlot vs Mavrud, cookies & cream vs stracciatella); STRICT ones must also be on both or neither
# (Zero vs regular cola, aged vs young rakia).
FLAVOURS = {
    # fruit
    "strawberry": [r"ЯГОД\w*", r"STRAWBERR\w*"], "raspberry": [r"МАЛИН\w*", r"RASPBERR\w*"],
    "blueberry": [r"БОРОВИН\w*", r"BLUEBERR\w*", r"BILBERR\w*", r"ЧЕРНИЧ\w*"],
    "cherry": [r"ЧЕРЕШ\w*", r"ВИШН\w*", r"CHERR\w*"], "peach": [r"ПРАСКОВ\w*", r"PEACH\w*"],
    "apricot": [r"КАЙСИ\w*", r"APRICOT\w*"], "mango": [r"МАНГО", r"MANGO"],
    "pineapple": [r"АНАНАС\w*", r"PINEAPPLE\w*"], "apple": [r"ЯБЪЛК\w*", r"APPLES?"],
    "pear": [r"КРУШ[АИО]\w*", r"PEARS?"], "grape": [r"ГРОЗД\w*", r"GRAPES?"],
    "orange": [r"ПОРТОКАЛ\w*", r"ORANGES?"], "lemon": [r"ЛИМОН(?:И|А|ОВ\w*)?", r"LEMONS?"],
    "lime": [r"ЛАЙМ\w*", r"LIMES?"], "grapefruit": [r"ГРЕЙПФРУТ\w*", r"GRAPEFRUIT"],
    "tangerine": [r"МАНДАРИН\w*", r"TANGERINE\w*", r"MANDARIN\w*"], "banana": [r"БАНАН\w*", r"BANANA\w*"],
    "coconut": [r"КОКОС\w*", r"COCONUT\w*", r"COCO"], "watermelon": [r"ДИНЯ", r"ДИНИ", r"WATERMELON"],
    "melon": [r"ПЪПЕШ\w*", r"MELON"], "kiwi": [r"КИВИ", r"KIWI"], "pomegranate": [r"НАР", r"POMEGRANATE"],
    "plum": [r"СЛИВ[АИО]\w*", r"PLUMS?"], "quince": [r"ДЮЛ[ЯИЕ]\w*", r"QUINCE"],
    "fig": [r"СМОКИН\w*", r"FIGS?"], "date": [r"ФУРМ[АИ]", r"DATES"],
    "blackcurrant": [r"КАСИС", r"ФРЕНСКО\s+ГРОЗДЕ", r"BLACKCURRANT"], "forest": [r"ГОРСК\w*", r"FOREST"],
    "tropical": [r"ТРОПИЧ\w*", r"TROPICAL", r"ЕКЗОТ\w*", r"EXOTIC"], "passion": [r"МАРАКУЯ", r"PASSION"],
    # nuts, sweets
    "hazelnut": [r"ЛЕШНИ\w*", r"HAZELNUT\w*"], "almond": [r"БАДЕМ\w*", r"ALMOND\w*"],
    "peanut": [r"ФЪСТЪ\w*", r"PEANUT\w*"], "pistachio": [r"ШАМФЪСТ\w*", r"PISTACHIO\w*"],
    "walnut": [r"ОРЕХ\w*", r"WALNUT\w*"], "cashew": [r"КАШУ", r"CASHEW\w*"],
    "chocolate": [r"ШОКОЛАД\w*", r"ШОКО", r"CHOCO\w*"], "cocoa": [r"КАКАО\w*", r"COCOA"],
    "vanilla": [r"ВАНИЛ\w*", r"VANIL\w*"], "caramel": [r"КАРАМЕЛ\w*", r"CARAMEL\w*", r"ТОФИ", r"TOFFEE"],
    "coffee": [r"КАФЕ", r"COFFEE", r"МОКА", r"MOCHA"], "honey": [r"МЕД", r"МЕДЕН\w*", r"HONEY"],
    "cookie": [r"БИСКВИТ\w*", r"COOKIES?", r"BISCUITS?"], "cream": [r"КРЕМ\w*", r"CREAM\w*", r"СМЕТАН\w*"],
    "stracciatella": [r"СТРАЧ\w*", r"СТРАТИЧЕЛ\w*", r"STRACCIATELLA"], "tiramisu": [r"ТИРАМИСУ", r"TIRAMISU"],
    "brownie": [r"БРАУНИ", r"BROWNIES?"], "cheesecake": [r"ЧИЙЗКЕЙК\w*", r"CHEESECAKE"],
    "praline": [r"ПРАЛИН\w*", r"PRALINE\w*"], "nougat": [r"НУГА", r"NOUGAT"],
    "mint": [r"МЕНТ[АО]\w*", r"MINT\w*", r"ДЖОДЖЕН", r"MENTHOL"], "cinnamon": [r"КАНЕЛ\w*", r"CINNAMON"],
    "ginger": [r"ДЖИНДЖИФИЛ\w*", r"GINGER"],
    # savoury
    "cheese": [r"СИРЕН\w*", r"CHEESE"], "kashkaval": [r"КАШКАВАЛ\w*"], "paprika": [r"ПАПРИКА", r"PAPRIKA"],
    "salt": [r"СОЛ", r"SALT\w*"], "onion": [r"ЛУК", r"ONION\w*"], "bacon": [r"БЕКОН", r"BACON"],
    "ketchup": [r"КЕТЧУП", r"KETCHUP"], "chili": [r"ЧИЛИ", r"CHILL?I", r"ЛЮТ\w*"], "garlic": [r"ЧЕСЪН\w*", r"GARLIC"],
    "barbecue": [r"БАРБЕКЮ", r"BBQ", r"BARBECUE"], "tomato": [r"ДОМАТ\w*", r"TOMATO\w*"],
    "mushroom": [r"ГЪБ[ИА]", r"MUSHROOMS?"],
    # meat and fish (pet food, deli)
    "chicken": [r"ПИЛЕ", r"ПИЛЕШК\w*", r"CHICKEN"], "turkey": [r"ПУЕШК\w*", r"ПУЙК\w*", r"TURKEY"],
    "pork": [r"СВИНСК\w*", r"PORK"], "beef": [r"ТЕЛЕШК\w*", r"ГОВЕЖД\w*", r"BEEF"], "lamb": [r"АГНЕШК\w*", r"LAMB"],
    "duck": [r"ПАТЕШК\w*", r"DUCK"], "rabbit": [r"ЗАЕШК\w*", r"RABBIT"], "tuna": [r"ТОН", r"TUNA"],
    "salmon": [r"СЬОМГ\w*", r"SALMON"], "trout": [r"ПЪСТЪРВ\w*", r"TROUT"],
    # milk of
    "cow": [r"КРАВЕ\w*", r"COW"], "sheep": [r"ОВЧ[ЕИ]\w*", r"SHEEP"], "goat": [r"КОЗ[ЕИ]", r"GOAT"],
    "buffalo": [r"БИВОЛ\w*", r"BUFFALO"],
    # colours (also chocolate and wine types)
    "milk": [r"МЛЕЧ(?:ЕН|НА|НО|НИ)", r"MILK"], "white": [r"БЯЛ[АО]?", r"БЕЛИ", r"WHITE"],
    "dark": [r"ЧЕР(?:ЕН|НА|НО|НИ)", r"BLACK", r"DARK", r"НАТУРАЛ(?:ЕН|НА|НИ)", r"ТЪМ(?:ЕН|НА|НИ)", r"BITTER"],
    "red": [r"ЧЕРВЕН\w*", r"RED"], "green": [r"ЗЕЛЕН[АОИ]?", r"GREEN"], "pink": [r"РОЗОВ\w*", r"РОЗЕ", r"PINK", r"ROSE"],
    "yellow": [r"ЖЪЛТ\w*", r"YELLOW"], "brown": [r"КАФЯВ\w*", r"BROWN"], "blue": [r"СИН[ЯИ]?", r"СИНЬО", r"BLUE"],
    "charcoal": [r"ВЪГЛЕН", r"CHARCOAL"],
    # grapes
    "merlot": [r"МЕРЛО", r"MERLOT"], "cabernet": [r"КАБЕРНЕ", r"CABERNET"], "mavrud": [r"МАВРУД", r"MAVRUD"],
    "chardonnay": [r"ШАРДОНЕ", r"CHARDONNAY"], "muscat": [r"МУСКАТ\w*", r"МИСКЕТ", r"MUSCAT", r"MOSCATO"],
    "sauvignon": [r"СОВИНЬОН", r"SAUVIGNON"], "franc": [r"ФРАН", r"FRANC"], "pinot": [r"ПИНО", r"PINOT"],
    "noir": [r"НОАР", r"NOIR"], "grigio": [r"ГРИДЖО", r"ГРИЖИО", r"GRIGIO", r"GRIS"],
    "syrah": [r"СИРА", r"ШИРАЗ", r"SYRAH", r"SHIRAZ"], "rubin": [r"РУБИН", r"RUBIN"], "melnik": [r"МЕЛНИК", r"MELNIK"],
    "gamza": [r"ГЪМЗА", r"GAMZA"], "dimyat": [r"ДИМЯТ", r"DIMYAT"], "traminer": [r"ТРАМИНЕР", r"TRAMINER"],
    "riesling": [r"РИЗЛИНГ", r"RIESLING"], "viognier": [r"ВИОНИЕ", r"VIOGNIER"],
    "tempranillo": [r"ТЕМПРАНИЛО", r"TEMPRANILLO"], "malbec": [r"МАЛБЕК", r"MALBEC"],
    "pamid": [r"ПАМИД", r"PAMID"], "sangiovese": [r"САНДЖОВЕЗЕ", r"SANGIOVESE"],
    # strict: present on one side only is already another product
    "zero": [r"ZERO", r"ЗИРО", r"LIGHT", r"ЛАЙТ", r"DIET"], "aged": [r"ОТЛЕЖАЛ\w*"],
    "decaf": [r"DECAF\w*", r"БЕЗКОФЕИН\w*"], "lactose_free": [r"БЕЗЛАКТОЗ\w*", r"LACTOSE"],
}
STRICT_FLAVOURS = {"zero", "aged", "decaf", "lactose_free"}
# Not a taste: a name may leave these out ('Хляб нарязан' is the white one, 'Сирене' the cow's milk one).
NOT_TASTES = {"milk", "white", "dark", "red", "green", "pink", "yellow", "brown", "blue", "charcoal", "cow", "sheep",
              "goat", "buffalo"} | STRICT_FLAVOURS
_FLAVOUR_RE = re.compile("|".join(f"(?P<{k}>{'|'.join(alts)})" for k, alts in FLAVOURS.items()))


def flavour_of(word: str) -> str | None:
    """The flavour/variety a whole upper-case word names ('ЯГОДОВ', 'STRAWBERRY' -> 'strawberry'), else None."""
    m = _FLAVOUR_RE.fullmatch(word)
    return m.lastgroup if m else None


KIND_LABEL = {k: label for k, label, _d, _a in KINDS}
KIND_DEPT = {k: d for k, _l, d, _a in KINDS}
for _parent, _subs in SUBKINDS.items():
    for _k, _label, _alts in _subs:
        KIND_LABEL.setdefault(_k, _label)
        KIND_DEPT.setdefault(_k, KIND_DEPT[_parent])

# Broad category words that set a department when no kind is found (category path segments, BulMag slugs).
DEPT_WORDS = [
    ("napitki", [r"НАПИТКИ", r"БЕЗАЛКОХОЛНИ"]), ("alkohol", [r"АЛКОХОЛ\w*", r"СПИРТНИ", r"ВИНА", r"БИРИ"]),
    ("kafe", [r"КАФЕ", r"ЧАЙ"]), ("mlechni", [r"МЛЕЧНИ", r"СИРЕНА", r"ЯЙЦА"]), ("meso", [r"МЕСО", r"РИБА", r"МЕСНИ"]),
    ("kolbasi", [r"КОЛБАСИ", r"ДЕЛИКАТЕСИ"]), ("plodove", [r"ПЛОДОВЕ", r"ЗЕЛЕНЧУЦИ"]),
    ("hlyab", [r"ПЕКАРНА", r"ХЛЕБНИ", r"ХЛЯБ"]), ("sladko", [r"СЛАДКО", r"СЛАДКИ", r"ЗАХАРНИ", r"ДЕСЕРТИ"]),
    ("soleno", [r"СОЛЕНО", r"СОЛЕНИ", r"СНАКС\w*", r"ЯДКИ"]),
    ("osnovni", [r"ОСНОВНИ", r"БАКАЛИЯ", r"ПАКЕТИРАНИ", r"ПАКЕТАЖ", r"JUST\s+ASIA", r"СПЕЦИАЛНИ\s+ХРАНИ",
                 r"БЕЗ\s+ОСНОВНА"]),
    ("konservi", [r"КОНСЕРВ\w*", r"СОСОВЕ"]), ("zamrazeni", [r"ЗАМРАЗЕН\w*"]),
    ("bebe", [r"БЕБЕ\w*", r"ДЕТЕТО", r"ДЕТСК\w*"]),
    ("kozmetika", [r"КОЗМЕТИКА", r"ЛИЧНА\s+ГРИЖА", r"ХИГИЕНА", r"ДРОГЕРИЯ"]),
    ("pochistvane", [r"ПОЧИСТ\w*", r"ПРАНЕ", r"ДОМАКИН\w*", r"ХАРТИЕНИ"]),
    ("dom", [r"ЗА\s+ДОМА", r"ДОМ", r"ГРАДИН\w*", r"КУХНЯ", r"ТЕХНИКА", r"ОФИСА", r"НЕХРАНИ"]),
    ("zoo", [r"ЗООМАГАЗИН", r"ЖИВОТНИ", r"ЛЮБИМЦИ", r"КУЧЕТА", r"КОТКИ"]),
    ("zdrave", [r"АПТЕКА", r"ЗДРАВЕ", r"ДОБАВКИ", r"ЛЕКАРСТВА"]),
    ("igrachki", [r"ИГРАЧКИ", r"СВОБОДНО\s+ВРЕМЕ", r"КНИГИ", r"ПАРТИ"]),
]

KZP_KIND = {
    **{c: "bread" for c in (1, 2, 3, 4)}, 5: "dough", 6: "milk", 7: "yogurt", 8: "white_cheese", 9: "white_cheese",
    10: "yellow_cheese", 11: "yellow_cheese", 12: "butter", 13: "cottage_cheese", 14: "cottage_cheese",
    15: "chicken", 16: "chicken", 17: "chicken", **{c: "pork" for c in (18, 19, 20, 21, 22)}, 23: "beef", 24: "beef",
    25: "mince", 26: "sausages", 27: "salami", 28: "salami", 29: "fish", 30: "fish", 31: "eggs", 32: "eggs",
    33: "legumes", 34: "legumes", 35: "rice", 36: "pasta", 37: "pasta", 38: "sugar", 39: "salt", 40: "flour",
    41: "flour", 42: "oil", 43: "olive_oil", 44: "vinegar", 45: "vinegar", 46: "canned_veg", 47: "canned_veg",
    48: "canned_tomatoes", 49: "lyutenitsa", 50: "citrus", 51: "citrus", 52: "bananas", 53: "apples", 54: "tomatoes",
    55: "onions", 56: "vegetables", 57: "vegetables", 58: "cucumbers", 59: "onions", 60: "mushrooms",
    61: "potatoes", 62: "olives", 63: "baby_food", 64: "baby_food", 65: "formula", 66: "biscuits", 67: "croissant",
    68: "pastry", 69: "chocolate", 70: "coffee", 71: "coffee", 72: "tea", 73: "water", 74: "beer", 75: "wine",
    76: "wine", 77: "rakia", 78: "tobacco", 79: "dish", 80: "toothbrush", 81: "toothpaste", 82: "shampoo",
    83: "soap", 84: "wet_wipes", 85: "paper", **{c: "medicine" for c in range(86, 102)},
}

# --------------------------------------------------------------------------- transliteration

_CYR2LAT = {"А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ж": "ZH", "З": "Z", "И": "I", "Й": "Y",
            "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
            "Ф": "F", "Х": "H", "Ц": "TS", "Ч": "CH", "Ш": "SH", "Щ": "SHT", "Ъ": "A", "Ь": "Y", "Ю": "YU",
            "Я": "YA", "Ё": "YO", "Э": "E", "Ы": "I"}
# Regex translit: slugs and Latin names spell some letters several ways (BulMag: 'sudzhuci', 'cikoriya').
_CYR2LAT_RE = {**_CYR2LAT, "Ц": "(?:TS|C|TZ)", "Ъ": "(?:A|U)", "Й": "(?:Y|I|J)?", "Я": "(?:YA|IA|JA)",
               "Ю": "(?:YU|IU|JU)", "Ж": "(?:ZH|J)", "Х": "(?:H|KH)", "Щ": "(?:SHT|ST)"}


def translit(s: str) -> str:
    """Cyrillic -> Latin (Bulgarian streamlined system), upper-cased."""
    return "".join(_CYR2LAT.get(ch, ch) for ch in s.upper())


_LAT2CYR = [("SHT", "Щ"), ("SH", "Ш"), ("CH", "Ч"), ("ZH", "Ж"), ("TS", "Ц"), ("YU", "Ю"), ("YA", "Я"),
            ("A", "А"), ("B", "Б"), ("C", "К"), ("D", "Д"), ("E", "Е"), ("F", "Ф"), ("G", "Г"), ("H", "Х"),
            ("I", "И"), ("J", "Дж"), ("K", "К"), ("L", "Л"), ("M", "М"), ("N", "Н"), ("O", "О"), ("P", "П"),
            ("Q", "К"), ("R", "Р"), ("S", "С"), ("T", "Т"), ("U", "У"), ("V", "В"), ("W", "У"), ("X", "КС"),
            ("Y", "Й"), ("Z", "З")]


def to_cyrillic(s: str) -> str:
    """Rough Latin -> Cyrillic ('roshen' -> 'РОШЕН'); only used to widen searches."""
    s, out, i = s.upper(), [], 0
    while i < len(s):
        for lat, cyr in _LAT2CYR:
            if s.startswith(lat, i):
                out.append(cyr.upper())
                i += len(lat)
                break
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def latin_key(word: str) -> str:
    """Normalised Latin spelling: 'Lacmi' and 'ЛАКМИ' -> 'LAKMI', 'Roshen'/'РОШЕН' -> 'ROSHEN', 'Melissa'/'МЕЛИСА'
    -> 'MELISA', 'Eduscho' -> 'EDUSHO'."""
    s = translit(word).replace("SCH", "SH").replace("CK", "K").replace("PH", "F").replace("Q", "K").replace("W", "V")
    s = re.sub(r"C(?!H)", "K", s.replace("X", "KS"))
    return re.sub(r"([A-Z])\1+", r"\1", s)


def consonants(word: str) -> str:
    """Vowel-blind form for 'is this brand in that name': 'ПОМОРИЙСКА' -> 'PMRSK' starts with 'POMORIE' -> 'PMR'."""
    return re.sub(r"[AEIOUY]", "", latin_key(word))


def shlyokavitsa(word: str) -> str:
    """Bulgarian typed in Latin chat-style ('shlyokavitsa'): q = я, w = в, x = х, 4 = ч ('mlqko' -> 'mlyako',
    '4ervena' -> 'chervena'). Numbers and pack sizes stay ('pampers 4', '4x80')."""
    w = word.lower()
    if not re.fullmatch(r"[a-z0-9]+", w) or w.isdigit() or re.search(r"\dx|x\d", w):
        return word
    w = w.replace("q", "ya").replace("w", "v").replace("x", "h")
    return re.sub(r"(?<=[a-z])4|4(?=[a-z])", "ch", w)


def typo_key(word: str) -> str:
    """Looser than skeleton(): every vowel dropped, so a missed or wrong vowel still matches
    ('кашкавл'/'кашкавал' -> 'QKSHKVL'). 'Q' never occurs in a latin_key, so these never meet one in 'alt'.
    '' when too short to be distinctive (5+ consonants)."""
    s = re.sub(r"([^A])\1+", r"\1", skeleton(word).replace("A", ""))
    return "Q" + s if len(s) >= 5 else ""


def phonetic_ok(key: str) -> bool:
    """A skeleton() key is distinctive enough to match on only with 4+ consonant letters ('MANSTAR' yes,
    'MALKA' -- Milka, малка, мелко -- no)."""
    return len(key.replace("A", "")) >= 4


def skeleton(word: str) -> str:
    """Script-independent phonetic key: consonants kept, every vowel run reduced to 'A', a final vowel dropped.
    'Monster'/'МОНСТЪР' -> 'MANSTAR', 'Roshen'/'РОШЕН' -> 'RASHAN', 'Lacmi'/'ЛАКМИ' -> 'LAKM', 'Colgate'/'КОЛГЕЙТ'
    -> 'KALGAT', while 'МАНАСТИР' -> 'MANASTAR' and 'Mainstr' -> 'MANSTR' stay apart."""
    s = latin_key(word).replace("J", "Y")
    s = re.sub(r"[^A-Z]", "", s)
    s = re.sub(r"(?<=[AEIOU])Y(?=[AEIOU]|$)", "", s)            # 'ИЙ'/'IY' endings: 'Енергийни' ~ 'Energini'
    s = re.sub(r"[AEIOUY]+", "A", s)
    s = re.sub(r"([^A])\1+", r"\1", s)
    return s[:-1] if len(s) > 1 and s.endswith("A") else s


# --------------------------------------------------------------------------- normalisation

_LOOKALIKE = str.maketrans({"A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О",
                            "P": "Р", "C": "С", "T": "Т", "X": "Х", "Y": "У"})
_ABBR = [(re.compile(p), r) for p, r in [
    (r"(?<!\w)Ш-Д(?!\w)", "ШОКОЛАД"), (r"(?<!\w)ЕН(?:ЕРГ)?\.\s*", "ЕНЕРГИЙНА "), (r"(?<!\w)НАП\.\s*", "НАПИТКА "),
    (r"(?<!\w)КИС\.\s*", "КИСЕЛО "), (r"(?<!\w)КИС\s+(?=МЛ)", "КИСЕЛО "), (r"(?<!\w)ПР\.\s*МЛ", "ПРЯСНО МЛ"), (r"(?<!\w)ПМ(?!\w)", "ПРЯСНО МЛЯКО"),
    (r"(?<!\w)(?<!\d )(?:[КK]\.\s*[МM]Л?\.|КМ(?!\w))", "КИСЕЛО МЛЯКО "),         # 'КМ ВЕРЕЯ', 'K.M.', 'К.МЛ.'
    (r"(?<!\w)ЧВ(?!\w)", "ЧЕРВЕНО ВИНО"), (r"(?<!\w)БВ(?!\w)", "БЯЛО ВИНО"), (r"(?<!\w)Б-ТИ(?!\w)", "БИСКВИТИ"),
    (r"(?<!\w)КР?-Н(?!\w)", "КРОАСАН"), (r"(?<!\w)МИН\.\s*ВОД", "МИНЕРАЛНА ВОД"), (r"(?<!\w)ПРЕП\.\s*", "ПРЕПАРАТ "),
    (r"(?<!\w)МАСЛ\.\s*МАСЛО", "МАСЛИНОВО МАСЛО"), (r"(?<!\w)(?:ШАМ|Ш\.)[\s-]*(?=ФЪСТ)", "ШАМ"),
    # Negations name what a product is *not*: 'Monster без захар' is not sugar.
    (r"(?<!\w)БЕЗ\s+(?:ДОБАВЕНА\s+)?(?:ЗАХАР|ЛАКТОЗА|ГЛУТЕН|АЛКОХОЛ|КОФЕИН|СОЛ)\w*", " "),
    (r"(?<!\w)(?:SUGAR\s+FREE|ZERO\s+SUGAR|NO\s+SUGAR)", " "),
]]


# Brands written out in words: 'СЕВЪН ДЕЙС СУПЕР МАКС' and '7ДЕЙС' are 7 Days.
BRAND_SPELLINGS = [(re.compile(r"(?<!\w)(?:СЕВЪН\s*|7\s*)ДЕЙС(?!\w)"), "7 DAYS")]


def fix_scripts(text: str) -> str:
    """Latin look-alikes inside Cyrillic words ('KИСЕЛО') -> Cyrillic. Each letter run is fixed on its own, so
    '500 ML/ОПАКОВКА' keeps its Latin 'ML'."""
    return re.sub(r"[A-ZА-Я]+", lambda m: m.group().translate(_LOOKALIKE)
                  if re.search(r"[А-Я]", m.group()) and re.search(r"[A-Z]", m.group()) else m.group(), text)


_PHRASES_ANY_CASE = [(re.compile(rx.pattern, re.I), rep) for rx, rep in BRAND_SPELLINGS + _ABBR]


def expand_phrases(text: str) -> str:
    """The phrase rewrites of normalize() on text as written (case kept elsewhere), for labels shown to people:
    'Севън Дейс кр-н Макс' -> '7 DAYS КРОАСАН Макс'."""
    for rx, rep in _PHRASES_ANY_CASE:
        text = rx.sub(rep, text)
    return text


def normalize(text: str) -> str:
    s = fix_scripts((text or "").upper().replace("Ё", "Е"))
    for rx, rep in BRAND_SPELLINGS:
        s = rx.sub(rep, s)
    for rx, rep in _ABBR:
        s = rx.sub(rep, s)
    return s


def _to_re_latin(alt: str) -> str:
    return "".join(_CYR2LAT_RE.get(ch, ch) for ch in alt)


class _Matcher:
    """Finds the earliest word-start match among many regex alternatives and, at that position, the longest.
    Alternatives are bucketed by their literal 2-letter prefix so each word start only tries a few."""

    def __init__(self, pairs):
        self.buckets: dict[str, list] = collections.defaultdict(list)
        self.wild: list = []
        for alt, key in pairs:
            rx = re.compile(f"(?:{alt})(?!\\w)")
            lit = re.match(r"[A-ZА-Я0-9]*", alt).group(0)
            (self.buckets[lit[:2]] if len(lit) >= 2 else self.wild).append((rx, key))

    def first(self, text: str, from_end: bool = False, start: int = 0) -> tuple[str | None, int]:
        return self.first_span(text, from_end, start)[:2]

    def first_span(self, text: str, from_end: bool = False, start: int = 0) -> tuple[str | None, int, int]:
        """(key, start, end) of the earliest (or, from_end, the last) match at or after `start`."""
        starts = [m for m in _WORD_START.finditer(text) if m.start() >= start]
        for m in (reversed(starts) if from_end else starts):
            pos = m.start()
            best = None
            for rx, key in self.buckets.get(text[pos:pos + 2], []) + self.wild:
                hit = rx.match(text, pos)
                if hit and (best is None or hit.end() > best[0]):
                    best = (hit.end(), key)
            if best:
                return best[1], pos, best[0]
        return None, -1, -1


_WORD_START = re.compile(r"(?<!\w)[\w*]")
_KIND_M = _Matcher([(a, k) for k, _l, _d, alts in KINDS for a in alts])
_KIND_M_LAT = _Matcher([(_to_re_latin(a), k) for k, _l, _d, alts in KINDS for a in alts])
# A generic kind found first in the name gives way to a specific one found anywhere in it, or named by the
# retailer category / KZP code: 'Мляко на прах за кърмачета', 'МЛЯКО NAN 1 ОПТИПРО' are formula, not milk.
# 'ПАСТА ORAL-B 3DW' is toothpaste, not spaghetti: an oral-care brand or 'за зъби' turns pasta into toothpaste.
_YIELDS = {"milk": {"formula"}, "pasta": {"toothpaste"}}
ORAL_CARE = [r"ЗА\s+ЗЪБИ", r"ORAL[\s-]*B", r"ОРАЛ[\s-]*Б", r"COLGATE", r"КОЛГЕЙТ", r"PARODONTAX", r"ПАРОДОНТАКС",
             r"SENSODYNE", r"СЕНСОДАЙН", r"LACALUT", r"ЛАКАЛУТ", r"BLEND[\s-]*A[\s-]*MED", r"БЛЕНД[\s-]*А[\s-]*МЕД",
             r"AQUAFRESH", r"АКУАФРЕШ", r"ELMEX", r"ЕЛМЕКС", r"SIGNAL", r"СИГНАЛ", r"ASTERA", r"АСТЕРА",
             r"MERIDOL", r"PRESIDENT", r"VITIS", r"CREST", r"MENTADENT", r"ZENDIUM", r"SPLAT"]


KIND_PHRASE = {k: re.compile(r"(?:" + "|".join(alts) + r")") for k, _l, _d, alts in KINDS}   # fullmatch a phrase
_KIND_ONLY = {k: re.compile(r"(?<!\w)(?:" + "|".join(alts + (ORAL_CARE if k == "toothpaste" else [])) + r")(?!\w)")
              for k, _l, _d, alts in KINDS if any(k in v for v in _YIELDS.values())}
_DEPT_M = _Matcher([(a, d) for d, alts in DEPT_WORDS for a in alts])
_DEPT_M_LAT = _Matcher([(_to_re_latin(a), d) for d, alts in DEPT_WORDS for a in alts])
_SUBKIND_RE = {parent: [(k, re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)")) for k, _l, alts in subs]
               for parent, subs in SUBKINDS.items()}


# A one-word adjective ('Протеинова', 'Бананови', 'Шоколадова', 'Ябълков') describes the noun after it: 'Протеинова
# бисквита' is a biscuit, 'Шоколадова вафла' a wafer, 'Ябълков оцет' vinegar. It names the type only when no noun
# follows ('Сливова' rakia).
_ADJECTIVE = re.compile(r"\w+(?:ОВ|ЕВ)[АОИ]?")


def kind_of_name(name: str) -> str | None:
    text = normalize(name)
    kind, pos, end = _KIND_M.first_span(text)
    while kind and _ADJECTIVE.fullmatch(text[pos:end]):          # 'Бананови Протеинови Бисквити': the last noun
        nxt = _WORD_START.search(text, end)
        noun, npos, nend = _KIND_M.first_span(text, start=nxt.start()) if nxt else (None, -1, -1)
        if not noun or npos != nxt.start():
            break
        kind, pos, end = noun, npos, nend
    for k in _YIELDS.get(kind, ()):
        if _KIND_ONLY[k].search(text):
            return k
    return kind


# Kinds named by a generic word ('Напитка', 'Препарат', 'Сирена', 'Протеин'): a more specific kind of the same
# department, from the retailer's category or the brand's other products, says more.
GENERIC_KINDS = {
    "soft_drink": {"energy_drink", "isotonic", "iced_tea", "juice"},
    "cleaner": {"dish", "laundry"},
    "supplement": {k for k, _l, d, _a in KINDS if d in ("sladko", "soleno", "mlechni", "hlyab", "osnovni")} - {"eggs"},
}


def refine(kind: str | None, text: str) -> str | None:
    """Narrow a broad kind to its sub-type when the name/category says which ('coffee' -> 'coffee_beans')."""
    subs = _SUBKIND_RE.get(kind)
    if not subs:
        return kind
    if subs[0][1].search(text):
        return subs[0][0]
    hits = [(m.start(), sub) for sub, rx in subs[1:] for m in [rx.search(text)] if m]
    return min(hits)[1] if hits else kind


def classify(name: str, category_path: str | None = None, slug: str | None = None,
             kzp_category: int | None = None) -> tuple[str | None, str]:
    """-> (kind, dept). The name says what the product is; the retailer's category is the tie-breaker for the
    department (a 'Monster' plush in 'Зоомагазин' is a pet product, not a drink)."""
    kind = kind_of_name(name)
    cat_kind = cat_dept = None
    # Category path from the leaf up: the first segment with a recognisable kind/department decides.
    segs = [s for s in (category_path or "").split(">") if s.strip()]
    for seg in reversed(segs):
        seg = normalize(seg)
        cat_kind = cat_kind or _KIND_M.first(seg)[0]
        cat_dept = cat_dept or _DEPT_M.first(seg)[0]
        if cat_kind:
            break
    if slug:
        # Slugs run root -> leaf ('alkoholni-napitki-bira-ken'), so the most specific word is the last one.
        s = slug.upper().replace("-", " ")
        cat_kind = cat_kind or _KIND_M_LAT.first(s, from_end=True)[0]
        cat_dept = cat_dept or _DEPT_M_LAT.first(s)[0]
    kind = kind or cat_kind or KZP_KIND.get(kzp_category or 0)
    # 'Напитка Monster' on the 'Енергийни напитки' shelf is an energy drink; 'Препарат' under 'За съдове' is for dishes.
    if cat_kind in GENERIC_KINDS.get(kind, ()):
        kind = cat_kind
    for k in (cat_kind, KZP_KIND.get(kzp_category or 0)):
        if k in _YIELDS.get(kind, ()):
            kind = k
    kind = refine(kind, normalize(f"{name} {segs[-1] if segs else ''}"))
    if kind in _YIELDS.get(cat_kind, ()):           # a 'Паста' category holding Oral-B is not the pasta shelf
        cat_kind = kind
    dept =(KIND_DEPT[cat_kind] if cat_kind else cat_dept) or (KIND_DEPT[kind] if kind else None)
    return kind, dept or "drugi"


# --------------------------------------------------------------------------- brands

_WORD = re.compile(r"[0-9A-ZА-Я][0-9A-ZА-Я'’&]*")
SUB_BRANDS = {"LACMI": "Roshen", "ЛАКМИ": "Roshen", "7DAYS": "7 Days", "МИЛКА": "Milka"}
GENERIC_BRANDS = {"BILLA", "LIDL", "KAUFLAND", "EBAG", "BIO", "БИО", "FRESH", "ФРЕШ", "PREMIUM", "КЛАСИК",
                  "CLASSIC", "БЪЛГАРИЯ", "БЪЛГАРСКО", "БЪЛГАРСКИ", "ДОМАШНО", "ДОМАШЕН", "ЗА", "БЕЗ", "КЕН", "ЗДРАВЕ",
                  "ФАМИЛИЯ", "PURE", "GREEN", "ЕЛИТ", "ВИТА", "ЧИСТО", "ДЕЛИКАТЕСЕН", "JUNIOR", "OCEAN", "ЛЕКИ",
                  "NATURAL", "ORIGINAL", "ОРИГИНАЛ", "НАТУРАЛ", "KIDS", "БЕБЕ", "BABY", "ЕКО", "ECO", "ГОЛД", "GOLD",
                  "NOBRAND", "NONAME", "БЕЗМАРКА", "НЕОПРЕДЕЛЕНА", "РАЗНИ", "ДРУГИ"}


def words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


class BrandIndex:
    """Brand lexicon built from retailer brand fields (eBag, Lidl). A brand is found in a name by its literal
    tokens or their transliteration; for distinctive brands (skeleton >= 4 consonants, rare) also by
    consonant skeleton, which bridges 'Monster'/'МОНСТЪР' and 'Roshen'/'РОШЕН'.

    A skeleton throws the vowels away, so it is only trusted inside one department: 'Dallmayr' (coffee) and
    'Далмор' (whisky) share the skeleton DALMAR but are different brands. brand_dept gives each brand field's
    main department; lookups by skeleton pass the product's department."""

    def __init__(self, brand_counts: dict[str, int], df: collections.Counter,
                 brand_dept: dict[str, str] | None = None):
        self.display: dict[str, str] = {}          # brand key -> display form
        self.by_seq: dict[tuple, str] = {}         # token sequence (literal/translit/(§, dept, skeleton)) -> key
        canon_by_skel: dict[tuple | str, str] = {}
        self._all: dict[tuple, str] = {}           # every brand-field spelling, incl. generic ones
        self.dept: dict[str, str | None] = {}      # brand key -> its main department
        self.alias: dict[str, str] = {}            # brand key -> the key it was merged into (merge_spellings)
        self.spellings: dict[str, set[str]] = {}   # brand key -> its retailer spellings ('Dove', 'DOVE', 'Дав')
        toks_of: dict[str, list[str]] = {}
        n_of: collections.Counter = collections.Counter()
        brand_dept = brand_dept or {}
        for raw, n in sorted(brand_counts.items(), key=lambda kv: -kv[1]):
            toks = words(raw)
            if not toks or len(toks) > 4 or "".join(toks) in GENERIC_BRANDS or toks[0] in GENERIC_BRANDS:
                continue
            dept = brand_dept.get(raw)
            skel = (dept, " ".join(skeleton(t) for t in toks))
            key = canon_by_skel.get(skel) if len(skel[1].replace(" ", "")) >= 4 else None
            key = key or canon_by_skel.get(translit(" ".join(toks))) or translit(" ".join(toks))
            canon_by_skel.setdefault(skel, key)
            self.dept.setdefault(key, dept)
            self._all.setdefault(tuple(toks), key)
            self.spellings.setdefault(key, set()).add(raw.strip())
            toks_of.setdefault(key, toks)
            n_of[key] += n
            canon_by_skel.setdefault(translit(" ".join(toks)), key)
            # Display form: Latin over Cyrillic ('Monster' over 'Монстър'), mixed case over SHOUTING.
            def rank(form):
                return bool(re.search(r"[A-Za-z]", form)), not form.isupper()
            if key not in self.display or rank(raw.strip()) > rank(self.display[key]):
                self.display[key] = raw.strip()
            # Short or common brand words ('Елена', 'Хит') are only trusted from a retailer's brand field. A
            # three-letter word ('Fit' detergent) names the brand only in its own department: 'Neo Fit протеинов
            # бар' is not Fit.
            for form in {tuple(toks), tuple(translit(t) for t in toks), tuple(to_cyrillic(t) for t in toks)}:
                if len(form) > 1 or (len(form[0]) >= 3 and form[0] not in GENERIC_BRANDS and not kind_of_name(form[0])
                                     and df.get(("=",) + form, 0) <= 40 * n + 100):
                    self.by_seq.setdefault(("@", dept) + form if len(form) == 1 and len(form[0]) <= 3 else form, key)
            if len(toks) > 1:              # 'СУПЕР МАКС' = 'SUPER MAX', also next to a Latin '7 DAYS'
                self.by_seq.setdefault(("~",) + tuple(latin_key(t) for t in toks), key)
            sk = tuple(skeleton(t) for t in toks)
            # A skeleton is only safe when it is distinctive: 'MLK' (Milka) is also 'МЛЯКО'.
            if phonetic_ok("".join(sk)) and all(sk) and df.get(("§",) + sk, 0) <= 5 * n + 30:
                self.by_seq.setdefault(("§", dept) + sk, key)
        for sub, brand in SUB_BRANDS.items():
            key = self.key_of(brand) or translit(brand.upper())
            self.display.setdefault(key, brand)
            self.by_seq.setdefault((sub,), key)
        # A product line filed as its own brand ('7 DAYS MAX', 'Верея Чудно') is its brand's: chains spell the line
        # anywhere in the name ('7 DAYS Кроасан max какао'), so it is a variant word, not another brand. Same
        # department, unless the line's brand field is on a product or two (Lidl files its 7 Days Max under 'дом').
        for key, toks in toks_of.items():
            for n in range(len(toks) - 1, 0, -1):
                parent = self.by_seq.get(tuple(toks[:n])) or self.by_seq.get(("@", self.dept.get(key)) + tuple(toks[:n]))
                if parent and parent != key and (self.dept.get(parent) == self.dept.get(key) or n_of[key] <= 2):
                    self.alias[key] = parent
                    break
        self._resolve_aliases()
        for key, form in self.display.items():
            if form.isupper() and len(form) > 3:
                self.display[key] = form.title()                  # "ROSHEN" -> "Roshen"
        self.maxlen = max((len(k) - (k[0] == "~") for k in self.by_seq if k[0] not in "§@"), default=1)

    def key_of(self, brand: str | None, dept: str | None = None) -> str | None:
        """Brand key for a retailer brand field (trusted, so generic words are accepted here)."""
        toks = words(brand or "")
        if not toks:
            return None
        key = (self.by_seq.get(tuple(toks)) or self.by_seq.get(("@", dept) + tuple(toks))
               or self.by_seq.get(("§", dept) + tuple(skeleton(t) for t in toks)) or self._all.get(tuple(toks)))
        return self.alias.get(key, key)

    def lookup(self, seq: tuple, skels: tuple, dept: str | None) -> str | None:
        """The brand these exact words name, else None."""
        # 'FIT SPO' is the brand 'FitSpo', '7 DAYS' is '7Days': the words joined count as one.
        key = (self.by_seq.get(seq) or self.by_seq.get(("@", dept) + seq)
               or (len(seq) > 1 and (self.by_seq.get(("".join(seq),))
                                     or self.by_seq.get(("~",) + tuple(latin_key(t) for t in seq))))
               or self.by_seq.get(("§", dept) + skels))
        return self.alias.get(key, key) if key else None

    def find(self, name: str, dept: str | None = None) -> str | None:
        toks = words(name)
        skels = [skeleton(t) for t in toks]
        for n in range(min(max(self.maxlen, 2), 4), 0, -1):      # 2: two words may spell a one-word brand
            found = []
            for i in range(len(toks) - n + 1):
                key = self.lookup(tuple(toks[i:i + n]), tuple(skels[i:i + n]), dept)
                if key:
                    found.append(key)
            if found:
                # 'MEGA MONSTER energy': the brand that sells in this department, else the first one named.
                return next((k for k in found if dept and self.dept.get(k) == dept), found[0])
        return None


    def merge_spellings(self, labelled) -> dict[str, str]:
        """eBag files many brands in Cyrillic ('Дав', 'Сейфгард') on names that spell them in Latin ('Душ Гел
        Dove ...'), so the two spellings are one brand: a brand field whose names mostly carry another brand
        sounding alike (same consonants) merges into that brand. labelled: (brand field, name, dept) triples."""
        labelled = list(labelled)
        votes = collections.defaultdict(collections.Counter)
        for field, name, dept in labelled:
            own = self.key_of(field, dept)
            other = self.find(name, dept)
            if own and other and other != own:
                votes[own][other] += 1
        n_of = collections.Counter(self.key_of(f, d) for f, _n, d in labelled)
        for own, c in votes.items():
            other, n = c.most_common(1)[0]
            a, b = sorted((consonants(self.display.get(k, k)) for k in (own, other)), key=len)
            if n >= 2 and n * 2 >= n_of[own] and len(a) >= max(2, len(b) / 2) and b.startswith(a):
                self.alias[own] = other
        self._resolve_aliases()
        return self.alias

    def _resolve_aliases(self):
        for key in list(self.alias):                      # chains: A -> B -> C
            seen = {key}
            while self.alias[key] in self.alias and self.alias[key] not in seen:
                seen.add(self.alias[key])
                self.alias[key] = self.alias[self.alias[key]]
        for key, target in self.alias.items():
            self.spellings.setdefault(target, set()).update(self.spellings.get(key, ()))


def word_df(names) -> collections.Counter:
    """How many names contain each word ('=', w) and 1-2 word skeleton ('§', s...) (BrandIndex ambiguity)."""
    df = collections.Counter()
    for name in names:
        toks = words(name)
        sk = [skeleton(t) for t in toks]
        df.update({("=", t) for t in toks} | {("§", a) for a in sk} | {("§", a, b) for a, b in zip(sk, sk[1:])})
    return df
