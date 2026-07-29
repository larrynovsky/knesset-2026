#!/usr/bin/env python3
"""Состав пилота объявляется ДО прогона. Это и есть смысл файла.

Пилот — 60 законопроектов из плотного ядра. Квоты и правило выбора внутри квоты
зафиксированы здесь и закоммичены раньше, чем сделан первый вызов модели.
Порядок доказывается git-историей, как в §3 — то же правило в другом приложении:
там критерии раньше данных, здесь состав выборки раньше результата.

Почему не случайная выборка: §14 требует воспроизводимости из чистого клона.
Внутри каждой квоты — равномерный шаг по BillID, а не голова списка. Голова
списка уже один раз соврала мне сегодня (выборка достижимости 12/12 была
смещена по времени и ничего не доказывала).

ВТОРАЯ ЧАСТЬ — пришпиливание оракула. `validation_set` в criteria/keyvotes.yaml
содержит 9 актов с ОЖИДАЕМЫМ знаком. Чтобы машинный оракул Р2 работал, каждый
акт надо связать с конкретным BillID. Связывание — это отождествление публично
названного закона, а не отбор: читатель может проверить его глазами.

Честная граница: если акт не пришпиливается однозначно, он НЕ включается в
оракул и об этом печатается. Оракул из семи пришпиленных актов честнее, чем
из девяти, два из которых угаданы.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "data" / "bills_scan.json"
DOCCACHE = ROOT / "data" / "document_bill.json"
OUT = ROOT / "data" / "pilot_selection.json"

# --- КВОТЫ. Объявлены до прогона, согласованы с владельцем 2026-07-29. -------
QUOTA = {"A_суд": 20, "C_надзор": 20, "basic_law": 11}
# 9 актов оракула добавляются сверх квот и не вытесняют их: они проверяют
# механизм, а квоты покрывают предмет. Пересечения дедуплицируются.

# --- Пришпиливание оракула ---------------------------------------------------
# Ключ — дата из validation_set. Значение — ивритские фразы, ВСЕ обязаны
# присутствовать в названии. Фразы взяты из официальных наименований актов,
# а не подобраны по корпусу: это отождествление, а не поиск удобного.
ORACLE_PINS = {
    ("2022-12-27", -1): ["חוק-יסוד", "הממשלה"],
    ("2022-12-28", -1): ["פקודת המשטרה"],
    ("2023-03-23", -1): ["חוק-יסוד", "הממשלה"],
    ("2023-07-24", -1): ["חוק-יסוד", "השפיטה"],
    ("2025-03-04", -1): ["נציב תלונות הציבור על שופטים"],
    ("2025-03-27", -1): ["חוק-יסוד", "השפיטה"],
    ("2026-07-15", -1): ["היועץ המשפטי לממשלה"],
    ("2026-07-15", 0): ["חוק-יסוד", "לימוד תורה"],
    ("2026-07-16", -1): ["שידור"],
}


def even_step(pool: list[int], n: int) -> list[int]:
    if n >= len(pool):
        return list(pool)
    step = len(pool) / n
    return [pool[int(i * step)] for i in range(n)]


def main() -> int:
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in scan["matched"]}
    core = set(scan["core_ids"])

    # Законопроекты с текстом нормы — только они могут получить знак (Р1).
    cache = json.loads(DOCCACHE.read_text(encoding="utf-8"))
    with_text = set()
    for d in cache["docs"]:
        k = (d.get("GroupTypeDesc") or "").strip()
        if k.startswith(("הצעת חוק", "חוק -", "חוק-")):
            with_text.add(d["BillID"])
    eligible = core & with_text
    print(f"ядро {len(core)} · с текстом нормы {len(eligible)} ← из них выбираем")

    # --- квоты ---
    pools = {
        "A_суд": sorted(b for b in eligible if "A_суд" in by_id[b]["groups"]),
        "C_надзор": sorted(b for b in eligible if "C_надзор" in by_id[b]["groups"]),
        "basic_law": sorted(b for b in eligible if by_id[b].get("basic_law")),
    }
    selected: dict[int, list[str]] = {}
    for k, n in QUOTA.items():
        got = even_step(pools[k], n)
        print(f"   квота {k:<12} {len(got)}/{n}  (пул {len(pools[k])})")
        for b in got:
            selected.setdefault(b, []).append(k)

    # --- оракул ---
    print("\nпришпиливание оракула — 9 актов из validation_set:")
    oracle, unpinned = [], []
    for (date, expect), phrases in ORACLE_PINS.items():
        year = date[:4]
        cand = [b for b in eligible
                if all(p in by_id[b]["name"] for p in phrases)
                and (by_id[b]["date"][:4] == year or not by_id[b]["date"])]
        if len(cand) == 1:
            oracle.append({"bill": cand[0], "date": date, "expect": expect,
                           "name": by_id[cand[0]]["name"]})
            selected.setdefault(cand[0], []).append("oracle")
            print(f"   ✓ {date} знак {expect:+d} → {cand[0]}  {by_id[cand[0]]['name'][:60]}")
        else:
            unpinned.append({"date": date, "expect": expect, "phrases": phrases,
                             "candidates": len(cand),
                             "sample": [by_id[b]["name"][:70] for b in cand[:4]]})
            print(f"   ✗ {date} знак {expect:+d} → кандидатов {len(cand)} — НЕ пришпилен")
            for s in [by_id[b]["name"][:70] for b in cand[:4]]:
                print(f"        · {s}")

    print(f"\nоракул: пришпилено {len(oracle)}/9, не пришпилено {len(unpinned)}")
    if unpinned:
        print("  Непришпиленные в оракул НЕ входят. Оракул из меньшего числа честнее,")
        print("  чем из девяти, часть которых угадана (§20).")
    signs = sorted({o["expect"] for o in oracle})
    print(f"  знаки в оракуле: {signs}")
    if signs == [-1]:
        print("  ⚠ в оракуле ТОЛЬКО минус — он структурно не обнаружит крен в минус (R2)")

    OUT.write_text(json.dumps(
        {"quota": QUOTA, "selected": sorted(selected),
         "reasons": {str(k): v for k, v in sorted(selected.items())},
         "oracle": oracle, "unpinned": unpinned,
         "eligible_total": len(eligible)},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nвыбрано уникальных: {len(selected)}\n{OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
