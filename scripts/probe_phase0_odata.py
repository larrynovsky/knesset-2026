#!/usr/bin/env python3
"""Фаза 0, часть P0-3. Четвёртая редакция — выгрузка через guarded_fetch (§23).

История редакций, потому что каждая ловила отдельную ловушку:
  1. `/EntitySet/$count` -> 404. Работает только `?$count=true&$top=0`.
  2. `KNS_PlenumVote` не имеет KnessetNum — режется по VoteDateTime,
     границы каденций из KNS_KnessetDates.
  3. `$top=200` МОЛЧА отдаёт 100: страница жёстко сотня. Фракции считались
     по первой сотне из 545, вывод о сшивке был неверен (21 вместо 76).
  4. Собственный цикл пагинации — это и есть обход §23. Теперь выгрузка идёт
     через guarded_fetch, который сверяет объём с независимым счётчиком
     и отказывается отдавать неполный результат наверх.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import count, fetch_all  # noqa: E402


def rule(t: str) -> None:
    print(f"\n{'=' * 76}\n{t}\n{'=' * 76}")


# ---- границы каденций ------------------------------------------------------
rule("Границы каденций (KNS_KnessetDates — по сессиям, границы агрегируются)")
rows = fetch_all("KNS_KnessetDates", select="KnessetNum,PlenumStart,PlenumFinish")
bounds: dict[int, tuple[str, str]] = {}
for row in rows:
    k, s, f = row["KnessetNum"], row.get("PlenumStart"), row.get("PlenumFinish")
    if not s:
        continue
    f = f or s
    bounds[k] = (min(bounds[k][0], s), max(bounds[k][1], f)) if k in bounds else (s, f)
for k in sorted(bounds):
    if k >= 14:
        print(f"   Кнессет {k:<3} {bounds[k][0][:10]} .. {bounds[k][1][:10]}")

# ---- объёмы ----------------------------------------------------------------
rule("Объёмы по каденциям")
print(f"   {'кнессет':<9}{'период':<24}{'голосований':>12}{'поимённых':>11}{'биллей':>8}{'фракций':>8}")
for k in sorted(bounds):
    if k < 14:
        continue
    lo, hi = bounds[k][0][:19] + "Z", bounds[k][1][:19] + "Z"
    pv = count("KNS_PlenumVote", f"VoteDateTime ge {lo} and VoteDateTime le {hi}")
    vr = count("KNS_PlenumVoteResult", f"VoteDate ge {lo} and VoteDate le {hi}")
    bl = count("KNS_Bill", f"KnessetNum eq {k}")
    fc = count("KNS_Faction", f"KnessetNum eq {k}")
    print(f"   {k:<9}{lo[:10] + '..' + hi[:10]:<24}{pv:>12}{vr:>11}{bl:>8}{fc:>8}")
    time.sleep(0.4)

# ---- сшивка фракций --------------------------------------------------------
rule("Сшиваются ли фракции между каденциями")
rows = fetch_all("KNS_Faction", select="Id,Name,KnessetNum")
by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
by_id: dict[int, set[str]] = defaultdict(set)
for row in rows:
    by_name[row["Name"]].append((row["KnessetNum"], row["Id"]))
    by_id[row["Id"]].add(row["Name"])

multi = {n: v for n, v in by_name.items() if len({k for k, _ in v}) > 1}
stable = [n for n, v in multi.items() if len({i for _, i in v}) == 1]
print(f"   записей: {len(rows)}   уникальных названий: {len(by_name)}")
print(f"   названий в >1 каденции: {len(multi)}")
print(f"   из них с ОДНИМ Id: {len(stable)}   с РАЗНЫМИ Id: {len(multi) - len(stable)}")
print("\n   самые долгоживущие:")
for n, v in sorted(multi.items(), key=lambda x: -len({k for k, _ in x[1]}))[:12]:
    ks = ",".join(str(k) for k in sorted({k for k, _ in v}))
    ids = sorted({i for _, i in v})
    mark = "ОДИН Id" if len(ids) == 1 else f"{len(ids)} разных Id"
    print(f"      {n[:32]:<34} [{ks[:34]:<34}] {mark}")

collide = {i: ns for i, ns in by_id.items() if len(ns) > 1}
print(f"\n   Id, под которыми в разных каденциях РАЗНЫЕ партии: {len(collide)}")

print("\n   фракции 25-го кнессета:")
for row in sorted([r for r in rows if r["KnessetNum"] == 25], key=lambda x: x["Id"]):
    print(f"      {row['Id']:>5}  {row['Name']}")

# ---- должности -------------------------------------------------------------
rule("Должности и министерские записи (сырьё для criteria/periods.yaml)")
for row in sorted(fetch_all("KNS_Position", select="Id,Description"),
                  key=lambda x: x["Id"]):
    print(f"      {row['Id']:>4}  {row['Description']}")

for k in (24, 25):
    tot = count("KNS_PersonToPosition", f"KnessetNum eq {k}")
    mins = count("KNS_PersonToPosition",
                 f"KnessetNum eq {k} and (PositionID eq 39 or PositionID eq 40 or PositionID eq 45)")
    print(f"\n   кнессет {k}: всего {tot}, министерского уровня {mins}")

rows = fetch_all("KNS_PersonToPosition",
                 flt="KnessetNum eq 25 and PositionID eq 39",
                 select="PersonID,GovMinistryName,StartDate,FinishDate")
print(f"\n   министерских назначений в 25-м кнессете: {len(rows)}")
for row in rows[:8]:
    print(f"      person={row.get('PersonID'):<7}"
          f"{str(row.get('StartDate'))[:10]}..{str(row.get('FinishDate'))[:10]}  "
          f"{row.get('GovMinistryName')}")

print("\nготово")
