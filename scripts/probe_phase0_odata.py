#!/usr/bin/env python3
"""Фаза 0, часть P0-3 — переписана после разведки форм запросов.

Что выяснилось probe_odata_shapes.py и учтено здесь:
  * путь `/EntitySet/$count` отдаёт 404 — работает только `?$count=true&$top=0`;
  * `KNS_PlenumVote` НЕ имеет поля KnessetNum — режется по VoteDateTime,
    границы берутся из KNS_KnessetDates;
  * `KNS_Faction.Id` выдаётся ПО КНЕССЕТУ — сшивка между каденциями
    проверяется по названию, а не по идентификатору.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from collections import defaultdict

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"


def q(entity: str, params: str = "") -> dict:
    url = f"{BASE}/{entity}?$format=json" + (("&" + params) if params else "")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"__err__": str(e)[:200]}


def count(entity: str, flt: str = "") -> int | str:
    p = "$count=true&$top=0"
    if flt:
        p += "&$filter=" + urllib.parse.quote(flt)
    r = q(entity, p)
    return r.get("@odata.count", r.get("__err__", "?"))


def rule(t: str) -> None:
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


# ---- границы каденций ------------------------------------------------------
rule("Границы каденций (KNS_KnessetDates)")
r = q("KNS_KnessetDates", "$select=KnessetNum,PlenumStart,PlenumFinish&$top=200")
bounds: dict[int, tuple[str, str]] = {}
for row in r.get("value", []):
    k = row["KnessetNum"]
    s, f = row.get("PlenumStart"), row.get("PlenumFinish")
    if not s:
        continue
    lo, hi = bounds.get(k, (s, f or s))
    bounds[k] = (min(lo, s), max(hi or "", f or s or ""))
for k in sorted(bounds):
    print(f"   Кнессет {k:<3} {bounds[k][0][:10]} .. {bounds[k][1][:10]}")

# ---- объёмы ----------------------------------------------------------------
rule("Объёмы по каденциям")
print(f"   {'кнессет':<9}{'период':<26}{'голосований':>13}{'поимённых':>12}{'биллей':>9}{'фракций':>9}")
for k in sorted(bounds):
    if k < 14:
        continue
    lo, hi = bounds[k]
    dflt = f"VoteDateTime ge {lo[:19]}Z and VoteDateTime le {hi[:19]}Z"
    pv = count("KNS_PlenumVote", dflt)
    vr = count("KNS_PlenumVoteResult", f"VoteDate ge {lo[:19]}Z and VoteDate le {hi[:19]}Z")
    bl = count("KNS_Bill", f"KnessetNum eq {k}")
    fc = count("KNS_Faction", f"KnessetNum eq {k}")
    print(f"   {k:<9}{lo[:10] + '..' + hi[:10]:<26}{pv:>13}{vr:>12}{bl:>9}{fc:>9}")
    time.sleep(0.5)

# ---- сшивка фракций --------------------------------------------------------
rule("Сшиваются ли фракции между каденциями (Id против названия)")
r = q("KNS_Faction", "$select=Id,Name,KnessetNum&$top=1000&$orderby=KnessetNum")
by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
by_id: dict[int, set[str]] = defaultdict(set)
for row in r.get("value", []):
    by_name[row["Name"]].append((row["KnessetNum"], row["Id"]))
    by_id[row["Id"]].add(row["Name"])

multi = {n: v for n, v in by_name.items() if len(v) > 1}
print(f"   всего записей фракций: {len(r.get('value', []))}")
print(f"   уникальных названий:   {len(by_name)}")
print(f"   названий в >1 каденции: {len(multi)}")
stable = sum(1 for v in multi.values() if len({i for _, i in v}) == 1)
print(f"   из них с ОДНИМ Id во всех каденциях: {stable}")
print(f"   с РАЗНЫМИ Id (сшивка по Id ломается): {len(multi) - stable}")
print("\n   примеры долгоживущих:")
for n, v in sorted(multi.items(), key=lambda x: -len(x[1]))[:8]:
    ks = ",".join(str(k) for k, _ in sorted(v))
    ids = sorted({i for _, i in v})
    mark = "ОДИН Id" if len(ids) == 1 else f"{len(ids)} разных Id"
    print(f"      {n[:34]:<36} кнессеты {ks:<28} {mark}")

collide = {i: ns for i, ns in by_id.items() if len(ns) > 1}
print(f"\n   Id, под которыми в разных каденциях РАЗНЫЕ партии: {len(collide)}")
for i, ns in list(collide.items())[:6]:
    print(f"      Id {i}: {' | '.join(sorted(ns))[:100]}")

# ---- министры --------------------------------------------------------------
rule("Министры и должности (сырьё для criteria/periods.yaml)")
r = q("KNS_Position", "$select=Id,Description&$top=50")
print("   справочник должностей:")
for row in sorted(r.get("value", []), key=lambda x: x["Id"]):
    print(f"      {row['Id']:>4}  {row['Description']}")
print(f"\n   KNS_PersonToPosition всего: {count('KNS_PersonToPosition')}")
for k in (24, 25):
    print(f"   кнессет {k}: {count('KNS_PersonToPosition', f'KnessetNum eq {k}')}")
r = q("KNS_PersonToPosition",
      "$filter=" + urllib.parse.quote("KnessetNum eq 25 and GovMinistryID ne null")
      + "&$select=PersonID,PositionID,GovMinistryName,StartDate,FinishDate,DutyDesc&$top=8")
print("\n   пример министерских записей 25-го кнессета:")
for row in r.get("value", [])[:8]:
    print(f"      person={row.get('PersonID')} pos={row.get('PositionID')} "
          f"{str(row.get('StartDate'))[:10]}..{str(row.get('FinishDate'))[:10]} "
          f"{row.get('GovMinistryName')}")

print("\nготово")
