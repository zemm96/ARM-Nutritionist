"""
meal_verifier.py — проверяет и форматирует недельный план питания от языковой модели.

Использование:
    python meal_verifier.py <plan.json> <products.json> <daily_cal>
                            <prot_pct> <fat_pct> <carb_pct> <weekly_budget>
                            [variety_level] [liked_foods]
"""
import json, sys, math, re
from typing import Dict, List, Optional, Tuple

_WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг",
             "Пятница", "Суббота", "Воскресенье"]


# ── Исправление JSON ──────────────────────────────────────────────────────────

def _balance_json(s: str) -> str:
    in_str = esc = False
    stack = []
    for i, c in enumerate(s):
        if esc:              esc = False; continue
        if c == '\\' and in_str: esc = True; continue
        if c == '"':         in_str = not in_str; continue
        if in_str:           continue
        if c in ('{', '['):  stack.append(c)
        elif c == '}':
            if stack and stack[-1] == '{': stack.pop()
            else: s = s[:i]; break
        elif c == ']':
            if stack and stack[-1] == '[': stack.pop()
            else: s = s[:i]; break
    if in_str:
        # Если строка обрезана сразу после обратного слэша, завершающий \ превратит
        # закрывающую " в \" (экранированную кавычку, не закрывающую строку).
        # Убираем висячий слэш перед закрытием.
        if esc:
            s = s.rstrip('\\')
        s += '"'
    closing = {'[': ']', '{': '}'}
    return s + ''.join(closing[c] for c in reversed(stack))


def _recover_partial_days(s: str) -> Optional[dict]:
    """Крайний способ восстановления: убираем неполные хвостовые дни по одному, пока JSON не распарсится."""
    # Find positions where each {"day": N begins
    day_starts = [m.start() for m in re.finditer(r'\{[^{]{0,20}"day"\s*:', s)]
    for pos in reversed(day_starts):
        truncated = s[:pos].rstrip().rstrip(',')
        if not truncated:
            continue
        try:
            result = json.loads(_balance_json(truncated))
            if isinstance(result, dict) and isinstance(result.get('days'), list) \
                    and result['days']:
                return result
            if isinstance(result, list) and result:
                return {'days': result}
        except json.JSONDecodeError:
            pass
    return None


def _fix_qwen_missing_brace(s: str) -> str:
    kp = r'("(?:type|dish|ingredients|product|grams|day|weekday|meals)"' + r'\s*:)'
    return re.sub(r'(\}),\s*' + kp, r'\1,{\2', s)


def _parse_llm_json(text: str) -> dict:
    s = text.strip()
    if s.startswith(chr(0xFEFF)): s = s[1:]
    s = re.sub(r'^```(?:json)?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*```\s*$', '', s).strip()
    start = next((i for i, c in enumerate(s) if c in ('{', '[')), -1)
    if start < 0:
        raise json.JSONDecodeError('No JSON found in LLM output', s, 0)
    s = s[start:]
    s_tc = re.sub(r',(\s*[}\]])', r'\1', s)
    s_mc = re.sub(r'([}\]])\s*([{[])', r'\1,\2', s_tc)
    s_ob = _fix_qwen_missing_brace(s_mc)
    for variant in (s, s_tc, s_mc, s_ob):
        try:
            return json.JSONDecoder().raw_decode(variant)[0]
        except json.JSONDecodeError:
            pass
        try:
            return json.loads(_balance_json(variant))
        except json.JSONDecodeError:
            pass
    # Крайний случай: восстанавливаем сколько угодно полных дней до обрезки.
    # add_missing_meals() в format_plan() заполнит остаток.
    recovered = _recover_partial_days(s)
    if recovered:
        return recovered
    raise json.JSONDecodeError('Cannot parse LLM JSON output', s, 0)

SCALE_MIN = 0.55
SCALE_MAX = 3.50

DRINK_KW = (
    "сок", "нектар", "чай", "кофе", "кисель", "компот",
    "морс", "напиток", "вода", "какао", "ряженк", "кефир",
    "эспрессо", "капучино", "латте",
)

NONFOOD_KW = (
    "сухарик", "сухари ",                # снеки
    "мука пшен", "мука высш", "мука ",  # сырая мука
    "ама мама",                          # детский бренд
    "книга", "хрестомат", "журнал", "газет", "учебник",
    "игрушк", "игрушек",  # toy (all cases: игрушка, игрушек)
    "игра ",              # board/card game ("Игра Мастер...") but not "икра"
    "мемори", "деталей",  # Memory game, "parts" (board game packaging)
    "канцел", "косметик", "шампун", "зубн", "дезодор", "стиральн",
    "игровой", "настольн", "пазл", "конструктор", "набор игр",
    "батарей", "лампочк", "посуд", "ложк", "вилк", "тарелк",
    "набор посуд",               # набор посуды — не еда
    "вата ",                     # сахарная вата — не еда
    "чистящ", "моющ", "порошок стир",
    "ручек", "ручки", "ручку", "ручкой", "шариков", "шариковы",
    "карандаш", "канцтовар", "beifa", "pilot pen", "pentel",
    # Косметика/бытовая химия с латинскими названиями или нестандартными написаниями
    "бурлящ",      # бурлящий шар (бомба для ванны)
    "cosmetolog",  # Fabrik Cosmetology и подобные (латиница)
    "labinel",     # LABINEL — стиральный порошок
    "стир. ",      # «стир. автомат» — порошок со сжатым словом
    "автомат 500", # характерное сочетание для стирального порошка
    "зонт",        # зонт/зонтик — не еда
    "спрей spf", "солнцезащ",  # солнцезащитные средства
)

BREAKFAST_FORBIDDEN_KW = (
    "говядин", "свинин", "барани", "телятин", "кроли",
    "курин", "индейк", "утк", "гусятин", "бройлер",
    "рыб", "минтай", "лосось", "скумбри", "тунец", "треска",
    "горбуш", "форель", "семг", "карп", "сельд", "сайр",
    "креветк", "кальмар", "мидий", "краб",
    "пельмен", "хинкал", "манты", "котлет", "фарш",
    "сосиск", "колбас", "ветчин", "карбонад", "грудинк",
    "бекон", "шпик", "нарезк", "окорок",
    "сметан",  # сметана не подходит для завтрака — только творог/йогурт/крупы
)

# Каши и хлопья — только для завтрака, в обед/ужин не уместны
_PORRIDGE_KW = ("овсян", "хлопья", "геркулес", "мюсли")

_FISH_KW = (
    "рыб", "тунец", "лосос", "скумбри", "минтай", "форел", "семг",
    "сельд", "горбуш", "треска", "сайра", "хек", "кильк",
)

_BULGUR_KW = ("булгур",)

_PASTA_KW = ("макарон", "спагетт", "лапш", "вермишел", "фетучин", "пенне", "фузилл")

# Продукты, запрещённые в Перекусе: перекус = фрукты / молочка / орехи / сладости
_SNACK_CARB_KW = (
    "макарон", "спагетт", "лапш", "вермишел", "фетучин", "пенне", "фузилл",
    "картофел", "fry me",
    "крупа", "смесь круп", "гречк", "булгур", "перловк",
    "рис ", "хлопья", "мюсли",
)

SWEET_KW = (
    "мёд", "варень", "джем", "повидл", "сгущ",
    "шоколад", "конфет", "карамел", "сироп", "зефир", "мармелад",
)

SAVORY_MAIN_KW = (
    "картофел", "гречк", "рис", "макарон", "лапш", "перловк", "булгур",
    "пельмен", "говядин", "свинин", "курин", "индейк",
    "рыб", "минтай", "лосось", "скумбри", "тунец",
    "колбас", "сосиск", "фарш", "котлет",
    "капуст", "баклажан", "кабачк", "морков",
)

# Keywords that identify a "hot" protein (meat / fish / eggs).
# творог, йогурт etc. are excluded — dairy alone must NOT serve as the main protein
# in lunch or dinner; the verifier will inject a real hot protein if none is present.
_HOT_PROT_KW = (
    "яйц", "тунец", "минтай", "треска", "форел", "семг", "лосос",
    "горбуш", "кета", "судак", "хек", "сельд", "скумбри", "сардин",
    "курин", "индейк", "говяд", "свинин", "телятин", "баранин",
    "кроли", "фарш", "стейк", "грудк", "котлет", "филе",
    "тушен", "тушён", "бройлер", "птиц",
    "ветчин", "карбонад", "окорок", "грудинк", "бекон",
)

# Доля дневных калорий по типу приёма пищи.
# Перекус намеренно мал — это инструмент расхода бюджета (фрукты/молочка/орехи/сладости),
# а не калорийный приём. Основные приёмы покрывают 100%; Перекус идёт сверх.
_MEAL_FRAC: Dict[str, float] = {"Завтрак": 0.25, "Обед": 0.40, "Ужин": 0.35, "Перекус": 0.10}
_MEAL_ORDER = ["Завтрак", "Обед", "Перекус", "Ужин"]


_COMPAT: Dict[Tuple[str, str], float] = {
    ("carbs",   "dairy"):   0.88,
    ("carbs",   "fats"):    0.72,
    ("carbs",   "fruits"):  0.82,
    ("carbs",   "protein"): 0.90,
    ("carbs",   "veggies"): 0.92,
    ("carbs",   "carbs"):   0.60,
    ("dairy",   "dairy"):   0.80,
    ("dairy",   "fats"):    0.65,
    ("dairy",   "fruits"):  0.92,
    ("dairy",   "protein"): 0.50,
    ("dairy",   "veggies"): 0.75,
    ("fats",    "fats"):    0.50,
    ("fats",    "fruits"):  0.68,
    ("fats",    "protein"): 0.75,
    ("fats",    "veggies"): 0.82,
    ("fruits",  "fruits"):  0.85,
    ("fruits",  "protein"): 0.35,
    ("fruits",  "veggies"): 0.70,
    ("protein", "protein"): 0.30,
    ("protein", "veggies"): 0.95,
    ("veggies", "veggies"): 0.88,
}

COMPAT_THRESHOLD = 0.70

_GROUP_PRIORITY = {"protein": 4, "carbs": 3, "dairy": 2, "veggies": 2,
                   "fats": 1, "fruits": 1, "other": 0}


def compat_score(g1: str, g2: str) -> float:
    if g1 == g2:
        return _COMPAT.get((g1, g2), 0.80)
    return _COMPAT.get((min(g1, g2), max(g1, g2)), 0.65)


def find_product(name: str, products: List[Dict]) -> Optional[Dict]:
    n = name.strip().lower()
    for p in products:
        if p["name"].lower() == n: return p
    for p in products:
        pl = p["name"].lower()
        if n in pl or pl in n: return p
    parts = n.split()
    if parts and len(parts[0]) >= 3:
        for p in products:
            if parts[0] in p["name"].lower(): return p
    return None


def type_key(prod: Dict) -> str:
    parts = prod["name"].split()
    return parts[0].lower() if parts else prod["name"].lower()


def gram_cap(kcal_per_100g: float, group: str = "other") -> int:
    if group == "protein":  return 250   # hard cap; keeps fat from fatty proteins in check
    if group == "dairy":    return 80 if kcal_per_100g >= 200 else 300
    if group == "fats":     return 30
    if group == "carbs":    return 400
    if group == "veggies":  return 150  # горошек/морковь — гарнир, не основа блюда
    if group == "fruits":   return 200
    if kcal_per_100g < 40:  return 250
    if kcal_per_100g < 100: return 300
    return 350


def _is_real_protein(p: Dict) -> bool:
    """True, если продукт является настоящим источником белка для составления блюда.

    Правила (по порядку):
    1. Слова сыр/молочка → всегда False (относятся к группе dairy).
    2. Жировые бомбы (>80% калорий из жира: паштет, сырокопчёная колбаса,
       сельдь в масле) → False независимо от названия.
    3. Именованные белковые продукты (рыба, мясо, яйца, тушёнка, филе) → True,
       если белок обеспечивает ≥12% калорий.
    4. Всё остальное → True только если белок обеспечивает ≥20% калорий.
    """
    name = p.get("name", "").lower()
    kcal     = float(p.get("kcal", 100) or 100)
    prot_cal = float(p.get("prot", 0)   or 0) * 4
    fat_cal  = float(p.get("fat",  0)   or 0) * 9

    if any(kw in name for kw in ("сыр", "творог", "творож", "плавл", "сметан",
                                  "йогурт", "биойогурт", "молок", "кефир",
                                  "ряженк", "сливк")):
        return False

    if fat_cal / max(kcal, 1) > 0.85:
        return False

    _PROTEIN_KW = (
        "яйц", "тунец", "минтай", "треска", "форел", "семг", "лосос",
        "горбуш", "кета", "судак", "хек", "сельд", "скумбри", "сардин",
        "курин", "индейк", "говяд", "свинин", "телятин", "баранин",
        "кроли", "фарш", "стейк", "грудк", "котлет", "филе",
        "тушен", "тушён", "бройлер", "птиц",
        "ветчин", "карбонад", "окорок", "грудинк", "бекон",
    )
    if any(kw in name for kw in _PROTEIN_KW):
        return prot_cal / max(kcal, 1) > 0.12

    # 4 — generic threshold
    return prot_cal / max(kcal, 1) > 0.20


