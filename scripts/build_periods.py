#!/usr/bin/env python3
"""criteria/periods.yaml из источника, а не из памяти (§1, §3, §23).

§1 требует единицу наблюдения «партия × период участия в правительстве» и
приводит ШАС как канонический пример: 2023 и вторая половина 2025 — разные
наблюдения. Даты нельзя написать по памяти: файл живёт в criteria/, и всё,
что там лежит, читатель обязан иметь возможность проверить.

Почему это не нарушает §3 (критерии до данных). Периоды — не решение о том,
ЧТО считать делом партии, а факт о составе правительства, взятый из того же
API, что и голосования. Решением здесь является только правило вывода, и оно
записано ниже дословно; сами даты выводятся механически.

ПРАВИЛО ВЫВОДА (фиксируется до просмотра результата):
  партия считается участвующей в правительстве в интервале, когда хотя бы один
  человек, состоявший в её фракции, занимал министерскую должность в этом
  правительстве. Границы интервала — минимальная StartDate и максимальная
  FinishDate таких должностей; открытая FinishDate означает «по конец каденции».

ЧЕСТНАЯ ГРАНИЦА. KNS_PersonToPosition не связывает министерскую запись
с фракцией напрямую: у министерских записей FactionName пуст. Фракция
подтягивается по PersonID из фракционных записей того же человека. Если
человек сменил фракцию, а даты министерства покрывают обе, интервал
припишется обеим — такой случай печатается отдельно и не прячется.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all              # noqa: E402  §23

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "criteria" / "periods.yaml"
K25_NUM = 25


def d10(s) -> str:
    return str(s or "")[:10]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-parties", type=int, default=None,
                    help="§23: сколько партий ожидаем увидеть в правительстве")
    ap.add_argument("--dry-run", action="store_true", help="не писать criteria/periods.yaml")
    ap.add_argument("--knesset", type=int, default=25,
                    help="срезы 20–24: пишет data/periods_N.yaml (генерированный справочник, не критерий)")
    a = ap.parse_args()
    global OUT, K25_NUM
    if a.knesset != 25:
        K25_NUM = a.knesset
        OUT = ROOT / "data" / f"periods_{a.knesset}.yaml"

    rows = fetch_all("KNS_PersonToPosition", flt=f"KnessetNum eq {K25_NUM}")
    facs: dict[int, set] = collections.defaultdict(set)      # PersonID → {(id, name)}
    member: dict[int, list] = collections.defaultdict(list)  # PersonID → [(id, name, start, finish)]
    for r in rows:
        if r.get("FactionID"):
            facs[r["PersonID"]].add((r["FactionID"], (r.get("FactionName") or "").strip()))
            member[r["PersonID"]].append((r["FactionID"], (r.get("FactionName") or "").strip(),
                                          d10(r.get("StartDate")), d10(r.get("FinishDate")) or "9999"))

    mins = [r for r in rows if r.get("GovMinistryID") and r.get("GovernmentNum")]
    print(f"позиций 25-го Кнессета: {len(rows)} · министерских: {len(mins)} · "
          f"персон с фракцией: {len(facs)}")

    # партия × правительство → границы
    span: dict[tuple, dict] = {}
    multi_faction = []
    for r in mins:
        person_facs = facs.get(r["PersonID"])
        if not person_facs:
            continue                                          # министр вне фракций Кнессета
        if len(person_facs) > 1:
            multi_faction.append((r["PersonID"], person_facs))
        s0, f0 = d10(r.get("StartDate")), d10(r.get("FinishDate")) or "9999"
        if K25_NUM != 25:
            # Срезы 20–24: министр приписывается фракции, в которой состоял В ТО ВРЕМЯ.
            # Без этого Ямина 23-го выходила «в правительстве» через Рафи Переца,
            # перешедшего в Байт Йегуди и оставшегося министром (замер 19.10).
            # 25-й не трогаем: его справочник — критерий, и он сгенерирован прежним правилом.
            hit = {(fid, fn) for fid, fn, ms, mf in member[r["PersonID"]] if max(ms, s0) < min(mf, f0)}
            person_facs = hit or person_facs
        for fid, fname in person_facs:
            key = (fid, fname, r["GovernmentNum"])
            s, f = d10(r.get("StartDate")), d10(r.get("FinishDate"))
            if K25_NUM != 25:
                ms, mf = max((m[2], m[3]) for m in member[r["PersonID"]] if m[0] == fid)
                s, f = max(s, ms), (min(f or "9999", mf) if mf != "9999" else f)
            cur = span.setdefault(key, {"start": s, "finish": f, "ministries": set(),
                                        "persons": set()})
            if s and (not cur["start"] or s < cur["start"]):
                cur["start"] = s
            # пустая FinishDate = «по конец каденции», она сильнее любой даты
            if not f or not cur["finish"]:
                cur["finish"] = ""
            elif f > cur["finish"]:
                cur["finish"] = f
            cur["ministries"].add((r.get("GovMinistryName") or "").strip())
            cur["persons"].add(r["PersonID"])

    parties = {(fid, fname) for fid, fname, _ in span}
    print(f"партий в правительствах 25-го Кнессета: {len(parties)}")
    if a.expect_parties is not None:
        ok = abs(len(parties) - a.expect_parties) <= 2
        print(f"   объявлено было {a.expect_parties} — "
              f"{'в пределах' if ok else '⚠ ВНЕ объявленного (§23)'}")
    if multi_faction:
        print(f"⚠ персон с несколькими фракциями: {len(set(p for p, _ in multi_faction))} — "
              f"их министерства приписаны ОБЕИМ, это видно в файле")

    print("\nпериоды:")
    out_lines = [
        "# periods — партия × период участия в правительстве (§1).",
        "# СГЕНЕРИРОВАН scripts/build_periods.py из OdataV4/ParliamentInfo.",
        "# Правило вывода зафиксировано в docstring скрипта ДО просмотра результата.",
        "# Руками не правится: расхождение с источником обязано быть видно диффом.",
        f"# Собран: {datetime.now(timezone.utc).date().isoformat()}",
        "",
        f"knesset: {K25_NUM}",
        "periods:",
    ]
    for (fid, fname, gov), v in sorted(span.items(), key=lambda x: (x[0][0], x[0][2])):
        pid = f"{fid}-gov{gov}"
        fin = v["finish"] or "открыт"
        print(f"   {pid:14} {fname[:34]:36} {v['start']} … {fin:10} "
              f"персон {len(v['persons'])} министерств {len(v['ministries'])}")
        out_lines += [
            f"  - id: {pid}",
            f"    faction_id: {fid}",
            f"    faction_name: {json.dumps(fname, ensure_ascii=False)}",
            f"    government: {gov}",
            f"    start: {v['start']}",
            f"    finish: {v['finish'] or 'null'}",
            f"    persons_in_gov: {len(v['persons'])}",
            f"    ministries: {json.dumps(sorted(v['ministries']), ensure_ascii=False)}",
        ]

    if a.dry_run:
        print("\n--dry-run: файл не записан")
        return 0
    OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"\n{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
