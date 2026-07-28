#!/usr/bin/env python3
"""Блок 1.1b — цепочки преемственности ОТ БЮЛЛЕТЕНЯ НАЗАД.

Почему отдельный модуль, а не правка предыдущего: другая единица анализа.
`build_lineage_candidates.py` шёл от графа — компоненты связности. Для тесных
клубков (F4: Яадут/Агудат/Дегель) это верно, для цепочек через перебежчиков —
нет: рёбра A-B и B-C связали Аводу, Мерец, НДИ и партию Ливни в один кластер
из 43 фракций, где решения не существует, а нужен разрез.

Здесь единица — партия, дошедшая до бюллетеня. От неё идём назад по каденциям
и на каждом шаге либо продолжаем автоматически, либо спрашиваем. Человек
решает «докуда тянется линия ЭТОЙ партии», а не «как разрезать граф».

Мне не нужен lineage всей истории. Нужен для тех, за кого можно проголосовать.

ПРАВИЛА АВТОПРОДОЛЖЕНИЯ объявлены до прогона:
  A1. пересечение состава >= AUTO_MERGE И одно название содержится в другом
      после нормализации (הליכוד внутри הליכוד בהנהגת בנימין נתניהו — это
      очевидно та же партия, спрашивать нечего);
  A2. пересечение >= STRONG и кандидат единственный выше FORK_LOW.
Всё остальное — вопрос человеку.

РАНЖИРОВАНИЕ КАНДИДАТОВ — по АБСОЛЮТНОМУ числу перешедших депутатов, а не по
доле. Первая редакция ранжировала по доле и увела цепочку Ликуда в однодневную
фракцию одного депутата: intersection/min(size) даёт 1.0 любому одиночке, чей
единственный член сидел в Ликуде, и цепочка тут же обрывалась. Доля отвечает
на вопрос «это подмножество?» — она нужна как ПОРОГ включения. Вопрос «кто
главный предшественник» — это сколько людей реально перешло.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all, require_join  # noqa: E402

AUTO_MERGE = 0.60
STRONG = 0.80
FORK_LOW = 0.15
FIRST_KNESSET = 16
ANCHOR_KNESSET = 25
MEMBER_POSITION = 54          # 'חבר/ת סיעה' — членство во фракции
OUT = Path(__file__).resolve().parent.parent / "criteria" / "ballot_lineage_draft.yaml"


def norm(s: str) -> str:
    """Нормализация названия: кавычки, лишние пробелы, служебные обороты."""
    s = (s or "").strip().replace('"', "").replace("'", "").replace("״", "").replace("׳", "")
    s = re.sub(r"\s+", " ", s)
    for junk in ("בראשות", "בהנהגת", "מיסודם של", "לראשות הממשלה"):
        s = s.split(junk)[0].strip()
    return s


def overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def main() -> int:
    factions = [f for f in fetch_all("KNS_Faction", select="Id,Name,KnessetNum")
                if f["KnessetNum"] >= FIRST_KNESSET]
    mem_raw = fetch_all("KNS_PersonToPosition", flt=f"PositionID eq {MEMBER_POSITION}",
                        select="PersonID,FactionID,KnessetNum")
    fac = {f["Id"]: f for f in factions}
    members: dict[int, set] = defaultdict(set)
    for m in mem_raw:
        if m.get("FactionID"):
            members[m["FactionID"]].add(m["PersonID"])
    require_join(set(fac), set(members), "KNS_Faction.Id <-> P2P.FactionID", min_overlap=100)

    by_k: dict[int, list[int]] = defaultdict(list)
    for i, f in fac.items():
        by_k[f["KnessetNum"]].append(i)

    anchors = sorted(by_k[ANCHOR_KNESSET], key=lambda i: -len(members.get(i, set())))
    chains, questions = [], []

    for a in anchors:
        chain = [{"knesset": ANCHOR_KNESSET, "id": a, "name": fac[a]["Name"].strip(),
                  "mks": len(members.get(a, set())), "step": "якорь"}]
        cur, k = a, ANCHOR_KNESSET
        while k > FIRST_KNESSET:
            cands = []
            for c in by_k[k - 1]:
                shared = len(members.get(cur, set()) & members.get(c, set()))
                ov = overlap(members.get(cur, set()), members.get(c, set()))
                if ov >= FORK_LOW:
                    cands.append((shared, ov, c))
            cands.sort(reverse=True)          # сначала по числу перешедших
            if not cands:
                chain.append({"knesset": k - 1, "step": "обрыв — предшественник не найден"})
                break
            _, ov, best = cands[0]
            na, nb = norm(fac[cur]["Name"]), norm(fac[best]["Name"])
            contained = na and nb and (na in nb or nb in na)
            shared_best = cands[0][0]
            second = cands[1][0] if len(cands) > 1 else 0
            auto = ((ov >= AUTO_MERGE and contained)
                    or (ov >= STRONG and len(cands) == 1)
                    or (shared_best >= 3 * max(second, 1) and shared_best >= 5))
            entry = {"knesset": k - 1, "id": best, "name": fac[best]["Name"].strip(),
                     "mks": len(members.get(best, set())), "overlap": round(ov, 2),
                     "step": "авто" if auto else "ВОПРОС"}
            if not auto:
                entry["alternatives"] = [
                    {"id": c, "name": fac[c]["Name"].strip(), "overlap": round(o, 2),
                     "shared": sh, "mks": len(members.get(c, set()))}
                    for sh, o, c in cands[:3]]
                questions.append({"anchor": fac[a]["Name"].strip(), "anchor_id": a,
                                  "at_knesset": k - 1, "from": fac[cur]["Name"].strip(),
                                  "cands": entry["alternatives"]})
            chain.append(entry)
            cur, k = best, k - 1
        chains.append({"anchor_id": a, "anchor": fac[a]["Name"].strip(), "chain": chain})

    out = ["# ballot_lineage_draft — цепочки ОТ БЮЛЛЕТЕНЯ НАЗАД. Кандидаты, не решения.",
           "meta:",
           f"  anchor_knesset: {ANCHOR_KNESSET}",
           f"  first_knesset: {FIRST_KNESSET}",
           f"  auto_merge: {AUTO_MERGE}", f"  strong: {STRONG}", f"  fork_low: {FORK_LOW}",
           "  auto_rules: [\"A1 пересечение>=auto_merge И вложенность названий\","
           " \"A2 пересечение>=strong И единственный кандидат\"]",
           f"  anchors: {len(anchors)}", f"  questions: {len(questions)}", "", "chains:"]
    for c in chains:
        out += [f"  - anchor: {json.dumps(c['anchor'], ensure_ascii=False)}",
                f"    anchor_id: {c['anchor_id']}", "    steps:"]
        for s in c["chain"]:
            base = (f"      - {{knesset: {s['knesset']}, step: {s['step']}"
                    + (f", id: {s['id']}, mks: {s['mks']}" if "id" in s else "")
                    + (f", overlap: {s['overlap']}" if "overlap" in s else "")
                    + (f", name: {json.dumps(s['name'], ensure_ascii=False)}" if "name" in s else "")
                    + "}")
            out.append(base)
            for alt in s.get("alternatives", []):
                out.append(f"        # альт: ov={alt['overlap']} "
                           f"перешло {alt['shared']} — {alt['name']} ({alt['mks']} деп.)")
        out += ["    decision: null   # continue_to:<knesset> | cut_at:<knesset>",
                "    rationale: null", "    decided_at: null"]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"якорей (фракции {ANCHOR_KNESSET}-го Кнессета): {len(anchors)}")
    print(f"ВОПРОСОВ ЧЕЛОВЕКУ: {len(questions)}\n")
    for c in chains:
        q = sum(1 for s in c["chain"] if s["step"] == "ВОПРОС")
        depth = c["chain"][-1]["knesset"]
        print(f"  {c['anchor'][:44]:<46} до к{depth:<3} шагов {len(c['chain'])-1:>2}  вопросов {q}")
    print(f"\n{OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