def _build_meal_ingredients(meal_type: str, products: List[Dict],
                             daily_cal: float, prot_pct: float,
                             fat_pct: float, carb_pct: float,
                             day_idx: int = 0,
                             variety: int = 2) -> List[Dict]:
    """Составляет список ингредиентов для одного приёма пищи под заданные макросы.

    Порции рассчитаны так, чтобы основная макрогруппа заполняла ~70% суточного
    целевого значения для этого приёма; вторичная группа — ~60%. Гарниры из овощей
    чередуются по day_idx, чтобы избежать одинаковых блюд каждый день.
    """
    meal_cal = daily_cal * _MEAL_FRAC.get(meal_type, 1 / 3)
    tgt_prot = meal_cal * prot_pct / 100 / 4  # target protein grams
    tgt_carb = meal_cal * carb_pct / 100 / 4  # target carb grams

    by_group: Dict[str, List[Dict]] = {}
    for p in products:
        by_group.setdefault(p.get("group", "other"), []).append(p)

    # Ищем в группах "protein" И "other" — некоторые продукты (напр., куриное филе,
    # помеченное селектором как "other") являются настоящими белками, которые нельзя пропускать.
    _all_prot_cands = [
        p for grp in ("protein", "other")
        for p in by_group.get(grp, [])
    ]
    real_proteins = sorted(
        [p for p in _all_prot_cands if _is_real_protein(p)],
        key=lambda p: -float(p.get("price", 0) or 0)  # expensive first
    ) or sorted(_all_prot_cands, key=lambda p: -float(p.get("price", 0) or 0))

    # meal_offset разносит завтрак/обед/ужин по разным слотам ротации
    _MEAL_OFFSET = {"Завтрак": 0, "Обед": 3, "Ужин": 6}
    _rot_idx = day_idx + _MEAL_OFFSET.get(meal_type, 0)

    def pick(group: str, avoid: tuple = ()) -> Optional[Dict]:
        cands = sorted(by_group.get(group, []),
                       key=lambda p: -float(p.get("price", 0) or 0))  # expensive first
        if avoid:
            preferred = [p for p in cands
                         if not any(kw in p["name"].lower() for kw in avoid)]
            cands = preferred if preferred else cands
        if not cands: return None
        n = len(cands) if variety >= 3 else min(len(cands), max(1, variety))
        return cands[_rot_idx % n]

    def pick_protein() -> Optional[Dict]:
        if not real_proteins: return None
        n = len(real_proteins) if variety >= 3 else min(len(real_proteins), max(1, variety))
        return real_proteins[_rot_idx % n]

    def pick_veggie(offset: int = 0) -> Optional[Dict]:
        cands = sorted(by_group.get("veggies", []),
                       key=lambda p: float(p.get("rating", 0)), reverse=True)
        if not cands: return None
        return cands[(_rot_idx + offset) % len(cands)]

    def grams(p: Dict, target_g: float, macro: str) -> int:
        per_100 = float(p.get(macro, 0) or 0)
        if per_100 < 1:
            # Product has negligible of this macro; size by calorie fraction
            kcal = float(p.get("kcal", 100) or 100)
            g = round(meal_cal * 0.25 * 100 / max(kcal, 1))
        else:
            g = round(target_g * 100 / per_100)
        kcal = float(p.get("kcal", 100) or 100)
        return max(50, min(gram_cap(kcal, p.get("group", "other")), g))

    ings: List[Dict] = []

    if meal_type == "Завтрак":
        # На завтрак: крупа (не хлеб/батон/паста) → правильная молочка → фрукт
        _BFAST_DAIRY_AVOID = ("масло", "сметан")
        _BFAST_CARB_AVOID  = _PASTA_KW + ("хлеб", "батон", "хлебц")  # хлеб — не крупы
        if carb := pick("carbs", avoid=_BFAST_CARB_AVOID):
            ings.append({"product": carb["name"],
                         "grams": grams(carb, tgt_carb * 0.75, "carb")})
        if dairy := pick("dairy", avoid=_BFAST_DAIRY_AVOID):
            if dairy["name"] not in {i["product"] for i in ings}:
                d_kcal = float(dairy.get("kcal", 80) or 80)
                ings.append({"product": dairy["name"],
                             "grams": min(gram_cap(d_kcal, "dairy"), 120)})
        # Второй молочный продукт другого ТИПА (йогурт+творог, но не ряженка+ряженка)
        dairy_cands = sorted(
            [p for p in by_group.get("dairy", [])
             if not any(kw in p["name"].lower() for kw in _BFAST_DAIRY_AVOID)],
            key=lambda p: float(p.get("rating", 0)), reverse=True)
        already_in    = {i["product"] for i in ings}
        already_stems = {i["product"].lower().split()[0] for i in ings}
        dairy2_pool   = [p for p in dairy_cands
                         if p["name"] not in already_in
                         and p["name"].lower().split()[0] not in already_stems]
        if dairy2_pool:
            dairy2 = dairy2_pool[(_rot_idx + 1) % len(dairy2_pool)]
            d2_kcal = float(dairy2.get("kcal", 80) or 80)
            ings.append({"product": dairy2["name"],
                         "grams": min(gram_cap(d2_kcal, "dairy"), 100)})
        # Фруктовая добавка: только если уже есть крупа или правильная молочка
        if fruit := pick("fruits"):
            if fruit["name"] not in {i["product"] for i in ings}:
                ings.append({"product": fruit["name"], "grams": 120})
        # При высоком целевом белке добавляем яйца/творог, чтобы белок на завтрак
        # не поступал только из хлеба и йогурта.
        if prot_pct >= 25 and real_proteins:
            bfast_prots = [
                p for p in real_proteins
                if not any(kw in p["name"].lower() for kw in BREAKFAST_FORBIDDEN_KW)
            ]
            if bfast_prots:
                bp = bfast_prots[day_idx % len(bfast_prots)]
                if bp["name"] not in {i["product"] for i in ings}:
                    ings.append({"product": bp["name"],
                                 "grams": grams(bp, tgt_prot * 0.7, "prot")})
        # Запасной вариант: молочка (без масла/сметаны) → фрукты → безопасный белок
        if not ings:
            bfast_dairy = [p for p in by_group.get("dairy", [])
                           if not any(kw in p["name"].lower()
                                      for kw in _BFAST_DAIRY_AVOID)]
            bfast_fruits = by_group.get("fruits", [])
            bfast_prots = [p for p in real_proteins
                           if not any(kw in p["name"].lower() for kw in BREAKFAST_FORBIDDEN_KW)]
            fallback_pool = bfast_dairy or bfast_fruits or bfast_prots
            if fallback_pool:
                p = fallback_pool[_rot_idx % len(fallback_pool)]
                ings.append({"product": p["name"], "grams": grams(p, tgt_prot, "prot")})

    elif meal_type == "Обед":
        # Белок + углеводы (без каш/хлопьев) + ротируемый овощ
        if protein := pick_protein():
            ings.append({"product": protein["name"],
                         "grams": grams(protein, tgt_prot, "prot")})
        if carb := pick("carbs", avoid=_PORRIDGE_KW):
            if carb["name"] not in {i["product"] for i in ings}:
                ings.append({"product": carb["name"],
                             "grams": grams(carb, tgt_carb * 0.70, "carb")})
        if veggie := pick_veggie(offset=0):
            if veggie["name"] not in {i["product"] for i in ings}:
                vk = float(veggie.get("kcal", 30) or 30)
                ings.append({"product": veggie["name"],
                             "grams": min(gram_cap(vk, "veggies"), 200)})

    elif meal_type == "Ужин":
        # Белок + другой овощ (смещение +1 относительно обеда)
        if protein := pick_protein():
            ings.append({"product": protein["name"],
                         "grams": grams(protein, tgt_prot * 1.1, "prot")})
        if veggie := pick_veggie(offset=1):
            if veggie["name"] not in {i["product"] for i in ings}:
                vk = float(veggie.get("kcal", 30) or 30)
                ings.append({"product": veggie["name"],
                             "grams": min(gram_cap(vk, "veggies"), 200)})
        # Обязательный углеводный гарнир на ужин (без каш/хлопьев)
        if carb := pick("carbs", avoid=_PORRIDGE_KW):
            if carb["name"] not in {i["product"] for i in ings}:
                ings.append({"product": carb["name"],
                             "grams": grams(carb, tgt_carb * 0.85, "carb")})

    elif meal_type == "Перекус":
        # Перекус: фрукт + молочка (йогурт/кефир) или орехи/сладости
        # масло сливочное, мясо и готовые горячие блюда в перекусе не уместны
        _SNACK_MAIN_KW = ("сэндвич", "оладьи", "бифштекс", "чебуречки",
                          "котлет", "бургер", "хинкал", "пельмен", "мякоть",
                          "шаурм", "блин", "блинч")
        # Солёная/твёрдая молочка (сыр, брынза) с фруктами — несовместимо
        _SAVORY_DAIRY_KW = ("сыр", "брынз", "плавл")
        if fruit := pick("fruits"):
            ings.append({"product": fruit["name"], "grams": 150})
        dairy_avoid = ("масло", "смет", "сливк") + _SNACK_MAIN_KW + _SAVORY_DAIRY_KW
        if dairy := pick("dairy", avoid=dairy_avoid):
            if dairy["name"] not in {i["product"] for i in ings}:
                ings.append({"product": dairy["name"], "grams": 120})
        # Если есть орехи/жиры, но молочка не добавлена — используем орехи (не масло, не мясо/бекон)
        _SNACK_FAT_AVOID = ("масло", "смет", "сливк") + BREAKFAST_FORBIDDEN_KW
        if len(ings) < 2:
            if fat := pick("fats", avoid=_SNACK_FAT_AVOID):
                if fat["name"] not in {i["product"] for i in ings}:
                    ings.append({"product": fat["name"], "grams": 30})
        # Dessert: replace or supplement if no fruit/dairy found
        if not ings:
            if dessert := pick("desserts"):
                ings.append({"product": dessert["name"], "grams": 80})

    return ings or ([{"product": products[0]["name"], "grams": 150}]
                    if products else [])


# ── Dish naming & compatibility ────────────────────────────────────────────────

def build_dish_name(ings: List[Dict], products: List[Dict],
                    meal_type: str = "") -> str:
    by_group: Dict[str, Dict] = {}
    for ing in ings:
        p = find_product(ing.get("product", ""), products)
        if p:
            grp = p.get("group", "other")
            if grp not in by_group:
                by_group[grp] = p

    def _short(p: Dict) -> str:
        nl = p["name"].lower()
        if any(k in nl for k in ("гречн", "гречк")):          return "гречка"
        if any(k in nl for k in ("овсян", "хлопья", "геркул")): return "овсянка"
        if "рис " in nl or nl.startswith("рис"):               return "рис"
        if "пшен" in nl:                                        return "пшено"
        if "булгур" in nl:                                      return "Булгур"
        return p["name"].split()[0]

    # Молочные продукты, иногда ошибочно попадающие в group="protein" при отсутствии КБЖУ
    _DAIRY_NAME_KW = ("творог", "йогурт", "биойогурт", "кефир", "ряженк",
                      "сметан", "молок", "сливк", "ряженк")
    protein_p = by_group.get("protein")
    # Если «protein» — это творог/йогурт/кефир, сбрасываем и ищем настоящий белок.
    if protein_p and any(kw in protein_p.get("name","").lower() for kw in _DAIRY_NAME_KW):
        protein_p = None
    # Крылышки, филе и т.п. могут попасть в группу "other" — проверяем её тоже.
    # Намеренно ограничиваем поиск группами protein/other, чтобы овощи (у которых
    # тоже бывает >20% ккал из белка) не ошибочно становились белком блюда.
    if protein_p is None:
        for ing in ings:
            p = find_product(ing.get("product", ""), products)
            if p and p.get("group") in ("protein", "other") and _is_real_protein(p):
                protein_p = p
                break
    carb_p    = by_group.get("carbs")
    dairy_p   = by_group.get("dairy")
    veggie_p  = by_group.get("veggies")
    fruit_p   = by_group.get("fruits")

    protein = _short(protein_p) if protein_p else None
    carb    = _short(carb_p)    if carb_p    else None
    dairy   = _short(dairy_p)   if dairy_p   else None
    veggie  = _short(veggie_p)  if veggie_p  else None
    fruit   = _short(fruit_p)   if fruit_p   else None

    carb_full = carb_p["name"].lower() if carb_p else ""

    if meal_type == "Завтрак":
        if carb and dairy:
            if any(k in carb_full for k in ("овсян", "хлопья", "геркул")):
                return f"Овсяная каша с {dairy}"
            if any(k in carb_full for k in ("гречн", "гречк")):
                return f"Гречневая каша с {dairy}"
            return f"{carb} с {dairy}"
        if dairy and fruit:
            return f"{dairy} с {fruit}"
        if carb:
            if any(k in carb_full for k in ("овсян", "хлопья")): return "Овсяная каша"
            if any(k in carb_full for k in ("гречн", "гречк")):  return "Гречневая каша"
            return carb
        if protein: return f"Омлет с {veggie}" if veggie else "Омлет"
        if dairy:   return dairy

    if protein and carb and veggie:
        return f"{protein} с {carb} и {veggie}"
    if protein and carb:
        return f"{protein} с {carb}"
    if protein and veggie:
        return f"{protein} с {veggie}"
    if carb and dairy:
        if any(k in carb_full for k in ("макарон", "спагетт", "лапш", "вермишел")):
            return f"Макароны с {dairy}"
        return f"{carb} с {dairy}"
    if carb and veggie: return f"{carb} с {veggie}"
    if protein:  return f"{protein} тушёный" if meal_type == "Обед" else f"{protein} запечённый"
    if carb:     return carb
    if veggie:   return f"Овощное блюдо с {veggie}"
    for ing in ings:
        p = find_product(ing.get("product", ""), products)
        if p: return p["name"].split()[0]
    return "Блюдо"


def _ing_groups(ings: List[Dict], products: List[Dict]) -> List[str]:
    groups = []
    for ing in ings:
        p = find_product(ing.get("product", ""), products)
        groups.append(p.get("group", "other") if p else "other")
    return groups


def meal_min_compat(ings: List[Dict], products: List[Dict]) -> float:
    groups = _ing_groups(ings, products)
    if len(groups) < 2: return 1.0
    return min(
        compat_score(groups[i], groups[j])
        for i in range(len(groups))
        for j in range(i + 1, len(groups))
    )


def fix_incompatible_meal(meal: Dict, products: List[Dict]) -> Dict:
    ings = meal.get("ingredients", [])
    for _ in range(len(ings)):
        if len(ings) < 2: break
        if meal_min_compat(ings, products) >= COMPAT_THRESHOLD: break
        groups = _ing_groups(ings, products)
        scores = []
        for i in range(len(ings)):
            others = [groups[j] for j in range(len(ings)) if j != i]
            avg    = sum(compat_score(groups[i], g) for g in others) / len(others)
            bonus  = _GROUP_PRIORITY.get(groups[i], 0) * 0.02
            scores.append(avg + bonus)
        worst = scores.index(min(scores))
        ings  = [ings[k] for k in range(len(ings)) if k != worst]
    meal["ingredients"] = ings
    return meal


# ── Macro accuracy ─────────────────────────────────────────────────────────────

def check_macro_errors(nutr: Dict, prot_pct: float,
                       fat_pct: float, carb_pct: float) -> Dict[str, float]:
    """Абсолютное процентное отклонение от целевого значения для каждого макро (шкала 0–100)."""
    cal = nutr.get("kcal", 0) or 1
    actual = {
        "prot": (nutr.get("prot", 0) * 4 / cal) * 100,
        "fat":  (nutr.get("fat",  0) * 9 / cal) * 100,
        "carb": (nutr.get("carb", 0) * 4 / cal) * 100,
    }
    targets = {"prot": prot_pct, "fat": fat_pct, "carb": carb_pct}
    return {
        k: abs(actual[k] - targets[k]) / targets[k] * 100 if targets[k] > 0 else 0.0
        for k in targets
    }


# ── Nutrition & cost ──────────────────────────────────────────────────────────

def calc_nutrition(ings: List[Dict], products: List[Dict]) -> Tuple[Dict, List[str]]:
    n = {"kcal": 0.0, "prot": 0.0, "fat": 0.0, "carb": 0.0, "cost": 0.0}
    missing: List[str] = []
    for ing in ings:
        p = find_product(ing["product"], products)
        if p is None:
            missing.append(ing["product"]); continue
        g = float(ing.get("grams", 100)) / 100.0
        n["kcal"] += float(p.get("kcal", 0) or 0) * g
        n["prot"] += float(p.get("prot", 0) or 0) * g
        n["fat"]  += float(p.get("fat",  0) or 0) * g
        n["carb"] += float(p.get("carb", 0) or 0) * g
        pack_g = float(p.get("pack_g", 500) or 500)
        n["cost"] += float(ing.get("grams", 100)) / pack_g * float(p.get("price", 0) or 0)
    return n, missing


