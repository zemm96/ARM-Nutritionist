"""
chizhik_bridge.py — мост между Qt-приложением и парсером Чижика.
Qt запускает этот скрипт как QProcess и читает JSON из stdout.

Использование:
    python chizhik_bridge.py <query> [max_price] [max_items] [output_json_path]

Если query пустая — выполняет полный обход каталога (category_id=133,
все страницы) и возвращает дедуплицированный список всех съедобных
продуктов с КБЖУ.  Если query задана — фильтрует по ключевому слову.

Вывод:
    JSON-массив продуктов в stdout (одна строка, UTF-8)
    Если передан output_json_path — дополнительно сохраняет туда же
    Отладочный лог парсера — в stderr (Qt его игнорирует)
"""

import os
import sys

_real_stdout_fd = os.dup(1)
os.dup2(2, 1)
_real_stdout = os.fdopen(_real_stdout_fd, 'wb', buffering=0)

import asyncio
import json
import warnings
from typing import Optional, Dict, List

try:
    from chi901 import (search_products_with_kbju, is_kbju_complete,
                        MANDATORY_FOOD_QUERIES, search_bulk_queries,
                        select_by_meal_categories)
except ImportError as e:
    _real_stdout.write(
        json.dumps({"error": f"Не удалось импортировать chi901: {e}"}).encode('utf-8') + b'\n'
    )
    _real_stdout.flush()
    sys.exit(1)


async def fetch_all_food(max_price: Optional[float]) -> List[Dict]:
    """Полный обход каталога — все съедобные продукты Чижика (category_id=133)."""
    return await search_products_with_kbju(
        query="",
        max_price=max_price,
        sort_by='rating',
        max_items=None,
    ) or []


async def fetch_by_query(query: str,
                         max_price: Optional[float],
                         max_items: int) -> List[Dict]:
    """Поиск по ключевому слову внутри каталога."""
    return await search_products_with_kbju(
        query=query,
        max_price=max_price,
        sort_by='rating',
        max_items=max_items,
    ) or []


async def fetch_mandatory_categories(max_price: Optional[float],
                                     max_items_per_query: int = 5,
                                     extra_queries: Optional[List[str]] = None) -> List[Dict]:
    """Однократный обход каталога по всем обязательным группам продуктов за один сеанс браузера.

    extra_queries — дополнительные запросы (любимые продукты пользователя), которые
    добавляются к MANDATORY_FOOD_QUERIES, если ещё не покрыты стандартным списком.
    """
    queries = list(MANDATORY_FOOD_QUERIES)
    if extra_queries:
        for q in extra_queries:
            ql = q.lower()
            # Не дублируем запросы, которые уже есть в стандартном списке
            if not any(ql in mq.lower() or mq.lower() in ql for mq in queries):
                queries.append(q)
    return await search_bulk_queries(
        queries=queries,
        max_price=max_price,
        max_items_each=max_items_per_query,
        max_pages=50,
    )


def serialize_product(p: Dict) -> Dict:
    kbju = p.get('кбжу', {})
    return {
        'title':         p.get('title', ''),
        'price':         p.get('price', 0.0),
        'rating':        p.get('рейтинг') or 0.0,
        'reviews':       p.get('отзывов') or 0,
        'calories':      kbju.get('калории')  or 0.0,
        'protein':       kbju.get('белки')    or 0.0,
        'fat':           kbju.get('жиры')     or 0.0,
        'carbs':         kbju.get('углеводы') or 0.0,
        'complete_kbju': is_kbju_complete(kbju),
        'category':      p.get('category', ''),
        'old_price':     p.get('old_price'),
    }


async def main():
    if len(sys.argv) < 2:
        _real_stdout.write(json.dumps({
            "error": "Использование: chizhik_bridge.py <query> [max_price] [max_items] [output_json]"
        }).encode('utf-8') + b'\n')
        _real_stdout.flush()
        sys.exit(1)

    query         = sys.argv[1]
    max_price     = float(sys.argv[2]) if len(sys.argv) > 2 else None
    max_items     = int(sys.argv[3])   if len(sys.argv) > 3 else 50
    output_json   = sys.argv[4]        if len(sys.argv) > 4 else None
    variety_level = int(sys.argv[5])   if len(sys.argv) > 5 else 2
    liked_foods   = sys.argv[6]        if len(sys.argv) > 6 else ""

    try:
        if query == "":
            raw_products = await fetch_all_food(max_price)
            # Любимые продукты пользователя добавляем к обязательным запросам,
            # чтобы они нашлись в каталоге даже если их нет в MANDATORY_FOOD_QUERIES.
            extra_queries = [w.strip() for w in liked_foods.split(",") if w.strip()]
            mandatory = await fetch_mandatory_categories(max_price, max_items_per_query=15,
                                                         extra_queries=extra_queries)
            existing_titles = {p.get('title', '').lower() for p in raw_products}
            for p in mandatory:
                if p.get('title', '').lower() not in existing_titles:
                    raw_products.append(p)
            raw_products = select_by_meal_categories(raw_products, variety_level, liked_foods)
        else:
            # Точечный поиск любимых продуктов — каждое слово ищем отдельно.
            # select_by_meal_categories не применяем: результаты мёржатся с готовым кэшем на стороне C++.
            queries = [q.strip() for q in query.split(",") if q.strip()]
            if len(queries) > 1:
                raw_products = await search_bulk_queries(
                    queries, max_price, max_items_each=5, max_pages=50)
            else:
                raw_products = await fetch_by_query(queries[0], max_price, max_items)
        result = [serialize_product(p) for p in raw_products]
        raw    = json.dumps(result, ensure_ascii=False)

        if output_json:
            with open(output_json, 'w', encoding='utf-8') as f:
                f.write(raw)
        _real_stdout.write(raw.encode('utf-8') + b'\n')
        _real_stdout.flush()
    except Exception as e:
        _real_stdout.write(json.dumps({"error": str(e)}).encode('utf-8') + b'\n')
        _real_stdout.flush()
        sys.exit(1)


if __name__ == '__main__':
    warnings.filterwarnings('ignore')
    asyncio.run(main())
