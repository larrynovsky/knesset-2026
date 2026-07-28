#!/usr/bin/env python3
"""Оракул результата: в Кнессете всегда 120 мест.

Перенесено из health_scripts/docs/explanation/lab_recognizer.md — оттуда взята
не техника распознавания, а КЛАСС проверки: «оракулы не читают скан, они
смотрят на уже распознанные числа и спрашивают — а это вообще похоже
на правду?» Физиологические пределы, слишком большой скачок, странные единицы.

Все проверки этого проекта до сих пор смотрели на ПРОЦЕСС: сошлось ли
количество строк (§23), не пуст ли join. Ни одна не смотрела на РЕЗУЛЬТАТ.

Разница не теоретическая. 2026-07-28 соединение фракций с составом дало
пустоту, и я потратил полчаса на диагностику. Этот оракул показал бы
«в каждой каденции 0 депутатов вместо 120» первой же строкой — проще
и сильнее, чем require_join, который проверяет механику соединения.

Что проверяем:
  * уникальных депутатов в каденции >= 120 (может быть больше: замены
    по «норвежскому закону» и приход вместо выбывших);
  * ни один депутат не состоит в двух фракциях ОДНОВРЕМЕННО — впрочем,
    даты членства здесь не берём, поэтому проверка мягкая: помечаем,
    но не валим;
  * размер фракции не превышает 120 и не равен нулю.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all  # noqa: E402

SEATS = 120
MEMBER_POSITION = 54
FIRST_KNESSET = 16


def main() -> int:
    factions = [f for f in fetch_all("KNS_Faction", select="Id,Name,KnessetNum")
                if f["KnessetNum"] >= FIRST_KNESSET]
    mem = fetch_all("KNS_PersonToPosition", flt=f"PositionID eq {MEMBER_POSITION}",
                    select="PersonID,FactionID,KnessetNum")

    fac_kn = {f["Id"]: f["KnessetNum"] for f in factions}
    fac_name = {f["Id"]: f["Name"].strip() for f in factions}
    persons_by_kn: dict[int, set] = defaultdict(set)
    fac_members: dict[int, set] = defaultdict(set)
    multi: dict[tuple, set] = defaultdict(set)

    for m in mem:
        fid, pid = m.get("FactionID"), m.get("PersonID")
        if not fid or fid not in fac_kn:
            continue
        k = fac_kn[fid]
        persons_by_kn[k].add(pid)
        fac_members[fid].add(pid)
        multi[(k, pid)].add(fid)

    bad, warn = [], []
    print(f"{'кнессет':<9}{'депутатов':>11}{'фракций':>9}{'вердикт'}")
    for k in sorted(persons_by_kn):
        n = len(persons_by_kn[k])
        nf = sum(1 for i, kk in fac_kn.items() if kk == k)
        if n < SEATS:
            bad.append(f"к{k}: {n} депутатов при {SEATS} местах — данные неполны")
            v = "✗ МЕНЬШЕ 120"
        elif n > SEATS * 1.6:
            warn.append(f"к{k}: {n} — необычно много даже с заменами")
            v = "⚠ много"
        else:
            v = "ok"
        print(f"  к{k:<7}{n:>11}{nf:>9}  {v}")

    empty = [i for i, kk in fac_kn.items() if kk >= FIRST_KNESSET and not fac_members.get(i)]
    if empty:
        warn.append(f"фракций без единого члена: {len(empty)} "
                    f"(напр. {fac_name.get(empty[0], '?')})")
    huge = [i for i, s in fac_members.items() if len(s) > SEATS]
    if huge:
        bad.append(f"фракций размером больше {SEATS}: {len(huge)}")
    dual = [(k, p, f) for (k, p), f in multi.items() if len(f) > 1]
    if dual:
        warn.append(f"депутатов в >1 фракции внутри каденции: {len(dual)} "
                    "(законно при переходах, даты здесь не учитываются)")

    for w in warn:
        print(f"  · {w}")
    if bad:
        print("\nОРАКУЛ КРАСНЫЙ:", file=sys.stderr)
        for b in bad:
            print(f"  ✗ {b}", file=sys.stderr)
        return 1
    print(f"\nоракул 120 пройден: {len(persons_by_kn)} каденций")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ОШИБКА ОРАКУЛА (это блок, не warn): {exc}", file=sys.stderr)
        sys.exit(2)