def shopping_cost(plan: Dict, products: List[Dict]) -> float:
    usage: Dict[str, Tuple[float, float, float]] = {}
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            for ing in meal.get("ingredients", []):
                p = find_product(ing["product"], products)
                if not p: continue
                nm = p["name"]
                pg = float(p.get("pack_g", 500) or 500)
                pr = float(p.get("price",  0)   or 0)
                g0 = usage[nm][0] if nm in usage else 0.0
                usage[nm] = (g0 + float(ing.get("grams", 100)), pg, pr)
    return sum(math.ceil(g / pg) * pr for g, pg, pr in usage.values())


# ── Plan corrections ──────────────────────────────────────────────────────────

def add_missing_days(plan: Dict) -> Dict:
    """Гарантирует, что план всегда содержит ровно 7 дней (дни 1–7).

    Языковая модель иногда обрезает вывод и выдаёт только 2–5 дней.
    Недостающие дни добавляются как пустые заглушки; add_missing_meals() их заполняет.
    """
    existing = {}
    for d in plan.get("days", []):
        try:
            existing[int(d.get("day", 0))] = d
        except (TypeError, ValueError):
            pass
    plan["days"] = [
        existing.get(i, {"day": i, "weekday": _WEEKDAYS[i - 1], "meals": []})
        for i in range(1, 8)
    ]
    return plan


def dedup_meal_types(plan: Dict) -> Dict:
    """Удаляет дублирующиеся типы приёмов пищи в пределах дня; сохраняет первое вхождение.

    Языковая модель иногда выдаёт один и тот же тип (напр., Завтрак) дважды в день.
    Должна выполняться до всех остальных шагов конвейера, чтобы последующая логика видела чистые данные.
    """
    for day in plan.get("days", []):
        seen: set = set()
        kept = []
        for meal in day.get("meals", []):
            t = meal.get("type", "").strip()
            if t:
                meal["type"] = t  # normalise whitespace
            if t not in seen:
                seen.add(t)
                kept.append(meal)
        day["meals"] = kept
    return plan


def clean_plan(plan: Dict, products: List[Dict]) -> Dict:
    for day in plan.get("days", []):
        kept = []
        for meal in day.get("meals", []):
            mtype    = meal.get("type", "")
            is_bfast = mtype == "Завтрак"
            is_main  = mtype in ("Обед", "Ужин")
            is_snack = mtype == "Перекус"
            clean = []
            for ing in meal.get("ingredients", []):
                name = ing.get("product", "")
                nl   = name.lower()
                if any(kw in nl for kw in DRINK_KW): continue
                if is_bfast and any(kw in nl for kw in BREAKFAST_FORBIDDEN_KW): continue
                if is_bfast and any(kw in nl for kw in _PASTA_KW): continue
                # Каши/хлопья не подходят для обеда и ужина
                if is_main  and any(kw in nl for kw in _PORRIDGE_KW): continue
                # В перекус мясо, рыба и бекон не идут
                if is_snack and any(kw in nl for kw in BREAKFAST_FORBIDDEN_KW): continue
                # В перекус не идут крупы, паста, картофель — только фрукты/молочка/орехи
                if is_snack and any(kw in nl for kw in _SNACK_CARB_KW): continue
                p = find_product(name, products)
                if p is None: continue
                pnl = p["name"].lower()
                if any(kw in pnl for kw in NONFOOD_KW): continue
                if is_bfast and any(kw in pnl for kw in BREAKFAST_FORBIDDEN_KW): continue
                if is_bfast and any(kw in pnl for kw in _PASTA_KW): continue
                if is_main  and any(kw in pnl for kw in _PORRIDGE_KW): continue
                if is_snack and any(kw in pnl for kw in BREAKFAST_FORBIDDEN_KW): continue
                if is_snack and any(kw in pnl for kw in _SNACK_CARB_KW): continue
                clean.append({**ing, "product": p["name"]})
            if clean:
                meal["ingredients"] = clean
                kept.append(meal)
        day["meals"] = kept
    return plan


def cap_pasta_weekly(plan: Dict, max_pasta: int = 3) -> Dict:
    """Разрешает не более max_pasta блюд из макарон/лапши в неделю.

    Макароны уместны раз-два, но не на каждый обед и ужин.
    Блюда, лишившиеся единственного ингредиента, становятся пустыми и перестраиваются
    в add_missing_meals без макаронного запасного варианта.
    """
    pasta_count = 0
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            ings = meal.get("ingredients", [])
            has_pasta = any(
                any(kw in ing.get("product", "").lower() for kw in _PASTA_KW)
                for ing in ings
            )
            if not has_pasta:
                continue
            pasta_count += 1
            if pasta_count > max_pasta:
                meal["ingredients"] = [
                    ing for ing in ings
                    if not any(kw in ing.get("product", "").lower() for kw in _PASTA_KW)
                ]
    return plan


def cap_fish_meals_weekly(plan: Dict, products: List[Dict],
                          daily_cal: float, prot_pct: float,
                          fat_pct: float, carb_pct: float,
                          variety: int, max_fish: int = 7) -> Dict:
    """Убирает рыбу из блюд сверх недельного лимита и перестраивает их без рыбы.

    Рыба на завтрак уже удаляется в strip_breakfast_forbidden.
    Лишние обеды/ужины с рыбой очищаются и перестраиваются только с нерыбными
    белками, чтобы ни одно блюдо не осталось без белка.
    """
    def _has_fish(meal: Dict) -> bool:
        return any(any(kw in ing.get("product", "").lower() for kw in _FISH_KW)
                   for ing in meal.get("ingredients", []))

    def _strip_fish(meal: Dict) -> None:
        meal["ingredients"] = [
            ing for ing in meal.get("ingredients", [])
            if not any(kw in ing.get("product", "").lower() for kw in _FISH_KW)
        ]

    non_fish = [p for p in products
                if not any(kw in p.get("name", "").lower() for kw in _FISH_KW)]

    fish_count = 0
    for day_idx, day in enumerate(plan.get("days", [])):
        for meal in day.get("meals", []):
            if not _has_fish(meal):
                continue
            fish_count += 1
            if fish_count <= max_fish:
                continue
            _strip_fish(meal)
            ings = meal.get("ingredients", [])
            has_hot = any(
                any(kw in (find_product(i.get("product", ""), products) or {})
                    .get("name", "").lower() for kw in _HOT_PROT_KW)
                for i in ings
            )
            if not has_hot:
                mtype = meal.get("type", "Обед")
                new_ings = _build_meal_ingredients(
                    mtype, non_fish or products, daily_cal,
                    prot_pct, fat_pct, carb_pct,
                    day_idx=day_idx + 10, variety=variety,
                )
                if new_ings:
                    meal["ingredients"] = new_ings
    return plan


def fix_bulgur_dairy_incompatibility(plan: Dict, products: List[Dict]) -> Dict:
    """Убирает молочные продукты из любого блюда, содержащего булгур (несовместимое сочетание)."""
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            ings = meal.get("ingredients", [])
            has_bulgur = any(any(kw in ing.get("product", "").lower()
                                 for kw in _BULGUR_KW) for ing in ings)
            if not has_bulgur:
                continue
            kept = [ing for ing in ings
                    if (find_product(ing.get("product", ""), products) or {})
                    .get("group") != "dairy"]
            if kept:
                meal["ingredients"] = kept
    return plan


def fix_dairy_in_main_meals(plan: Dict, products: List[Dict]) -> Dict:
    """Убирает молочку из Обеда/Ужина, если присутствует горячий белок (мясо/рыба/яйца).

    Молочка относится к завтраку; в горячем блюде она добавляет лишние жиры
    и путает названия блюд. Блюда, где молочка — ЕДИНСТВЕННЫЙ белок,
    оставляются нетронутыми — ими занимается rebuild_bad_meals.
    """
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            if meal.get("type") not in ("Обед", "Ужин"):
                continue
            ings = meal.get("ingredients", [])
            has_hot = any(
                any(kw in (find_product(i.get("product", ""), products) or {})
                    .get("name", "").lower() for kw in _HOT_PROT_KW)
                for i in ings
            )
            if not has_hot:
                continue
            # Убираем молочку как по группе "dairy", так и по имени (творог может
            # быть в группе "protein" в каталоге, но в горячем блюде он неуместен).
            _DAIRY_MAIN_KW = ("творог", "йогурт", "биойогурт", "кефир", "ряженк", "сметан")
            kept = [ing for ing in ings
                    if (find_product(ing.get("product", ""), products) or {})
                    .get("group") != "dairy"
                    and not any(kw in ing.get("product", "").lower()
                                for kw in _DAIRY_MAIN_KW)]
            if kept:
                meal["ingredients"] = kept
    return plan


def diversify_across_days(plan: Dict, products: List[Dict],
                          daily_cal: float, prot_pct: float,
                          fat_pct: float, carb_pct: float,
                          variety: int) -> Dict:
    """Перестраивает блюда, в которых одни и те же углеводы/белок повторяются более 2× за неделю.

    Языковая модель склонна переиспользовать один продукт (напр., «Каша Фросток» каждый завтрак).
    Функция обнаруживает перегруженные основные ингредиенты по типу приёма пищи и заставляет
    построитель на основе кода генерировать свежие блюда для дней-переполнений.
    """
    for mtype in ("Завтрак", "Обед", "Ужин"):
        # Count how many days each primary carb / protein appears in this meal type
        usage: Dict[str, List[int]] = {}  # product_name → [day_indices]
        for day_idx, day in enumerate(plan.get("days", [])):
            for meal in day.get("meals", []):
                if meal.get("type") != mtype:
                    continue
                for ing in meal.get("ingredients", []):
                    p = find_product(ing["product"], products)
                    if p and p.get("group") in ("carbs", "protein"):
                        nm = p["name"]
                        usage.setdefault(nm, []).append(day_idx)
                        break  # first carb/protein is the primary

        max_repeats = 2
        for _, day_indices in usage.items():
            if len(day_indices) <= max_repeats:
                continue
            # Сохраняем первые max_repeats вхождений; остальные перестраиваем со сдвигом
            for rebuild_pos, day_idx in enumerate(day_indices[max_repeats:], start=max_repeats):
                day = plan["days"][day_idx]
                for meal in day.get("meals", []):
                    if meal.get("type") != mtype:
                        continue
                    new_ings = _build_meal_ingredients(
                        mtype, products, daily_cal, prot_pct, fat_pct, carb_pct,
                        day_idx=day_idx + rebuild_pos * 7,  # shift rotation slot
                        variety=variety
                    )
                    if new_ings:
                        meal["ingredients"] = new_ings
    return plan


def add_missing_meals(plan: Dict, products: List[Dict],
                      daily_cal: float, prot_pct: float,
                      fat_pct: float, carb_pct: float,
                      variety: int = 2, budget: float = 2000.0) -> Dict:
    """Добавляет Завтрак / Обед / Ужин (и Перекус при большом бюджете) для дней без этих приёмов."""
    add_snack = budget >= 5000
    for day_idx, day in enumerate(plan.get("days", [])):
        existing = {m.get("type") for m in day.get("meals", [])}
        for mtype in _MEAL_ORDER:
            if mtype == "Перекус" and not add_snack:
                continue
            if mtype not in existing:
                ings = _build_meal_ingredients(
                    mtype, products, daily_cal, prot_pct, fat_pct, carb_pct,
                    day_idx=day_idx, variety=variety
                )
                day.setdefault("meals", []).append({"type": mtype, "ingredients": ings})
        day["meals"].sort(
            key=lambda m: _MEAL_ORDER.index(m.get("type"))
            if m.get("type") in _MEAL_ORDER else len(_MEAL_ORDER)
        )
    return plan


_SAVORY_DAIRY_KW = ("сыр", "брынз", "плавл")

def fix_savory_dairy_with_fruits(plan: Dict, products: List[Dict]) -> Dict:
    """Убирает твёрдый сыр/брынзу из любого блюда, где есть фрукты.

    Йогурт, творог, кефир с фруктами — нормально. Сыр с апельсином/бананом — нет.
    Если после удаления сыра блюдо осталось непустым — оставляем его как есть.
    """
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            ings = meal.get("ingredients", [])
            has_fruit = any(
                (find_product(i.get("product", ""), products) or {}).get("group") == "fruits"
                for i in ings
            )
            if not has_fruit:
                continue
            cleaned = [
                i for i in ings
                if not any(kw in i.get("product", "").lower() for kw in _SAVORY_DAIRY_KW)
            ]
            if cleaned:
                meal["ingredients"] = cleaned
    return plan


def fix_compatibility(plan: Dict, products: List[Dict]) -> Dict:
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            ings = meal.get("ingredients", [])
            if not ings: continue
            has_savory = any(
                any(kw in i["product"].lower() for kw in SAVORY_MAIN_KW) for i in ings
            )
            if has_savory:
                ings = [i for i in ings
                        if not any(kw in i["product"].lower() for kw in SWEET_KW)]
            proteins = [i for i in ings
                        if (find_product(i["product"], products) or {}).get("group") == "protein"]
            if len(proteins) > 1:
                best = max(proteins, key=lambda i: float(i.get("grams", 0)))
                ings = [i for i in ings if i not in proteins or i is best]
            meal["ingredients"] = ings if ings else meal.get("ingredients", [])
    return plan


def apply_compatibility_matrix(plan: Dict, products: List[Dict]) -> Dict:
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            if meal_min_compat(meal.get("ingredients", []), products) < COMPAT_THRESHOLD:
                fix_incompatible_meal(meal, products)
    return plan


def rebuild_bad_meals(plan: Dict, products: List[Dict],
                      daily_cal: float, prot_pct: float,
                      fat_pct: float, carb_pct: float,
                      variety: int = 2) -> Dict:
    """Перестраивает только действительно пустые / нулевые по калориям блюда.

    НЕ запускается при отклонении макросов: распределение макросов одного приёма пищи
    всегда будет отклоняться от суточного целевого (завтрак — углеводный, ужин — белковый),
    поэтому проверки макросов по блюду заставляют запасной построитель перезаписывать каждое
    блюдо модели, оставляя только молоко и макароны.
    Коррекция макросов осуществляется через optimize_macros / fix_calories.
    """
    for day_idx, day in enumerate(plan.get("days", [])):
        for meal in day.get("meals", []):
            ings  = meal.get("ingredients", [])
            mtype = meal.get("type", "Обед")
            if not ings:
                rebuild = True
            else:
                nutr, _ = calc_nutrition(ings, products)
                rebuild = nutr["kcal"] < 50
            # Перестраиваем ужин/обед, где единственный «белок» — молочка (напр., творог+овощи).
            if not rebuild and mtype in ("Обед", "Ужин"):
                has_hot = any(
                    any(kw in (find_product(i.get("product",""), products) or {})
                        .get("name", "").lower() for kw in _HOT_PROT_KW)
                    for i in ings
                    if find_product(i.get("product",""), products)
                )
                if not has_hot:
                    rebuild = True
            # Перестраиваем завтрак, если нет нормальной КРУПЫ (не хлеб) И нет йогурта/творога/кефира.
            # Ряженка/сливы без крупы — не настоящий завтрак; творог без крупы — мало калорий.
            if not rebuild and mtype == "Завтрак" and ings:
                _PROPER_BFAST_DAIRY = ("йогурт", "творог", "кефир", "биойогурт")
                _PROPER_GRAIN_KW = ("гречк", "овсян", "рис ", "пшен", "мюсли",
                                    "хлопья", "булгур", "смесь", "крупа", "перловк")
                _BREAD_KW = ("хлеб", "батон", "хлебц")
                has_grain = any(
                    (find_product(i.get("product",""), products) or {}).get("group") == "carbs"
                    and any(kw in i.get("product","").lower() for kw in _PROPER_GRAIN_KW)
                    and not any(bk in i.get("product","").lower() for bk in _BREAD_KW)
                    for i in ings
                    if find_product(i.get("product",""), products)
                )
                has_proper_dairy = any(
                    any(kw in i.get("product","").lower() for kw in _PROPER_BFAST_DAIRY)
                    for i in ings
                )
                bfast_nutr, _ = calc_nutrition(ings, products)
                # Нет крупы и нет нормальной молочки → rebuild
                if not has_grain and not has_proper_dairy:
                    rebuild = True
                # Только творог без крупы и мало калорий → добавить кашу
                elif not has_grain and has_proper_dairy and bfast_nutr["kcal"] < daily_cal * 0.15:
                    rebuild = True
            if rebuild:
                meal["ingredients"] = _build_meal_ingredients(
                    mtype, products, daily_cal, prot_pct, fat_pct, carb_pct,
                    day_idx=day_idx, variety=variety
                )
    return plan


