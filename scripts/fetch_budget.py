#!/usr/bin/env python3
"""Канал Б: выгрузка бюджета Израиля из obudget. CLAUDE.md §23, §11.

Что делает и чего НЕ делает. Достаёт две таблицы и записывает как есть.
Ничего не интерпретирует, ничего не сопоставляет, никаких терминов поиска не
знает — сопоставление живёт в scripts/map_commitments.py по правилу из
criteria/budget_mapping.yaml.

  raw_budget      — полное дерево бюджета за годы периода. Коды длиной
                    2/4/6/8/10; длина 10 — תקנה תקציבית, нижний публикуемый
                    уровень. Три величины в строке: net_allocated
                    (первоначально утверждённый — база сравнения по §11),
                    net_revised, net_executed.
  budget_changes  — переносы внутри года. Решение владельца D-1 от 2026-07-30:
                    без них «дали переносом» и «не дали вовсе» неразличимы,
                    и ошибка систематическая, против партии.

⚠️ Измерено 2026-07-30, важно для §23: obudget отдаёт СТРАНИЦАМИ ПО 1000 строк
независимо от запроса. Запрос на 5 970 строк возвращает 1 000, HTTP 200, без
предупреждения. Поэтому выгрузка идёт только через guarded_fetch.fetch_sql,
который сверяет объём с отдельным count(1).

⚠️ Гранулярность переносов НЕ совпадает с гранулярностью такан.
`budget_code_title` в budget_changes несёт коды длиной 8 (иногда 4 в
`summary.to`), а обязательство сопоставляется с кодом длиной 10. Значит
найденный перенос НЕ доказывает адресность узкого обязательства — он
показывает лишь, что деньги пришли в ветку. Это причина, по которой
`targeting_proven` в правиле по умолчанию false.

Запуск на Studio (canonical, §19; у MacBook сети для этого нет):
    ssh larry@studio 'cd ~/knesset && python3 -u scripts/fetch_budget.py'
Самопроверка (нужна сеть):
    python3 scripts/fetch_budget.py --selftest
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import ShortRead, count_sql, fetch_sql  # noqa: E402  §23

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Годы периода ШАС в правительстве 37 — из criteria/budget_mapping.yaml.
# Здесь дублируются намеренно и только как ДЕФОЛТ аргумента: модуль выгрузки
# не читает критерии, иначе он начнёт зависеть от их формы. Правило — дом
# решения, этот список — дом удобства, и расхождение видно в диффе.
DEFAULT_YEARS = (2023, 2024, 2025)

TAKANOT_FIELDS = (
    "code, parent, title, year, depth, non_repeating, "
    "net_allocated, net_revised, net_executed, "
    "title_level2, title_level4, title_level6, title_level8"
)
CHANGES_FIELDS = (
    "transaction_id, year, date, req_code, req_title, change_title, "
    "change_type_name, committee_id, budget_code_title, summary, "
    "amount, net_expense_diff, gross_expense_diff, commitment_limit_diff, "
    "is_pending, explanation"
)


def _years_sql(years) -> str:
    """Годы — числа, не строки: в SQL идут без литералов и экранировать нечего."""
    ys = [int(y) for y in years]          # int() и есть проверка границы доверия
    if not ys:
        raise ValueError("fetch_budget: пустой список лет")
    return "year in (" + ", ".join(str(y) for y in ys) + ")"


def _refuse_if_empty(rows: list, what: str) -> list:
    """Ноль строк — отказ, а не результат «выгружать нечего».

    Тот же класс, что require_join в guarded_fetch: операция отчиталась об
    успехе и вернула пустоту, из которой получается вывод «данных нет»,
    неотличимый от «мы неверно спросили».
    """
    if not rows:
        raise ShortRead(f"§23 ПУСТАЯ ВЫГРУЗКА [{what}]: ноль строк. Это отказ, "
                        "а не результат: пустой ответ и неверный запрос "
                        "выглядят одинаково.")
    return rows


def _write(name: str, rows: list, meta: dict) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / name
    payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "https://next.obudget.org/api/query",
        **meta,
        "rows": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def fetch_takanot(years=DEFAULT_YEARS) -> list[dict]:
    """Полное дерево raw_budget за указанные годы, все уровни кода."""
    where = _years_sql(years)
    rows = fetch_sql("raw_budget", TAKANOT_FIELDS, "year, code", where=where)
    return _refuse_if_empty(rows, "raw_budget")


def fetch_changes(years=DEFAULT_YEARS) -> list[dict]:
    """Переносы budget_changes за указанные годы (D-1)."""
    where = _years_sql(years)
    rows = fetch_sql("budget_changes", CHANGES_FIELDS, "transaction_id", where=where)
    return _refuse_if_empty(rows, "budget_changes")


def selftest() -> int:
    """Оракул: краснеет, если выгрузка молча недобирает или врёт о фильтре."""
    where = "year = 2025 and length(code) = 4"
    n = count_sql("raw_budget", where)
    rows = fetch_sql("raw_budget", "code, year", "code", where=where)
    assert len(rows) == n, f"§23: count(1)={n}, выгрузка={len(rows)}"
    assert all(len(r["code"]) == 4 for r in rows), \
        "сервер вернул коды не той длины — фильтр применён не так, как заявлен"
    assert all(r["year"] == 2025 for r in rows), "сервер вернул чужой год"
    print(f"  OK: {n} строк, длина кода и год совпали с фильтром")

    # Пустая выгрузка обязана быть отказом, а не тихим «нечего выгружать».
    try:
        _refuse_if_empty([], "проверка")
        print("  ПРОВАЛ САМОПРОВЕРКИ: пустая выгрузка не отвергнута", file=sys.stderr)
        return 1
    except ShortRead:
        print("  OK: пустая выгрузка отвергнута")

    # Пустой список лет — тоже отказ, а не «выгрузить всё».
    try:
        _years_sql([])
        print("  ПРОВАЛ САМОПРОВЕРКИ: пустой список лет прошёл", file=sys.stderr)
        return 1
    except ValueError:
        print("  OK: пустой список лет отвергнут")

    assert _years_sql([2023, 2024]) == "year in (2023, 2024)"
    assert _years_sql(["2023"]) == "year in (2023)", "год обязан приводиться к int"
    print("самопроверка fetch_budget пройдена: 6 утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    years = DEFAULT_YEARS
    print(f"канал Б: годы {years}")

    t0 = time.time()
    takanot = fetch_takanot(years)
    p1 = _write("budget_takanot.json", takanot,
                {"table": "raw_budget", "years": list(years), "count": len(takanot)})
    by_len: dict[int, int] = {}
    for r in takanot:
        by_len[len(r["code"])] = by_len.get(len(r["code"]), 0) + 1
    print(f"  raw_budget: {len(takanot)} строк -> {p1.name}")
    print("  по длине кода: " + ", ".join(f"{k}:{v}" for k, v in sorted(by_len.items())))

    changes = fetch_changes(years)
    p2 = _write("budget_changes.json", changes,
                {"table": "budget_changes", "years": list(years),
                 "count": len(changes)})
    print(f"  budget_changes: {len(changes)} переносов -> {p2.name}")
    print(f"готово за {time.time() - t0:.0f} с")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ShortRead as exc:
        print(f"\n§23 ОТКАЗ: {exc}", file=sys.stderr)
        sys.exit(1)
