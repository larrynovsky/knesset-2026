#!/usr/bin/env python3
"""Ф22 — диагноз канала А: по каким голосованиям известна позиция фракции.

Вопрос пришёл из голландских данных: в Tweede Kamer поимённо проходит около
1,5% голосований, но позиция каждой ФРАКЦИИ известна почти по 100%, потому
что при голосовании поднятием рук фиксируется результат по фракциям. Если
Кнессет устроен так же — канал А расширяется. Если нет — по решению
владельца (B-14, вариант «а») он объявляется измеряющим самопрезентацию.

ПЕРВАЯ РЕДАКЦИЯ ЭТОГО СКРИПТА ДАЛА ОТВЕТ ПРЕЖДЕВРЕМЕННО. Она сравнивала
среднее число поимённых записей на голосование (69,6) с числом мест в
Кнессете (120) и заключала «значит записи есть не у всех». Но 120 — это
списочный состав, а не явка; 69,6 — правдоподобная явка, и из неё НИЧЕГО не
следует. Плюс редакция не заметила поле VoteMethodDesc, которое отвечает на
вопрос прямо. Ошибка того же класса, что уже случалась в проекте: механизм
построен, выдал число, и число было прочитано в удобную сторону.

Здесь считается то, что отвечает на вопрос:
  1) распределение голосований по ЗАЯВЛЕННОМУ методу (VoteMethodDesc);
  2) у скольких голосований реально есть поимённые записи — выборкой;
  3) сколько голосований покрывает наша выгрузка (data/votes_25.json).

§23-exempt: чтение $metadata — это схема, а не данные; объёма у неё нет и
объявлять нечего. Все выгрузки и счётчики ниже идут через guarded_fetch.

    python3 scripts/probe_vote_publicity.py
"""
from __future__ import annotations

import json
import random
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guarded_fetch as gf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MD = "https://knesset.gov.il/OdataV4/ParliamentInfo/$metadata"
K25_START = "2022-11-15T00:00:00Z"
K25_END = "2026-12-31T00:00:00Z"
SAMPLE = 40
SEED = 20260731


def schema_vote_entities() -> dict[str, list[str]]:
    raw = urllib.request.urlopen(MD, timeout=90).read().decode("utf-8", "replace")
    out = {}
    for name, body in re.findall(r'<EntityType Name="([^"]+)"(.*?)</EntityType>',
                                 raw, re.S):
        if "vote" in name.lower() or "faction" in name.lower():
            out[name] = re.findall(r'Property Name="([A-Za-z0-9_]+)"', body)
    return out


def main() -> int:
    print("=" * 72)
    print("Ф22: по каким голосованиям известна позиция ФРАКЦИИ")
    print("=" * 72)

    ents = schema_vote_entities()
    frac_vote = [n for n in ents if "faction" in n.lower() and "vote" in n.lower()]
    print(f"\n1. Сущностей со словом Vote/Faction: {len(ents)} — {sorted(ents)}")
    print(f"   Сущность «голосование x фракция»: "
          f"{frac_vote if frac_vote else 'НЕТ'}")

    flt = f"VoteDateTime ge {K25_START} and VoteDateTime lt {K25_END}"
    votes = gf.fetch_all("KNS_PlenumVote", flt=flt,
                         select="Id,VoteMethodID,VoteMethodDesc,VoteStatusDesc")
    print(f"\n2. Голосований пленума за 25-й Кнессет: {len(votes)}")
    print("   Распределение по ЗАЯВЛЕННОМУ методу голосования:")
    for desc, n in Counter((v.get("VoteMethodDesc") or "—") for v in votes).most_common():
        print(f"      {n:6d}  {desc}")
    print("   По статусу:")
    for desc, n in Counter((v.get("VoteStatusDesc") or "—") for v in votes).most_common():
        print(f"      {n:6d}  {desc}")

    # 3. Есть ли поимённые записи — проверяем выборкой, а не выгрузкой полумиллиона
    ids = sorted(v["Id"] for v in votes)
    sample = random.Random(SEED).sample(ids, min(SAMPLE, len(ids)))
    with_named, without = [], []
    for vid in sample:
        n = gf.count("KNS_PlenumVoteResult", f"VoteID eq {vid}")
        (with_named if n else without).append((vid, n))
    print(f"\n3. Случайная выборка {len(sample)} голосований (зерно {SEED}):")
    print(f"   с поимёнными записями: {len(with_named)}")
    print(f"   БЕЗ поимённых записей: {len(without)}")
    if with_named:
        got = [n for _, n in with_named]
        print(f"   голосов в записи: мин {min(got)}, медиана "
              f"{sorted(got)[len(got)//2]}, макс {max(got)}")
    if without:
        print(f"   примеры пустых: {[v for v, _ in without[:5]]}")

    # 4. Что покрывает наша выгрузка
    ours = ROOT / "data" / "votes_25.json"
    if ours.exists():
        d = json.loads(ours.read_text(encoding="utf-8"))
        rows = d.get("rows") or d.get("votes") or []
        print(f"\n4. Наша выгрузка data/votes_25.json: {len(rows)} голосований "
              f"= {100*len(rows)/max(len(votes),1):.1f}% от {len(votes)}")
    else:
        print("\n4. data/votes_25.json на этой машине нет")

    print("\n5. ЧТО ИЗ ЭТОГО СЛЕДУЕТ — читать вместе с числами выше, не вместо.")
    share = len(with_named) / len(sample) if sample else 0
    if frac_vote:
        print("   Есть отдельная сущность с фракционным результатом: позиция")
        print("   фракции известна независимо от поимённости. Канал А расширяется.")
    elif share >= 0.95:
        print(f"   Поимённые записи есть практически у всех ({share:.0%} выборки).")
        print("   Отдельной фракционной сущности нет, но она и не нужна:")
        print("   позиция фракции выводится из поимённых голосов по всем")
        print("   голосованиям. Возражение о самоотборе СНИМАЕТСЯ, и снимается")
        print("   не нами. Тогда наши 258 — это наш собственный фильтр, а не")
        print("   ограничение источника, и вот это надо объяснять отдельно.")
    else:
        print(f"   Поимённые записи есть у {share:.0%} выборки, отдельной")
        print("   фракционной сущности нет. Позиция фракции существует ровно")
        print("   там, где голосование было поимённым, а поимённость —")
        print("   решение самих партий. B-14, вариант (а): канал А меряет")
        print("   самопрезентацию, и это пишется в отчёте открытым текстом.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except gf.ShortRead as exc:
        print(f"\n§23 ОТКАЗ: {exc}", file=sys.stderr)
        sys.exit(1)