def strip_breakfast_forbidden(plan: Dict) -> Dict:
    """Финальная защитная сетка: убирает мясо/рыбу из всех завтраков.

    clean_plan запускается в начале конвейера; последующие шаги (diversify_across_days,
    rebuild_bad_meals и т.д.) могут повторно внести запрещённые ингредиенты через
    блюда, построенные кодом. Этот шаг выполняется перед расчётом порций для гарантии чистых завтраков.
    """
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            if meal.get("type") != "Завтрак":
                continue
            clean = [
                ing for ing in meal.get("ingredients", [])
                if not any(kw in ing.get("product", "").lower()
                           for kw in BREAKFAST_FORBIDDEN_KW)
            ]
            if clean:  # only apply if at least one non-forbidden ingredient remains
                meal["ingredients"] = clean
    return plan


def strip_pasta_from_breakfast(plan: Dict) -> Dict:
    """Убирает макароны/лапшу из завтраков — они могут просочиться через бюджетные шаги."""
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            if meal.get("type") != "Завтрак":
                continue
            clean = [
                ing for ing in meal.get("ingredients", [])
                if not any(kw in ing.get("product", "").lower() for kw in _PASTA_KW)
            ]
            if clean:
                meal["ingredients"] = clean
    return plan


def strip_snack_forbidden(plan: Dict) -> Dict:
    """Финальная защита: убирает масло, мясо и рыбу из перекусов.

    Запускается после всех бюджетных шагов, т.к. fill_budget_with_premium
    и inject_for_budget могут занести неуместные продукты в Перекус.
    К этому моменту имена ингредиентов уже канонизированы.
    """
    _BAD = BREAKFAST_FORBIDDEN_KW + ("масло",) + _SNACK_CARB_KW
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            if meal.get("type") != "Перекус":
                continue
            clean = [
                ing for ing in meal.get("ingredients", [])
                if not any(kw in ing.get("product", "").lower() for kw in _BAD)
            ]
            if clean:
                meal["ingredients"] = clean
    return plan


def fill_calories_with_carbs(plan: Dict, products: List[Dict],
                             daily_cal: float) -> Dict:
    """Добирает недостающие калории углеводами, чередуя дешёвые и дорогие.

    Запускается после balance_meal_portions и до scale_to_budget.
    Углеводы отсортированы по цене за 100 ккал; ротация по дням/приёмам
    гарантирует, что в плане будет MIX дешёвых (вермишель, гречка) и
    дорогих (булгур, паста). Это улучшает соотношение ккал/рубль до того,
    как scale_to_budget масштабирует план под бюджет.
    """
    eligible = [
        p for p in products
        if p.get("group") == "carbs"
        and float(p.get("kcal", 0) or 0) >= 80
        and not any(kw in p.get("name", "").lower() for kw in _PORRIDGE_KW)
    ]
    if not eligible:
        return plan

    def _cost_per_kcal(p: Dict) -> float:
        price_per_g = float(p.get("price", 999) or 999) / float(p.get("pack_g", 500) or 500)
        kcal_per_g  = max(float(p.get("kcal", 1) or 1) / 100.0, 0.01)
        return price_per_g / kcal_per_g

    # Сортируем: дешёвые по ккал — первые (ротация даст mix дешёвых + дорогих)
    carbs_ranked = sorted(eligible, key=_cost_per_kcal)
    cheap_carb_names = {c["name"] for c in carbs_ranked}

    for day_idx, day in enumerate(plan.get("days", [])):
        if _day_kcal(day, products) >= daily_cal * 0.97:
            continue  # день уже в норме

        for mi, meal in enumerate(day.get("meals", [])):
            if meal.get("type") not in ("Обед", "Ужин"):
                continue
            # Перепроверяем после каждого обеда/ужина — не перебрать лишнего
            if _day_kcal(day, products) >= daily_cal * 0.97:
                break
            ings = meal.get("ingredients", [])
            meal_names = {i["product"] for i in ings}

            # Ротация: Обед — чётный слот, Ужин — нечётный; вместе дают MIX
            chosen = carbs_ranked[(day_idx * 2 + mi) % len(carbs_ranked)]
            cap    = gram_cap(float(chosen.get("kcal", 350) or 350), "carbs")

            # Если ДЕШЁВЫЙ углевод уже есть — максимизируем его порцию.
            # Дорогие (Оладьи, Бифштекс с пюре) не трогаем — они урезаны
            # cap_product_weekly_packs и не должны возвращаться обратно.
            for ing in ings:
                p = find_product(ing.get("product", ""), products)
                if p and p.get("group") == "carbs" and p["name"] in cheap_carb_names:
                    if float(ing.get("grams", 0)) < cap:
                        _set_grams(ing, products, cap)
                    break
            else:
                # Дешёвых углеводов нет — добавляем выбранный
                if chosen["name"] not in meal_names:
                    ings.append({"product": chosen["name"], "grams": min(cap, 300)})
    return plan


def _day_kcal(day: Dict, products: List[Dict]) -> float:
    return sum(
        float((find_product(i["product"], products) or {}).get("kcal", 0) or 0)
        * float(i.get("grams", 100)) / 100.0
        for m in day.get("meals", [])
        for i in m.get("ingredients", [])
    )


def _cost_per_100kcal(p: Dict) -> float:
    pg = float(p.get("pack_g", 500) or 500)
    pr = float(p.get("price", 999) or 999)
    kc = float(p.get("kcal", 1) or 1)
    return pr / pg * 100 / max(kc, 1)


def ensure_daily_calories(plan: Dict, products: List[Dict],
                           daily_cal: float, budget: float) -> Dict:
    """Финальная гарантия: каждый день набирает норму калорий.

    Алгоритм:
    1. Для каждого дня с дефицитом > 8% — максимизирует порции дешёвых углеводов
       (вермишель, гречка) в обеде и ужине, чередуя их между днями.
    2. Если после этого бюджет превышен — срезает самый дорогой по р/100ккал продукт
       (на 1 пачку), НЕ трогая дешёвые углеводы.
    Запускается последней — после trim_to_budget и снековых шагов.
    """
    cheap_carbs = sorted(
        [p for p in products
         if p.get("group") == "carbs"
         and float(p.get("kcal", 0) or 0) >= 80
         and not any(kw in p.get("name", "").lower() for kw in _PORRIDGE_KW)],
        key=_cost_per_100kcal
    )
    # Зерновые крупы — для добора калорий в Завтраке (паста и хлебобулочные неуместны)
    bfast_carbs = sorted(
        [p for p in products
         if p.get("group") == "carbs"
         and float(p.get("kcal", 0) or 0) >= 80
         and any(kw in p.get("name", "").lower() for kw in _PORRIDGE_KW)],
        key=_cost_per_100kcal
    )
    if not cheap_carbs and not bfast_carbs:
        return plan
    cheap_names = {c["name"] for c in cheap_carbs} | {c["name"] for c in bfast_carbs}

    # Запоминаем, какие дни были в дефиците ДО добавления углеводов,
    # чтобы защитить их в шаге 2 от урезания.
    deficit_days = {i for i, d in enumerate(plan.get("days", []))
                    if _day_kcal(d, products) < daily_cal * 0.97}
    # Когда ВСЕ дни в дефиците, нельзя пропускать их в шаге 2 — иначе дорогие
    # товары не срезаются и бюджет не освобождается для дешёвых углеводов.
    all_days_deficit = bool(deficit_days) and (
        len(deficit_days) == len(plan.get("days", []))
    )

    # ── Шаг 1: добираем калории дешёвыми углеводами ───────────────────────────
    for day_idx, day in enumerate(plan.get("days", [])):
        if _day_kcal(day, products) >= daily_cal * 0.97:
            continue
        for mi, meal in enumerate(day.get("meals", [])):
            mtype = meal.get("type", "")
            if mtype not in ("Обед", "Ужин", "Завтрак"):
                continue
            if _day_kcal(day, products) >= daily_cal * 0.97:
                break
            ings = meal.get("ingredients", [])
            # Завтрак — только крупы (хлопья, овсянка, гречка); обед/ужин — некрупяные углеводы
            if mtype == "Завтрак":
                if not bfast_carbs:
                    continue
                chosen = bfast_carbs[day_idx % len(bfast_carbs)]
            else:
                if not cheap_carbs:
                    continue
                chosen = cheap_carbs[(day_idx * 2 + mi) % len(cheap_carbs)]
            cap_g  = gram_cap(float(chosen.get("kcal", 350) or 350), "carbs")

            boosted = False
            for ing in ings:
                p = find_product(ing.get("product", ""), products)
                # Бустим только ДЕШЁВЫЕ углеводы (включая крупы для завтрака).
                if p and p.get("group") == "carbs" and p["name"] in cheap_names:
                    cur_g = float(ing.get("grams", 0))
                    if cur_g < cap_g:
                        _set_grams(ing, products, cap_g)
                        boosted = True
                    break
            if not boosted:
                if chosen["name"] not in {i["product"] for i in ings}:
                    ings.append({"product": chosen["name"], "grams": cap_g})

    # ── Шаг 2: бюджет превышен → срезаем дорогие из дней с нормальными калориями ─
    # Дни, изначально бывшие в дефиците, обычно исключаем из урезания, чтобы не
    # срезать только что добавленные углеводы. НО: когда ВСЕ дни в дефиците
    # (all_days_deficit), исключения нет — иначе дорогие товары (десерты, деликатесы)
    # не срезаются и бюджет не освобождается. Дешёвые углеводы защищены через cheap_names.
    for _ in range(30):
        cost = shopping_cost(plan, products)
        if cost <= budget:
            break

        usage: Dict[str, Tuple[float, float]] = {}
        for di, day2 in enumerate(plan.get("days", [])):
            if di in deficit_days and not all_days_deficit:
                continue  # не учитываем дефицитные дни (только если есть не-дефицитные)
            for meal2 in day2.get("meals", []):
                for ing2 in meal2.get("ingredients", []):
                    p2 = find_product(ing2.get("product", ""), products)
                    if not p2 or p2["name"] in cheap_names:
                        continue
                    nm = p2["name"]
                    pg = float(p2.get("pack_g", 500) or 500)
                    g0 = usage[nm][0] if nm in usage else 0.0
                    usage[nm] = (g0 + float(ing2.get("grams", 100)), pg)

        if not usage:
            break

        # Ищем самый дорогой по р/100ккал продукт с > 1 пачки
        expensive = [
            (_cost_per_100kcal(
                next((x for x in products if x["name"] == nm), {})),
             nm, g, pg)
            for nm, (g, pg) in usage.items()
            if math.ceil(g / pg) > 1
        ]
        if expensive:
            expensive.sort(reverse=True)
            _, best_nm, best_g, best_pg = expensive[0]
            cur_packs = math.ceil(best_g / best_pg)
            target_g  = (cur_packs - 1) * best_pg * 0.97
            if target_g <= 0:
                break
            scale = target_g / max(best_g, 1.0)
        else:
            # Всё по 1 пачке — масштабируем самый дорогой до вписывания в бюджет
            top = sorted(usage.keys(),
                         key=lambda n: _cost_per_100kcal(
                             next((p for p in products if p["name"] == n), {})),
                         reverse=True)
            if not top:
                break
            best_nm = top[0]
            scale   = budget / max(cost, 1)
            target_g = None  # сигнал: использовать scale напрямую

        for di, day2 in enumerate(plan.get("days", [])):
            if di in deficit_days and not all_days_deficit:
                continue  # не урезаем дефицитные дни (только если есть не-дефицитные)
            for meal2 in day2.get("meals", []):
                for ing2 in meal2.get("ingredients", []):
                    p2 = find_product(ing2.get("product", ""), products)
                    if p2 and p2["name"] == best_nm:
                        ing2["grams"] = max(1, round(float(ing2.get("grams", 100)) * scale))
        if target_g is None:
            break  # пропорциональное масштабирование сделано за 1 раз

    return plan


def rebalance_daily_calories(plan: Dict, products: List[Dict],
                             daily_cal: float) -> Dict:
    """Выравнивает суточные калории, перераспределяя порции между днями.

    Принцип: дни с профицитом (>5%) уступают часть своих углеводных и
    белковых порций дням с дефицитом (<92%). Суммарные граммы по каждому
    продукту за неделю не меняются — список покупок и бюджет остаются прежними.
    За 1 итерацию передаётся до 40% разности; цикл до 15 раз.
    """
    TARGET_LO = daily_cal * 0.975
    TARGET_HI = daily_cal * 1.005
    days = plan.get("days", [])

    for _ in range(40):
        day_kcals    = [_day_kcal(d, products) for d in days]
        deficit_list = [(i, daily_cal - k) for i, k in enumerate(day_kcals)
                        if k < TARGET_LO]
        surplus_list = [(i, k - daily_cal)  for i, k in enumerate(day_kcals)
                        if k > TARGET_HI]

        if not deficit_list or not surplus_list:
            break

        moved_any = False

        for rec_idx, rec_def in deficit_list:
            if rec_def <= 50:
                continue
            rec_day = days[rec_idx]

            for don_idx, don_sur in surplus_list:
                if don_sur <= 50:
                    continue
                don_day  = days[don_idx]
                transfer = min(rec_def * 0.80, don_sur * 0.80)

                for don_meal in don_day.get("meals", []):
                    mtype = don_meal.get("type", "")
                    if mtype not in ("Обед", "Ужин"):
                        continue
                    rec_meal = next(
                        (m for m in rec_day.get("meals", [])
                         if m.get("type") == mtype), None
                    )
                    if rec_meal is None:
                        continue

                    for ing in list(don_meal.get("ingredients", [])):
                        p = find_product(ing.get("product", ""), products)
                        if not p or p.get("group") not in ("carbs", "protein", "other"):
                            continue
                        kcal_pg  = float(p.get("kcal", 100) or 100) / 100.0
                        cur_g    = float(ing.get("grams", 0))
                        move_g   = round(min((cur_g - 30) * 0.5,
                                             transfer / max(kcal_pg, 0.1)))
                        if move_g < 1:
                            continue

                        # Снимаем у донора
                        ing["grams"] = max(1, round(cur_g - move_g))

                        # Добавляем реципиенту
                        rec_ings = rec_meal.get("ingredients", [])
                        matched  = False
                        for r_ing in rec_ings:
                            rp = find_product(r_ing.get("product", ""), products)
                            if rp and rp["name"] == p["name"]:
                                r_ing["grams"] = round(
                                    float(r_ing.get("grams", 0)) + move_g)
                                matched = True
                                break
                        if not matched:
                            rec_ings.append({"product": p["name"],
                                             "grams": move_g})

                        moved_kcal  = move_g * kcal_pg
                        transfer   -= moved_kcal
                        rec_def    -= moved_kcal
                        don_sur    -= moved_kcal
                        moved_any   = True

                        if transfer <= 50 or rec_def <= 50 or don_sur <= 50:
                            break
                    if rec_def <= 50:
                        break
                if rec_def <= 50:
                    break

        if not moved_any:
            break

    return plan


