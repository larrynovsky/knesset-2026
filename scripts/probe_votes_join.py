#!/usr/bin/env python3
"""Разведка-2: чем голосование сцепляется с законопроектом и все ли MkId сшиваются.

§23-exempt: предмет изучения — существуют ли мосты вообще. Ожидание объёма
здесь не проверка, а искомое.

Что уже выяснено probe_votes_shape.py (30.07):
  · $filter применяется; 25-й Кнессет — 7558 голосований, 526 517 поимённых;
  · MkId и KNS_Person.Id совпали у 3 из 5 проверенных, у двух новых депутатов
    Person не нашёлся. SOURCES утверждает «моста нет» — данные говорят
    «мост частичный». Пять человек — не выборка, здесь считаем всех.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"
K25 = "2022-11-15T00:00:00Z"


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=120, context=CTX) as r:
        return json.loads(r.read())


def page(entity: str, flt: str = "", select: str = "", limit: int = 100000):
    """Полный обход nextLink. $top игнорируется сервером, страница жёстко 100."""
    url = f"{BASE}/{entity}?$format=json"
    if flt:
        url += "&$filter=" + urllib.parse.quote(flt)
    if select:
        url += "&$select=" + select
    out = []
    while url and len(out) < limit:
        r = get(url)
        out.extend(r.get("value", []))
        url = r.get("@odata.nextLink")
    return out


def probe_entity(name: str) -> None:
    try:
        v = get(f"{BASE}/{name}?$format=json").get("value", [])
        print(f"   {name:26} ПОЛЯ: {list(v[0].keys()) if v else 'пусто'}")
    except Exception as e:                                   # noqa: BLE001
        print(f"   {name:26} нет ({type(e).__name__})")


def main() -> int:
    print("=== 5. ЧЕМ ГОЛОСОВАНИЕ СЦЕПЛЯЕТСЯ С ЗАКОНОПРОЕКТОМ ===")
    print("VoteSubject у голосований 25-го пуст; остаётся ItemID. Ищем сущность-мост.\n")
    for e in ("KNS_PlenumSessionItem", "KNS_DocumentBill", "KNS_BillName",
              "KNS_ItemType", "KNS_PlenumSession", "KNS_BillHistoryInitiator"):
        probe_entity(e)

    print("\n=== 6. ЗАПОЛНЕН ЛИ VoteTitle У 25-го ===")
    v = page("KNS_PlenumVote", f"VoteDateTime gt {K25}", limit=200)
    titled = sum(1 for x in v if str(x.get("VoteTitle") or "").strip())
    subj = sum(1 for x in v if str(x.get("VoteSubject") or "").strip())
    print(f"   из {len(v)} голосований: VoteTitle заполнен у {titled}, VoteSubject у {subj}")
    for x in v[:3]:
        print(f"      {x['Id']}: title={str(x.get('VoteTitle'))[:70]!r}")

    print("\n=== 7. ПОКРЫТИЕ МОСТА MkId → фракция (§23: join объявляет ожидание) ===")
    print("   Ожидание: 120 мандатов + замены по норме Норвежского закона.")
    pos = page("KNS_PersonToPosition", "KnessetNum eq 25",
               select="PersonID,FactionID,FactionName,PositionID,StartDate,FinishDate")
    by_person = {}
    for p in pos:
        if p.get("FactionID"):
            by_person.setdefault(p["PersonID"], set()).add((p["FactionID"], p["FactionName"]))
    print(f"   позиций 25-го: {len(pos)} · персон с фракцией: {len(by_person)}")

    res = page("KNS_PlenumVoteResult", f"VoteDate gt {K25}", select="MkId", limit=30000)
    mks = {r["MkId"] for r in res if r.get("MkId") is not None}
    matched = mks & set(by_person)
    print(f"   уникальных MkId в первых {len(res)} голосах: {len(mks)}")
    print(f"   из них сшиваются с фракцией: {len(matched)} ({len(matched)/max(len(mks),1):.0%})")
    missing = sorted(mks - set(by_person))[:12]
    print(f"   НЕ сшиваются (первые): {missing}")

    facs = {}
    for pid in matched:
        for f in by_person[pid]:
            facs.setdefault(f, 0)
            facs[f] += 1
    print("\n   фракции, найденные через мост:")
    for (fid, fname), n in sorted(facs.items(), key=lambda x: -x[1]):
        print(f"      {fid} {fname!r:34} персон {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
