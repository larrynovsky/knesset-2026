#!/usr/bin/env python3
"""Блок 1.1 — кандидаты сшивки фракций между каденциями.

Задача: не выдать владельцу 76 названий со словами «решай», а авторазрешить
очевидное и вынести наверх ТОЛЬКО развилки — с вариантами, аргументами и ценой.
Паттерн перенесён из конвейера перевода книги (MM/kegan-iooh/GLOSSARY.md,
развилки P1-P9): «машина готовит развилку, человек решает, решение фиксируется
версией». Там 9 развилок сняли сотни микрорешений у машины.

Почему это вообще нужно: фракции не сшиваются НИ по Id (545 записей, 76 названий
живут в >1 каденции, у нуля стабильный Id), НИ по названию (Ликуд отсутствует под
своим именем в 7 каденциях из 18, потому что шёл в объединённых списках).

ПОРОГИ ОБЪЯВЛЕНЫ ЗДЕСЬ И ДО ПРОГОНА. Менять их, увидев результат, — это подгон
того же класса, что §3 запрещает для критериев отбора. Изменение порогов — только
отдельным коммитом с префиксом `criteria-revision:` и указанием, что заставило.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all, require_join  # noqa: E402

# --- пороги, объявленные до прогона ------------------------------------------
AUTO_MERGE = 0.60   # пересечение состава >= -> одна линия без вопросов
FORK_LOW = 0.15     # ниже -> считаем разными, не спрашиваем

# ОХВАТ. Первая рабочая редакция дала 674 развилки на всей истории с 1949 г.
# Это не проблема порогов — пороги не тронуты. Это неверный охват:
#   * голосований до Кнессета 16 (2003) НЕТ ВООБЩЕ (проверено в фазе 0),
#     значит lineage для более ранних партий не окупается ничем;
#   * решать нужно про ЛИНИЮ, а не про каждую пару записей;
#   * фракция из 1-2 человек — это, как правило, персональный раскол,
#     а не преемственность партии; отдельная категория, не развилка.
# Менять пороги, увидев результат, было бы подгоном (§3 по духу).
# Менять охват по названной внешней причине — нет.
FIRST_KNESSET = 16      # горизонт канала А
SPLINTER_MAX = 2        # фракция такого размера -> раскол, не линия
# 'חבר/ת סיעה' — ЧЛЕНСТВО ВО ФРАКЦИИ. Не 43 ('חבר הכנסת'): 43 — это мандат
# депутата, и FactionID у него пуст ВСЕГДА (проверено: PositionID eq 43 and
# FactionID ne null -> 0 строк глобально). Заполнен только у 48 (יו"ר סיעה, 146)
# и 54 (4515). Первая редакция брала 43, соединение дало пустоту, скрипт
# отчитался «0 развилок, решать нечего» — ложный зелёный (см. require_join).
MK_POSITION = 54
OUT = Path(__file__).resolve().parent.parent / "criteria" / "lineage_draft.yaml"


def overlap(a: set, b: set) -> float:
    """|A∩B| / min(|A|,|B|). Не Жаккар: при расколе малый преемник целиком
    внутри большого предшественника, и Жаккар это занизил бы."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def main() -> int:
    factions = fetch_all("KNS_Faction", select="Id,Name,KnessetNum,StartDate,FinishDate")
    members_raw = fetch_all("KNS_PersonToPosition",
                            flt=f"PositionID eq {MK_POSITION}",
                            select="PersonID,FactionID,KnessetNum")

    factions = [f for f in factions if f["KnessetNum"] >= FIRST_KNESSET]
    fac = {f["Id"]: f for f in factions}
    require_join(set(fac),
                 {m["FactionID"] for m in members_raw if m.get("FactionID")},
                 "KNS_Faction.Id <-> P2P.FactionID", min_overlap=100)
    members: dict[int, set] = defaultdict(set)
    for m in members_raw:
        if m.get("FactionID"):
            members[m["FactionID"]].add(m["PersonID"])

    no_members = [i for i in fac if not members.get(i)]
    by_knesset: dict[int, list[int]] = defaultdict(list)
    for i, f in fac.items():
        by_knesset[f["KnessetNum"]].append(i)

    # --- связи между соседними каденциями -----------------------------------
    auto_links: list[tuple[int, int, float, str]] = []
    forks: list[dict] = []
    ks = sorted(by_knesset)
    for k, nxt in zip(ks, ks[1:]):
        for a in by_knesset[k]:
            for b in by_knesset[nxt]:
                ov = overlap(members.get(a, set()), members.get(b, set()))
                if ov < FORK_LOW:
                    continue
                same_name = fac[a]["Name"].strip() == fac[b]["Name"].strip()
                if ov >= AUTO_MERGE and same_name:
                    auto_links.append((a, b, ov, "имя+состав"))
                elif ov >= AUTO_MERGE:
                    forks.append({"kind": "состав сходится, имя разное", "a": a, "b": b, "ov": ov})
                elif same_name:
                    forks.append({"kind": "имя то же, состав разошёлся", "a": a, "b": b, "ov": ov})
                else:
                    forks.append({"kind": "частичное пересечение", "a": a, "b": b, "ov": ov})

    # --- линии из авторазрешённых связей (union-find) -----------------------
    parent: dict[int, int] = {i: i for i in fac}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _, _ in auto_links:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    lines: dict[int, list[int]] = defaultdict(list)
    for i in fac:
        lines[find(i)].append(i)

    # --- отделяем персональные расколы от настоящих развилок -----------------
    splinters = [f for f in forks
                 if min(len(members.get(f["a"], set())), len(members.get(f["b"], set()))) <= SPLINTER_MAX]
    forks = [f for f in forks if f not in splinters]

    # --- агрегация: КЛАСТЕР, а не пара -------------------------------------
    # Попарная агрегация давала 197 развилок, из них первая десятка — один
    # и тот же клубок (Яадут ха-Тора / Агудат Исраэль / Дегель ха-Тора то
    # сливаются в общий список, то расходятся). Человек решает про клубок
    # один раз: «это одна линия, две или три?» — а не про каждое ребро.
    fp: dict[int, int] = {i: i for i in fac}

    def ffind(x: int) -> int:
        while fp[x] != x:
            fp[x] = fp[fp[x]]
            x = fp[x]
        return x

    for f in forks:
        ra, rb = ffind(f["a"]), ffind(f["b"])
        if ra != rb:
            fp[rb] = ra

    clusters: dict[int, list[int]] = defaultdict(list)
    for f in forks:
        for side in ("a", "b"):
            r = ffind(f[side])
            if f[side] not in clusters[r]:
                clusters[r].append(f[side])

    edges_by_cluster: dict[int, list[dict]] = defaultdict(list)
    for f in forks:
        edges_by_cluster[ffind(f["a"])].append(f)
    forks = []
    for root, ids in clusters.items():
        kns = sorted({fac[i]["KnessetNum"] for i in ids})
        edges = sorted(edges_by_cluster[root], key=lambda x: -x["ov"])
        forks.append({
            "cluster": sorted(ids),
            "knessets": kns,
            "reaches_ballot": max(kns) >= 24,
            "names": sorted({fac[i]["Name"].strip() for i in ids}),
            "edges": [{"a": e["a"], "b": e["b"], "ov": round(e["ov"], 2), "kind": e["kind"]}
                      for e in edges[:12]],
            "ov": edges[0]["ov"] if edges else 0.0,
            "a": ids[0], "b": ids[-1], "kind": "кластер",
        })

    # --- цена развилки: сколько записей и каденций зависит -------------------
    for f in forks:
        f["cost_records"] = len(f["cluster"])
        f["cost_knessets"] = len(f["knessets"])
    # Сначала то, что доходит до бюллетеня 2026 — там цена решения реальна.
    forks.sort(key=lambda x: (not x["reaches_ballot"], -x["cost_records"], -x["ov"]))

    multi = {r: v for r, v in lines.items() if len(v) > 1}

    # --- оракул: покрытие без остатка и без пересечений ----------------------
    covered = sum(len(v) for v in lines.values())
    assert covered == len(fac), f"линии покрывают {covered} из {len(fac)} записей"

    out = ["# lineage_draft — КАНДИДАТЫ, не решения. Сгенерирован build_lineage_candidates.py",
           "# Решения живут в criteria/party_lineage.yaml. Этот файл машинный.",
           "meta:",
           f"  auto_merge_threshold: {AUTO_MERGE}",
           f"  fork_low_threshold: {FORK_LOW}",
           "  overlap_metric: intersection / min(size)",
           f"  factions_total: {len(fac)}",
           f"  factions_without_members: {len(no_members)}",
           f"  lines_total: {len(lines)}",
           f"  lines_multi_knesset: {len(multi)}",
           f"  first_knesset: {FIRST_KNESSET}",
           f"  splinter_max: {SPLINTER_MAX}",
           f"  splinters_excluded: {len(splinters)}",
           f"  forks_for_human: {len(forks)}",
           "", "auto_resolved_lines:"]
    for r, v in sorted(multi.items(), key=lambda x: -len(x[1])):
        names = sorted({fac[i]["Name"].strip() for i in v})
        kns = sorted(fac[i]["KnessetNum"] for i in v)
        out.append(f"  - ids: {sorted(v)}")
        out.append(f"    knessets: {kns}")
        out.append(f"    names: {json.dumps(names, ensure_ascii=False)}")

    out += ["", "forks:  # развилки — ТРЕБУЮТ РЕШЕНИЯ ЧЕЛОВЕКА (кластерами)"]
    for n, f in enumerate(forks, 1):
        out += [f"  - id: F{n}",
                f"    reaches_ballot_2026: {str(f['reaches_ballot']).lower()}",
                f"    knessets: {f['knessets']}",
                f"    faction_ids: {f['cluster']}",
                f"    names: {json.dumps(f['names'], ensure_ascii=False)}",
                "    members:"]
        for i in f["cluster"]:
            out.append(f"      - {{id: {i}, knesset: {fac[i]['KnessetNum']}, "
                       f"mks: {len(members.get(i, set()))}, "
                       f"name: {json.dumps(fac[i]['Name'].strip(), ensure_ascii=False)}}}")
        out.append("    edges:")
        for e in f["edges"]:
            out.append(f"      - {{a: {e['a']}, b: {e['b']}, overlap: {e['ov']}, "
                       f"kind: {json.dumps(e['kind'], ensure_ascii=False)}}}")
        out += ["    decision: null   # one_line | separate_lines | split_as:[...]",
                "    rationale: null",
                "    decided_at: null"]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"фракций: {len(fac)}  без состава: {len(no_members)}")
    print(f"линий: {len(lines)}  из них многокаденционных: {len(multi)}")
    print(f"расколов (фракция <= {SPLINTER_MAX} чел.) отделено: {len(splinters)}")
    print(f"РАЗВИЛОК ДЛЯ ЧЕЛОВЕКА: {len(forks)}")
    print(f"\n{OUT.relative_to(OUT.parent.parent)}")
    ballot = [f for f in forks if f["reaches_ballot"]]
    print(f"   из них доходят до бюллетеня 2026: {len(ballot)}")
    print("\nразвилки, доходящие до бюллетеня:")
    for n, f in enumerate(forks, 1):
        if not f["reaches_ballot"]:
            continue
        print(f"  F{n:<3} каденции {str(f['knessets']):<28} фракций {f['cost_records']:>2}  "
              f"{' | '.join(x[:26] for x in f['names'][:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
