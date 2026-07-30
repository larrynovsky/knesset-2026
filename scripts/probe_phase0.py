#!/usr/bin/env python3
"""Фаза 0 — разведка глубины. Ничего не фиксирует, только выясняет горизонт.

Запускать на Studio (canonical, у него сеть и он же будет делать реальную выгрузку):
    /opt/homebrew/bin/python3.11 scripts/probe_phase0.py

Вывод — в stdout, оттуда руками в docs/reference/SOURCES.md.
Скрипт без зависимостей: только stdlib.

§23-exempt: одноразовая разведка ГЛУБИНЫ, написана до §23 и до канала Б.
Ходит в obudget собственным urlopen и объёма не сверяет — предмет изучения
здесь сама форма выдачи, а не выборка. Рабочая выгрузка канала Б —
scripts/fetch_budget.py через guarded_fetch.fetch_sql. Этот файл — долг
на удаление (follow-up 1 снимка 2026-07-30).
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "knesset-research/0.1 (personal research; contact via repo)"}
CTX = ssl.create_default_context()
BUDGET = "https://next.obudget.org/api/query"


def get(url: str, timeout: int = 45) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400], dict(e.headers or {})
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode(), {}


def head(url: str, timeout: int = 30) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {})
    except Exception as e:  # noqa: BLE001
        return -1, {"err": str(e)}


def sql(q: str) -> object:
    url = f"{BUDGET}?query={urllib.parse.quote(q)}"
    st, body, _ = get(url)
    if st != 200:
        return {"__http__": st, "__body__": body[:300].decode("utf-8", "replace")}
    try:
        return json.loads(body)
    except Exception as e:  # noqa: BLE001
        return {"__parse__": str(e)}


def rule(t: str) -> None:
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


# ---------------------------------------------------------------- P0-1 бюджет
def p0_1() -> None:
    rule("P0-1  BudgetKey: глубина ряда и есть ли ПЕРВОНАЧАЛЬНЫЙ бюджет (§11)")

    print("\n-- колонки таблицы budget --")
    r = sql("select column_name, data_type from information_schema.columns "
            "where table_name='budget' order by ordinal_position")
    rows = r.get("rows") if isinstance(r, dict) else None
    if rows:
        for row in rows:
            print(f"   {row.get('column_name'):<28} {row.get('data_type')}")
    else:
        print("   !! ", json.dumps(r, ensure_ascii=False)[:400])

    print("\n-- годы: сколько строк, у скольких есть факт --")
    r = sql("select year, count(1) as n, count(net_executed) as n_exec, "
            "count(net_revised) as n_rev from budget group by year order by year")
    rows = r.get("rows") if isinstance(r, dict) else None
    if rows:
        print(f"   {'год':<6}{'строк':>10}{'с фактом':>12}{'с планом':>12}")
        for row in rows:
            print(f"   {str(row.get('year')):<6}{row.get('n', 0):>10}"
                  f"{row.get('n_exec', 0):>12}{row.get('n_rev', 0):>12}")
    else:
        print("   !! ", json.dumps(r, ensure_ascii=False)[:400])

    print("\n-- поиск колонок, похожих на ПЕРВОНАЧАЛЬНО утверждённый бюджет --")
    r = sql("select column_name from information_schema.columns where table_name='budget' "
            "and (column_name like '%%allocat%%' or column_name like '%%approv%%' "
            "or column_name like '%%origin%%' or column_name like '%%amount%%' "
            "or column_name like '%%proposal%%')")
    print("   ", json.dumps(r.get("rows") if isinstance(r, dict) else r, ensure_ascii=False)[:600])

    print("\n-- таблицы, где может лежать первоначальный бюджет --")
    r = sql("select table_name from information_schema.tables "
            "where table_name like '%%budget%%' or table_name like '%%proposal%%' "
            "order by table_name")
    print("   ", json.dumps(r.get("rows") if isinstance(r, dict) else r, ensure_ascii=False)[:900])

    print("\n-- изменения бюджета (перебросы) --")
    r = sql("select count(1) as n, min(year) as y0, max(year) as y1 from budget_changes")
    print("   ", json.dumps(r.get("rows") if isinstance(r, dict) else r, ensure_ascii=False)[:300])


# ------------------------------------------------------------- P0-2 соглашения
def p0_2() -> None:
    rule("P0-2  Коалиционные соглашения: какие правительства доступны")
    base = "https://m.knesset.gov.il/mk/government/documents/cagreement{}.pdf"
    found = []
    for n in range(1, 41):
        st, h = head(base.format(n))
        if st == 200:
            size = h.get("Content-Length", "?")
            ctype = h.get("Content-Type", "?")
            found.append((n, size, ctype))
            print(f"   cagreement{n:<3} 200  {size:>10} B  {ctype}")
        time.sleep(0.25)
    if not found:
        print("   ничего не найдено по этой схеме имён")
    print(f"\n   ИТОГО доступно: {len(found)} файлов -> {[n for n, _, _ in found]}")

    if found:
        n = found[0][0]
        st, body, _ = get(base.format(n))
        print(f"\n-- проба текстового слоя на cagreement{n} ({len(body)} B) --")
        # Грубая эвристика без зависимостей: в текстовом PDF есть потоки с /Font,
        # у чистого скана их обычно нет, зато есть /Image.
        print(f"   встречается '/Font':  {body.count(b'/Font')}")
        print(f"   встречается '/Image': {body.count(b'/Image')}")
        print("   (эвристика: Font>0 и Image~0 -> текстовый; Image>>Font -> скан)")


# P0-3 вытеснен scripts/probe_phase0_odata.py (выгрузка через guarded_fetch, §23).
# Здесь остались только бюджет и PDF соглашений — OData этот файл больше не трогает.


if __name__ == "__main__":
    print(f"probe_phase0 — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    for fn in (p0_1, p0_2):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"\n!! {fn.__name__} упал: {exc}", file=sys.stderr)
    print("\nготово")
