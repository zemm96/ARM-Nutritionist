"""
meal_selector.py — фильтрует продукты по бюджету и макросам, возвращает компактный
список для построения плана питания языковой моделью.

Использование:
    python meal_selector.py <products_json> <weekly_budget> <daily_calories>
                            <protein_pct> <fat_pct> <carb_pct> <variety>
                            [disliked_foods] [liked_foods]

Вывод: JSON-массив компактных продуктов в stdout.
"""
import json, re, sys, math
from typing import List, Dict

_BABY_AGE_RE = re.compile(r'[0-9]+\s*м\+|[0-9]+\s*мес', re.IGNORECASE)

_GROUPS: Dict[str, List[str]] = {
    "protein":  ["мясо", "курица", "курин", "говядина", "говяж", "свинина", "свин",
                 "индейка", "индюш", "рыба", "рыбн",
                 "яйцо", "яйц", "творог", "сыр", "колбас", "сосиск", "фарш", "стейк",
                 "тунец", "лосось", "скумбрия", "минтай", "форел", "семг",
                 "сельд", "горбуш", "треска", "кальмар", "креветк",
                 "тушён", "тушен", "консерв"],
    "carbs":    ["крупа", "макарон", "рис", "гречка", "овсян", "хлеб",
                 "картофел", "хлопья", "мюсли", "батон", "булгур", "перловк",
                 "лапш", "спагетт", "вермишел", "кускус"],
    "dairy":    ["молоко", "молочн", "кисломол", "йогурт", "сметана", "творог", "сыр", "масло слив",
                 "кефир", "ряженк", "творожок"],
    "veggies":  ["капуста", "морков", "лук", "помидор", "огурец", "огурц", "перец болг",
                 "свёкл", "брокколи", "шпинат", "горошек", "кукуруза", "томат",
                 "кабачок", "баклажан", "зелен", "укроп", "петрушк", "салат"],
    "fats":     ["масло раст", "маргарин", "орех", "семечк", "арахис"],
    "fruits":   ["яблок", "банан", "апельсин", "груш", "виноград", "ягод",
                 "клубник", "черник", "малин", "персик", "манго", "киви",
                 "мандарин", "абрикос", "слив"],
    "desserts": ["мороженое", "пломбир", "зефир", "пастил", "мармелад",
                 "торт", "пирожн", "кекс", "вафл", "маффин", "круассан", "слойк"],
}

_GROUP_MINIMUMS: Dict[str, int] = {
    "protein":  3,
    "carbs":    2,
    "dairy":    1,
    "veggies":  2,
    "fruits":   1,
    "desserts": 0,   # 0 по умолчанию; увеличивается для высоких бюджетов в ensure_coverage
}

PACK_WEIGHT: Dict[str, float] = {
    "protein":  600.0,
    "carbs":    800.0,
    "dairy":    900.0,
    "veggies":  800.0,
    "fats":     200.0,
    "fruits":   1000.0,
    "desserts": 300.0,
    "other":   500.0,
}

# Категории Чижика, которые блокируются целиком — независимо от названия продукта.
# Чипсы/снеки могут пройти через _FOOD_CATEGORY_KW если в названии есть "сыр" или "картофел".
_HARD_BAD_STORE_CATEGORIES = [
    "чипс", "снек", "попкорн", "сухарик", "crackers",
]

_HARD_NONFOOD_KW = [
    "игрушк", "игрушек",       # игрушка (все падежи)
    "игра ",                   # настольная/карточная игра (пробел не даёт совпасть с «икра»)
    "мемори", "деталей",       # игра «Мемори», «N деталей»
    "настольн игр", "пазл", "конструктор", "набор игр",
    "игровой набор", "кукла", "машинк", "солдатик", "мозаик",
    "детский набор", "набор для творч",
    "книга", "хрестомат", "журнал", "учебник", "тетрадь",
    "ручк", "ручек", "ручки", "ручку", "ручкой",  # ручки во всех падежах
    "шариков", "шариковы",                          # шариковые ручки
    "карандаш", "альбом для рисов",
    "канцтовар", "канцелярск", "канцелярии",
    "beifa", "pilot pen", "pentel", "staedtler",
    "шампун", "зубная паст", "зубн паст", "дезодор",
    "мыло жидк", "гель для душ", "крем для лиц", "крем для рук",
    "стирал", "порошок стир", "моющ средств", "чистящ", "отбелив",
    "подгузник", "пеленк", "прокладк", "тампон",
    "батарей", "лампочк", "удлинит",
    "ложк", "вилк", "тарелк", "кружк", "кастрюл", "сковород",
    "термос", "бутылк для вод",
    "набор посуд",               # набор посуды — не еда
    # Косметика/бытовая химия с латинскими или нестандартными названиями
    "бурлящ",      # бурлящий шар (бомба для ванны)
    "cosmetolog",  # Fabrik Cosmetology и аналоги (латиница)
    "labinel",     # LABINEL стиральный порошок
    "стир. ",      # «стир. автомат» — порошок, сокращённое написание
    "автомат 500", # стиральный порошок
    "зонт",        # зонт/зонтик — не еда
    "спрей spf", "солнцезащ",  # солнцезащитные средства
    # Корма и зоотовары — ловим по слову независимо от порядка («для стерилизованных кошек»)
    "корм для", "зоотовар", "для кошек", "для собак", "для животных",
    "кошек", "собак",          # «для стерилизованных кошек» не содержит «для кошек» как подстроку
    "наполнитель",             # наполнитель для туалета — кошачий
    # Канцелярия / товары для рисования, не попавшие в общий список
    "скетчпад", "планшет для рисов", "led дисплей",
    # Зоотовары с латинскими брендами
    "pedigree", "purina", "sheba", "whiskas", "perfect fit", "kiwi pets",
]

