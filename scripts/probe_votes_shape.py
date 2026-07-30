#!/usr/bin/env python3
"""Разведка перед fetch_votes.py: работают ли фильтры и где мост MkId ↔ фракция.

§23-exempt: скрипт изучает, ПРИМЕНЯЕТ ли сервер $filter вообще. Ожидание объёма
здесь и есть предмет исследования, а не проверка — guarded_fetch скрыл бы ровно
то, что здесь выясняется.

Повод: инлайн-разведка 30.07 дала фильтр, который сервер молча проигнорировал
(вернулись голоса 2003 года на фильтр «после 2025»). Причина оказалась в
экранировании `$` при передаче команды через ssh, а не в сервере, — но именно
так и выглядит §23-отказ, и отличить одно от другого можно только скриптом
в файле, а не строкой в шелле.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"
K25_START = "2022-11-15T00:00:00Z"


def get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90, context=CTX) as r:
        return json.loads(r.read())


def count(entity: str, flt: str = "") -> int | str:
    url = f"{BASE}/{entity}?$format=json&$count=true&$top=0"
    if flt:
        url += "&$filter=" + urllib.parse.quote(flt)
    try:
        r = get(url)
    except Exception as e:                                   # noqa: BLE001
        return f"ERR {type(e).__name__}: {str(e)[:70]}"
    return r.get("@odata.count", "НЕТ ПОЛЯ @odata.count")


def sample(entity: str, flt: str = "", n: int = 3) -> list[dict]:
    url = f"{BASE}/{entity}?$format=json&$top={n}"
    if flt:
        url += "&$filter=" + urllib.parse.quote(flt)
    try:
        return get(url).get("value", [])
    except Exception as e:                                   # noqa: BLE001
        return [{"ERR": f"{type(e).__name__}: {str(e)[:70]}"}]


def main() -> int:
    print("=== 1. РАБОТАЕТ ЛИ $filter ВООБЩЕ ===")
    print("Признак работы: число с фильтром МЕНЬШЕ числа без него.\n")
    for ent, flt, why in (
        ("KNS_PlenumVote", f"VoteDateTime gt {K25_START}", "голосования 25-го Кнессета"),
        ("KNS_PlenumVoteResult", f"VoteDate gt {K25_START}", "поимённые 25-го"),
        ("KNS_PersonToPosition", "KnessetNum eq 25", "позиции 25-го"),
        ("KNS_PersonToPosition", "KnessetNum eq 25 and FactionID eq 1095", "ШАС в 25-м"),
    ):
        a, b = count(ent), count(ent, flt)
        works = isinstance(a, int) and isinstance(b, int) and b < a
        print(f"{ent:24} всего {a!s:>9} · с фильтром {b!s:>9} "
              f"{'✓ фильтр применён' if works else '⚠ ФИЛЬТР НЕ ПРИМЕНЁН ИЛИ РАВЕН'}  ({why})")

    print("\n=== 2. ДАТЫ В ВЫБОРКЕ СООТВЕТСТВУЮТ ФИЛЬТРУ ===")
    print("Проверка независима от счётчика: смотрим сами значения.\n")
    for r in sample("KNS_PlenumVoteResult", f"VoteDate gt {K25_START}", 3):
        print("   ", r.get("VoteDate"), r.get("LastName"), r.get("MkId"))

    print("\n=== 3. МОСТ MkId ↔ ФРАКЦИЯ ===")
    print("SOURCES: моста Person.Id ↔ vip_id в API нет. Проверяем на живых данных.\n")
    res = sample("KNS_PlenumVoteResult", f"VoteDate gt {K25_START}", 5)
    for r in res:
        mk = r.get("MkId")
        if mk is None:
            continue
        pers = sample("KNS_Person", f"Id eq {mk}", 1)
        pname = f"{pers[0].get('LastName')} {pers[0].get('FirstName')}" if pers else "НЕТ"
        pos = sample("KNS_PersonToPosition", f"PersonID eq {mk} and KnessetNum eq 25", 5)
        facs = {(p.get("FactionID"), p.get("FactionName")) for p in pos if p.get("FactionID")}
        same = pname.strip() == f"{r.get('LastName')} {r.get('FirstName')}".strip()
        print(f"   MkId {mk}: голос «{r.get('LastName')} {r.get('FirstName')}» · "
              f"Person «{pname}» {'СОВПАЛ' if same else '✗ РАЗНЫЕ ЛЮДИ'} · фракции {facs or '—'}")

    print("\n=== 4. СВЯЗЬ ГОЛОСОВАНИЯ С ЗАКОНОПРОЕКТОМ ===")
    v = sample("KNS_PlenumVote", f"VoteDateTime gt {K25_START}", 2)
    for x in v:
        print(f"   VoteId {x.get('Id')} ItemID {x.get('ItemID')} SessionID {x.get('SessionID')}")
        print(f"      ForOption: {x.get('ForOptionDesc')!r} · Against: {x.get('AgainstOptionDesc')!r}")
        print(f"      тема: {str(x.get('VoteSubject'))[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
