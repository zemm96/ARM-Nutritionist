"""
chi901.py — Chizhik КБЖУ парсер
Зависимости:
    pip install chizhik_api
"""

import asyncio
import random
import re
import warnings
from typing import Optional, Dict, List, Tuple

from chizhik_api import ChizhikAPI

NON_EDIBLE_KEYWORDS = [
    'шампунь', 'гель для душа', 'мыло жидкое', 'крем для', 'лосьон',
    'порошок стиральный', 'чистящее', 'моющее средство', 'отбеливатель',
    'зубная паста', 'щетка зубная', 'ополаскиватель', 'дезодорант', 'антиперспирант',
    'прокладки', 'тампоны', 'подгузники',
    'туалетная бумага', 'салфетки влажные', 'бумажные полотенца',
    'губка для посуды', 'тряпка для', 'щетка для',
    'корм для кошек', 'корм для собак', 'наполнитель для',
    'батарейки', 'аккумулятор', 'лампочка', 'светильник',
    'спички', 'зажигалка', 'пакет мусорный', 'мешки для мусора',
    'фольга', 'пленка пищевая', 'пергамент для',
    'кастрюля', 'сковорода', 'тарелка', 'посуда',
    'зонт', 'зонтик',  # зонты — не еда
    'игрушка', 'конструктор', 'пазл',  # игрушки
    'книга', 'тетрадь', 'карандаш',   # канцелярия
    'спрей spf', 'солнцезащ',          # косметика
]

KBJU_KEYS = ['калории', 'белки', 'жиры', 'углеводы']

MANDATORY_FOOD_QUERIES: List[str] = [
    "яйца куриные",
    "молоко",
    "кефир",
    "творог",
    "сметана",
    "гречка",
    "рис",
    "овсяная крупа",
    "перловая крупа",
    "макароны",
    "картофель",
    "морковь",
    "помидор",
    "огурец",
    "яблоко",
    "банан",
    "куриная грудка",
    "говяжий фарш",
    "стейк",
    "треска",
    "тушёнка говяжья",
    "консервы рыбные",
    # Мясные деликатесы — часто в другой категории каталога
    "ветчина",
    "карбонад",
    "грудинка",
    "окорок",
]

MEAL_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    'ЯЙЦА':       ['яйц', 'яичн'],
    'МЯСО_РЫБА':  [
        'куриц', 'курин', 'цыпленк', 'цыплён',
        'грудк',
        'бедр', 'голен', 'окорочок', 'окорочк', 'бройлер',
        'индейк', 'индюш',
        'говяд', 'говяж',
        'телятин',
        'свинин', 'свин',
        'фарш', 'котлет', 'стейк',
        'тушен', 'тушён', 'консерв',  # тушёнка и рыбные/мясные консервы
        # Рыба
        'форел', 'сёмг', 'семг', 'лосос',
        'треск', 'минтай', 'хек', 'навага',
        'тунец', 'скумбри', 'сельд', 'горбуш',
        'рыбн', 'рыб',
        'креветк', 'кальмар', 'морепродукт',
    ],
    'МОЛОЧКА':    [
        'молок', 'молочн',
        'йогурт', 'творог', 'творожн',
        'сыр', 'брынз',
        'кефир', 'ряженк', 'сметан',
    ],
    'КРУПЫ_ХЛЕБ': [
        'гречк', 'рисов', 'рис',
        'овсян', 'геркулес',
        'перловк', 'булгур', 'пшен', 'полба',
        'хлопь',
        'макарон', 'спагет', 'лапш', 'феттучин', 'пенне', 'вермишел', 'кускус',
    ],
    'ОВОЩИ':      [
        'капуст', 'брокол', 'томат', 'помидор',
        'огурц', 'огурец', 'баклажан',
        'морков', 'перец болг', 'кабачк', 'свёкл', 'свекл',
        'горошек', 'кукуруз', 'шпинат',
    ],
    'ФРУКТЫ':     [
        'яблок', 'банан', 'груш',
        'апельсин', 'мандарин', 'грейпфрут',
        'виноград', 'слив', 'персик', 'клубник',
    ],
}

# Продукты, исключаемые при отборе по категориям
_CHI_JUNK_KW = [
    "хлебц", "батон", "багет", "лаваш", "булк",
    "ама мама",                          # детский бренд молочки
    "сухарик", "сухари ",                # снеки-сухарики
    "мука пшен", "мука высш", "мука ",  # сырая мука — не еда
    "жгучий", "острый суп", "азиатский суп", "siem", "lanzhou",  # острые быстрые супы
    "рамен", "nongshim",  # корейский/японский instant ramen — не обычная лапша
    "московский картофел",  # бренд снековых чипсов «Московский Картофель»
    "сосиск", "колбас", "нарезк",
    "конфет", "шоколад", "мармелад", "зефир", "торт", "пирожн", "кекс", "вафл",
    "чипс", "снек", "попкорн",
    "пиво", "водк", "вино", "газированн", "лимонад",
    "мороженое", "пломбир",
    "пицц", "бургер", "нагетс",
    "агуша", "растишка", "нутрилон", "фрутоняня",
    "детск питан", "смесь молочн",
    "соус", "кетчуп", "майонез",
    "пельмен", "вареник", "манты",
    "маринован", "вялен", "ассорти",
    "корейск",
]