# Всегда фильтруется независимо от бюджета
_JUNK_KW = [
    "конфет", "шоколад", "чипс", "снек", "попкорн", "драже",
    "пиво", "водк", "вино", "газированн", "лимонад", "cola",
    "пицц", "бургер", "нагетс", "картофель фри",
    "агуша", "растишка", "нутрилон", "фрутоняня", "gerber", "ама мама",
    "детск питан", "смесь молочн",
    "соус", "кетчуп", "майонез",
    "сок ", "нектар", "чай ", "кофе ", "кисель", "компот", "морс ", "какао ",
    "напиток",
    "батон", "хлебц",
    "сухарик", "сухари ", "мука ", "мука пшен", "мука высш",  # снеки и сырые полуфабрикаты
    "жгучий", "острый суп", "азиатский суп", "siem", "lanzhou",  # острые быстрые супы
    "рамен", "nongshim", "доширак",  # корейский/японский instant ramen и лапша б/п
    "сосиск", "колбас", "нарезк",
    "пельмен", "вареник", "манты",
    "маринован", "вялен", "ассорти",
    "корейск",
    "хинкал", "паэл", "бефстроган", "чебурек",
    " в масле",  # рыба/другое в масле (сельдь в масле, шпроты в масле)
    "соленые",   # маринованные/солёные продукты — не настоящие овощи
    "шпроты",    # шпроты всегда в масле
    "кильк",     # килька в масле/рассоле
    "крекер",    # снековые крекеры — не компонент блюд
    "ватрушк",   # выпечка с начинкой — не полноценный обед/ужин
    "вата ",     # сахарная вата — не еда для плана питания
    "оладь", "оладьи",  # готовые оладьи — полуфабрикат, не крупа
    "масло",     # все масла/жиры (сливочное, подсолнечное, оливковое) — не добавлять в план
    "оливк",     # зелёные оливки — не компонент блюд
    "маслин",    # чёрные маслины — то же
    "печенье",   # бисквитное/сдобное печенье — не крупа, не еда для плана питания
    "сметан",    # сметана — только приправа, не компонент рациона
    "fry me",            # Картофель Fry Me = замороженные фри — нездоровый полуфабрикат
    "московский картофел",  # бренд снековых чипсов «Московский Картофель»
    " б/п ",     # быстрого приготовления (instant): пюре б/п, лапша б/п со вкусом и т.п.
    "б/п вкус",  # б/п вкус.курицы и подобное — ароматизированный порошковый продукт
]

# Сладости: фильтруются при бюджете < 3500р; разрешены при высоком бюджете.
# Также сюда входят ряженка (кисломолочный продукт) и творожок (молочный снэк).
_DESSERT_KW = [
    "мороженое", "пломбир", "сгущ",
    "мармелад", "зефир", "карамел", "торт", "пирожн",
    "кекс", "вафл", "маффин", "десерт",
    "круассан", "слойк", "рогалик",
]