def rebuild_veggie_only_snacks(plan: Dict, products: List[Dict],
                               daily_cal: float, prot_pct: float,
                               fat_pct: float, carb_pct: float,
                               variety: int) -> Dict:
    """Перестраивает перекусы, состоящие только из овощей/фруктов.

    Перекус из одной брокколи или мандаринов (< 100 ккал) не имеет
    питательной ценности. Перестраиваем его с нуля через стандартный
    снек-билдер, который попытается добавить молочку или более сытный фрукт.
    """
    snack_min_kcal = max(50.0, daily_cal * _MEAL_FRAC.get("Перекус", 0.10) * 0.3)
    for day_idx, day in enumerate(plan.get("days", [])):
        for meal in day.get("meals", []):
            if meal.get("type") != "Перекус":
                continue
            ings = meal.get("ingredients", [])
            nutr, _ = calc_nutrition(ings, products)
            all_veggie = all(
                (find_product(i.get("product", ""), products) or {}).get("group")
                in ("veggies", "fruits", None)
                for i in ings
            ) if ings else True
            # Одиночная молочка без фруктов — не полноценный перекус:
            # стакан молока или кусок сыра сам по себе неуместен как снек.
            is_lone_dairy = (
                len(ings) == 1 and
                (find_product(ings[0].get("product", ""), products) or {}).get("group") == "dairy"
            )
            if all_veggie or is_lone_dairy or nutr["kcal"] < snack_min_kcal:
                new_ings = _build_meal_ingredients(
                    "Перекус", products, daily_cal,
                    prot_pct, fat_pct, carb_pct,
                    day_idx=day_idx, variety=variety
                )
                if new_ings:
                    meal["ingredients"] = new_ings
    return plan


def dedup_per_meal(plan: Dict, products: List[Dict]) -> Dict:
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            seen: Dict[str, int] = {}
            result: List[Dict] = []
            for ing in meal.get("ingredients", []):
                p  = find_product(ing.get("product", ""), products)
                tk = type_key(p) if p else ing.get("product", "").lower()
                if tk not in seen:
                    seen[tk] = len(result)
                    result.append(ing)
                elif float(ing.get("grams", 0)) > float(result[seen[tk]].get("grams", 0)):
                    result[seen[tk]] = ing
            meal["ingredients"] = result
    return plan


def normalize_varieties(plan: Dict, products: List[Dict], variety: int = 2) -> Dict:
    """Сворачивает разнообразие типов продуктов до запрошенного уровня разнообразия.

    variety=1  один продукт каждого типа на всю неделю
    variety=2  до двух продуктов каждого типа: первая/вторая половина
    variety=3  сохраняет выбор модели — только разрешает названия в каталоге
    """
    days = plan.get("days", [])
    if variety >= 3:
        for day in days:
            for meal in day.get("meals", []):
                for ing in meal.get("ingredients", []):
                    p = find_product(ing.get("product", ""), products)
                    if p: ing["product"] = p["name"]
        return plan

    n_blocks   = 1 if variety <= 1 else 2
    block_size = max(1, math.ceil(len(days) / n_blocks))
    for b in range(n_blocks):
        block = days[b * block_size: (b + 1) * block_size]
        if not block: continue
        usage: Dict[str, Dict[str, float]] = {}
        for day in block:
            for meal in day.get("meals", []):
                for ing in meal.get("ingredients", []):
                    p = find_product(ing.get("product", ""), products)
                    if not p: continue
                    tk = type_key(p)
                    usage.setdefault(tk, {})
                    usage[tk][p["name"]] = usage[tk].get(p["name"], 0.0) + float(ing.get("grams", 0))
        repl: Dict[str, str] = {}
        for tk, names in usage.items():
            if len(names) <= 1: continue
            canonical = max(names, key=lambda n: names[n])
            for nm in names:
                if nm != canonical: repl[nm] = canonical
        for day in block:
            for meal in day.get("meals", []):
                for ing in meal.get("ingredients", []):
                    if ing.get("product") in repl:
                        ing["product"] = repl[ing["product"]]
    return plan


def ensure_meal_complete(plan: Dict, products: List[Dict], daily_cal: float) -> Dict:
    meal_cal = daily_cal / 3.0
    by_group: Dict[str, List[Dict]] = {}
    for p in products:
        by_group.setdefault(p.get("group", "other"), []).append(p)

    _emc_cands = [p for grp in ("protein", "other") for p in by_group.get(grp, [])]
    real_proteins = sorted(
        [p for p in _emc_cands if _is_real_protein(p)],
        key=lambda p: -float(p.get("price", 0) or 0)  # сначала дорогие
    ) or sorted(_emc_cands, key=lambda p: -float(p.get("price", 0) or 0))

    def cheapest(group: str) -> Optional[Dict]:
        if group == "protein" and real_proteins:
            return real_proteins[0]
        cands = sorted(by_group.get(group, []), key=lambda p: float(p.get("price", 9999)))
        return cands[0] if cands else None

    def add_ingredient(ings: List[Dict], p: Dict, fraction: float) -> None:
        vk  = float(p.get("kcal", 200) or 200)
        grp = p.get("group", "other")
        g   = max(50, min(gram_cap(vk, grp), round(meal_cal * fraction * 100 / vk)))
        ings.append({"product": p["name"], "grams": g})

    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            ings   = meal.get("ingredients", [])
            groups = {(find_product(i["product"], products) or {}).get("group", "other")
                      for i in ings}
            mtype  = meal.get("type", "")
            if mtype == "Завтрак":
                if not groups & {"carbs", "dairy", "fruits"}:
                    p = cheapest("carbs") or cheapest("dairy")
                    if p: add_ingredient(ings, p, 0.6)
            elif mtype in ("Обед", "Ужин"):
                # Требуется «горячий» белок (мясо/рыба/яйца).
                # Творог относится к группе "protein", но НЕ должен быть единственным
                # белком в горячем блюде (творог+овощи — не нормальный обед/ужин).
                has_hot = any(
                    any(kw in (find_product(i["product"], products) or {}).get("name", "").lower()
                        for kw in _HOT_PROT_KW)
                    for i in ings
                )
                if not has_hot and real_proteins:
                    add_ingredient(ings, real_proteins[0], 0.5)
                    groups.add("protein")
                if mtype in ("Обед", "Ужин") and "carbs" not in groups:
                    p = cheapest("carbs")
                    if p: add_ingredient(ings, p, 0.4)
    return plan


def add_veggie_sides(plan: Dict, products: List[Dict], daily_cal: float) -> Dict:
    veggies = sorted(
        [p for p in products
         if p.get("group") in ("veggies", "fruits")
         and not any(kw in p["name"].lower() for kw in NONFOOD_KW)],
        key=lambda p: float(p.get("price", 0))
    )
    if not veggies: return plan
    vi = 0
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            if meal.get("type") in ("Завтрак", "Перекус"): continue
            ings = meal["ingredients"]
            if len(ings) >= 3: continue
            existing = {type_key(find_product(i["product"], products))
                        for i in ings if find_product(i["product"], products)}
            for offset in range(len(veggies)):
                cand = veggies[(vi + offset) % len(veggies)]
                if type_key(cand) in existing: continue
                meal_kcal = sum(
                    float((find_product(i["product"], products) or {}).get("kcal", 0) or 0)
                    * float(i.get("grams", 100)) / 100.0 for i in ings
                )
                headroom = daily_cal / 3.0 - meal_kcal
                if headroom > 20:
                    vk    = float(cand.get("kcal", 30) or 30)
                    grams = min(250, max(80, round(headroom * 0.35 * 100 / vk)))
                    ings.append({"product": cand["name"], "grams": grams})
                vi = (vi + offset + 1) % len(veggies)
                break
    return plan


def _set_grams(ing: Dict, products: List[Dict], new_g: float) -> None:
    p      = find_product(ing.get("product", ""), products)
    kcal_d = float(p.get("kcal", 100) or 100) if p else 100.0
    grp    = p.get("group", "other")            if p else "other"
    ing["grams"] = max(30, min(gram_cap(kcal_d, grp), round(new_g)))


def optimize_macros(plan: Dict, products: List[Dict],
                    prot_pct: float, fat_pct: float, carb_pct: float) -> Dict:
    """Корректирует порции ингредиентов в каждом блюде для устранения отклонений макросов в диапазоне 10–30%."""
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            ings = meal.get("ingredients", [])
            if not ings: continue
            nutr, _ = calc_nutrition(ings, products)
            if nutr["kcal"] < 50: continue
            errors = check_macro_errors(nutr, prot_pct, fat_pct, carb_pct)
            if max(errors.values()) <= 10: continue

            cal      = nutr["kcal"] or 1
            actual_p = nutr["prot"] * 4 / cal * 100
            actual_f = nutr["fat"]  * 9 / cal * 100
            actual_c = nutr["carb"] * 4 / cal * 100

            for ing in ings:
                p   = find_product(ing.get("product", ""), products)
                grp = (p or {}).get("group", "other")
                g   = float(ing.get("grams", 100))
                if errors["prot"] > 10 and actual_p < prot_pct and grp == "protein":
                    _set_grams(ing, products, g * 1.25)
                elif errors["carb"] > 10 and actual_c < carb_pct and grp == "carbs":
                    _set_grams(ing, products, g * 1.20)
                elif errors["fat"] > 10 and actual_f > fat_pct and grp in ("fats", "dairy"):
                    _set_grams(ing, products, g * 0.75)
    return plan


def fix_calories(plan: Dict, products: List[Dict], daily_cal: float) -> Dict:
    # Многократный проход: при большом дефиците (< 50% нормы) одного прохода с
    # SCALE_MAX=2.0 недостаточно. Повторяем до 5 раз — каждый раз приближаемся к цели.
    for _ in range(5):
        any_scaled = False
        for day in plan.get("days", []):
            day_kcal = sum(
                float((find_product(ing["product"], products) or {}).get("kcal", 0) or 0)
                * float(ing.get("grams", 100)) / 100.0
                for meal in day.get("meals", [])
                for ing in meal.get("ingredients", [])
            )
            if day_kcal <= 0: continue
            scale = max(SCALE_MIN, min(SCALE_MAX, daily_cal / day_kcal))
            if abs(scale - 1.0) < 0.05: continue
            any_scaled = True
            for meal in day.get("meals", []):
                for ing in meal.get("ingredients", []):
                    _set_grams(ing, products, float(ing.get("grams", 100)) * scale)
        if not any_scaled:
            break
    return plan


def clamp_to_daily_ceiling(plan: Dict, products: List[Dict], daily_cal: float) -> Dict:
    """Масштабирует вниз дни, превышающие 1.10× дневную норму калорий.

    Вызывается после всех бюджетных шагов, чтобы финальный вывод соблюдал норму калорий
    даже после выполнения swap_cheap_for_premium и inject_for_budget. Зажимает только
    дни выше порога — сбалансированные дни не трогает.
    """
    ceiling = daily_cal * 1.10
    for day in plan.get("days", []):
        day_kcal = sum(
            float((find_product(ing["product"], products) or {}).get("kcal", 0) or 0)
            * float(ing.get("grams", 100)) / 100.0
            for meal in day.get("meals", [])
            for ing in meal.get("ingredients", [])
        )
        if day_kcal <= ceiling:
            continue
        scale = ceiling / day_kcal
        for meal in day.get("meals", []):
            for ing in meal.get("ingredients", []):
                _set_grams(ing, products, float(ing.get("grams", 100)) * scale)
    return plan


def _kcal_ceiling_factor() -> float:
    """Фиксированный потолок калорий 1.10×.

    Дополнительный бюджет должен идти на более дорогие продукты, а не на больше еды.
    Буфер 10% выше суточной нормы покрывает округление порций без заметного превышения калорий.
    """
    return 1.10


def scale_to_budget(plan: Dict, products: List[Dict], budget: float,
                    daily_cal: float = 0.0) -> Dict:
    n_days       = max(len(plan.get("days", [])), 1)
    _cf          = _kcal_ceiling_factor()
    kcal_ceiling = daily_cal * n_days * _cf if daily_cal > 0 else 0.0
    prev_cost    = None
    for _ in range(40):
        cost = shopping_cost(plan, products)
        if cost <= 0: break
        if abs(cost - budget) / budget < 0.01: break
        if prev_cost is not None and abs(cost - prev_cost) < 1.0: break
        ratio = budget / cost
        if ratio > 1.0 and kcal_ceiling > 0:
            cur_kcal = sum(
                float((find_product(ing["product"], products) or {}).get("kcal", 0) or 0)
                * float(ing.get("grams", 100)) / 100.0
                for day in plan.get("days", [])
                for meal in day.get("meals", [])
                for ing in meal.get("ingredients", [])
            )
            if cur_kcal > 0: ratio = min(ratio, kcal_ceiling / cur_kcal)
        scale = max(SCALE_MIN, min(SCALE_MAX, ratio))
        if abs(scale - 1.0) < 0.005: break
        for day in plan.get("days", []):
            for meal in day.get("meals", []):
                for ing in meal.get("ingredients", []):
                    _set_grams(ing, products, float(ing.get("grams", 100)) * scale)
        prev_cost = cost
    return plan