_CATEGORY_COUNTS: Dict[str, Dict[int, int]] = {
    'КРУПЫ_ХЛЕБ': {1: 5, 2: 8,  3: 18},
    'МЯСО_РЫБА':  {1: 4, 2: 7,  3: 15},
    'МОЛОЧКА':    {1: 3, 2: 5,  3: 10},
    'ОВОЩИ':      {1: 3, 2: 6,  3: 12},
    'ЯЙЦА':       {1: 1, 2: 1,  3: 3},
    'ФРУКТЫ':     {1: 2, 2: 3,  3: 7},
}

_CATEGORY_MIN: Dict[str, int] = {
    'КРУПЫ_ХЛЕБ': 2,
    'МЯСО_РЫБА':  2,
    'МОЛОЧКА':    2,
    'ОВОЩИ':      2,
    'ЯЙЦА':       1,
    'ФРУКТЫ':     1,
}

AVERAGE_KBJU_DB: Dict[str, Dict[str, float]] = {
    # Молочные
    'молоко':    {'калории': 64,  'белки': 3.2,  'жиры': 3.6,  'углеводы': 4.8},
    'кефир':     {'калории': 53,  'белки': 2.8,  'жиры': 2.5,  'углеводы': 4.0},
    'ряженка':   {'калории': 85,  'белки': 2.9,  'жиры': 4.5,  'углеводы': 4.7},
    'йогурт':    {'калории': 75,  'белки': 4.5,  'жиры': 3.0,  'углеводы': 6.0},
    'сметана':   {'калории': 206, 'белки': 2.5,  'жиры': 20.0, 'углеводы': 3.4},
    'творог':    {'калории': 121, 'белки': 16.0, 'жиры': 5.0,  'углеводы': 2.5},
    'сыр':       {'калории': 350, 'белки': 25.0, 'жиры': 28.0, 'углеводы': 1.0},
    # Мясо и птица
    'курица':    {'калории': 165, 'белки': 20.0, 'жиры': 9.0,  'углеводы': 0.0},
    'индейка':   {'калории': 190, 'белки': 22.0, 'жиры': 11.0, 'углеводы': 0.0},
    'говядина':  {'калории': 250, 'белки': 18.0, 'жиры': 19.0, 'углеводы': 0.0},
    'свинина':   {'калории': 320, 'белки': 16.0, 'жиры': 28.0, 'углеводы': 0.0},
    'фарш':      {'калории': 220, 'белки': 17.0, 'жиры': 16.0, 'углеводы': 0.0},
    'колбаса':   {'калории': 300, 'белки': 12.0, 'жиры': 27.0, 'углеводы': 2.0},
    'сосиски':   {'калории': 280, 'белки': 11.0, 'жиры': 25.0, 'углеводы': 3.0},
    'ветчина':   {'калории': 180, 'белки': 15.0, 'жиры': 12.0, 'углеводы': 2.0},
    # Рыба
    'рыба':      {'калории': 150, 'белки': 18.0, 'жиры': 8.0,  'углеводы': 0.0},
    'тунец':     {'калории': 130, 'белки': 22.0, 'жиры': 4.5,  'углеводы': 0.0},
    'скумбрия':  {'калории': 190, 'белки': 18.0, 'жиры': 13.0, 'углеводы': 0.0},
    'лосось':    {'калории': 200, 'белки': 20.0, 'жиры': 13.0, 'углеводы': 0.0},
    'минтай':    {'калории': 72,  'белки': 15.9, 'жиры': 0.9,  'углеводы': 0.0},
    'консервы':  {'калории': 150, 'белки': 15.0, 'жиры': 8.0,  'углеводы': 2.0},
    # Яйца
    'яйца':      {'калории': 155, 'белки': 12.6, 'жиры': 10.6, 'углеводы': 1.2},
    # Хлеб и выпечка
    'хлеб':      {'калории': 265, 'белки': 8.0,  'жиры': 2.0,  'углеводы': 50.0},
    'батон':     {'калории': 270, 'белки': 7.5,  'жиры': 3.0,  'углеводы': 52.0},
    # Крупы и макароны
    'гречка':    {'калории': 343, 'белки': 13.0, 'жиры': 3.5,  'углеводы': 68.0},
    'рис':       {'калории': 344, 'белки': 7.0,  'жиры': 2.5,  'углеводы': 74.0},
    'овсянка':   {'калории': 368, 'белки': 12.0, 'жиры': 7.0,  'углеводы': 65.0},
    'макароны':  {'калории': 350, 'белки': 12.0, 'жиры': 2.0,  'углеводы': 70.0},
    'перловка':  {'калории': 324, 'белки': 9.0,  'жиры': 1.2,  'углеводы': 66.0},
    'булгур':    {'калории': 342, 'белки': 12.0, 'жиры': 1.3,  'углеводы': 70.0},
    # Полуфабрикаты
    'пельмени':  {'калории': 250, 'белки': 11.0, 'жиры': 12.0, 'углеводы': 25.0},
    # Овощи
    'картофель': {'калории': 77,  'белки': 2.0,  'жиры': 0.4,  'углеводы': 17.0},
    'морковь':   {'калории': 41,  'белки': 0.9,  'жиры': 0.2,  'углеводы': 9.6},
    'капуста':   {'калории': 27,  'белки': 1.8,  'жиры': 0.1,  'углеводы': 5.4},
    'лук':       {'калории': 41,  'белки': 1.4,  'жиры': 0.0,  'углеводы': 9.5},
    'помидор':   {'калории': 20,  'белки': 1.1,  'жиры': 0.2,  'углеводы': 3.7},
    'огурец':    {'калории': 15,  'белки': 0.7,  'жиры': 0.1,  'углеводы': 2.8},
    'свёкла':    {'калории': 43,  'белки': 1.5,  'жиры': 0.1,  'углеводы': 9.6},
    'перец':     {'калории': 27,  'белки': 1.3,  'жиры': 0.1,  'углеводы': 5.7},
    # Фрукты
    'яблоко':    {'калории': 52,  'белки': 0.3,  'жиры': 0.4,  'углеводы': 13.8},
    'банан':     {'калории': 89,  'белки': 1.1,  'жиры': 0.3,  'углеводы': 22.8},
    'апельсин':  {'калории': 47,  'белки': 0.9,  'жиры': 0.2,  'углеводы': 11.8},
    'мандарин':  {'калории': 53,  'белки': 0.8,  'жиры': 0.3,  'углеводы': 13.3},
    'груша':     {'калории': 57,  'белки': 0.4,  'жиры': 0.3,  'углеводы': 15.2},
    # Масла
    'масло':     {'калории': 720, 'белки': 0.5,  'жиры': 82.0, 'углеводы': 0.5},
    # Напитки
    'сок':       {'калории': 50,  'белки': 0.3,  'жиры': 0.1,  'углеводы': 11.5},
    'нектар':    {'калории': 55,  'белки': 0.2,  'жиры': 0.1,  'углеводы': 13.0},
    'чай':       {'калории': 2,   'белки': 0.1,  'жиры': 0.0,  'углеводы': 0.4},
    'кофе':      {'калории': 5,   'белки': 0.2,  'жиры': 0.0,  'углеводы': 0.7},
    'какао':     {'калории': 375, 'белки': 24.0, 'жиры': 15.0, 'углеводы': 44.0},
}