_FOOD_CATEGORY_KW = [
    "мяс", "говяд", "свин", "рыб", "морепродукт", "птиц", "курин", "индейк",
    "молок", "молочн", "кисломол", "сливк", "йогурт", "сыр", "творог", "яйц",
    "кефир", "ряженк",
    "крупы", "крупа", "гречк", "рис", "овсян", "макарон",
    "консервы", "замороженн",
    "овощ", "фрукт", "ягод", "масло",
    "деликатес", "бобов", "горох", "фасоль", "нут", "мука",
    "яблок", "банан", "апельсин", "мандарин", "груш", "виноград",
    "орех", "семечк", "арахис",
    "мороженое", "пломбир", "зефир", "пастил", "вафл", "десерт",
    # ── Названия отделов магазина без ключевых слов продуктов ───────────────
    # «Бакалея» — название отдела с сухими товарами (крупы, зерно, макароны, бобовые).
    # Без этой записи каждый крупяной и макаронный продукт молча отбрасывался,
    # оставляя ~14 продуктов при variety=3.
    "бакалей", "бакал",
    "гастроном",        # отдел деликатесов/гастрономии
    "кондитер",         # кондитерский отдел (десерты при высоком бюджете)
    "снек",             # отдел снэков и орехов
]


# Все ключевые слова рыбы/морепродуктов — для расширения фильтра при нелюбимой рыбе
_FISH_ALL_KW = (
    "рыб", "тунец", "лосос", "скумбри", "минтай", "форел", "семг",
    "сельд", "горбуш", "треска", "сайра", "хек", "кильк", "шпроты",
    "морепродукт", "краб", "мидий", "осьминог", "гребешок",
)


def detect_group(title: str, fat: float = 0, kcal: float = 0) -> str:
    t = title.lower()
    # Творог — всегда молочный продукт, независимо от жирности и наличия КБЖУ.
    # Без этого творог при kcal=0 попадал в group="protein" через _GROUPS,
    # что давало бредовые названия вроде «Творог тушёный» вместо «Фарш тушёный».
    if "творог" in t or "творожн" in t:
        return "dairy"
    # Жирный сыр → молочка (нежирный может быть белком, напр. рикотта).
    if "сыр" in t:
        fat_cal_pct = fat * 9 / max(kcal, 1) * 100 if kcal > 0 else 0
        if fat_cal_pct > 40 or kcal <= 0 or "плавл" in t or "сливочн" in t:
            return "dairy"
    for grp, kws in _GROUPS.items():
        if any(kw in t for kw in kws):
            return grp
    return "other"


