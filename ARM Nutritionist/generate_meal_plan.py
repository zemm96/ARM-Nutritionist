#!/usr/bin/env python3
"""Генерирует 7-дневный план питания с помощью локальной модели Qwen3 8B GGUF.

Использование:
    python generate_meal_plan.py [параметры]

Параметры:
    --model-path PATH   Путь к .gguf файлу (по умолчанию: автопоиск в папке скрипта)
    --calories  N       Суточная норма калорий (по умолчанию: 2000)
    --protein   N       % белков от калорий (по умолчанию: 25)
    --fat       N       % жиров от калорий (по умолчанию: 30)
    --carbs     N       % углеводов от калорий (по умолчанию: 45)
    --budget    N       Недельный бюджет на питание в рублях (по умолчанию: 2000)
    --variety   1|2|3   1=низкое, 2=среднее, 3=высокое (по умолчанию: 2)
    --liked     TEXT    Любимые продукты через запятую
    --disliked  TEXT    Нелюбимые продукты через запятую
    --products  FILE    JSON список продуктов в формате arm_compact.json
    --output    FILE    Записать JSON плана в файл вместо stdout
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# ── Настройки автозагрузки ────────────────────────────────────────────────────
_HF_REPO  = "Qwen/Qwen3-8B-GGUF"
_HF_QUANT = "Q4_K_M"          # помещается в 8 ГБ VRAM; ~5.2 ГБ загрузки


def _log(msg: str) -> None:
    print(f"[meal-plan] {msg}", file=sys.stderr)


def _die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def detect_gpu() -> int:
    """Возвращает n_gpu_layers на основе первого обнаруженного GPU NVIDIA.

    RTX 3070 (8 ГБ)  -> -1  (все слои на GPU)
    GTX 960  (2 ГБ)  ->  6  (частичная выгрузка)
    нет NVIDIA        ->  0  (только CPU)
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            _log("nvidia-smi завершился с ошибкой — CPU fallback (n_gpu_layers=0)")
            return 0

        line  = result.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        name_raw   = parts[0]
        vram_total = int(parts[1])
        vram_free  = int(parts[2])

        _log(f"GPU: {name_raw} (всего {vram_total} МБ, свободно {vram_free} МБ)")

        # Qwen3-8B-Q4_K_M ≈ 5 200 МБ + KV-кэш (n_ctx=6144) ≈ 900 МБ + 400 МБ запас
        NEEDED_MB = 5200 + 900 + 400  # 6 500 МБ

        if vram_free >= NEEDED_MB:
            _log(f"Достаточно свободной VRAM ({vram_free} МБ) → n_gpu_layers = -1 (все слои на GPU)")
            return -1

        # Частичная выгрузка: ~150 МБ на слой, резервируем 900 МБ под KV-кэш и 300 МБ запас
        avail_for_layers = max(0, vram_free - 900 - 300)
        layers = max(4, min(35, avail_for_layers // 150))
        _log(f"Недостаточно свободной VRAM ({vram_free} МБ < {NEEDED_MB}) → n_gpu_layers = {layers}")
        return layers

    except FileNotFoundError:
        _log("nvidia-smi не найден — CPU fallback (n_gpu_layers=0)")
        return 0
    except Exception as exc:
        _log(f"Ошибка определения GPU: {exc} — CPU fallback")
        return 0


def _pick_gguf(files: list[Path]) -> Path:
    preferred = [f for f in files if "qwen" in f.name.lower()]
    return preferred[0] if preferred else files[0]


def _hf_filename() -> str:
    """Возвращает точное имя GGUF-файла из репозитория HuggingFace.

    Запрашивает список файлов репозитория, если доступен huggingface_hub,
    чтобы всегда получить каноническое имя; иначе возвращает известное значение по умолчанию.
    """
    default = f"Qwen3-8B-{_HF_QUANT}.gguf"
    try:
        from huggingface_hub import list_repo_files
        gguf = [f for f in list_repo_files(_HF_REPO) if f.endswith(".gguf")]
        pref = [f for f in gguf if _HF_QUANT in f]
        return (pref or gguf or [default])[0]
    except Exception:
        return default


def _download_model(save_dir: Path) -> str:
    """Скачивает модель Qwen3-8B GGUF с HuggingFace.

    Стратегия:
    1. Если установлен huggingface_hub — используем hf_hub_download
       (поддерживает LFS, возобновляемая загрузка, кэширование).
    2. Иначе — прямая HTTPS-загрузка через urllib.

    Прогресс выводится в stderr (Qt перехватывает и показывает пользователю).
    """
    import shutil
    import time
    import urllib.request

    filename = _hf_filename()
    dest     = save_dir / filename
    tmp      = save_dir / (filename + ".part")

    if dest.is_file() and dest.stat().st_size > 1_000_000_000:
        _log(f"Модель найдена: {dest}")
        return str(dest)

    # ── Проверка места на диске ──────────────────────────────────────────
    needed = 6 * 1024 ** 3
    free   = shutil.disk_usage(save_dir).free
    if free < needed:
        _die(
            f"Недостаточно места на диске: нужно ≥6 ГБ, "
            f"доступно {free / 1024**3:.1f} ГБ ({save_dir})"
        )

    save_dir.mkdir(parents=True, exist_ok=True)
    _log(f"Модель не найдена. Загрузка {filename} (~5.2 ГБ) с HuggingFace…")
    _log(f"Сохранение в: {save_dir}")
    _log("Это может занять 10–30 минут в зависимости от скорости соединения.")

    # ── 1. huggingface_hub ───────────────────────────────────────────────
    try:
        import os
        from huggingface_hub import hf_hub_download
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        _log("Используется huggingface_hub…")
        path = hf_hub_download(
            repo_id=_HF_REPO,
            filename=filename,
            local_dir=str(save_dir),
            local_dir_use_symlinks=False,
        )
        _log(f"Загрузка завершена: {path}")
        return str(path)
    except ImportError:
        _log("huggingface_hub не установлен — прямая HTTPS-загрузка.")
    except Exception as e:
        _log(f"huggingface_hub: ошибка ({e}) — переключаюсь на прямую загрузку.")

    # ── 2. Прямая HTTPS-загрузка ─────────────────────────────────────────
    url    = f"https://huggingface.co/{_HF_REPO}/resolve/main/{filename}?download=true"
    _log(f"URL: {url}")

    last_t = [time.monotonic()]

    def _reporthook(count: int, block_size: int, total_size: int) -> None:
        now = time.monotonic()
        if now - last_t[0] < 10:          # одна строка лога каждые 10 секунд
            return
        last_t[0] = now
        done = count * block_size
        if total_size > 0:
            pct = min(100, done * 100 // total_size)
            _log(f"  {pct}%  ({done / 1_048_576:.0f} / {total_size / 1_048_576:.0f} МБ)")
        else:
            _log(f"  {done / 1_048_576:.0f} МБ загружено…")

    try:
        urllib.request.urlretrieve(url, str(tmp), reporthook=_reporthook)
        tmp.rename(dest)
        _log(f"Загрузка завершена: {dest}")
        return str(dest)
    except Exception as exc:
        for f in (tmp, dest):
            try:
                f.unlink()
            except OSError:
                pass
        _die(
            f"Не удалось скачать модель: {exc}\n"
            f"Установите huggingface_hub и повторите запуск:\n"
            f"  pip install huggingface_hub\n"
            f"Или скачайте вручную:\n"
            f"  huggingface-cli download {_HF_REPO} {filename} --local-dir \"{save_dir}\""
        )
    return ""  # недостижимо


def find_model(override: str | None) -> str:
    if override:
        path = Path(override)
        if not path.is_file():
            _die(f"Файл модели не найден: '{override}'")
        return str(path)

    # Поднимаемся от папки скрипта, проверяя каждую родительскую директорию и
    # её ближайших соседей. Находит модель, даже если скрипт скопирован
    # в папку сборки далеко от дерева исходников.
    visited: set[Path] = set()
    d = SCRIPT_DIR
    for _ in range(7):
        if d in visited or not d.exists():
            break
        visited.add(d)

        hits = sorted(d.glob("*.gguf"))
        if hits:
            chosen = _pick_gguf(hits)
            _log(f"Модель: {chosen}")
            return str(chosen)

        # Проверяем соседей d (другие подпапки d.parent)
        try:
            for sib in sorted(d.parent.iterdir()):
                if not sib.is_dir() or sib == d or sib in visited:
                    continue
                hits = sorted(sib.glob("*.gguf"))
                if hits:
                    chosen = _pick_gguf(hits)
                    _log(f"Модель: {chosen}")
                    return str(chosen)
        except PermissionError:
            pass

        d = d.parent

    # Модель не найдена локально — автоматическая загрузка с HuggingFace
    _log("Файл модели .gguf не найден — начинаю автоматическую загрузку.")
    return _download_model(SCRIPT_DIR)


def load_model(model_path: str, n_gpu_layers: int):
    try:
        from llama_cpp import Llama
    except ImportError:
        _die(
            "llama-cpp-python не установлен.\n"
            "  Установка: pip install llama-cpp-python\n"
            "  С CUDA: pip install llama-cpp-python --extra-index-url "
            "https://abetlen.github.io/llama-cpp-python/whl/cu121"
        )

    _log(f"Загрузка модели (n_gpu_layers={n_gpu_layers}) …")

    # n_ctx=6144 для всего железа: экономит ~300 МБ VRAM по сравнению с 8192,
    # что критично на 8 ГБ картах под Windows (система занимает 1–2 ГБ VRAM).
    n_ctx = 6144
    _log(f"n_ctx={n_ctx}")

    base_kwargs = dict(
        model_path=model_path,
        n_ctx=n_ctx,
        n_threads=12,
        n_gpu_layers=n_gpu_layers,
        verbose=False,
    )
    try:
        llm = Llama(**base_kwargs, flash_attn=True)
    except TypeError:
        # flash_attn добавлен в llama-cpp-python ≥ 0.2.56
        _log("flash_attn не поддерживается текущей версией llama-cpp-python — пропущено")
        llm = Llama(**base_kwargs)

    _log("Модель готова.")
    return llm

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
_VARIETY_LABEL = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}


def _goal_label(protein_pct: float, carb_pct: float) -> str:
    if protein_pct >= 28:
        return "Weight Loss"
    if carb_pct >= 50:
        return "Weight Gain"
    return "Weight Maintenance"


_SYSTEM_TMPL = (
    "You are a nutritionist. Create a COMPLETE 7-day meal plan from the grocery list below.\n\n"
    "GOAL: {goal} (protein {p}%, fat {f}%, carbohydrates {c}%)\n"
    "Daily calorie intake: {kcal} kcal.\n"
    "Weekly budget: {budget}₽.\n\n"
    "VARIETY LEVEL: {variety_level}\n"
    "DISH REPEAT RULES:\n"
    "- LOW: same dish up to 4x/week, adjacent repeats allowed\n"
    "- MEDIUM: same dish up to 2x/week, adjacent repeats PROHIBITED\n"
    "- HIGH: each dish unique across ALL 7 days — ABSOLUTELY NO two days may share "
    "the same dish name or the same ingredient combination. "
    "If only a few products are available, vary quantities, cooking methods and "
    "combinations (e.g. 'Гречка с говядиной' ≠ 'Говядина с гречкой и капустой'). "
    "Days 1 and 2 MUST differ in ALL three meals. Days 3-7 MUST each differ from "
    "all previous days.\n\n"
    "RULES:\n"
    "1. Use ONLY products from the provided list.\n"
    "1a. LIKED PRODUCTS (listed under 'Liked:'): each of them MUST appear in at least "
    "2–3 meals across the 7-day plan. Do not ignore them.\n"
    "2. Every meal must be a complete, cooked dish with a real name (e.g. 'Гречневая каша с куриной грудкой', 'Омлет с овощами', 'Борщ'). "
    "FORBIDDEN: bare ingredient lists ('Хлеб + творог'), bread as the main component, or meals named after a single ingredient.\n"
    "3. Each meal must contain 3–6 ingredients that form one coherent dish.\n"
    "4. Bread no more than 1 serving per day, only as a side — never the main ingredient of a meal.\n"
    "5. Breakfast: dairy/eggs/grains/fruit ONLY — no meat, fish, or pasta/noodles/spaghetti. "
    "Use PORRIDGE or GRAIN (гречка, овсянка, булгур, рис, пшено) as the carb base, NEVER pasta.\n"
    "6. Lunch and dinner: must include a protein source AND a vegetable.\n"
    "7. Sweets (jam, honey) only as a small dessert (≤50g).\n"
    "8. Daily calories: target ±3%, each macro ±5%.\n"
    "9. DO NOT include gram amounts — the app calculates exact portions automatically.\n"
    "10. Spend the full weekly budget — use EXPENSIVE products (meat, fish, dairy, "
    "fresh vegetables, fruits, nuts). Cheap pasta alone cannot fill a large budget. "
    "Prioritise higher-priced items from the list. {snack_rule}\n"
    "11. Fish maximum ONCE per day, NEVER at breakfast. Total fish meals across "
    "the whole week: no more than 5. Other days must use meat (chicken, beef) or eggs.\n"
    "12. Dairy (творог, yogurt, кефир) is for breakfast ONLY. Never put dairy as "
    "a main ingredient in lunch or dinner; use meat, fish, or eggs there instead. "
    "NEVER use plain milk (молоко) as a standalone dish or snack — replace it with "
    "yogurt or kefir at all times.\n"
    "13. Bulgur and dairy are INCOMPATIBLE — never put творог, yogurt, or кефир "
    "in the same meal as булгур.\n\n"
    "OUTPUT FORMAT — compact JSON only, no markdown, no explanation:\n"
    '{{"days":['
    '{{"day":1,"weekday":"Понедельник","meals":['
    '{{"type":"Завтрак","dish":"Название","ingredients":[{{"product":"Имя из списка"}}]}},'
    '{{"type":"Обед","dish":"...","ingredients":[...]}},'
    '{snack_slot}'
    '{{"type":"Ужин","dish":"...","ingredients":[...]}}'
    ']}},'
    '...,'
    '{{"day":7,"weekday":"Воскресенье","meals":[...]}}'
    ']}}\n'
    "All names in Russian. No grams field. First char {{, last char }}."
)


_SNACK_RULE = (
    "11. Include a 'Перекус' (snack) each day: 1–2 items from fruits, dairy, or nuts. "
    "On 2–3 days per week also add a dessert (мороженое, зефир, вафли) if available."
)
_SNACK_SLOT = '{{"type":"Перекус","dish":"...","ingredients":[...]}},'


def _build_system_prompt(args: argparse.Namespace) -> str:
    large_budget = args.budget >= 5000
    return _SYSTEM_TMPL.format(
        goal=_goal_label(args.protein, args.carbs),
        p=round(args.protein),
        f=round(args.fat),
        c=round(args.carbs),
        kcal=round(args.calories),
        budget=round(args.budget),
        variety_level=_VARIETY_LABEL[args.variety],
        snack_rule=_SNACK_RULE if large_budget else "",
        snack_slot=_SNACK_SLOT if large_budget else "",
    )


def _build_example_day(products: list) -> str:
    """Строит компактный однодневный пример с реальными именами продуктов из списка.
    Возвращает строку JSON без пробелов или "" если список слишком мал."""
    def first(*kws):
        for kw in kws:
            for p in products:
                if kw in p.get("name", "").lower():
                    return p["name"]
        return None

    grain  = first("овсян", "гречк")
    dairy  = first("молок", "кефир", "йогурт")
    fruit  = first("банан", "яблок")
    prot1  = first("курин", "грудк", "филе")
    prot2  = first("говяд", "минтай", "скумбр", "треск", "форел")
    grain2 = first("гречк", "рис", "макарон")
    veg1   = first("морков", "брокол", "капуст")
    veg2   = first("капуст", "огурц", "помидор", "томат")

    if not (grain and prot1 and (dairy or fruit) and veg1):
        return ""

    grain2       = grain2 or grain
    prot2        = prot2  or prot1
    veg2         = veg2   or veg1
    side         = dairy  or fruit
    side_g       = 180 if dairy else 120

    g1 = grain.split()[0];  g2 = grain2.split()[0]
    p1 = prot1.split()[0].lower();  p2 = prot2.split()[0].lower()
    v1 = veg1.split()[0].lower();   v2 = veg2.split()[0].lower()
    sd = side.split()[0].lower()

    day = {"day": 0, "weekday": "ОБРАЗЕЦ", "meals": [
        {"type": "Завтрак",
         "dish": f"{g1} с {sd}",
         "ingredients": [{"product": grain, "grams": 80},
                         {"product": side,  "grams": side_g}]},
        {"type": "Обед",
         "dish": f"{g2} с тушёным {p1} и {v1}",
         "ingredients": [{"product": grain2, "grams": 100},
                         {"product": prot1,  "grams": 180},
                         {"product": veg1,   "grams": 80}]},
        {"type": "Ужин",
         "dish": f"Запечённый {p2} с {v2}",
         "ingredients": [{"product": prot2, "grams": 200},
                         {"product": veg2,  "grams": 150}]},
    ]}
    return json.dumps(day, ensure_ascii=False, separators=(",", ":"))


_PASTA_KW_GEN = ("макарон", "спагетт", "лапш", "вермишел")


def _build_day_assignments(products: list) -> str:
    """Предварительно назначает базовый углевод и основной белок каждому дню.

    Чередует углеводы без макарон, затем макароны; белки по убыванию цены,
    чтобы дорогие товары (курица, рыба) появлялись в начале. Заставляет модель
    распределяться по всему списку продуктов, а не использовать макароны каждый день.
    """
    carbs_nonpasta = [p for p in products
                      if p.get("group") == "carbs"
                      and not any(kw in p["name"].lower() for kw in _PASTA_KW_GEN)]
    carbs_pasta    = [p for p in products
                      if p.get("group") == "carbs"
                      and any(kw in p["name"].lower() for kw in _PASTA_KW_GEN)]
    all_carbs = carbs_nonpasta + carbs_pasta  # сначала не макароны

    proteins = sorted(
        [p for p in products
         if p.get("group") in ("protein", "other") and float(p.get("prot", 0)) > 5],
        key=lambda p: float(p.get("price", 0)), reverse=True
    )

    if not all_carbs or not proteins:
        return ""

    lines = []
    for i in range(7):
        c  = all_carbs[i % len(all_carbs)]["name"]
        pr = proteins[i % len(proteins)]["name"]
        lines.append(f"  Day {i + 1}: base carb = \"{c}\", main protein = \"{pr}\"")

    return (
        "PRODUCT ROTATION — each day MUST feature its assigned base carb and protein "
        "(other ingredients can be added freely):\n" + "\n".join(lines)
    )


def _build_user_message(products: list, variety: int,
                        liked: str = "", disliked: str = "") -> str:
    prod_lines = []
    for pr in products:
        prod_lines.append(
            f"{pr['name']} | {round(pr['kcal'])}kcal | "
            f"P{pr['prot']:.1f} F{pr['fat']:.1f} C{pr['carb']:.1f} | "
            f"{round(pr['price'])}₽"
        )
    parts = ["Products (name | kcal/100g | P/F/C per 100g | price):\n" +
             "\n".join(prod_lines)]
    if liked.strip():
        parts.append(f"Liked: {liked}")
    if disliked.strip():
        parts.append(f"Disliked: {disliked}")

    assignments = _build_day_assignments(products)
    if assignments:
        parts.append(assignments)

    example = _build_example_day(products)
    if example:
        parts.append(
            "REFERENCE DAY — follow this dish-naming style and ingredient structure "
            "(do NOT copy these dishes; generate your own for all 7 days):\n" + example
        )

    parts.append(f"Variety level: {_VARIETY_LABEL[variety]}")
    days_list = "\n".join(
        f"Day {i+1} — {WEEKDAYS[i]}" for i in range(7)
    )
    parts.append(
        f"Generate the meal plan for ALL 7 days:\n{days_list}\n"
        "All 7 days are REQUIRED. Return ONLY the JSON object."
    )
    return "\n\n".join(parts)


def _raw_prompt(system: str, user: str, no_think: bool) -> str:
    prefix = "<think>\n</think>\n" if no_think else ""
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n{prefix}"
    )


# Убираем блоки размышлений Qwen3 (полные и обрезанные)
_THINK_RE       = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_THINK_TRUNC_RE = re.compile(r"<think>.*",              re.DOTALL)


def _strip_think(text: str) -> str:
    text = _THINK_RE.sub("", text)
    text = _THINK_TRUNC_RE.sub("", text)
    return text.strip()


# Продукты, вызывающие «ленивые» паттерны блюд (хлеб как основа, колбаса + крупа).
# Фильтруются до передачи модели; альтернативные углеводы/белки остаются доступными.
_FILLER_KW = ["батон", "хлеб", "хлебц", "сосиск", "колбас", "нарезк",
              "круассан", "слойк", "рогалик", "молоко"]


def _remove_fillers(products: list) -> list:
    out = [p for p in products
           if not any(kw in p.get("name", "").lower() for kw in _FILLER_KW)]
    removed = len(products) - len(out)
    if removed:
        _log(f"Удалено {removed} наполнителей (хлеб/колбасы) перед вызовом модели")
    return out


def generate_plan(llm, products: list, args: argparse.Namespace,
                  max_tokens: int = 4000, no_think: bool = False) -> str:
    products = _remove_fillers(products)

    system_msg = _build_system_prompt(args)
    user_msg   = _build_user_message(products, args.variety, args.liked, args.disliked)
    prompt     = _raw_prompt(system_msg, user_msg, no_think)

    # Измеряем реальное количество входных токенов и ограничиваем вывод так,
    # чтобы вход+выход ≤ n_ctx
    try:
        input_tokens = len(llm.tokenize(prompt.encode("utf-8")))
        n_ctx        = llm.n_ctx()
        available    = n_ctx - input_tokens - 64   # запас 64 токена
        if available < 1500:
            _log(f"ВНИМАНИЕ: только {available} токенов для вывода — план может быть обрезан!")
        max_tokens = min(max_tokens, max(available, 512))
        _log(f"Промпт: {input_tokens} токенов | n_ctx: {n_ctx} | макс. вывод: {max_tokens}")
    except Exception as e:
        _log(f"Подсчёт токенов недоступен ({e}) — используем max_tokens={max_tokens}")

    # Более высокая температура для большего разнообразия блюд при высоком variety.
    # variety=1 требует детерминизма; variety=3 требует подлинного исследования.
    temperature = {1: 0.15, 2: 0.40, 3: 0.85}.get(getattr(args, "variety", 2), 0.40)
    _log(f"Отправка запроса модели (max_tokens={max_tokens}, no_think={no_think}, "
         f"temperature={temperature}) …")

    response = llm.create_completion(
        prompt=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        stop=["<|im_end|>", "<|im_start|>"],
    )
    raw    = response["choices"][0]["text"]
    result = _strip_think(raw)

    if not result:
        _log("ВНИМАНИЕ: модель вернула пустой вывод")
        _log(f"СЫРОЙ ВЫВОД (первые 500 символов): {raw[:500]!r}")

    return result


_SAMPLE_PRODUCTS = [
    {"name": "Куриное филе",           "kcal": 110, "prot": 23.0, "fat":  1.5, "carb":  0.0, "price": 350},
    {"name": "Гречка",                  "kcal": 330, "prot": 12.6, "fat":  3.3, "carb": 64.0, "price":  90},
    {"name": "Яйца куриные (10 шт)",    "kcal": 157, "prot": 12.7, "fat": 11.5, "carb":  0.7, "price": 110},
    {"name": "Молоко 2.5%",             "kcal":  54, "prot":  2.9, "fat":  2.5, "carb":  4.8, "price":  75},
    {"name": "Творог 5%",               "kcal": 121, "prot": 17.0, "fat":  5.0, "carb":  1.8, "price": 130},
    {"name": "Рис длиннозёрный",         "kcal": 344, "prot":  6.7, "fat":  0.7, "carb": 78.0, "price":  85},
    {"name": "Овсянка",                 "kcal": 352, "prot": 12.0, "fat":  6.2, "carb": 58.0, "price":  70},
    {"name": "Говядина (вырезка)",       "kcal": 218, "prot": 26.0, "fat": 12.0, "carb":  0.0, "price": 520},
    {"name": "Масло сливочное 72.5%",   "kcal": 661, "prot":  0.8, "fat": 73.3, "carb":  1.3, "price": 120},
    {"name": "Капуста белокочанная",     "kcal":  27, "prot":  1.8, "fat":  0.1, "carb":  4.7, "price":  40},
    {"name": "Морковь",                 "kcal":  35, "prot":  1.3, "fat":  0.1, "carb":  6.9, "price":  30},
    {"name": "Лук репчатый",            "kcal":  41, "prot":  1.4, "fat":  0.2, "carb":  8.2, "price":  25},
    {"name": "Огурец свежий",           "kcal":  15, "prot":  0.8, "fat":  0.1, "carb":  2.8, "price":  80},
    {"name": "Помидоры свежие",         "kcal":  20, "prot":  1.1, "fat":  0.2, "carb":  3.7, "price": 120},
    {"name": "Яблоко",                  "kcal":  47, "prot":  0.4, "fat":  0.4, "carb":  9.8, "price": 100},
    {"name": "Банан",                   "kcal":  89, "prot":  1.1, "fat":  0.3, "carb": 22.8, "price":  90},
    {"name": "Хлеб ржаной",            "kcal": 259, "prot":  6.7, "fat":  3.3, "carb": 45.0, "price":  55},
    {"name": "Подсолнечное масло",      "kcal": 884, "prot":  0.0, "fat": 99.9, "carb":  0.0, "price": 120},
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Генерирует 7-дневный план питания с помощью локальной модели Qwen3 8B.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--model-path", metavar="PATH",
                    help="Путь к .gguf файлу (по умолчанию: автопоиск в папке скрипта).")
    ap.add_argument("--calories",  type=float, default=2000.0,
                    help="Суточная норма калорий (по умолчанию: 2000).")
    ap.add_argument("--protein",   type=float, default=25.0,
                    help="%% белков от калорий (по умолчанию: 25).")
    ap.add_argument("--fat",       type=float, default=30.0,
                    help="%% жиров от калорий (по умолчанию: 30).")
    ap.add_argument("--carbs",     type=float, default=45.0,
                    help="%% углеводов от калорий (по умолчанию: 45).")
    ap.add_argument("--budget",    type=float, default=2000.0,
                    help="Недельный бюджет на питание в рублях (по умолчанию: 2000).")
    ap.add_argument("--variety",   type=int,   default=2, choices=[1, 2, 3],
                    help="Уровень разнообразия: 1=низкий, 2=средний, 3=высокий (по умолчанию: 2).")
    ap.add_argument("--liked",     type=str,   default="",
                    help="Любимые продукты через запятую.")
    ap.add_argument("--disliked",  type=str,   default="",
                    help="Нелюбимые продукты через запятую.")
    ap.add_argument("--products",  type=str,   default=None,
                    help="JSON список продуктов (формат arm_compact.json).")
    ap.add_argument("--output",    type=str,   default=None,
                    help="Записать JSON плана в файл вместо stdout.")
    args = ap.parse_args()

    total_pct = args.protein + args.fat + args.carbs
    if abs(total_pct - 100.0) > 0.5:
        _die(f"--protein + --fat + --carbs должны давать в сумме 100 (получено {total_pct:.1f})")

    model_path   = find_model(args.model_path)
    n_gpu_layers = detect_gpu()
    llm          = load_model(model_path, n_gpu_layers)

    # Полный GPU: 4500 токенов — запас для 7 дней (~3000 токенов) без мышления.
    # Частичный/CPU: 3000 — план влезает, генерация на ~25% быстрее.
    max_tok  = 4500 if n_gpu_layers == -1 else 3000
    # Мышление отключено для всего железа: задача — структурированный JSON, а не
    # рассуждение. Цепочка think съедает 1000-2000 токенов из лимита вывода,
    # оставляя план обрезанным после дня 4-5 даже на быстром GPU.
    no_think = True

    if args.products:
        p = Path(args.products)
        if not p.is_file():
            _die(f"Файл продуктов не найден: '{args.products}'")
        with open(p, encoding="utf-8") as f:
            products = json.load(f)
        _log(f"Загружено {len(products)} продуктов из '{p}'")
    else:
        products = _SAMPLE_PRODUCTS
        _log(f"Используется {len(products)} встроенных образцов продуктов")

    plan_text = generate_plan(llm, products, args, max_tokens=max_tok, no_think=no_think)

    try:
        parsed = json.loads(plan_text)
        output = json.dumps(parsed, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        _log("ВНИМАНИЕ: вывод модели не является валидным JSON — записываем как текст")
        output = plan_text

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        _log(f"План сохранён в '{args.output}'")
    else:
        print(output)


if __name__ == "__main__":
    main()