_NUTRIENT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'carb|углевод',           re.I), 'углеводы'),
    (re.compile(r'protein|белк',           re.I), 'белки'),
    (re.compile(r'\bfat[s_]?|жир',         re.I), 'жиры'),
    (re.compile(r'energy|calori|kcal|ккал', re.I), 'калории'),
]


def _code_to_nutrient(code: str) -> Optional[str]:
    """Сопоставляет любой код meta_data с названием нутриента через паттерны.
    Обрабатывает как известные ключи (carboh, carbohydrates), так и будущие варианты."""
    for pattern, nutrient in _NUTRIENT_PATTERNS:
        if pattern.search(code):
            return nutrient
    return None


def is_kbju_complete(kbju: dict) -> bool:
    return all(kbju.get(k) is not None for k in KBJU_KEYS)


def has_any_kbju_missing(kbju: dict) -> bool:
    return any(kbju.get(k) is None for k in KBJU_KEYS)


def is_edible(title: str) -> bool:
    t = title.lower()
    return not any(kw in t for kw in NON_EDIBLE_KEYWORDS)


def remove_duplicates(products: list) -> list:
    seen, result = {}, []
    for p in products:
        key = (re.sub(r'[.,\s]+', ' ', p['title'].lower().strip()), p['price'])
        if key not in seen:
            seen[key] = p
            result.append(p)
        else:
            existing = seen[key]
            if p.get('рейтинг') and not existing.get('рейтинг'):
                existing['рейтинг'] = p['рейтинг']
                existing['отзывов'] = p.get('отзывов', 0)
    return result


def get_category_name(categories_tree: list) -> str:
    if not categories_tree:
        return ""
    cat = categories_tree[0]
    while cat.get('children'):
        cat = cat['children'][0]
    return cat.get('name', '')

