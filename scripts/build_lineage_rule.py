#!/usr/bin/env python3
"""Преемственность партий по объявленному правилу. Без вопросов человеку.

РЕШЕНИЕ ВЛАДЕЛЬЦА 2026-07-28: вместо 39 частных суждений — одно правило,
применяемое одинаково ко всем. Причина: владелец не эксперт в израильской
политике (иначе проект был бы не нужен), а публичный документ, где читатель
спорит С ПРАВИЛОМ, честнее документа, где он спорит с осведомлённостью автора.
Та же логика, по которой отвергнут суммарный балл (§13).

ПРАВИЛО:
    Фракции разных каденций принадлежат одной линии, если больше половины
    состава КАЖДОЙ из них — одни и те же люди.

Симметрия несущая. «Большинство B пришло из A» в одиночку склеило бы с Ликудом
каждую однодневную фракцию перебежчика (2026-07-28 это уже случилось однажды).
«Большинство A ушло в B» в одиночку сломалось бы на расколе пополам.
Вместе — «это по большей части те же люди».

ЧТО ПРАВИЛО ДЕЛАЕТ, принято заранее:
  * расколы не сливаются с материнской партией;
  * раскол пополам даёт две новые линии — ни одна половина не «главнее»;
  * смена названия при сохранении людей — одна линия;
  * сохранение названия при смене всех людей — две линии. Случай Аводы
    между к21 и к23. Юридически неверно, по объявленному правилу честно.

ГЛУБИНА: с 16-го Кнессета (17.02.2003). Владелец просил ограничить 2000-м
годом; фактический предел жёстче и задан данными — поимённых голосований
раньше нет вовсе. Бюджетный канал (данные с 1997) режется той же датой:
три года с одним каналом из двух — это риск R-E, где молчание канала А
читается как «партия не голосовала за».
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all, require_join  # noqa: E402

MAJORITY = 0.5
FIRST_KNESSET = 16
MEMBER_POSITION = 54
OUT = Path(__file__).resolve().parent.parent / "criteria" / "party_lineage.yaml"
OUT_JSON = OUT.with_suffix(".json")


def main() -> int:
    factions = [f for f in fetch_all("KNS_Faction", select="Id,Name,KnessetNum")
                if f["KnessetNum"] >= FIRST_KNESSET]
    mem = fetch_all("KNS_PersonToPosition", flt=f"PositionID eq {MEMBER_POSITION}",
                    select="PersonID,FactionID,KnessetNum")
    fac = {f["Id"]: f for f in factions}
    members: dict[int, set] = defaultdict(set)
    for m in mem:
        if m.get("FactionID") in fac:
            members[m["FactionID"]].add(m["PersonID"])
    require_join(set(fac), set(members), "Faction <-> состав", min_overlap=100)

    by_k: dict[int, list[int]] = defaultdict(list)
    for i, f in fac.items():
        by_k[f["KnessetNum"]].append(i)

    # --- применение правила ---------------------------------------------------
    links = []
    ks = sorted(by_k)
    for k, nxt in zip(ks, ks[1:]):
        for a in by_k[k]:
            A = members.get(a, set())
            if not A:
                continue
            for b in by_k[nxt]:
                B = members.get(b, set())
                if not B:
                    continue
                shared = len(A & B)
                if shared / len(A) > MAJORITY and shared / len(B) > MAJORITY:
                    links.append((a, b, shared, round(shared / len(A), 2),
                                  round(shared / len(B), 2)))

    parent = {i: i for i in fac}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, *_ in links:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    lines: dict[int, list[int]] = defaultdict(list)
    for i in fac:
        lines[find(i)].append(i)

    assert sum(len(v) for v in lines.values()) == len(fac), "покрытие нарушено"
    # Оракул правила: фракция не может попасть в две линии одновременно.
    seen = set()
    for v in lines.values():
        assert not (seen & set(v)), "фракция в двух линиях"
        seen |= set(v)

    out_lines = []
    for root, ids in lines.items():
        ids = sorted(ids, key=lambda i: fac[i]["KnessetNum"])
        kns = [fac[i]["KnessetNum"] for i in ids]
        names = []
        for i in ids:
            n = fac[i]["Name"].strip()
            if n not in names:
                names.append(n)
        out_lines.append({"line_id": f"L{root}", "faction_ids": ids, "knessets": kns,
                          "names": names, "reaches_ballot": max(kns) >= 25,
                          "size_max": max(len(members.get(i, set())) for i in ids)})
    out_lines.sort(key=lambda x: (not x["reaches_ballot"], -x["size_max"]))

    ballot = [l for l in out_lines if l["reaches_ballot"]]
    hdr = [
        "# party_lineage — преемственность партий. v1.0, 2026-07-28.",
        "#",
        "# ПРАВИЛО (применено механически, вопросов человеку нет):",
        "#   Фракции разных каденций принадлежат одной линии, если больше",
        "#   половины состава КАЖДОЙ из них — одни и те же люди.",
        "#",
        "# Принято заранее: расколы не сливаются с материнской партией; раскол",
        "# пополам даёт две линии; смена названия при тех же людях — одна линия;",
        "# смена всех людей при том же названии — две линии (случай Аводы к21/к23,",
        "# юридически неверно, по объявленному правилу честно).",
        "#",
        f"# Глубина: с {FIRST_KNESSET}-го Кнессета (17.02.2003) — предел задан данными,",
        "# поимённых голосований раньше нет. Бюджетный канал режется той же датой.",
        "#",
        "# Файл СГЕНЕРИРОВАН scripts/build_lineage_rule.py. Правки — через правило.",
        f'version: "1.0"',
        f"rule: \"больше половины состава каждой фракции — одни и те же люди\"",
        f"majority: {MAJORITY}",
        f"first_knesset: {FIRST_KNESSET}",
        f"factions: {len(fac)}",
        f"lines: {len(out_lines)}",
        f"lines_reaching_ballot: {len(ballot)}",
        "", "lines:"]
    for l in out_lines:
        hdr += [f"  - line_id: {l['line_id']}",
                f"    reaches_ballot_2026: {str(l['reaches_ballot']).lower()}",
                f"    knessets: {l['knessets']}",
                f"    faction_ids: {l['faction_ids']}",
                f"    names: {json.dumps(l['names'], ensure_ascii=False)}"]
    OUT.write_text("\n".join(hdr) + "\n", encoding="utf-8")
    OUT_JSON.write_text(json.dumps(
        {"rule": "больше половины состава каждой фракции — одни и те же люди",
         "majority": MAJORITY, "first_knesset": FIRST_KNESSET,
         "lines": out_lines,
         "links": [{"a": a, "b": b, "shared": s, "of_a": oa, "of_b": ob}
                   for a, b, s, oa, ob in links]},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"фракций {len(fac)} · связей по правилу {len(links)} · линий {len(out_lines)}")
    print(f"линий, доходящих до бюллетеня 2026: {len(ballot)}\n")
    for l in ballot:
        print(f"  к{str(l['knessets'][0]):<3}→к{str(l['knessets'][-1]):<3} "
              f"фракций {len(l['faction_ids']):>2}  {' / '.join(l['names'][:3])[:76]}")
    print(f"\n{OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