def load_products(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    raise ValueError("products JSON must be an array")


# Таблица расширений: слово → все корни (существительный + прилагательный).
# Нужна потому что у части русских слов прилагательная форма имеет другой корень:
# говядина (noun) → говяжий (adj), свинина → свиной, курица → куриный.
_LIKED_EXTRA_STEMS: Dict[str, List[str]] = {
    "говядина": ["говядин", "говяж"],
    "свинина":  ["свинин", "свин"],
    "курица":   ["куриц",  "курин"],
    "индейка":  ["индей",  "индюш"],
    "баранина": ["баранин","баран"],
    "телятина": ["телятин","телячь"],
}


def _liked_stems(word: str) -> List[str]:
    """Все корни слова: из таблицы или авто-стем (убрать 1-2 буквы окончания)."""
    if word in _LIKED_EXTRA_STEMS:
        return _LIKED_EXTRA_STEMS[word]
    if len(word) >= 6:
        return [word[:-2]]
    if len(word) >= 4:
        return [word[:-1]]
    return [word]


def _stem(word: str) -> str:
    """Первый корень слова (обратная совместимость для фильтра нелюбимых)."""
    return _liked_stems(word)[0]


def _liked_match(word: str, title: str) -> bool:
    """Проверяет вхождение с учётом падежей и адъективных форм."""
    return any(s in title for s in _liked_stems(word))


def filter_products(products: List[Dict], max_price: float, disliked: str,
                    budget: float = 2000.0, liked: str = "") -> List[Dict]:
    """Жёсткие фильтры: удаление несъедобных товаров, белый список пищевых категорий, цена, мусор.

    Сладости (_DESSERT_KW) разрешены только при бюджете >= 5000р.
    Любимые продукты (liked) обходят _JUNK_KW — пользователь явно разрешил их.
    """
    bad = [w.strip().lower() for w in disliked.split(",") if w.strip()]
    # Семантическое расширение: «рыба» в нелюбимых → фильтруем ВСЕ рыбные продукты
    if any("рыб" in b or b == "fish" for b in bad):
        bad = list(bad) + [kw for kw in _FISH_ALL_KW if kw not in bad]
    liked_words = [w.strip().lower() for w in liked.split(",") if w.strip()]
    block_desserts = budget < 5000
    out = []
    for p in products:
        cat = p.get("category", "")
        if cat:
            cat_l = cat.lower()
            if any(kw in cat_l for kw in _HARD_BAD_STORE_CATEGORIES):
                continue
            if not any(kw in cat_l for kw in _FOOD_CATEGORY_KW):
                grp = detect_group(p.get("title", ""),
                                   fat=p.get("fat", 0),
                                   kcal=p.get("calories", 0))
                if grp == "other":
                    continue
        title_l  = p.get("title", "").lower()
        is_liked = bool(liked_words and any(_liked_match(w, title_l) for w in liked_words))
        price = p.get("price", 0)
        if price <= 0 or (price > max_price and not is_liked):
            continue
        if any(kw in title_l for kw in _HARD_NONFOOD_KW):
            continue
        # Любимые продукты проходят даже без данных КБЖУ (Чижик иногда не указывает их)
        if not is_liked and not (p.get("calories", 0) or p.get("protein", 0)
                                  or p.get("fat", 0) or p.get("carbs", 0)):
            continue
        if any(j in title_l for j in _JUNK_KW):
            continue
        if block_desserts and not is_liked and any(d in title_l for d in _DESSERT_KW):
            continue
        if _BABY_AGE_RE.search(title_l):
            continue
        if any(b in title_l for b in bad):
            continue
        out.append(p)
    return out


def score(p: Dict, prot_pct: float, fat_pct: float, carb_pct: float,
          weekly_budget: float = 2000.0,
          liked_words: List[str] = None) -> float:
    cal   = p.get("calories", 0) or 1
    price = p.get("price",    1) or 1
    tp, tf, tc = prot_pct / 100, fat_pct / 100, carb_pct / 100
    pp = (p.get("protein", 0) * 4) / cal
    pf = (p.get("fat",     0) * 9) / cal
    pc = (p.get("carbs",   0) * 4) / cal
    bju  = 1 - (abs(pp - tp) + abs(pf - tf) + abs(pc - tc)) / 2
    eff  = min((cal / price) / 50.0, 1.0)
    rate = min(p.get("rating", 0) / 5.0, 1.0)
    kbju = 0.1 if p.get("complete_kbju", False) else 0.0
    if weekly_budget >= 3000:
        # Высокий бюджет: максимизируем разнообразие продуктов и охват цен.
        # eff (калории/рубль) намеренно ИСКЛЮЧЁН — он поощряет дешёвые макароны
        # и делает невозможным потратить высокий бюджет на качественные продукты.
        # Вместо этого используем budget_s: более высокая цена → более высокий балл,
        # чтобы курица (250р) и рыба (200р) обгоняли макароны (44р).
        budget_s = min(price / 350.0, 1.0)
        s = 0.25 * bju + 0.30 * rate + 0.40 * budget_s + 0.05 * kbju
    elif weekly_budget >= 2000:
        premium = min(price / 300.0, 1.0)
        s = 0.30 * bju + 0.10 * eff + 0.35 * rate + 0.10 * kbju + 0.15 * premium
    else:
        s = 0.35 * bju + 0.35 * eff + 0.20 * rate + 0.10 * kbju
    # Повышаем приоритет любимых продуктов
    if liked_words:
        tl = p.get("title", "").lower()
        if any(_liked_match(w, tl) for w in liked_words):
            s = min(1.0, s * 1.35)
    return s


def ensure_coverage(selected: List[Dict], pool: List[Dict],
                    variety: int, budget: float = 2000.0) -> List[Dict]:
    """Добавляет продукты из пула, пока каждая группа не достигнет минимального количества.

    Молочка всегда обязательна (мин. 1) независимо от разнообразия или бюджета —
    план без молочных продуктов даёт плохие завтраки и не использует бюджет.
    Фрукты, орехи и сладости добавляются пропорционально бюджету.
    """
    from collections import Counter
    if variety == 1:
        required = {"protein": 2, "carbs": 2, "dairy": 1, "veggies": 1, "fruits": 0}
    elif variety == 3:
        required = {"protein": 8, "carbs": 5, "dairy": 5, "veggies": 8, "fruits": 4, "fats": 2}
    else:
        required = dict(_GROUP_MINIMUMS)

    # Переопределения по бюджету — всегда минимум 1 молочный; больше разнообразия при высоких бюджетах.
    # Логика уровней совпадает с _budget_mandatory_stems:
    #   < 2000р  → только базовые
    #   ≥ 2000р  → фрукты + дополнительная молочка
    #   ≥ 3000р  → появляются орехи (дорогие за упаковку, отличны для бюджета)
    #   ≥ 3500р  → больше разнообразия фруктов
    #   ≥ 5000р  → сладости (только когда дорогие белки/молочка уже покрыты)
    required["dairy"] = max(required.get("dairy", 0), 1)
    if budget >= 2000:
        required["fruits"] = max(required.get("fruits", 0), 1)
        required["dairy"]  = max(required.get("dairy",  0), 2)
    if budget >= 3000:
        required["fats"]   = max(required.get("fats",   0), 1)   # орехи/семечки
    if budget >= 3500:
        required["fruits"] = max(required.get("fruits", 0), 2)
        required["fats"]   = max(required.get("fats",   0), 2)
    if budget >= 5000:
        required["desserts"] = max(required.get("desserts", 0), 1)

    counts = Counter(detect_group(p["title"]) for p in selected)
    selected_ids = {id(p) for p in selected}

    for grp, min_count in required.items():
        if min_count == 0:
            continue
        deficit = min_count - counts.get(grp, 0)
        if deficit <= 0:
            continue
        # Считаем стебли, уже присутствующие в группе — не добавляем >2 одного вида
        grp_stems: Counter = Counter(
            p["title"].lower().split()[0]
            for p in selected
            if detect_group(p.get("title", "")) == grp and p.get("title", "").strip()
        )
        cands = sorted(
            [p for p in pool if detect_group(p["title"]) == grp and id(p) not in selected_ids],
            key=lambda p: p.get("rating", 0), reverse=True
        )
        added = 0
        for p in cands:
            if added >= deficit:
                break
            stem = p.get("title", "").lower().split()[0] if p.get("title", "").strip() else ""
            if grp_stems.get(stem, 0) >= 2:
                continue  # не добавляем 3-й продукт с тем же первым словом
            selected.append(p)
            selected_ids.add(id(p))
            counts[grp] += 1
            grp_stems[stem] += 1
            added += 1
    return selected


def cap_by_category(products: List[Dict], max_per_cat: int = 2) -> List[Dict]:
    """Оставляет не более max_per_cat продуктов из одной категории магазина (порядок по баллу сохраняется)."""
    counts: Dict[str, int] = {}
    result = []
    for p in products:
        cat = p.get("category", "")
        if not cat:
            result.append(p)
            continue
        n = counts.get(cat, 0)
        if n < max_per_cat:
            result.append(p)
            counts[cat] = n + 1
    return result


def cap_by_stem(products: List[Dict], max_per_stem: int = 2) -> List[Dict]:
    """Ограничивает количество схожих продуктов с одинаковым первым словом (напр., 3 типа макарон).

    cap_by_category устраняет дубли по категории магазина; cap_by_group ограничивает
    переполнение группы (30 йогуртов). cap_by_stem останавливает 3× «Макароны…» или
    3× «Биойогурт…» в одной группе от попадания к языковой модели.
    """
    counts: Dict[str, int] = {}
    result = []
    for p in products:
        title = p.get("title", "")
        stem = title.lower().split()[0] if title.strip() else ""
        n = counts.get(stem, 0)
        if n < max_per_stem:
            result.append(p)
            counts[stem] = n + 1
    return result


def cap_by_group(products: List[Dict], max_per_group: int) -> List[Dict]:
    """Оставляет не более max_per_group продуктов из одной пищевой группы (порядок по баллу сохраняется).

    Предотвращает заполнение одной группой (напр., 30+ йогуртов с баллом ~0.33) итогового отбора
    и вытеснение белков, овощей и фруктов.
    """
    counts: Dict[str, int] = {}
    result = []
    for p in products:
        grp = detect_group(p.get("title", ""),
                           fat=p.get("fat", 0), kcal=p.get("calories", 0))
        n = counts.get(grp, 0)
        if n < max_per_group:
            result.append(p)
            counts[grp] = n + 1
    return result


_FISH_PROTEIN_KW = (
    "рыб", "тунец", "лосос", "скумбри", "минтай", "форел", "семг",
    "сельд", "горбуш", "треска", "сайра", "хек", "кильк", "шпроты",
)

_CHICKEN_BEEF_KW = (
    "курин", "грудк", "бройлер", "говяд", "свинин", "индейк",
    "телятин", "баранин", "кроли", "фарш",
    "тушён", "тушен",   # говяжья/свиная тушёнка считается мясом
    "стейк",            # стейк — мясо, форсируем в отбор наравне с курицей
)


def _budget_mandatory_stems(budget: float, variety: int) -> List[str]:
    """Возвращает стебли, которые должны присутствовать в отборе, масштабируемые по бюджету и разнообразию.

    Порядок приоритета:
      любой бюджет  → яйца, гречка, молочка, курица
      ≥ 2000р       → один фрукт (яблоко)
      ≥ 3000р       → орехи/семечки (полезные жиры, повышают расход бюджета)
      ≥ 3500р       → второй тип фрукта (банан)
      ≥ 5000р       → сладости (снэк-уровень; только когда качественная еда уже включена)
    """
    stems = ["яйц", "гречк"]               # всегда: яйца + гречка
    stems += ["йогурт", "кефир", "творог"]  # молочка всегда обязательна
    stems += ["курин", "грудк", "бройлер"]  # всегда предпочитаем курицу/птицу перед рыбой
    if budget >= 1500:
        stems += ["тушён"]                  # тушёнка (говяжья) как дешёвый запасной белок
    if budget >= 2000 or variety >= 2:
        stems += ["яблок"]
    if budget >= 3000:
        stems += ["орех", "семечк"]         # орехи: дёшевы в граммах, дороги за упаковку
    if budget >= 3500:
        stems += ["банан"]
    if budget >= 5000:
        stems += ["мороженое", "зефир", "пастил", "вафл"]  # сладости только при большом бюджете
    return stems


def inject_mandatory(selected: List[Dict], pool: List[Dict],
                     budget: float = 2000.0, variety: int = 2) -> List[Dict]:
    """Гарантирует наличие хотя бы одного продукта под каждый обязательный стебель."""
    selected_ids = {id(p) for p in selected}
    for stem in _budget_mandatory_stems(budget, variety):
        if any(stem in p.get("title", "").lower() for p in selected):
            continue
        cands = [p for p in pool
                 if stem in p.get("title", "").lower() and id(p) not in selected_ids]
        if not cands:
            continue
        best = max(cands, key=lambda p: p.get("_s", 0))
        selected.append(best)
        selected_ids.add(id(best))
    return selected


_PASTA_FAMILY_KW = ("макарон", "спагетт", "лапш", "вермишел", "фетучин", "пенне", "фузилл")

# Извлечение веса упаковки: парсим название продукта для получения явного веса/объёма.
# Точный pack_g критичен для расчёта бюджета — рыбное филе 200г за 429р стоит
# в 4 раза дороже за грамм, чем подразумевает дефолт группы 600г.
_PACK_G_PATTERNS = [
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*кг\b', re.IGNORECASE), 1000.0),
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:л|литр)(?!\w)', re.IGNORECASE), 1000.0),
    (re.compile(r'(\d{2,}(?:[.,]\d+)?)\s*г(?:р)?\.?(?!\w)', re.IGNORECASE), 1.0),
]