# Псевдонимы для detect_product_category: (список подстрок, ключ AVERAGE_KBJU_DB)
_CATEGORY_ALIASES: List[Tuple[List[str], str]] = [
    (['молок'],                                     'молоко'),
    (['кефир'],                                     'кефир'),
    (['ряженк'],                                    'ряженка'),
    (['йогурт'],                                    'йогурт'),
    (['сметан'],                                    'сметана'),
    (['творог'],                                    'творог'),
    (['сыр', 'брынз', 'рикотт', 'маскарпон'],       'сыр'),
    (['куриц', 'бройлер', 'окорочок', 'грудк'],     'курица'),
    (['индейк'],                                    'индейка'),
    (['стейк'],                                      'говядина'),
    (['говяд', 'телятин'],                          'говядина'),
    (['свинин', 'карбонад', 'окорок'],              'свинина'),
    (['фарш'],                                      'фарш'),
    (['колбас', 'карбонад'],                        'колбаса'),
    (['сосис', 'сардел'],                           'сосиски'),
    (['ветчин'],                                    'ветчина'),
    (['тунец'],                                     'тунец'),
    (['скумбри'],                                   'скумбрия'),
    (['лосось', 'сёмга', 'форел'],                  'лосось'),
    (['минтай', 'треск', 'хек', 'навага'],          'минтай'),
    (['рыб', 'консерв'],                            'консервы'),
    (['яйц'],                                       'яйца'),
    (['батон', 'булк', 'багет'],                    'батон'),
    (['хлеб', 'лаваш'],                             'хлеб'),
    (['греч'],                                      'гречка'),
    (['овсян', 'геркулес'],                         'овсянка'),
    (['перловк'],                                   'перловка'),
    (['булгур'],                                    'булгур'),
    (['макарон', 'спагет', 'лапш', 'феттучин'],     'макароны'),
    (['пельмен', 'манты', 'хинкал', 'вареник'],     'пельмени'),
    (['картофел'],                                  'картофель'),
    (['морков'],                                    'морковь'),
    (['капуст'],                                    'капуста'),
    (['лук реп', 'лук'],                            'лук'),
    (['помидор', 'томат'],                          'помидор'),
    (['огурец', 'огурц'],                           'огурец'),
    (['свёкл', 'свекл'],                            'свёкла'),
    (['перец болг', 'перец'],                       'перец'),
    (['яблок'],                                     'яблоко'),
    (['банан'],                                     'банан'),
    (['апельсин', 'грейпфрут'],                     'апельсин'),
    (['мандарин'],                                  'мандарин'),
    (['груш'],                                      'груша'),
    (['масло слив', 'масло раст', 'масло'],         'масло'),
    (['нектар'],                                    'нектар'),
    (['сок'],                                       'сок'),
    (['чай'],                                       'чай'),
    (['кофе'],                                      'кофе'),
    (['какао'],                                     'какао'),
]


def detect_product_category(title: str) -> Optional[str]:
    t = title.lower()
    for keywords, category in _CATEGORY_ALIASES:
        if any(kw in t for kw in keywords):
            return category
    return None


def classify_product_to_meal_category(title: str) -> Optional[str]:
    """Относит продукт к одной из шести категорий меню по ключевым словам в названии."""
    t = title.lower()
    for category, keywords in MEAL_CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return category
    return None


