#!/usr/bin/env python3
"""Фаза 0, часть P0-3. Третья редакция.

Учтено после двух неудачных прогонов:
  * путь `/EntitySet/$count` отдаёт 404 — работает только `?$count=true&$top=0`;
  * `KNS_PlenumVote` НЕ имеет KnessetNum — режется по VoteDateTime,
    границы берутся из KNS_KnessetDates;
  * `KNS_Faction.Id` выдаётся ПО КАДЕНЦИИ — сшивка проверяется по названию;
  * ⚠️ страница жёстко 100 строк, `$top=200` МОЛЧА отдаёт 100.
    Вторая редакция скрипта на это наступила и считала фракции по первой
    сотне записей из 545. Отсюда fetch_all() с обходом @odata.nextLink.
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


def _get(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"__err__": str(e)[:200]}


def fetch_all(entity: str, params: str = "", cap: int = 20000) -> list[dict]:
    """Обход @odata.nextLink. Без него любая выборка молча обрезается сотней."""
    url = f"{BASE}/{entity}?$format=json" + (("&" + params) if params else "")
    out: list[dict] = []
    pages = 0
    while url and len(out) < cap:
        r = _get(url)
        if "__err__" in r:
            print(f"   !! {r['__err__']}")
            break
        out.extend(r.get("value", []))
        url = r.get("@odata.nextLink")
        pages += 1
        if url:
            time.sleep(0.35)
    print(f"   [{entity}: {len(out)} записей за {pages} стр.]")
    return out


def count(entity: str, flt: str = "") -> int | str:
    p = "$count=true&$top=0"
    if flt:
        p += "&$filter=" + urllib.parse.quote(flt)
    r = _get(f"{BASE}/{entity}?$format=json&{p}")
    return r.get("@odata.count", r.get("__err__", "?"))


def rule(t: str) -> None:
    print(f"\n{'=' * 76}\n{t}\n{'=' * 76}")


# ---- границы каденций ------------------------------------------------------
rule("Границы каденций (KNS_KnessetDates, 165 записей — по сессиям, не по каденциям)")
rows = fetch_all("KNS_KnessetDates", "$select=KnessetNum,PlenumStart,PlenumFinish")
bounds: dict[int, tuple[str, str]] = {}
for row in rows:
    k, s, f = row["KnessetNum"], row.get("PlenumStart"), row.get("PlenumFinish")
    if not s:
        continue
    f = f or s
    if k in bounds:
        bounds[k] = (min(bounds[k][0], s), max(bounds[k][1], f))
    else:
        bounds[k] = (s, f)
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

# ---- сшивка фракций (ПОЛНАЯ выборка) ---------------------------------------
rule("Сшиваются ли фракции между каденциями — полные 545 записей")
rows = fetch_all("KNS_Faction", "$select=Id,Name,KnessetNum&$orderby=KnessetNum")
by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
by_id: dict[int, set[str]] = defaultdict(set)
for row in rows:
    by_name[row["Name"]].append((row["KnessetNum"], row["Id"]))
    by_id[row["Id"]].add(row["Name"])

multi = {n: v for n, v in by_name.items() if len({k for k, _ in v}) > 1}
stable = [n for n, v in multi.items() if len({i for _, i in v}) == 1]
print(f"   уникальных названий: {len(by_name)}   в >1 каденции: {len(multi)}")
print(f"   с ОДНИМ Id во всех каденциях: {len(stable)}")
print(f"   с РАЗНЫМИ Id: {len(multi) - len(stable)}")
print("\n   самые долгоживущие названия:")
for n, v in sorted(multi.items(), key=lambda x: -len({k for k, _ in x[1]}))[:14]:
    ks = ",".join(str(k) for k in sorted({k for k, _ in v}))
    ids = sorted({i for _, i in v})
    mark = "ОДИН Id" if len(ids) == 1 else f"{len(ids)} разных Id"
    print(f"      {n[:32]:<34} [{ks[:34]:<34}] {mark}")

collide = {i: ns for i, ns in by_id.items() if len(ns) > 1}
print(f"\n   Id, под которыми в разных каденциях РАЗНЫЕ партии: {len(collide)}")
for i, ns in list(collide.items())[:5]:
    print(f"      Id {i}: {' | '.join(sorted(ns))[:90]}")

print("\n   фракции 25-го кнессета:")
for row in sorted([r for r in rows if r["KnessetNum"] == 25], key=lambda x: x["Id"]):
    print(f"      {row['Id']:>5}  {row['Name']}")

# ---- министры --------------------------------------------------------------
rule("Министерские записи (сырьё для criteria/periods.yaml)")
MIN_POS = {39: "שר", 40: "סגן שר", 45: "ראש הממשלה", 31: "משנה לרה\"מ",
           50: "סגן רה\"מ", 51: "מ\"מ רה\"מ"}
for k in (24, 25):
    tot = count("KNS_PersonToPosition", f"KnessetNum eq {k}")
    mins = count("KNS_PersonToPosition",
                 f"KnessetNum eq {k} and (PositionID eq 39 or PositionID eq 40 or PositionID eq 45)")
    print(f"   кнессет {k}: всего {tot}, из них министерских/замминистерских/премьер: {mins}")
    time.sleep(0.3)

rows = fetch_all("KNS_PersonToPosition",
                 "$filter=" + urllib.parse.quote("KnessetNum eq 25 and PositionID eq 39")
                 + "&$select=PersonID,GovMinistryName,StartDate,FinishDate", cap=300)
print(f"\n   министерских назначений в 25-м кнессете: {len(rows)}")
for row in rows[:10]:
    print(f"      person={row.get('PersonID'):<7}"
          f"{str(row.get('StartDate'))[:10]}..{str(row.get('FinishDate'))[:10]}  "
          f"{row.get('GovMinistryName')}")

print("\nготово")
