#!/usr/bin/env python3
"""Диагностика: почему соединение KNS_Faction.Id <-> P2P.FactionID дало ноль.

§23-exempt: скрипт изучает СЫРОЕ поведение форм запросов и намеренно смотрит
на неполные выборки; ожидание объёма здесь и есть предмет изучения.

Повод: build_lineage_candidates отчитался «545 фракций, 545 без состава,
0 развилок» — ложный зелёный. Соединение вернуло пустоту, и скрипт прочитал
это как «всё авторазрешилось».

Отдельный урок метода: первую диагностику я сделал ssh-однострочником с
вложенным экранированием, `$`-параметры потерялись, и выдача выглядела как
«сервер игнорирует $filter». Диагностика тем же способом, что и ошибка.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from collections import Counter

CTX = ssl.create_default_context()
B = "https://knesset.gov.il/OdataV4/ParliamentInfo/"


def g(entity: str, **params) -> dict:
    qs = "&".join(f"${k}=" + urllib.parse.quote(str(v)) for k, v in params.items())
    url = f"{B}{entity}?$format=json" + ("&" + qs if qs else "")
    req = urllib.request.Request(url, headers={"User-Agent": "knesset-research/0.1"})
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        return json.loads(r.read())


print("=== 1. работает ли $filter вообще ===")
r = g("KNS_Faction", filter="KnessetNum eq 25", select="Id,Name,KnessetNum")
kn = Counter(x["KnessetNum"] for x in r["value"])
print(f"   строк: {len(r['value'])}  каденции в выдаче: {dict(kn)}")
print(f"   пример Id: {[x['Id'] for x in r['value'][:5]]}")

print("\n=== 2. соблюдается ли $top ===")
for t in (1, 5, 50):
    rr = g("KNS_Faction", top=t, select="Id")
    print(f"   $top={t:<3} -> получено {len(rr['value'])}")

print("\n=== 3. FactionID в MK-записях по каденциям ===")
for k in (20, 24, 25):
    rr = g("KNS_PersonToPosition", filter=f"KnessetNum eq {k} and PositionID eq 43",
           select="PersonID,FactionID,FactionName")
    vals = rr["value"]
    withf = [x for x in vals if x.get("FactionID")]
    print(f"   к{k}: строк {len(vals)}, с FactionID {len(withf)}")
    if withf:
        print(f"       примеры: {[(x['FactionID'], (x.get('FactionName') or '')[:20]) for x in withf[:3]]}")

print("\n=== 4. пересекаются ли пространства Id ===")
fac = g("KNS_Faction", filter="KnessetNum eq 25", select="Id,Name")["value"]
fac_ids = {x["Id"] for x in fac}
p2p = g("KNS_PersonToPosition", filter="KnessetNum eq 25 and PositionID eq 43",
        select="FactionID,FactionName")["value"]
p2p_ids = {x["FactionID"] for x in p2p if x.get("FactionID")}
print(f"   KNS_Faction.Id (к25):   {sorted(fac_ids)}")
print(f"   P2P.FactionID (к25):    {sorted(p2p_ids)}")
print(f"   пересечение:            {sorted(fac_ids & p2p_ids)}")

print("\n=== 5. если Id не сходятся — сходятся ли имена ===")
fac_names = {(x["Name"] or "").strip() for x in fac}
p2p_names = {(x.get("FactionName") or "").strip() for x in p2p if x.get("FactionName")}
print(f"   имён в KNS_Faction: {len(fac_names)}, в P2P: {len(p2p_names)}, "
      f"совпало: {len(fac_names & p2p_names)}")
only_p2p = p2p_names - fac_names
if only_p2p:
    print(f"   только в P2P: {sorted(only_p2p)[:6]}")

print("\n=== 6. есть ли у P2P свой справочник фракций ===")
allp = g("KNS_PersonToPosition", filter="PositionID eq 43 and FactionID ne null",
         select="FactionID,FactionName,KnessetNum")["value"]
print(f"   первая страница: {len(allp)} строк, уникальных FactionID: "
      f"{len({x['FactionID'] for x in allp})}")
print(f"   диапазон FactionID: {min(x['FactionID'] for x in allp)}..{max(x['FactionID'] for x in allp)}")

print("\n=== 7. у КАКИХ должностей FactionID вообще заполнен ===")
pos = {p["Id"]: p["Description"] for p in g("KNS_Position", select="Id,Description")["value"]}
for pid, desc in sorted(pos.items()):
    try:
        n = g("KNS_PersonToPosition", top=0, count="true",
              filter=f"PositionID eq {pid} and FactionID ne null")["@odata.count"]
    except Exception as e:  # noqa: BLE001
        n = f"err {str(e)[:20]}"
    tot = g("KNS_PersonToPosition", top=0, count="true",
            filter=f"PositionID eq {pid}")["@odata.count"]
    if n:
        print(f"   pos {pid:<4} {desc[:28]:<30} с FactionID: {n} из {tot}")

print("\n=== 8. что предлагает Open Knesset ===")
import urllib.error  # noqa: E402
LIST = ("https://storage.googleapis.com/storage/v1/b/knesset-data-pipelines/o"
        "?prefix=data/members/&delimiter=/")
try:
    req = urllib.request.Request(LIST, headers={"User-Agent": "knesset-research/0.1"})
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        d = json.loads(r.read())
    for p in d.get("prefixes", []):
        print(f"   {p}")
except Exception as e:  # noqa: BLE001
    print(f"   не удалось: {str(e)[:120]}")

for name in ("data/members/mk_individual/faction_memberships.csv",
             "data/members/mk_individual/factions.csv",
             "data/members/mk_individual/mk_individual.csv"):
    u = "https://storage.googleapis.com/knesset-data-pipelines/" + name
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "knesset-research/0.1",
                                                 "Range": "bytes=0-600"})
        with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
            head = r.read().decode("utf-8", "replace").splitlines()[:3]
        print(f"\n   ✓ {name}")
        for line in head:
            print(f"       {line[:150]}")
    except Exception as e:  # noqa: BLE001
        print(f"\n   ✗ {name}: {str(e)[:80]}")