def parse_pack_g(title: str, group_default: float) -> float:
    """Извлекает вес упаковки в граммах из строки названия продукта.

    Пробует кг → литры → г по очереди; пропускает значения вне диапазона 50–5000 г.
    При отсутствии совпадения возвращает group_default (напр., 600 г для белков).
    """
    for pattern, factor in _PACK_G_PATTERNS:
        m = pattern.search(title.lower())
        if m:
            try:
                val = float(m.group(1).replace(',', '.')) * factor
                if 50.0 <= val <= 5000.0:
                    return val
            except ValueError:
                pass
    return group_default


def cap_pasta_types(products: List[Dict], max_pasta: int = 1) -> List[Dict]:
    """Оставляет не более max_pasta изделий из макаронной семьи независимо от стебля.

    cap_by_stem ограничивает дубли по стеблю (2× «Макароны…»), но всё равно пропускает
    «Макароны…» + «Спагетти…» + «Лапша…» одновременно. Эта функция ограничивает
    общее количество макаронных изделий вне зависимости от стебля.
    """
    pasta_count = 0
    result = []
    for p in products:
        title = p.get("title", "").lower()
        is_pasta = any(kw in title for kw in _PASTA_FAMILY_KW)
        if is_pasta:
            if pasta_count < max_pasta:
                result.append(p)
                pasta_count += 1
        else:
            result.append(p)
    return result