def inject_for_budget(plan: Dict, products: List[Dict],
                      budget: float, daily_cal: float) -> Dict:
    """Увеличивает порции самого дорогого ингредиента в блюде, когда расход бюджета < 88%.

    scale_to_budget останавливается, когда достигнут калорийный потолок, а бюджет
    ещё не израсходован. Эта функция добавляет плоский прирост 20 г к самому дорогому
    ингредиенту в каждом блюде за итерацию, пока план не достигнет 90% бюджета
    или жёсткого калорийного ограничения.
    """
    cost = shopping_cost(plan, products)
    if cost <= 0 or cost >= budget * 0.88:
        return plan

    n_days        = max(len(plan.get("days", [])), 1)
    _cf           = _kcal_ceiling_factor()
    kcal_hard_cap = daily_cal * n_days * _cf

    def _total_kcal() -> float:
        return sum(
            float((find_product(ing["product"], products) or {}).get("kcal", 0) or 0)
            * float(ing.get("grams", 100)) / 100.0
            for day in plan.get("days", [])
            for meal in day.get("meals", [])
            for ing in meal.get("ingredients", [])
        )

    for _ in range(30):
        if shopping_cost(plan, products) >= budget * 0.90:
            break
        if kcal_hard_cap > 0 and _total_kcal() >= kcal_hard_cap:
            break
        any_boost = False
        for day in plan.get("days", []):
            for meal in day.get("meals", []):
                mtype = meal.get("type", "")
                if mtype == "Перекус":
                    continue
                meal_target = daily_cal * _MEAL_FRAC.get(mtype, 0.35)
                cur_meal_kcal = sum(
                    float((find_product(ing.get("product", ""), products) or {}).get("kcal", 0) or 0)
                    * float(ing.get("grams", 100)) / 100.0
                    for ing in meal.get("ingredients", [])
                )
                if meal_target > 0 and cur_meal_kcal >= meal_target * 1.12:
                    continue
                best_ing, best_price = None, 0.0
                for ing in meal.get("ingredients", []):
                    p = find_product(ing.get("product", ""), products)
                    if p:
                        pr = float(p.get("price", 0) or 0)
                        if pr > best_price:
                            best_price, best_ing = pr, ing
                if best_ing is None or best_price < 50:
                    continue
                _set_grams(best_ing, products,
                           float(best_ing.get("grams", 100)) + 20)
                any_boost = True
        if not any_boost:
            break
    return plan


def swap_cheap_for_premium(plan: Dict, products: List[Dict],
                           budget: float) -> Dict:
    """Повышает использование бюджета без добавления калорий.

    Обед/ужин: уменьшает граммы дешёвых углеводов на 40% и добавляет дорогой белок
    в эквивалентных по калориям граммах, чтобы итоговые калории блюда не изменились.
    Завтрак: заменяет дешёвые углеводы на самый дорогой углевод той же группы
    (мясо/рыба на завтрак не добавляются).
    Запускается, когда расход ниже 95% бюджета.
    """
    cost = shopping_cost(plan, products)
    if cost >= budget * 0.95:
        return plan

    cheap_price_cap = 80.0 if budget < 3000 else 100.0 if budget < 5000 else 130.0

    exp_prots = sorted(
        [p for p in products
         if float(p.get("price", 0) or 0) > 100 and _is_real_protein(p)],
        key=lambda p: float(p.get("price", 0) or 0), reverse=True
    )

    # Бюджет-пропорциональный лимит: чем больше бюджет, тем чаще разрешён дорогой белок.
    # Потолок — 7 (не более 1 раза в день); минимум — 3 (каждые ~2 дня).
    # Функция уже ротирует белки по принципу «сначала наименее используемый»,
    # поэтому несколько белков распределяются равномерно автоматически.
    max_uses_per_prot = max(3, min(7, round(budget / 1000)))

    # Премиальные углеводы (для апгрейда завтрака): сортировка по убыванию цены
    exp_carbs = sorted(
        [p for p in products if p.get("group") == "carbs"],
        key=lambda p: -float(p.get("price", 0) or 0)
    )

    for _ in range(80):
        if shopping_cost(plan, products) >= budget * 0.95:
            break
        prot_usage: Dict[str, int] = {p["name"]: 0 for p in exp_prots}
        for d2 in plan.get("days", []):
            for m2 in d2.get("meals", []):
                for i2 in m2.get("ingredients", []):
                    if i2["product"] in prot_usage:
                        prot_usage[i2["product"]] += 1

        for day in plan.get("days", []):
            for meal in day.get("meals", []):
                mtype = meal.get("type", "")
                if mtype == "Перекус":
                    continue

                meal_names = {i["product"] for i in meal["ingredients"]}

                if mtype == "Завтрак":
                    # Апгрейд завтрака: заменяем самый дешёвый углевод на самый дорогой
                    cheap_carb_ing = None
                    for ing in meal["ingredients"]:
                        p = find_product(ing["product"], products)
                        if p and p.get("group") == "carbs":
                            pr = float(p.get("price", 0) or 0)
                            if pr <= cheap_price_cap:
                                cheap_carb_ing = cheap_carb_ing or (ing, p)
                    if cheap_carb_ing is None:
                        continue
                    ing, cheap_p = cheap_carb_ing
                    # На завтрак апгрейдим только крупами — макаронам здесь не место
                    pricier = [p for p in exp_carbs
                               if p["name"] not in meal_names
                               and float(p.get("price", 0) or 0) > float(cheap_p.get("price", 0) or 0) * 1.5
                               and not any(kw in p.get("name", "").lower() for kw in _PASTA_KW)]
                    if not pricier:
                        continue
                    new_c = pricier[0]
                    old_g   = float(ing.get("grams", 100))
                    old_kcal = float(cheap_p.get("kcal", 330) or 330) / 100 * old_g
                    new_kcal_pg = float(new_c.get("kcal", 330) or 330) / 100
                    new_g = max(50, min(gram_cap(float(new_c.get("kcal", 100) or 100), "carbs"),
                                       round(old_kcal / max(new_kcal_pg, 0.5))))
                    ing["product"] = new_c["name"]
                    ing["grams"]   = new_g
                    continue

                # Обед / Ужин: меняем дешёвый углевод → дорогой белок
                cheap_carb_ing = None
                for ing in meal["ingredients"]:
                    p = find_product(ing["product"], products)
                    if p and p.get("group") == "carbs":
                        if float(p.get("price", 0) or 0) <= cheap_price_cap:
                            cheap_carb_ing = cheap_carb_ing or (ing, p)
                if cheap_carb_ing is None:
                    continue
                if not exp_prots:
                    continue
                available = sorted(
                    [p for p in exp_prots
                     if p["name"] not in meal_names
                     and prot_usage.get(p["name"], 0) < max_uses_per_prot],
                    key=lambda p: prot_usage.get(p["name"], 0)
                )
                if not available:
                    # Нет альтернативного белка — делаем калорийно-нейтральный обмен:
                    # срезаем дешёвый углевод → добавляем граммы дорогого белка,
                    # который уже есть в блюде. Стоимость растёт, калории не меняются.
                    if cheap_carb_ing is not None:
                        carb_ing_obj, cheap_p_obj = cheap_carb_ing
                        old_carb_g = float(carb_ing_obj.get("grams", 100))
                        cut_g = round(old_carb_g * 0.25)
                        if cut_g >= 10 and old_carb_g - cut_g >= 50:
                            saved_kcal = cut_g * float(cheap_p_obj.get("kcal", 330) or 330) / 100
                            carb_ing_obj["grams"] = max(50, round(old_carb_g - cut_g))
                            best_ing2, best_pr2 = None, 100.0
                            for ing2 in meal["ingredients"]:
                                p2 = find_product(ing2.get("product", ""), products)
                                if p2 and _is_real_protein(p2):
                                    pr2 = float(p2.get("price", 0) or 0)
                                    if pr2 > best_pr2:
                                        best_pr2, best_ing2 = pr2, ing2
                            if best_ing2 is not None:
                                p_obj = find_product(best_ing2.get("product", ""), products)
                                prot_kcal_g = float((p_obj or {}).get("kcal", 150) or 150) / 100
                                add_g = round(saved_kcal / max(prot_kcal_g, 0.5))
                                _set_grams(best_ing2, products,
                                           float(best_ing2.get("grams", 100)) + add_g)
                    continue
                new_prot = available[0]
                ing, cheap_p = cheap_carb_ing
                old_g = float(ing.get("grams", 100))
                cut_g = old_g * 0.40
                saved_kcal = cut_g * float(cheap_p.get("kcal", 350) or 350) / 100
                ing["grams"] = max(50, round(old_g - cut_g))
                prot_kcal_g = float(new_prot.get("kcal", 150) or 150) / 100
                new_g = max(50, round(saved_kcal / max(prot_kcal_g, 0.5)))
                meal["ingredients"].append({"product": new_prot["name"], "grams": new_g})
                prot_usage[new_prot["name"]] = prot_usage.get(new_prot["name"], 0) + 1
    return plan


def balance_meal_portions(plan: Dict, products: List[Dict], daily_cal: float) -> Dict:
    """Масштабирует ингредиенты в каждом приёме пищи, чтобы попасть в целевую долю калорий.

    Завтрак → 25%, Обед → 40%, Ужин → 35%.
    Перекус пропускается — это инструмент расхода бюджета, не калорийный приём.
    """
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            mtype = meal.get("type", "")
            if mtype not in _MEAL_FRAC or mtype == "Перекус":
                continue
            ings = meal.get("ingredients", [])
            if not ings:
                continue
            target_kcal = daily_cal * _MEAL_FRAC[mtype]
            cur_kcal = sum(
                float((find_product(i["product"], products) or {}).get("kcal", 0) or 0)
                * float(i.get("grams", 100)) / 100.0
                for i in ings
            )
            if cur_kcal < 10:
                continue
            scale = max(SCALE_MIN, min(SCALE_MAX, target_kcal / cur_kcal))
            if abs(scale - 1.0) < 0.03:
                continue
            for ing in ings:
                _set_grams(ing, products, float(ing.get("grams", 100)) * scale)
    return plan


# ── Code-based portion calculation ────────────────────────────────────────────

def code_set_portions(plan: Dict, products: List[Dict],
                      daily_cal: float, prot_pct: float, carb_pct: float) -> Dict:
    """Заменяет граммы от языковой модели оптимальными порциями, рассчитанными кодом.

    Языковая модель ненадёжна в арифметике — она выбирает КАКИЕ продукты сочетать
    (состав блюда), тогда как код вычисляет СКОЛЬКО каждого продукта нужно для точного
    попадания в калорийную и макронутриентную цель приёма пищи.

    Стратегия по роли ингредиента:
      protein  → граммы, достаточные для доли белка приёма пищи
      carbs    → граммы, достаточные для доли углеводов приёма пищи
      veggies  → фиксированный ~100 ккал гарнир
      other    → заполняет оставшийся калорийный разрыв
    """
    for day_data in plan.get("days", []):
        for meal in day_data.get("meals", []):
            mtype     = meal.get("type", "")
            meal_kcal = daily_cal * _MEAL_FRAC.get(mtype, 1 / 3)
            tgt_prot  = meal_kcal * prot_pct / 100 / 4   # target protein g
            tgt_carb  = meal_kcal * carb_pct / 100 / 4   # target carb g

            ings = meal.get("ingredients", [])
            resolved = [(ing, find_product(ing.get("product", ""), products))
                        for ing in ings]
            resolved = [(ing, p) for ing, p in resolved if p]
            if not resolved:
                continue

            prot_ings: list = []
            carb_ings: list = []
            veg_ings:  list = []
            other_ings: list = []
            for ing, p in resolved:
                grp = p.get("group", "other")
                if _is_real_protein(p) or grp == "protein":
                    prot_ings.append((ing, p))
                elif grp == "carbs":
                    carb_ings.append((ing, p))
                elif grp in ("veggies", "fruits"):
                    veg_ings.append((ing, p))
                else:
                    other_ings.append((ing, p))

            def _sg(ing: Dict, p: Dict, target_g: float) -> None:
                kcal_d = float(p.get("kcal", 100) or 100)
                grp    = p.get("group", "other")
                ing["grams"] = max(30, min(gram_cap(kcal_d, grp), round(target_g)))

            # Белковые источники: делим целевой белок поровну
            for ing, p in prot_ings:
                prot_pg = float(p.get("prot", 0) or 0) / 100
                share   = 1.0 / max(len(prot_ings), 1)
                if prot_pg > 0.005:
                    _sg(ing, p, tgt_prot * share / prot_pg)
                else:
                    kcal_pg = float(p.get("kcal", 100) or 100) / 100
                    _sg(ing, p, meal_kcal * 0.25 * share / max(kcal_pg, 0.1))

            # Углеводные источники: делим целевые углеводы поровну
            for ing, p in carb_ings:
                carb_pg = float(p.get("carb", 0) or 0) / 100
                share   = 1.0 / max(len(carb_ings), 1)
                if carb_pg > 0.005:
                    _sg(ing, p, tgt_carb * share / carb_pg)
                else:
                    kcal_pg = float(p.get("kcal", 100) or 100) / 100
                    _sg(ing, p, meal_kcal * 0.35 * share / max(kcal_pg, 0.1))

            # Овощи: фиксированный гарнир ~100 ккал
            for ing, p in veg_ings:
                kcal_pg = float(p.get("kcal", 30) or 30) / 100
                _sg(ing, p, 100.0 / max(kcal_pg, 0.1))

            # Прочие продукты: заполняем оставшийся калорийный разрыв поровну
            if other_ings:
                used = sum(
                    float(p.get("kcal", 0) or 0) / 100 * float(ing.get("grams", 100))
                    for ing, p in prot_ings + carb_ings + veg_ings
                )
                gap     = max(0.0, meal_kcal - used)
                n_other = max(len(other_ings), 1)
                for ing, p in other_ings:
                    kcal_pg = float(p.get("kcal", 100) or 100) / 100
                    _sg(ing, p, gap / n_other / max(kcal_pg, 0.1))
    return plan


def limit_carbs_per_main_meal(plan: Dict, products: List[Dict]) -> Dict:
    """Оставляет не более 1 углеводного продукта в каждом Обеде и Ужине.

    Модель иногда кладёт 2 вида макарон в одно блюдо → 600г пасты на 2100 ккал.
    Сохраняет самый калорийный углевод; остальные удаляются.
    """
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            if meal.get("type") not in ("Обед", "Ужин"):
                continue
            ings = meal.get("ingredients", [])
            carb_ings = [
                (i, find_product(i.get("product", ""), products))
                for i in ings
                if (find_product(i.get("product", ""), products) or {}).get("group") == "carbs"
            ]
            if len(carb_ings) <= 1:
                continue
            best = max(carb_ings,
                       key=lambda x: float(x[0].get("grams", 0))
                                    * float((x[1] or {}).get("kcal", 0)) / 100)
            remove_names = {x[0]["product"] for x in carb_ings} - {best[0]["product"]}
            meal["ingredients"] = [i for i in ings if i["product"] not in remove_names]
    return plan