def select_by_meal_categories(products: List[Dict], variety_level: int = 2,
                              liked_foods: str = "") -> List[Dict]:
    """Отбирает продукты по категориям с учётом уровня разнообразия.

    Некатегоризированные продукты с ненулевым КБЖУ добавляются как fallback —
    это страховка от мяса/рыбы с нестандартными названиями, не попавшими в keywords.
    Любимые продукты (liked_foods) пинятся в начало своей категории — они всегда
    попадают в итоговый список, не занимая лишних слотов у остальных.
    """
    variety_level = max(1, min(3, variety_level))
    liked_words = [w.strip().lower() for w in liked_foods.split(",") if w.strip()]

    # Дедупликация по нормализованному названию
    seen_names: Dict[str, Dict] = {}
    for p in products:
        key = re.sub(r'[.,\s]+', ' ', p.get('title', '').lower().strip())
        if key and key not in seen_names:
            seen_names[key] = p
    deduped = list(seen_names.values())

    # Убираем мусор, чтобы не занимать слоты категорий товарами, которые meal_selector отклонит
    deduped = [p for p in deduped
               if not any(kw in p.get('title', '').lower() for kw in _CHI_JUNK_KW)]

    _CHI_EXTRA = {
        "говядина": ["говядин", "говяж"],
        "свинина":  ["свинин",  "свин"],
        "курица":   ["куриц",   "курин"],
        "индейка":  ["индей",   "индюш"],
        "баранина": ["баранин", "баран"],
        "телятина": ["телятин", "телячь"],
    }
    def _is_liked(p: Dict) -> bool:
        t = p.get('title', '').lower()
        def _stems(w): return _CHI_EXTRA.get(w, [w[:-2] if len(w)>=6 else w[:-1] if len(w)>=4 else w])
        return bool(liked_words and any(any(s in t for s in _stems(w)) for w in liked_words))

    # Раскладываем по категориям; продукты без совпадения → запасной список
    categorized: Dict[str, List[Dict]] = {cat: [] for cat in MEAL_CATEGORY_KEYWORDS}
    uncategorized: List[Dict] = []
    for p in deduped:
        cat = classify_product_to_meal_category(p.get('title', ''))
        if cat:
            categorized[cat].append(p)
        else:
            kbju = p.get('кбжу', {})
            cal  = kbju.get('калории') or p.get('calories') or p.get('kcal') or 0
            if cal > 0:
                uncategorized.append(p)

    # Отбор из каждой категории: любимые пинятся в начало, остальные перемешиваются
    selected: List[Dict] = []
    for cat in MEAL_CATEGORY_KEYWORDS:
        cat_products = categorized[cat]
        if not cat_products:
            print(f"  [категории] {cat}: нет продуктов — пропускаем", flush=True)
            continue
        liked_first  = [p for p in cat_products if _is_liked(p)][:2]  # макс. 2 любимых на категорию
        rest         = [p for p in cat_products if not _is_liked(p)]
        random.shuffle(rest)
        ordered = liked_first + rest
        target  = _CATEGORY_COUNTS.get(cat, {}).get(variety_level, 4)
        minimum = _CATEGORY_MIN.get(cat, 1)
        count   = max(minimum, min(target, len(ordered)), len(liked_first))
        selected.extend(ordered[:count])
        print(f"  [категории] {cat}: {len(cat_products)} доступно → {count} выбрано"
              + (f" (вкл. {len(liked_first)} любимых)" if liked_first else ""),
              flush=True)

    # Fallback: некатегоризированные продукты (по рейтингу, лимит зависит от variety)
    # Любимые некатегоризированные тоже всегда добавляются
    if uncategorized:
        unc_limit   = {1: 5, 2: 8, 3: 20}.get(variety_level, 8)
        liked_unc   = [p for p in uncategorized if _is_liked(p)]
        rest_unc    = [p for p in uncategorized if not _is_liked(p)]
        rest_unc.sort(key=lambda p: -(p.get('рейтинг') or p.get('rating') or 0))
        added = liked_unc + rest_unc[:max(0, unc_limit - len(liked_unc))]
        selected.extend(added)
        print(f"  [категории] Прочие: {len(uncategorized)} → {len(added)} добавлено",
              flush=True)

    print(f"  [категории] Итого: {len(selected)} продуктов (variety={variety_level})",
          flush=True)
    return selected


def fill_missing_with_average(product: dict) -> bool:
    category = detect_product_category(product.get('title', ''))
    if not category:
        return False
    avg = AVERAGE_KBJU_DB.get(category)
    if not avg:
        return False
    kbju = product.setdefault('кбжу', {})
    filled = False
    for key in KBJU_KEYS:
        if kbju.get(key) is None and avg.get(key) is not None:
            kbju[key] = avg[key]
            product[f'источник_{key}'] = 'среднее'
            filled = True
    return filled


# ─── Парсинг КБЖУ из текста ──────────────────────────────────────────────────

def _parse_kbju_from_text(text: str) -> dict:
    """Извлекает пищевую ценность из произвольной текстовой строки.

    Обрабатывает полные формы («Углеводы: 45г»), английские формы («carbohydrates 45»)
    и русские сокращённые метки («У45г», «Б14 Ж5 У68 Э350ккал»).
    Полные паттерны проверяются раньше сокращений во избежание ложных совпадений.
    """
    if not text:
        return {}
    t = text.lower()
    kbju = {}
    patterns = [
        # ── Углеводы ──────────────────────────────────────────────────────────
        (r'углевод[ыа]\D{0,6}(\d+[.,]\d+|\d+)\s*г?',     'углеводы'),
        (r'carbohydrates?\D{0,6}(\d+[.,]\d+|\d+)',        'углеводы'),
        (r'carbs?\D{0,6}(\d+[.,]\d+|\d+)',                'углеводы'),
        # ── Белки ─────────────────────────────────────────────────────────────
        (r'белк[иа]\D{0,6}(\d+[.,]\d+|\d+)\s*г?',        'белки'),
        (r'proteins?\D{0,6}(\d+[.,]\d+|\d+)',             'белки'),
        # ── Жиры ──────────────────────────────────────────────────────────────
        (r'жир[ыа]\D{0,6}(\d+[.,]\d+|\d+)\s*г?',         'жиры'),
        (r'fats?\D{0,6}(\d+[.,]\d+|\d+)',                 'жиры'),
        # ── Калории ───────────────────────────────────────────────────────────
        (r'(\d+[.,]\d+|\d+)\s*кк?ал',                    'калории'),
        (r'ккал\D{0,4}(\d+[.,]\d+|\d+)',                  'калории'),
        (r'энергетическ\w+\D{0,6}(\d+[.,]\d+|\d+)',       'калории'),
        (r'calories?\D{0,6}(\d+[.,]\d+|\d+)',             'калории'),
        # ── Сокращённые метки: "Б14г Ж5г У68г" или "Б: 14.5" ─────────────────
        (r'(?<!\w)у\s*:?\s*(\d+[.,]\d+|\d+)\s*г',        'углеводы'),
        (r'(?<!\w)б\s*:?\s*(\d+[.,]\d+|\d+)\s*г',        'белки'),
        (r'(?<!\w)ж\s*:?\s*(\d+[.,]\d+|\d+)\s*г',        'жиры'),
        (r'(?<!\w)э(?:нерг)?\s*:?\s*(\d+[.,]\d+|\d+)',   'калории'),
    ]
    for pattern, key in patterns:
        if kbju.get(key) is not None:
            continue
        m = re.search(pattern, t)
        if m:
            try:
                kbju[key] = round(float(m.group(1).replace(',', '.')), 1)
            except (ValueError, TypeError):
                pass
    return kbju


