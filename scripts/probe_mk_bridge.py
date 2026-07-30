#!/usr/bin/env python3
"""Разведка-3: почему мост MkId → фракция покрыл лишь 22,5% голосов.

§23-exempt: предмет изучения — состав пространств идентификаторов.

Что случилось. Первая проверка моста (probe_votes_shape, пять депутатов)
дала «3 из 5 совпали» и я записал в коммит, что свод неточен и мост есть.
Прогон на 2869 голосах показал обратное: 77,5% не сшиваются, ШАС получила
десять голосов вместо сотен. Пять примеров не были выборкой — совпали
старые депутаты, у которых Person.Id и vip_id исторически равны.
Свод (SOURCES, ловушка 3) оказался прав, а я поспешил.

Здесь проверяются три кандидата на мост, по возрастанию цены ошибки:
  A. KNS_Person: есть ли в самой сущности поле с альтернативным id;
  B. ФИО: LastName+FirstName из голоса ↔ KNS_Person. Дёшево, но однофамильцы;
  C. KNS_MkSiteCode: KnsID ↔ SiteId — третье пространство, вдруг оно мостит.
"""
from __future__ import annotations

import collections
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


def nm(s) -> str:
    return " ".join(str(s or "").split()).strip()


def main() -> int:
    print("=== A. ПОЛЯ KNS_Person — есть ли альтернативный id ===")
    p1 = get(f"{BASE}/KNS_Person?$format=json").get("value", [])
    print("   ", list(p1[0].keys()) if p1 else "пусто")

    print("\n=== B. СШИВКА ПО ФИО ===")
    pos = page("KNS_PersonToPosition", "KnessetNum eq 25",
               select="PersonID,FactionID,FactionName")
    fac_by_person = {p["PersonID"]: (p["FactionID"], p["FactionName"])
                     for p in pos if p.get("FactionID")}
    persons = page("KNS_Person", "", select="Id,LastName,FirstName")
    by_name = collections.defaultdict(set)
    for p in persons:
        by_name[(nm(p.get("LastName")), nm(p.get("FirstName")))].add(p["Id"])
    print(f"   персон в KNS_Person: {len(persons)} · с фракцией 25-го: {len(fac_by_person)}")

    res = page("KNS_PlenumVoteResult", f"VoteDate gt {K25}",
               select="MkId,LastName,FirstName", limit=20000)
    voters = {}
    for r in res:
        voters[r["MkId"]] = (nm(r.get("LastName")), nm(r.get("FirstName")))
    print(f"   уникальных голосующих (по первым {len(res)} голосам): {len(voters)}")

    direct = sum(1 for mk in voters if mk in fac_by_person)
    by_nm_ok, ambiguous, absent = 0, 0, 0
    resolved = {}
    for mk, key in voters.items():
        cands = by_name.get(key, set())
        withfac = {c for c in cands if c in fac_by_person}
        if len(withfac) == 1:
            by_nm_ok += 1
            resolved[mk] = fac_by_person[withfac.pop()]
        elif len(withfac) > 1:
            ambiguous += 1
        else:
            absent += 1
    print(f"   прямой мост MkId==PersonID:      {direct}/{len(voters)} "
          f"({direct/max(len(voters),1):.0%})")
    print(f"   мост по ФИО, однозначно:         {by_nm_ok}/{len(voters)} "
          f"({by_nm_ok/max(len(voters),1):.0%})")
    print(f"   ФИО совпало с НЕСКОЛЬКИМИ:       {ambiguous}   (догадка запрещена)")
    print(f"   ФИО не нашлось с фракцией:       {absent}")

    facs = collections.Counter(v[1] for v in resolved.values())
    print("\n   фракции после сшивки по ФИО:")
    for f, n in facs.most_common():
        print(f"      {str(f)[:44]:46} персон {n}")

    print("\n=== C. KNS_MkSiteCode как третий мост ===")
    site = page("KNS_MkSiteCode", limit=3000)
    kns_ids = {s["KnsID"] for s in site}
    print(f"   записей: {len(site)} · MkId голосующих, найденных в KnsID: "
          f"{len(set(voters) & kns_ids)}/{len(voters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