def inject_budget_proteins(selected: List[Dict], pool: List[Dict],
                           budget: float) -> List[Dict]:
    """Гарантирует наличие дорогих белков и разнообразия мясо/птица в отборе.

    Всегда включает хотя бы 1 курицу/говядину, чтобы план не был только рыбным.
    При высоком бюджете добавляет дополнительные дорогие белки для расхода бюджета.
    """
    selected_ids = {id(p) for p in selected}

    # Всегда гарантируем хотя бы 1 курицу/говядину/птицу независимо от бюджета
    current_meat = [
        p for p in selected
        if detect_group(p.get("title", "")) == "protein"
        and any(kw in p.get("title", "").lower() for kw in _CHICKEN_BEEF_KW)
    ]
    if not current_meat:
        meat_cands = sorted(
            [p for p in pool
             if detect_group(p.get("title", "")) == "protein"
             and any(kw in p.get("title", "").lower() for kw in _CHICKEN_BEEF_KW)
             and id(p) not in selected_ids],
            key=lambda p: float(p.get("price", 0) or 0), reverse=True
        )
        if meat_cands:
            selected.append(meat_cands[0])
            selected_ids.add(id(meat_cands[0]))

    if budget < 3000:
        return selected

    exp_threshold = 120.0
    current_exp = [
        p for p in selected
        if detect_group(p.get("title", "")) == "protein"
        and float(p.get("price", 0) or 0) >= exp_threshold
    ]
    needed_count = 2
    if budget >= 4000: needed_count = 3
    if budget >= 5000: needed_count = 4
    needed = max(0, needed_count - len(current_exp))
    if needed > 0:
        # Предпочитаем мясо перед рыбой: рыба идёт ниже в сортировке
        def _protein_pref(p: Dict) -> tuple:
            price = float(p.get("price", 0) or 0)
            is_fish = any(kw in p.get("title", "").lower() for kw in _FISH_PROTEIN_KW)
            return (1 if is_fish else 0, -price)  # сначала мясо, затем по цене убыванию
        candidates = sorted(
            [p for p in pool
             if detect_group(p.get("title", "")) == "protein"
             and float(p.get("price", 0) or 0) >= exp_threshold
             and id(p) not in selected_ids],
            key=_protein_pref
        )
        for p in candidates[:needed]:
            selected.append(p)
            selected_ids.add(id(p))

    # При высоком бюджете также добавляем премиальную молочку + жиры (орехи)
    if budget >= 4000:
        for grp, min_price, force_count in (("dairy", 100.0, 2), ("fats", 80.0, 1)):
            current_grp = [
                p for p in selected
                if detect_group(p.get("title", "")) == grp
                and float(p.get("price", 0) or 0) >= min_price
            ]
            still_needed = max(0, force_count - len(current_grp))
            cands = sorted(
                [p for p in pool
                 if detect_group(p.get("title", "")) == grp
                 and float(p.get("price", 0) or 0) >= min_price
                 and id(p) not in selected_ids],
                key=lambda p: float(p.get("price", 0) or 0), reverse=True
            )
            for p in cands[:still_needed]:
                selected.append(p)
                selected_ids.add(id(p))
    return selected


