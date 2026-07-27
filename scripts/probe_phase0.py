#!/usr/bin/env python3
"""Фаза 0 — разведка глубины. Ничего не фиксирует, только выясняет горизонт.

Запускать на Studio (canonical, у него сеть и он же будет делать реальную выгрузку):
    /opt/homebrew/bin/python3.11 scripts/probe_phase0.py

Вывод — в stdout, оттуда руками в docs/reference/SOURCES.md.
Скрипт без зависимостей: только stdlib.
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
ODATA = "https://knesset.gov.il/OdataV4/ParliamentInfo"
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


# ---------------------------------------------------------------- P0-3 OData
def p0_3() -> None:
    rule("P0-3  OData: горизонты сущностей и сшиваются ли фракции")

    print("\n-- список entity sets --")
    st, body, _ = get(f"{ODATA}?$format=json")
    if st == 200:
        try:
            names = sorted(x["name"] for x in json.loads(body).get("value", []))
            print(f"   всего {len(names)}")
            for i in range(0, len(names), 3):
                print("   " + "  ".join(f"{x:<34}" for x in names[i:i + 3]))
        except Exception as e:  # noqa: BLE001
            print("   !! parse:", e)
    else:
        print(f"   !! HTTP {st}: {body[:200]!r}")

    def count(entity: str, flt: str | None = None) -> str:
        url = f"{ODATA}/{entity}/$count"
        if flt:
            url += "?$filter=" + urllib.parse.quote(flt)
        st, body, _ = get(url)
        return body.decode("utf-8", "replace").strip() if st == 200 else f"HTTP {st}"

    print("\n-- объёмы по кнессетам --")
    print(f"   {'кнессет':<10}{'PlenumVote':>14}{'VoteResult':>14}{'Bill':>10}{'Faction':>10}")
    for k in range(16, 27):
        pv = count("KNS_PlenumVote", f"KnessetNum eq {k}")
        vr = count("KNS_PlenumVoteResult", f"KnessetNum eq {k}")
        bl = count("KNS_Bill", f"KnessetNum eq {k}")
        fc = count("KNS_Faction", f"KnessetNum eq {k}")
        print(f"   {k:<10}{pv:>14}{vr:>14}{bl:>10}{fc:>10}")
        time.sleep(0.4)

    print("\n-- сшиваются ли FactionID между кнессетами --")
    for k in (24, 25):
        url = (f"{ODATA}/KNS_Faction?$filter=" + urllib.parse.quote(f"KnessetNum eq {k}")
               + "&$select=FactionID,Name,KnessetNum&$top=100")
        st, body, _ = get(url)
        if st != 200:
            print(f"   кнессет {k}: HTTP {st}")
            continue
        try:
            vals = json.loads(body).get("value", [])
            print(f"   кнессет {k}: {len(vals)} фракций")
            for v in vals[:12]:
                print(f"      {v.get('FactionID'):>8}  {v.get('Name')}")
        except Exception as e:  # noqa: BLE001
            print("   !! parse:", e)
        time.sleep(0.4)

    print("\n-- сущности правительств/должностей (для periods.yaml) --")
    for ent in ("KNS_Government", "KNS_Position", "KNS_PersonToPosition"):
        print(f"   {ent:<24} {count(ent)}")
        time.sleep(0.3)


if __name__ == "__main__":
    print(f"probe_phase0 — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    for fn in (p0_1, p0_2, p0_3):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"\n!! {fn.__name__} упал: {exc}", file=sys.stderr)
    print("\nготово")