def _to_float(value) -> Optional[float]:
    """Преобразует значение meta_data (число или строку вида '14.5 г') в float."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r'(\d+(?:[.,]\d+)?)', value.replace(',', '.'))
        if m:
            return float(m.group(1))
    return None


def extract_kbju_from_meta(meta_data: list) -> dict:
    """Извлекает КБЖУ из meta_data продукта.

    Использует сопоставление кодов по паттернам, что позволяет обрабатывать
    любые варианты названий ключей Чижика (carboh, carbohydrates, carbs_100g и т.д.)
    без явных обновлений маппинга.

    Запасной вариант — полнотекстовый поиск по всем строковым значениям в meta_data.
    """
    kbju: Dict[str, float] = {}
    extra: Dict[str, str]  = {}

    for meta in meta_data:
        code  = (meta.get('code') or '').strip()
        value = meta.get('value')

        nutrient = _code_to_nutrient(code)
        if nutrient and kbju.get(nutrient) is None:
            num = _to_float(value)
            if num is not None:
                kbju[nutrient] = round(num, 1)
        else:
            code_l = code.lower()
            if code_l in ('composition', 'состав'):
                extra['состав'] = value
            elif code_l in ('about_product', 'description', 'описание'):
                extra['описание'] = value
            elif code_l in ('brand_name', 'brand', 'бренд'):
                extra['бренд'] = value

    # Запасной вариант: сканирование всех строковых значений meta_data по паттернам КБЖУ
    if has_any_kbju_missing(kbju):
        for meta in meta_data:
            value = meta.get('value')
            if not isinstance(value, str) or len(value) < 4:
                continue
            parsed = _parse_kbju_from_text(value)
            for key in KBJU_KEYS:
                if kbju.get(key) is None and parsed.get(key) is not None:
                    kbju[key] = parsed[key]
                    extra[f'источник_{key}'] = 'текст_метаданных'
            if not has_any_kbju_missing(kbju):
                break

    return {'кбжу': kbju, **{k: v for k, v in extra.items() if v}}


async def get_product_details(api: ChizhikAPI, product_id: int) -> Optional[dict]:
    """Загружает КБЖУ и рейтинг продукта со страницы Чижика.

    После извлечения meta_data сканирует все строковые поля верхнего уровня
    в ответе API как дополнительный запасной вариант.
    """
    try:
        data = (await api.Catalog.Product.info(product_id)).json()
        result = extract_kbju_from_meta(data.get('meta_data', []))
        kbju = result.setdefault('кбжу', {})

        # Сканируем поля верхнего уровня для заполнения оставшихся пустых нутриентов
        if has_any_kbju_missing(kbju):
            for field in ('name', 'description', 'short_description',
                          'composition', 'full_description', 'about_product'):
                text = data.get(field) or ''
                if not text:
                    continue
                parsed = _parse_kbju_from_text(str(text))
                for key in KBJU_KEYS:
                    if kbju.get(key) is None and parsed.get(key) is not None:
                        kbju[key] = parsed[key]
                        result[f'источник_{key}'] = f'поле_{field}'
                if not has_any_kbju_missing(kbju):
                    break

        rating    = data.get('rating')
        feedbacks = max(data.get('feedbacks_count', 0), data.get('reviews_count', 0))
        if rating:
            result['рейтинг'] = float(rating)
            result['отзывов'] = feedbacks

        return result
    except Exception:
        return None


# ─── Основная функция поиска ──────────────────────────────────────────────────

async def search_products_with_kbju(
    query: str = "",
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    on_sale_only: bool = False,
    sort_by: str = 'rating',
    max_items: Optional[int] = None,
) -> List[Dict]:
    """Получает продукты из Чижика, загружает КБЖУ и заполняет пропуски средними.

    query="" — полный обход съедобного каталога (category_id=133, все страницы).
    Непустой query фильтрует по ключевому слову на тех же страницах каталога.
    """
    print(f"\n{'=' * 60}")
    print(f"ПОИСК: '{query or 'весь ассортимент'}'")
    print('=' * 60)

    async with ChizhikAPI(headless=True) as api:

        # ── Шаг 1: пагинация каталога ─────────────────────────────────────────
        products: List[Dict] = []
        page, total_pages = 1, None
        consecutive_errors = 0

        print("Загружаем каталог...")
        while True:
            try:
                # Если запрос задан — используем search= (ищет по всем категориям сайта).
                # Без запроса — обходим категорию 133 (все продукты питания).
                if query:
                    data = (await api.Catalog.products_list(page=page, search=query)).json()
                else:
                    data = (await api.Catalog.products_list(category_id=133, page=page)).json()
                items = data.get('items', [])

                if total_pages is None:
                    total_pages = data.get('total_pages', 1)
                    print(f"  Всего: {data.get('count', 0)} товаров, {total_pages} стр.")

                if not items or page > total_pages:
                    break

                consecutive_errors = 0   # сбрасываем после каждой успешной страницы
                print(f"  Стр. {page}/{total_pages}...", end=' ', flush=True)
                matches = 0
                for item in items:
                    title = item.get('title', '')
                    price = item.get('price')
                    if price is None:
                        continue
                    if min_price and price < min_price:
                        continue
                    if max_price and price > max_price:
                        continue
                    if on_sale_only and not item.get('old_price'):
                        continue
                    if not is_edible(title):
                        continue
                    products.append({
                        'id':        item.get('id'),
                        'title':     title,
                        'price':     price,
                        'old_price': item.get('old_price'),
                        'category':  get_category_name(item.get('categories_tree', [])),
                    })
                    matches += 1
                    if max_items and len(products) >= max_items:
                        break
                print(f"{matches} товаров")
                if max_items and len(products) >= max_items:
                    break
                page += 1

            except Exception as e:
                consecutive_errors += 1
                action = "прерываем" if consecutive_errors >= 3 else "пропускаем"
                print(f"  Ошибка стр.{page}: {e} — {action}")
                page += 1
                if consecutive_errors >= 3:
                    break
                continue

        if not products:
            print("Ничего не найдено")
            return []

        products = remove_duplicates(products)
        print(f"\nПосле дедупликации: {len(products)} товаров")

        # ── Шаг 2: параллельная загрузка КБЖУ из Чижика ──────────────────────
        KBJU_WORKERS = 20
        sem = asyncio.Semaphore(KBJU_WORKERS)

        print(f"\nЗагружаем КБЖУ ({len(products)} шт., {KBJU_WORKERS} потоков)...")

        async def _fetch(product):
            async with sem:
                return await get_product_details(api, product['id'])

        details_list = await asyncio.gather(
            *[_fetch(p) for p in products], return_exceptions=True
        )

        ok = 0
        for product, details in zip(products, details_list):
            if isinstance(details, Exception) or details is None:
                product.setdefault('кбжу', {})
                continue
            product.update({
                'кбжу':    details.get('кбжу', {}),
                'бренд':   details.get('бренд'),
                'рейтинг': details.get('рейтинг'),
                'отзывов': details.get('отзывов', 0),
            })
            for k, v in details.items():
                if k.startswith('источник_'):
                    product[k] = v
            if details.get('кбжу', {}).get('калории'):
                ok += 1
        print(f"  КБЖУ из Чижика: {ok}/{len(products)}")

        # ── Шаг 3: заполнение средними значениями ─────────────────────────────
        incomplete = [p for p in products if has_any_kbju_missing(p.get('кбжу', {}))]
        if incomplete:
            filled = sum(1 for p in incomplete if fill_missing_with_average(p))
            print(f"  Среднее значение: {filled}/{len(incomplete)}")

        # ── Шаг 4: сортировка ─────────────────────────────────────────────────
        sort_fns = {
            'price':  lambda x: x.get('price', float('inf')),
            'rating': lambda x: -(x.get('рейтинг') or 0),
        }
        products.sort(key=sort_fns.get(sort_by, sort_fns['rating']))

        # ── Итоги ─────────────────────────────────────────────────────────────
        with_kcal  = sum(1 for p in products if p.get('кбжу', {}).get('калории'))
        with_carbs = sum(1 for p in products if p.get('кбжу', {}).get('углеводы') is not None)
        prices     = [p['price'] for p in products]
        print(f"\nИтого: {len(products)} | КБЖУ: {with_kcal} | Углеводы: {with_carbs}")
        if prices:
            print(f"Цены: {min(prices)}–{max(prices)} руб. | Средняя: {sum(prices)/len(prices):.0f} руб.")

        return products


async def search_bulk_queries(
    queries: List[str],
    max_price: Optional[float] = None,
    max_items_each: int = 5,
    max_pages: int = 10,
) -> List[Dict]:
    """Обходит категорию 133 постранично через ОДИН сеанс ChizhikAPI и сопоставляет
    каждый товар сразу со всеми ключевыми запросами.

    В отличие от N-кратного вызова search_products_with_kbju (N браузерных сессий,
    N полных обходов по 52 страницы), открывает ОДИН сеанс и загружает каждую страницу
    ровно один раз, проверяя все запросы на каждый товар. Останавливается, когда все
    запросы выполнены или достигнут max_pages. КБЖУ загружается параллельно в том же сеансе.
    """
    print(f"\n{'='*60}")
    print(f"ДОПОЛНИТЕЛЬНЫЙ ПОИСК: {len(queries)} категорий (1 сеанс, макс. {max_pages} стр.)")
    print('='*60)

    async with ChizhikAPI(headless=True) as api:
        all_products: List[Dict] = []
        seen_ids: set = set()

        # Каждый запрос ищем через search= (охватывает все категории сайта, не только 133)
        for q in queries:
            found = 0
            consecutive_errors = 0
            for pg in range(1, max_pages + 1):
                if found >= max_items_each:
                    break
                try:
                    data  = (await api.Catalog.products_list(page=pg, search=q)).json()
                    items = data.get('items', [])
                    total = data.get('total_pages', 1)
                    if not items:
                        break
                    for item in items:
                        title = item.get('title', '')
                        price = item.get('price')
                        pid   = item.get('id')
                        if price is None or (max_price and price > max_price):
                            continue
                        if not is_edible(title):
                            continue
                        if pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                        all_products.append({
                            'id':        pid,
                            'title':     title,
                            'price':     price,
                            'old_price': item.get('old_price'),
                            'category':  get_category_name(item.get('categories_tree', [])),
                        })
                        found += 1
                        if found >= max_items_each:
                            break
                    consecutive_errors = 0
                    if pg >= total:
                        break
                except Exception as e:
                    consecutive_errors += 1
                    action = "прерываем" if consecutive_errors >= 3 else "пропускаем"
                    print(f"  «{q}» стр.{pg}: {e} — {action}", flush=True)
                    if consecutive_errors >= 3:
                        break
            if found > 0:
                print(f"  «{q}»: {found}", flush=True)

        if not all_products:
            print("Дополнительных товаров не найдено")
            return []

        # Загружаем КБЖУ для всех найденных продуктов в том же сеансе
        print(f"Загружаем КБЖУ ({len(all_products)} доп. товаров)...")
        sem = asyncio.Semaphore(10)

        async def _fetch(p: dict):
            async with sem:
                return await get_product_details(api, p['id'])

        details_list = await asyncio.gather(
            *[_fetch(p) for p in all_products], return_exceptions=True
        )
        ok = 0
        for product, details in zip(all_products, details_list):
            if isinstance(details, Exception) or details is None:
                product.setdefault('кбжу', {})
                continue
            product.update({
                'кбжу':    details.get('кбжу', {}),
                'бренд':   details.get('бренд'),
                'рейтинг': details.get('рейтинг'),
                'отзывов': details.get('отзывов', 0),
            })
            for k, v in details.items():
                if k.startswith('источник_'):
                    product[k] = v
            if details.get('кбжу', {}).get('калории'):
                ok += 1
        print(f"  КБЖУ из Чижика: {ok}/{len(all_products)}")

        incomplete = [p for p in all_products if has_any_kbju_missing(p.get('кбжу', {}))]
        if incomplete:
            filled = sum(1 for p in incomplete if fill_missing_with_average(p))
            print(f"  Заполнено средними: {filled}/{len(incomplete)}")

        return all_products


# ─── Интерактивный режим ──────────────────────────────────────────────────────

async def _interactive():
    print("\n" + "=" * 60)
    print("  CHIZHIK КБЖУ ПАРСЕР")
    print("=" * 60)
    print("\n1. Полный каталог  2. Поиск по слову  3. Выход\n")

    choice = input("Выберите (1-3): ").strip()
    if choice == "3":
        print("До свидания!")
        return
    if choice == "2":
        query = input("Что ищем? ").strip()
    else:
        query = ""

    max_p  = input("Макс. цена (Enter — без ограничения): ").strip()
    sale   = input("Только со скидкой? (y/n): ").strip().lower() == 'y'
    sort_s = input("Сортировка: 1-по цене 2-по рейтингу (Enter=2): ").strip()
    max_n  = input("Максимум товаров (Enter — все): ").strip()

    products = await search_products_with_kbju(
        query=query,
        max_price=float(max_p) if max_p else None,
        on_sale_only=sale,
        sort_by='price' if sort_s == '1' else 'rating',
        max_items=int(max_n) if max_n.isdigit() else None,
    )

    print(f"\nНайдено {len(products)} товаров.")
    for p in products[:20]:
        kbju = p.get('кбжу', {})
        print(f"  {p['title'][:50]:<50} {p['price']}₽  "
              f"Б{kbju.get('белки', '?')} Ж{kbju.get('жиры', '?')} "
              f"У{kbju.get('углеводы', '?')} Э{kbju.get('калории', '?')}")

    input("\nEnter для продолжения...")
    await _interactive()


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=ResourceWarning)
    try:
        asyncio.run(_interactive())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
    except Exception as e:
        print(f"\nОшибка: {e}")