def inject_liked_foods(selected: List[Dict], pool: List[Dict],
                       liked: str) -> List[Dict]:
    """Гарантирует наличие хотя бы одного продукта под каждое слово из liked."""
    if not liked.strip():
        return selected
    liked_words = [w.strip().lower() for w in liked.split(",") if w.strip()]
    selected_ids = {id(p) for p in selected}
    for word in liked_words:
        if any(_liked_match(word, p.get("title", "").lower()) for p in selected):
            continue
        cands = [p for p in pool
                 if _liked_match(word, p.get("title", "").lower()) and id(p) not in selected_ids]
        if not cands:
            continue
        best = max(cands, key=lambda p: p.get("_s", p.get("rating", 0)))
        selected.append(best)
        selected_ids.add(id(best))
    return selected


def select(products: List[Dict], daily_cal: float, prot_pct: float,
           fat_pct: float, carb_pct: float, variety: int,
           weekly_budget: float = 2000.0, liked: str = "") -> List[Dict]:
    # Количество продуктов и лимиты по категории/группе/стеблю масштабируются с уровнем разнообразия.
    # При высоком бюджете нужно больше продуктов, чтобы дорогие товары могли заполнить бюджет.
    target        = {1: 15, 2: 28, 3: 120}.get(variety, 28)
    if weekly_budget >= 4000 and variety >= 2:
        target += 15   # дополнительные слоты: дорогие белки + молочка + орехи + сладости
    # При variety=3 лимиты намеренно мягкие — каталог Чижика достаточно мал,
    # чтобы именно лимиты были ограничивающим фактором, а не разнообразие продуктов.
    max_per_cat   = {1: 1,  2: 3,  3: 15}.get(variety, 3)
    max_per_group = {1: 3,  2: 6,  3: 20}.get(variety, 6)
    # Лимит по стеблю предотвращает 3× «Макароны…» или 3× «Биойогурт…» в одной группе
    max_per_stem  = {1: 1,  2: 2,  3: 2}.get(variety, 2)
    # Межстебельный лимит макарон: независимо от разнообразия, ограничиваем семью макарон/лапши 1 типом
    max_pasta     = {1: 1,  2: 1,  3: 2}.get(variety, 1)

    liked_words = [w.strip().lower() for w in liked.split(",") if w.strip()]

    for p in products:
        p["_s"] = score(p, prot_pct, fat_pct, carb_pct, weekly_budget, liked_words)
    products.sort(key=lambda p: p["_s"], reverse=True)
    # Сохраняем полный отсортированный список как пул для ensure_coverage / inject_mandatory ДО лимитов
    full_pool = list(products)
    capped    = cap_by_category(products, max_per_cat=max_per_cat)
    capped    = cap_by_group(capped, max_per_group=max_per_group)
    capped    = cap_by_stem(capped, max_per_stem=max_per_stem)
    capped    = cap_pasta_types(capped, max_pasta=max_pasta)
    chosen    = capped[:target]
    chosen    = ensure_coverage(chosen, full_pool, variety, budget=weekly_budget)
    chosen    = inject_mandatory(chosen, full_pool, budget=weekly_budget, variety=variety)
    chosen    = inject_budget_proteins(chosen, full_pool, weekly_budget)
    chosen    = inject_liked_foods(chosen, full_pool, liked)

    # Ограничиваем рыбные белки 2 типами независимо от бюджета/разнообразия.
    # Больше рыбы означает рыбу на каждый обед/ужин — ограничиваем ущерб разнообразию.
    max_fish = 2
    fish_ids = [
        id(p) for p in chosen
        if detect_group(p.get("title", "")) == "protein"
        and any(kw in p.get("title", "").lower() for kw in _FISH_PROTEIN_KW)
    ]
    if len(fish_ids) > max_fish:
        remove_ids = set(fish_ids[max_fish:])  # оставляем первые 2 (с высшим баллом), остальные убираем
        chosen = [p for p in chosen if id(p) not in remove_ids]

    # Ограничиваем сыр 1 позицией (творог разрешён отдельно).
    cheese_items = [p for p in chosen
                    if p.get("title", "").lower().split()[0] == "сыр"]
    if len(cheese_items) > 1:
        best_cheese = max(cheese_items, key=lambda p: p.get("_s", p.get("rating", 0)))
        chosen = [p for p in chosen
                  if p.get("title", "").lower().split()[0] != "сыр" or p is best_cheese]

    for p in chosen:
        p.pop("_s", None)
    return chosen if chosen else capped[:target]