def guarantee_carb_per_main_meal(plan: Dict, products: List[Dict]) -> Dict:
    """Добавляет углевод в каждый Обед и Ужин, где его нет.

    Углеводные гарниры (крупы, макароны, картофель) обязательны в каждом
    основном приёме пищи — без них суточная норма 2750–2850 ккал недостижима.
    Выполняется перед code_set_portions, чтобы расчёт порций учитывал крупы.
    """
    carbs = sorted(
        [p for p in products
         if p.get("group") == "carbs"
         and float(p.get("kcal", 0) or 0) >= 80
         and not any(kw in p.get("name", "").lower() for kw in _PORRIDGE_KW)],
        key=lambda p: float(p.get("price", 0) or 0)
    )
    if not carbs:
        return plan

    for day_idx, day in enumerate(plan.get("days", [])):
        for mi, meal in enumerate(day.get("meals", [])):
            if meal.get("type") not in ("Обед", "Ужин"):
                continue
            ings = meal.get("ingredients", [])
            has_carb = any(
                (find_product(i.get("product", ""), products) or {}).get("group") == "carbs"
                for i in ings
            )
            if not has_carb:
                chosen = carbs[(day_idx * 2 + mi) % len(carbs)]
                ings.append({"product": chosen["name"], "grams": 200})
    return plan


def cap_product_weekly_packs(plan: Dict, products: List[Dict],
                             max_packs: int = 3) -> Dict:
    """Ограничивает любой продукт max_packs упаковками в неделю.

    Пропорционально масштабирует порции ингредиентов, чтобы список покупок
    никогда не приобретал более max_packs одного и того же товара. Предотвращает
    доминирование плана одним дешёвым продуктом (напр., 6× творог).
    """
    # Считаем суммарные граммы по каждому продукту за неделю
    total_g: Dict[str, float] = {}
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            for ing in meal.get("ingredients", []):
                p = find_product(ing.get("product", ""), products)
                if not p:
                    continue
                nm = p["name"]
                total_g[nm] = total_g.get(nm, 0) + float(ing.get("grams", 100))

    # Вычисляем коэффициенты масштабирования по продуктам, где превышен лимит.
    # Овощи и фрукты — гарнир, не основа; ограничиваем 2 упаковками независимо от max_packs.
    # Углеводы не срезаются ниже 150г/порции — без крупы норма ккал не набирается.
    _VEGGIE_PACK_MAX = 2
    _CARB_MIN_G = 80.0   # минимум 80г крупы/макарон за порцию после масштабирования
    scale_factors: Dict[str, float] = {}
    for nm, used_g in total_g.items():
        p = next((p for p in products if p["name"] == nm), None)
        if not p:
            continue
        pack_g = float(p.get("pack_g", 500) or 500)
        grp = p.get("group", "other")
        effective_max = _VEGGIE_PACK_MAX if grp in ("veggies", "fruits") else max_packs
        if math.ceil(used_g / pack_g) > effective_max:
            sf = (effective_max * pack_g) / used_g
            # Для углеводов: не масштабируем ниже _CARB_MIN_G за порцию в среднем
            if p.get("group") == "carbs":
                meals_with_this = sum(
                    1 for d in plan.get("days", [])
                    for m in d.get("meals", [])
                    for i in m.get("ingredients", [])
                    if (find_product(i.get("product", ""), products) or {}).get("name") == nm
                )
                if meals_with_this > 0:
                    avg_g_after = used_g * sf / meals_with_this
                    if avg_g_after < _CARB_MIN_G:
                        sf = max(sf, _CARB_MIN_G * meals_with_this / used_g)
            scale_factors[nm] = sf

    if not scale_factors:
        return plan

    # Применяем коэффициенты масштабирования ко всем порциям ингредиентов
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            for ing in meal.get("ingredients", []):
                p = find_product(ing.get("product", ""), products)
                if not p:
                    continue
                sf = scale_factors.get(p["name"])
                if sf and sf < 1.0:
                    _set_grams(ing, products, float(ing.get("grams", 100)) * sf)
    return plan


# ── Прямое заполнение бюджета (управляется кодом) ────────────────────────────

def fill_budget_with_premium(plan: Dict, products: List[Dict], budget: float) -> Dict:
    """Заменяет дешёвые ингредиенты дорогими аналогами той же пищевой группы.

    Прямой ответ кода на недоиспользование бюджета. Для каждого ингредиента
    находит самый дорогой продукт той же пищевой группы, которого ещё нет в блюде,
    и заменяет его в калорийно-эквивалентных граммах.
    Завтрак защищён — мясо/рыба не вводятся.
    Выполняет до 10 проходов; останавливается при достижении 95% бюджета.
    """
    if shopping_cost(plan, products) >= budget * 0.95:
        return plan

    # Индексируем продукты по группе, сортируем по убыванию цены за грамм.
    by_group: Dict[str, List[Dict]] = {}
    for p in products:
        by_group.setdefault(p.get("group", "other"), []).append(p)
    for grp in by_group:
        by_group[grp].sort(
            key=lambda p: -(float(p.get("price", 0) or 0)
                            / float(p.get("pack_g", 500) or 500))
        )

    for _pass in range(10):
        if shopping_cost(plan, products) >= budget * 0.95:
            break
        upgraded = False
        for day in plan.get("days", []):
            for meal in day.get("meals", []):
                mtype      = meal.get("type", "")
                if mtype == "Перекус":
                    continue
                meal_names = {i["product"] for i in meal.get("ingredients", [])}

                for ing in list(meal.get("ingredients", [])):
                    p = find_product(ing["product"], products)
                    if not p:
                        continue
                    grp      = p.get("group", "other")
                    cur_unit = (float(p.get("price", 0) or 0)
                                / float(p.get("pack_g", 500) or 500))

                    for new_p in by_group.get(grp, []):
                        if new_p["name"] in meal_names:
                            continue
                        new_unit = (float(new_p.get("price", 0) or 0)
                                    / float(new_p.get("pack_g", 500) or 500))
                        if new_unit <= cur_unit * 1.3:
                            break  # список отсортирован; дальше ничего дороже нет
                        if (mtype == "Завтрак"
                                and any(kw in new_p["name"].lower()
                                        for kw in BREAKFAST_FORBIDDEN_KW)):
                            continue
                        # Калорийно-нейтральная замена
                        old_g      = float(ing.get("grams", 100))
                        old_kcal   = float(p.get("kcal", 100) or 100) / 100 * old_g
                        new_kcal_g = float(new_p.get("kcal", 100) or 100) / 100
                        new_g      = max(30, min(
                            gram_cap(float(new_p.get("kcal", 100) or 100), grp),
                            round(old_kcal / max(new_kcal_g, 0.1))
                        ))
                        ing["product"] = new_p["name"]
                        ing["grams"]   = new_g
                        meal_names.discard(p["name"])
                        meal_names.add(new_p["name"])
                        upgraded = True
                        break
        if not upgraded:
            break
    return plan


def enforce_product_variety(plan: Dict, products: List[Dict],
                            variety: int) -> Dict:
    """При variety=3: каждый продукт не более чем в 3 приёмах пищи за неделю.

    Заменяет лишние вхождения на наименее используемые альтернативы той же группы,
    чтобы список покупок содержал ≥17 уникальных продуктов и 1 упаковка каждого
    покрывала всё потребление недели.
    """
    if variety < 3:
        return plan

    MAX_USES = 3

    # Индексируем продукты по группе (сортировка по цене убыванием для приоритета дорогих)
    by_group: Dict[str, List[Dict]] = {}
    for p in products:
        by_group.setdefault(p.get("group", "other"), []).append(p)
    for g in by_group:
        by_group[g].sort(key=lambda p: float(p.get("price", 0) or 0), reverse=True)

    # Собираем использование: product_name → [(day_idx, meal_idx, ing_idx)]
    usage: Dict[str, List[tuple]] = {}
    for di, day in enumerate(plan.get("days", [])):
        for mi, meal in enumerate(day.get("meals", [])):
            for ii, ing in enumerate(meal.get("ingredients", [])):
                p = find_product(ing.get("product", ""), products)
                if not p:
                    continue
                nm = p["name"]
                usage.setdefault(nm, []).append((di, mi, ii))

    used_names = set(usage.keys())

    for nm, occurrences in list(usage.items()):
        if len(occurrences) <= MAX_USES:
            continue
        p_orig = next((p for p in products if p["name"] == nm), None)
        if not p_orig:
            continue
        grp = p_orig.get("group", "other")

        # Кандидаты: та же группа, отсортированные по числу текущих использований
        group_cands = by_group.get(grp, [])

        for di, mi, ii in occurrences[MAX_USES:]:
            # Ищем наименее используемый продукт из той же группы
            best = None
            best_uses = MAX_USES
            for cand in group_cands:
                if cand["name"] == nm:
                    continue
                n_uses = len(usage.get(cand["name"], []))
                if n_uses < best_uses:
                    best_uses = n_uses
                    best = cand
            if best is None:
                # Разрешаем на 1 использование больше, если альтернатив нет
                continue
            plan["days"][di]["meals"][mi]["ingredients"][ii]["product"] = best["name"]
            usage.setdefault(best["name"], []).append((di, mi, ii))
            used_names.add(best["name"])

    return plan


def trim_to_budget(plan: Dict, products: List[Dict], budget: float) -> Dict:
    """Финальная гарантия: итог покупок (целые упаковки) не превышает бюджет.

    Выбирает продукт, чья цена одной упаковки ближайшая к сумме превышения
    снизу — это минимизирует недоиспользование бюджета. Если ни одна упаковка
    не покрывает превышение, берёт самую дорогую. Повторяет до полного погашения.
    """
    for _ in range(30):
        cost = shopping_cost(plan, products)
        if cost <= budget:
            break
        overshoot = cost - budget

        # Собираем суммарные граммы, размер и цену упаковки по каждому продукту
        usage: Dict[str, Tuple[float, float, float]] = {}
        for day in plan.get("days", []):
            for meal in day.get("meals", []):
                for ing in meal.get("ingredients", []):
                    p = find_product(ing.get("product", ""), products)
                    if not p:
                        continue
                    nm = p["name"]
                    pg = float(p.get("pack_g", 500) or 500)
                    pr = float(p.get("price", 0) or 0)
                    g0 = usage[nm][0] if nm in usage else 0.0
                    usage[nm] = (g0 + float(ing.get("grams", 100)), pg, pr)

        # Ищем упаковку, цена которой ≥ превышения и ближайшая к нему (минимум недоиспользования)
        candidates = [
            (pr - overshoot, nm, g, pg)
            for nm, (g, pg, pr) in usage.items()
            if math.ceil(g / pg) > 1 and pr >= overshoot
        ]
        if candidates:
            candidates.sort()                               # минимальный перерасход первым
            _, best_nm, best_g, best_pg = candidates[0]
        else:
            # Ни одна упаковка не покрывает превышение целиком — убираем самую дорогую
            expensive = [
                (math.ceil(g / pg) * pr, nm, g, pg)
                for nm, (g, pg, pr) in usage.items()
                if math.ceil(g / pg) > 1
            ]
            if not expensive:
                break
            expensive.sort(reverse=True)
            _, best_nm, best_g, best_pg = expensive[0]

        # Уменьшаем граммы этого продукта до (N-1) упаковок × 0.97 (запас на округление)
        current_packs = math.ceil(best_g / best_pg)
        target_g = (current_packs - 1) * best_pg * 0.97
        if target_g <= 0:
            break
        scale = target_g / max(best_g, 1.0)

        # Используем прямое присвоение (min=1г) вместо _set_grams (min=30г),
        # иначе продукты на минимальном пороге (напр. масло 30г) не масштабируются
        # и количество пачек не снижается.
        for day in plan.get("days", []):
            for meal in day.get("meals", []):
                for ing in meal.get("ingredients", []):
                    p = find_product(ing.get("product", ""), products)
                    if p and p["name"] == best_nm:
                        ing["grams"] = max(1, round(float(ing.get("grams", 100)) * scale))

    return plan


# ── Основной конвейер и форматированный вывод ─────────────────────────────────

