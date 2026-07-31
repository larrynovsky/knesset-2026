#!/usr/bin/env python3
"""Link-only замер: чем голосование сцепляется с законопроектом, по классам.

§23-exempt: предмет изучения — покрытие прямого ключа. Ожидание объёма здесь и
есть искомое; сами ожидания объявлены заранее в
criteria/declared_before_link_2026-07-31.yaml (P7-P10) и закоммичены раньше.

Ничего не чинит и ничего не пишет в data/. Печатает распределение по классам.
Поимённые результаты НЕ качает: трёхсуточную классификацию до закрытия этой
границы запускать нельзя.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from guarded_fetch import fetch_all          # noqa: E402  §23
from classify_direction import norm_he       # noqa: E402

K25_START, K25_END = "2022-11-15", "2026-07-18"


def main() -> int:
    scan = json.loads((ROOT / "data" / "bills_scan.json").read_text(encoding="utf-8"))
    corpus = {m["id"]: m for m in scan["matched"]}
    print(f"перепись: {len(corpus)} актов")

    # P10: во что превращается перепись при схлопывании по имени
    by_alias: dict[str, set] = collections.defaultdict(set)
    for m in scan["matched"]:
        by_alias[norm_he(m["name"])].add(m["id"])
    collapsed = len(corpus) - len(by_alias)
    print(f"P10 · уникальных имён: {len(by_alias)} · актов теряется при "
          f"схлопывании: {collapsed}")

    heads = fetch_all(
        "KNS_PlenumVote",
        flt=f"VoteDateTime ge {K25_START} and VoteDateTime lt {K25_END}",
        select="Id,VoteDateTime,ItemID,SessionID,VoteTitle")
    print(f"голосований 25-го Кнессета: {len(heads)}")

    items = fetch_all("KNS_PlmSessionItem",
                      select="ItemID,PlenumSessionID,ItemTypeID,ItemTypeDesc")
    print(f"пунктов повестки всего: {len(items)}")

    # ключ (сессия, пункт) → тип. Один пункт может встречаться в сессии
    # несколько раз (Ordinal), тип при этом обязан совпадать.
    typ: dict[tuple, set] = collections.defaultdict(set)
    by_item: dict[int, set] = collections.defaultdict(set)
    for it in items:
        typ[(it["PlenumSessionID"], it["ItemID"])].add(it["ItemTypeID"])
        by_item[it["ItemID"]].add(it["ItemTypeID"])

    # P8: тип 2 обязан означать «идентификатор из пространства законопроектов»
    bills_all = fetch_all("KNS_Bill", flt="KnessetNum eq 25", select="Id")
    bill_ids = {b["Id"] for b in bills_all}
    t2 = {i for i, ts in by_item.items() if 2 in ts}
    in_bill = len(t2 & bill_ids)
    print(f"P8 · пунктов с типом 2: {len(t2)} · из них есть в KNS_Bill 25-го: "
          f"{in_bill} ({in_bill / max(len(t2), 1):.3f})")

    cls = collections.Counter()
    types_seen = collections.Counter()
    direct_bills = set()
    for h in heads:
        key = (h.get("SessionID"), h.get("ItemID"))
        ts = typ.get(key)
        if ts is None:
            cls["нет пункта повестки"] += 1
            continue
        for t in ts:
            types_seen[t] += 1
        if len(ts) > 1:
            cls["тип пункта неоднозначен"] += 1
        elif 2 in ts:
            iid = h.get("ItemID")
            if iid in corpus:
                cls["direct_bill_id · в переписи"] += 1
                direct_bills.add(iid)
            elif iid in bill_ids:
                cls["direct_bill_id · вне переписи"] += 1
            else:
                cls["тип 2, но ItemID не законопроект"] += 1
        else:
            cls["non_bill_item"] += 1

    print("\nРАЗБИЕНИЕ ВСЕХ ЗАГОЛОВКОВ ПО КЛАССАМ:")
    for k, n in cls.most_common():
        print(f"   {n:>6}  {k}")
    total = sum(cls.values())
    print(f"   {'-' * 6}")
    print(f"   {total:>6}  сумма — {'СОШЛАСЬ' if total == len(heads) else 'НЕ СОШЛАСЬ'}"
          f" с {len(heads)}")
    # Разбиение обязано быть полным. Неполное — тихая потеря, а тихая потеря на
    # этом проекте уже трижды выглядела как аккуратный отчёт. Поэтому отказ, а
    # не строчка в выводе: разведка тоже не имеет права врать успехом.
    assert total == len(heads), (
        f"классы не покрывают все заголовки: {total} против {len(heads)}. "
        "Где-то запись выпала из разбиения молча.")

    print(f"\nактов переписи, достигнутых прямым ключом: {len(direct_bills)}")
    print("\nтипы пунктов, встреченные у голосований (топ):")
    desc = {i["ItemTypeID"]: i["ItemTypeDesc"] for i in items}
    for t, n in types_seen.most_common(8):
        print(f"   тип {t:<4} {n:>6}  {desc.get(t, '?')}")

    # P7: восстанавливает ли прямой ключ то, что сшивалось по имени
    old = Path("/tmp/votes_25_OLD.json")
    if not old.exists():
        old = Path.home() / "knesset_votes_25_OLD_backup.json"
    if old.exists():
        o = json.loads(old.read_text(encoding="utf-8"))
        old_pairs = {(r["vote_id"], r["bill_id"]) for r in o["rows"]}
        got = sum(1 for h in heads if (h["Id"], h.get("ItemID")) in old_pairs)
        print(f"\nP7 · прежних пар (голосование, акт) подтверждено прямым "
              f"ключом: {got} из {len(old_pairs)}")
        lost3 = {1042100, 1057405, 1057406}
        print(f"P7 · три потерянных акта достигнуты: "
              f"{sorted(lost3 & direct_bills)} из {sorted(lost3)}")
    else:
        print("\nP7 · эталона нет — сверять не с чем, и это надо сказать вслух")
    return 0


if __name__ == "__main__":
    sys.exit(main())