def compact(products: List[Dict]) -> List[Dict]:
    out = []
    for p in products:
        grp = detect_group(p["title"],
                           fat=p.get("fat", 0),
                           kcal=p.get("calories", 0))
        out.append({
            "name":     p["title"],
            "price":    round(p["price"], 2),
            "kcal":     round(p.get("calories", 0), 1),
            "prot":     round(p.get("protein",  0), 1),
            "fat":      round(p.get("fat",       0), 1),
            "carb":     round(p.get("carbs",     0), 1),
            "category": p.get("category", ""),
            "group":    grp,
            "pack_g":   parse_pack_g(p["title"], PACK_WEIGHT.get(grp, 500.0)),
            "rating":   round(p.get("rating", 0), 1),
        })
    return out


def emit(data) -> None:
    sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main():
    if len(sys.argv) < 8:
        emit({"error": "Недостаточно аргументов для meal_selector.py"})
        sys.exit(1)

    products_path = sys.argv[1]
    weekly_budget = float(sys.argv[2])
    daily_cal     = float(sys.argv[3])
    prot_pct      = float(sys.argv[4])
    fat_pct       = float(sys.argv[5])
    carb_pct      = float(sys.argv[6])
    variety       = int(sys.argv[7])
    disliked      = sys.argv[8] if len(sys.argv) > 8 else ""
    liked_foods   = sys.argv[9] if len(sys.argv) > 9 else ""

    try:
        all_p = load_products(products_path)
    except Exception as e:
        emit({"error": f"Не удалось загрузить продукты: {e}"})
        sys.exit(1)

    max_item_price = weekly_budget / 3.0
    filtered = filter_products(all_p, max_item_price, disliked, budget=weekly_budget, liked=liked_foods)
    if not filtered:
        filtered = filter_products(all_p, float("inf"), disliked, budget=weekly_budget, liked=liked_foods)
    if not filtered:
        filtered = [p for p in all_p if p.get("price", 0) > 0]
    if not filtered:
        emit({"error": "Магазин не вернул ни одного продукта"})
        sys.exit(1)

    chosen = select(filtered, daily_cal, prot_pct, fat_pct, carb_pct,
                    variety, weekly_budget, liked_foods)

    # Финальная страховка: нелюбимые не попадают в компакт даже если прошли inject_*
    if disliked:
        bad_final = [w.strip().lower() for w in disliked.split(",") if w.strip()]
        if any("рыб" in b or b == "fish" for b in bad_final):
            bad_final = list(bad_final) + [kw for kw in _FISH_ALL_KW if kw not in bad_final]
        chosen = [p for p in chosen
                  if not any(_stem(b) in p.get("title", "").lower() for b in bad_final)]

    emit(compact(chosen))


if __name__ == "__main__":
    main()