def format_plan(plan: Dict, products: List[Dict],
                daily_cal: float, prot_pct: float, fat_pct: float,
                carb_pct: float, budget: float,
                variety_level: int = 2, liked_foods: str = "",
                disliked_foods: str = "") -> str:

    # ── Фильтр нелюбимых продуктов ──────────────────────────────────────────
    # Убираем нелюбимые продукты из рабочего каталога ДО любой обработки:
    # find_product() не найдёт их → clean_plan удалит их из блюд,
    # а все функции перестройки не смогут их подобрать.
    if disliked_foods:
        dl_kws = [kw.strip().lower()
                  for kw in re.split(r"[,;]+", disliked_foods) if kw.strip()]
        if dl_kws:
            # Семантическое расширение: «рыба» → фильтруем ВСЕ рыбные/морские продукты
            _FISH_ALL = (
                "рыб", "тунец", "лосос", "скумбри", "минтай", "форел", "семг",
                "сельд", "горбуш", "треска", "сайра", "хек", "кильк", "шпроты",
                "морепродукт", "краб", "мидий", "осьминог", "гребешок",
            )
            if any("рыб" in kw or kw == "fish" for kw in dl_kws):
                dl_kws = list(dl_kws) + [kw for kw in _FISH_ALL if kw not in dl_kws]
            products = [p for p in products
                        if not any(kw in p.get("name", "").lower() for kw in dl_kws)]

    # ── Конвейер коррекции ───────────────────────────────────────────────────
    # Нормализуем ингредиенты: модель может выдавать строки вместо словарей,
    # когда граммы опущены из формата (напр., ["product"] вместо [{"product":"..."}]).
    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            meal["ingredients"] = [
                {"product": ing} if isinstance(ing, str) else ing
                for ing in meal.get("ingredients", [])
                if ing
            ]
    plan = add_missing_days(plan)           # гарантируем 7 дней, даже если модель обрезала вывод
    plan = dedup_meal_types(plan)           # до clean_plan — удаляет дублированные приёмы от модели
    plan = clean_plan(plan, products)       # убирает макароны + мясо/рыбу с завтраков
    # При высокой доле углеводов (≥50%) паста — основной источник у/в; ограничиваем мягче.
    # variety=3 — разнообразие важнее, потому лимит ниже даже при высоком carb_pct.
    if variety_level >= 3:
        _max_pasta = 5 if carb_pct >= 50 else 3
    else:
        _max_pasta = 12 if carb_pct >= 50 else 5
    plan = cap_pasta_weekly(plan, max_pasta=_max_pasta)
    plan = add_missing_meals(plan, products, daily_cal, prot_pct, fat_pct,
                             carb_pct, variety=variety_level, budget=budget)
    plan = fix_compatibility(plan, products)
    plan = fix_savory_dairy_with_fruits(plan, products)
    plan = apply_compatibility_matrix(plan, products)
    plan = dedup_per_meal(plan, products)
    plan = normalize_varieties(plan, products, variety_level)
    plan = dedup_per_meal(plan, products)
    plan = ensure_meal_complete(plan, products, daily_cal)
    plan = add_veggie_sides(plan, products, daily_cal)
    plan = dedup_per_meal(plan, products)
    plan = normalize_varieties(plan, products, variety_level)
    # Разбиваем повторение по дням: тот же углевод/белок 3+ раз в том же типе → перестройка
    plan = diversify_across_days(plan, products, daily_cal, prot_pct, fat_pct,
                                 carb_pct, variety=variety_level)
    # Перестраиваем блюда без горячего белка (творог+овощи на ужин) или пустые
    plan = rebuild_bad_meals(plan, products, daily_cal, prot_pct, fat_pct,
                             carb_pct, variety=variety_level)
    # Защитная сетка: убираем мясо/рыбу, проникшие в завтраки через поздние шаги
    plan = strip_breakfast_forbidden(plan)
    # Лимит рыбы — 7 блюд/неделю (макс. одно в день); убираем молочку из блюд с булгуром
    # и из обеда/ужина, когда уже есть горячий белок.
    plan = cap_fish_meals_weekly(plan, products, daily_cal, prot_pct, fat_pct,
                                 carb_pct, variety_level, max_fish=7)
    plan = fix_bulgur_dairy_incompatibility(plan, products)
    plan = fix_dairy_in_main_meals(plan, products)
    plan = rebuild_bad_meals(plan, products, daily_cal, prot_pct, fat_pct,
                             carb_pct, variety=variety_level)
    # При высоком разнообразии: каждый продукт ≤ 3 раз в неделю → ≥17 уникальных
    if variety_level >= 3:
        plan = enforce_product_variety(plan, products, variety_level)
    # Гарантируем углевод в каждом основном приёме пищи ДО расчёта порций.
    plan = guarantee_carb_per_main_meal(plan, products)
    # Не более 1 вида углеводов в блюде (убирает «Макароны Макфа 300г + Макароны Щедрый 300г»).
    plan = limit_carbs_per_main_meal(plan, products)
    plan = dedup_per_meal(plan, products)
    # ── Расчёт порций кодом ──────────────────────────────────────────────────
    # Языковая модель выбирает КАКИЕ продукты сочетать; код вычисляет СКОЛЬКО.
    # Заменяет ненадёжную арифметику модели точным нутриентным таргетингом.
    plan = code_set_portions(plan, products, daily_cal, prot_pct, carb_pct)
    # Нормализуем каждый день до суточной нормы ДО масштабирования бюджета,
    # чтобы scale_to_budget не усиливал суточные превышения от модели.
    plan = fix_calories(plan, products, daily_cal)
    plan = optimize_macros(plan, products, prot_pct, fat_pct, carb_pct)
    # balance_meal_portions ДОЛЖНА выполняться ДО масштабирования бюджета, чтобы
    # scale_to_budget мог пропорционально увеличивать порции без немедленной отмены.
    plan = balance_meal_portions(plan, products, daily_cal)
    # Добираем недостающие калории углеводами (mix дешёвых + дорогих) ДО
    # масштабирования под бюджет — улучшает ккал/рубль всего плана.
    plan = fill_calories_with_carbs(plan, products, daily_cal)
    plan = scale_to_budget(plan, products, budget, daily_cal)
    plan = inject_for_budget(plan, products, budget, daily_cal)
    plan = swap_cheap_for_premium(plan, products, budget)   # калорийно-нейтральная замена: дешёвые углеводы → дорогой белок
    plan = strip_pasta_from_breakfast(plan)   # бюджетные шаги могли добавить макароны в завтрак
    # После strip завтрак может стать пустым — перестраиваем если < 50 ккал
    plan = rebuild_bad_meals(plan, products, daily_cal, prot_pct, fat_pct,
                             carb_pct, variety=variety_level)
    plan = fill_budget_with_premium(plan, products, budget)   # прямое заполнение бюджета кодом
    # Второй проход: premium-функции выше могли вытеснить дешёвые углеводы.
    # Возвращаем углеводы для набора нормы калорий, trim_to_budget уложит в бюджет.
    plan = fill_calories_with_carbs(plan, products, daily_cal)
    # variety=3: не более 2 упаковок каждого продукта (разнообразие обеспечивает
    # enforce_product_variety — ≤3 блюда на продукт); max_packs=1 давал слишком
    # мало еды и не позволял набрать норму калорий.
    max_packs = 5 if variety_level >= 3 else 7
    plan = cap_product_weekly_packs(plan, products, max_packs=max_packs)
    # Финальная гарантия: дискретный итог покупок (ceil упаковок) не превышает бюджет
    plan = trim_to_budget(plan, products, budget)
    # Финальная защита перекуса: убираем масло/мясо, которые могли занести бюджетные шаги
    plan = strip_snack_forbidden(plan)
    # Перекус из одних овощей — не снек; перестраиваем с добавлением молочки/фруктов
    plan = rebuild_veggie_only_snacks(plan, products, daily_cal, prot_pct,
                                      fat_pct, carb_pct, variety_level)
    # Финальная гарантия калорий: добираем дешёвыми углеводами, срезаем дорогие
    # при перерасходе — обязательно выполняется ПОСЛЕДНЕЙ.
    plan = ensure_daily_calories(plan, products, daily_cal, budget)
    # Выравниваем калории по дням: переносим порции из дней с профицитом
    # в дни с дефицитом. Список покупок и бюджет не меняются.
    plan = rebalance_daily_calories(plan, products, daily_cal)
    # clamp запускается последним — после всех шагов добора калорий,
    # чтобы ни fill_calories_with_carbs (2й проход), ни ensure_daily_calories
    # не могли снова накачать дни выше 1.10× нормы.
    plan = clamp_to_daily_ceiling(plan, products, daily_cal)
    # Clamp уменьшил порции → стоимость упала. Добираем оставшийся бюджет
    # калорийно-нейтральной заменой дешёвых ингредиентов дорогими,
    # затем обрезаем если вышли за бюджет.
    plan = fill_budget_with_premium(plan, products, budget)
    plan = trim_to_budget(plan, products, budget)
    # Финальный контроль качества перед выводом
    plan = limit_carbs_per_main_meal(plan, products)   # убираем двойные углеводы в блюде
    plan = strip_pasta_from_breakfast(plan)             # убираем макароны из завтраков
    plan = rebuild_bad_meals(plan, products, daily_cal, prot_pct, fat_pct,
                             carb_pct, variety=variety_level)  # восстанавливаем пустые завтраки
    # Финальный лимит по пасте
    plan = cap_pasta_weekly(plan, max_pasta=_max_pasta)
    # cap_pasta убрал лапшу → восполняем пустые углеводные слоты КРУПАМИ, а не снова пастой
    _np = [p for p in products
           if not any(kw in p.get("name", "").lower() for kw in _PASTA_KW)]
    if _np:
        plan = guarantee_carb_per_main_meal(plan, _np)
        plan = fill_calories_with_carbs(plan, _np, daily_cal)
    # После удаления пасты — перераспределяем бюджет на дорогие белки/молочку.
    plan = fill_budget_with_premium(plan, products, budget)
    # fill_budget_with_premium мог добавить дорогой продукт (макароны) в завтрак.
    # Убираем пасту и перестраиваем пустые завтраки (крупа/йогурт).
    plan = strip_pasta_from_breakfast(plan)
    plan = rebuild_bad_meals(plan, products, daily_cal, prot_pct, fat_pct,
                             carb_pct, variety=variety_level)
    plan = cap_product_weekly_packs(plan, products, max_packs=max_packs)
    plan = clamp_to_daily_ceiling(plan, products, daily_cal)
    plan = trim_to_budget(plan, products, budget)
    # После всех шагов очистки (cap_pasta_weekly, cap_product_weekly_packs,
    # clamp_to_daily_ceiling) порции могут быть урезаны ниже нормы калорий.
    # Финальный добор дешёвыми углеводами закрывает этот дефицит без выхода за бюджет.
    plan = ensure_daily_calories(plan, products, daily_cal, budget)
    plan = trim_to_budget(plan, products, budget)
    # Финальное перераспределение: переносим калории из дней с профицитом
    # в дни с дефицитом. Не меняет граммы в сумме → бюджет не меняется.
    plan = rebalance_daily_calories(plan, products, daily_cal)

    tgt_prot = (daily_cal * prot_pct / 100) / 4
    tgt_fat  = (daily_cal * fat_pct  / 100) / 9
    tgt_carb = (daily_cal * carb_pct / 100) / 4

    SEP = "─" * 48

    lines: List[str] = []
    shop:  Dict[str, Tuple[float, float, float]] = {}
    wk = {"kcal": 0.0, "prot": 0.0, "fat": 0.0, "carb": 0.0}

    for day_data in plan.get("days", []):
        lines.append(f"\n{SEP}")
        lines.append(f"День {day_data.get('day', '?')} — {day_data.get('weekday', '')}")
        lines.append(SEP)
        day = {"kcal": 0.0, "prot": 0.0, "fat": 0.0, "carb": 0.0}

        for meal in day_data.get("meals", []):
            mtype  = meal.get("type", "")
            ings   = meal.get("ingredients", [])
            nutr, _ = calc_nutrition(ings, products)
            dish   = build_dish_name(ings, products, mtype)
            weight = sum(float(i.get("grams", 100)) for i in ings)
            ing_str = ", ".join(
                f"{i['product']} ({i.get('grams', 100)}г)" for i in ings
            )

            lines.append(
                f"\n{mtype}: {dish}  ({round(weight)}г)\n"
                f"  {ing_str}\n"
                f"  {round(nutr['kcal'])} ккал  "
                f"Б {round(nutr['prot'], 1)}г  "
                f"Ж {round(nutr['fat'],  1)}г  "
                f"У {round(nutr['carb'], 1)}г  "
                f"~{round(nutr['cost'])}р"
            )

            for k in day:
                day[k] += nutr[k]
            for ing in ings:
                p = find_product(ing["product"], products)
                if not p: continue
                nm = p["name"]
                pg = float(p.get("pack_g", 500) or 500)
                pr = float(p.get("price",  0)   or 0)
                g0 = shop[nm][0] if nm in shop else 0.0
                shop[nm] = (g0 + float(ing.get("grams", 100)), pg, pr)

        lines.append(
            f"\nИтого дня: {round(day['kcal'])} ккал  "
            f"Б {round(day['prot'], 1)}г  "
            f"Ж {round(day['fat'],  1)}г  "
            f"У {round(day['carb'], 1)}г"
        )
        for k in wk:
            wk[k] += day[k]

    lines.append(f"\n{SEP}")
    lines.append("Список покупок на неделю")
    lines.append(SEP)
    shop_total = 0.0
    for nm, (g, pg, pr) in sorted(shop.items()):
        packs       = max(1, math.ceil(g / pg))
        cost        = packs * pr
        shop_total += cost
        lines.append(f"  {nm} — {packs} уп. x {round(pr)}р = {round(cost)}р")
    budget_ok = "OK" if shop_total <= budget else "ПРЕВЫШЕН"
    lines.append(
        f"\nИтого за покупки: {round(shop_total)}р  "
        f"(бюджет: {round(budget)}р — {budget_ok})"
    )

    under      = budget - shop_total
    budget_pct = round(shop_total / budget * 100) if budget > 0 else 0

    def _acc(actual: float, target: float) -> str:
        if target <= 0: return "—"
        pct = max(0, round(100 - abs(actual - target) / target * 100))
        return f"{pct}%↑" if actual > target else f"{pct}%"

    lines.append(f"\n{SEP}")
    lines.append("Итоги недели")
    lines.append(SEP)
    lines.append(
        f"\n  Калории:   {round(wk['kcal'])} ккал"
        f"  (цель {round(daily_cal * 7)} ккал)  {_acc(wk['kcal'], daily_cal * 7)}\n"
        f"  Белки:     {round(wk['prot'], 1)} г"
        f"  (цель {round(tgt_prot * 7, 1)} г)  {_acc(wk['prot'], tgt_prot * 7)}\n"
        f"  Жиры:      {round(wk['fat'],  1)} г"
        f"  (цель {round(tgt_fat  * 7, 1)} г)  {_acc(wk['fat'],  tgt_fat  * 7)}\n"
        f"  Углеводы:  {round(wk['carb'], 1)} г"
        f"  (цель {round(tgt_carb * 7, 1)} г)  {_acc(wk['carb'], tgt_carb * 7)}\n"
        f"  Стоимость: {round(shop_total)} р"
        f"  (бюджет {round(budget)} р)  {_acc(shop_total, budget)}"
    )
    if under > budget * 0.10:
        if budget_pct < 50:
            lines.append(
                f"\nБюджет использован на {budget_pct}% "
                f"(сэкономлено {round(under)}р). "
                f"Сэкономленные средства можно потратить на более дорогие продукты — "
                f"попробуйте добавить в план мясо, рыбу или молочные продукты."
            )
        else:
            lines.append(
                f"\nБюджет использован на {budget_pct}% "
                f"(сэкономлено {round(under)}р)."
            )
    # Предупреждение: любимые продукты, которых нет в каталоге Чижика
    if liked_foods:
        liked_chk = [w.strip().lower() for w in liked_foods.split(",") if w.strip()]
        _V_EXTRA = {
            "говядина": ["говядин", "говяж"],
            "свинина":  ["свинин",  "свин"],
            "курица":   ["куриц",   "курин"],
            "индейка":  ["индей",   "индюш"],
            "баранина": ["баранин", "баран"],
            "телятина": ["телятин", "телячь"],
        }
        def _v_stems(w: str) -> list:
            if w in _V_EXTRA: return _V_EXTRA[w]
            return [w[:-2] if len(w) >= 6 else w[:-1] if len(w) >= 4 else w]
        missing   = [w for w in liked_chk
                     if not any(any(s in p.get("name","").lower() for s in _v_stems(w))
                                for p in products)]
        if missing:
            lines.insert(0,
                f"⚠️  Любимые продукты сейчас отсутствуют в каталоге Чижика: "
                f"{', '.join(missing)}.\n"
                f"    Попробуйте другое название (например, 'говядина' вместо 'стейк').\n")

    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 8:
        print(
            "Usage: meal_verifier.py plan.json products.json "
            "daily_cal prot_pct fat_pct carb_pct weekly_budget "
            "[variety_level] [liked_foods]",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
            plan = _parse_llm_json(f.read())
    except Exception as e:
        print(f"Не удалось разобрать план от модели: {e}", file=sys.stderr)
        sys.exit(1)

    if isinstance(plan, list):
        plan = {"days": plan}
    elif not isinstance(plan, dict):
        print("Неверная структура ответа модели", file=sys.stderr)
        sys.exit(1)
    if "days" not in plan:
        for key in ("week", "план", "plan", "menu"):
            if key in plan:
                plan = {"days": plan[key]}
                break
        else:
            plan = {"days": []}

    try:
        with open(sys.argv[2], encoding="utf-8", errors="replace") as f:
            products = json.load(f)
    except Exception as e:
        print(f"Не удалось загрузить продукты: {e}", file=sys.stderr)
        sys.exit(1)

    daily_cal     = float(sys.argv[3])
    prot_pct      = float(sys.argv[4])
    fat_pct       = float(sys.argv[5])
    carb_pct      = float(sys.argv[6])
    budget        = float(sys.argv[7])
    variety_level  = int(sys.argv[8])  if len(sys.argv) > 8 else 2
    liked_foods    = sys.argv[9]       if len(sys.argv) > 9 else ""
    disliked_foods = sys.argv[10]      if len(sys.argv) > 10 else ""

    try:
        result = format_plan(
            plan, products, daily_cal, prot_pct, fat_pct, carb_pct,
            budget, variety_level, liked_foods, disliked_foods
        )
    except Exception as e:
        print(f"Ошибка при форматировании плана: {e}", file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(result + "\n")


if __name__ == "__main__":
    main()
