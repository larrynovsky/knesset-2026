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

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "data" / "bills_scan.json"
DOCCACHE = ROOT / "data" / "document_bill.json"
OUT = ROOT / "data" / "pilot_selection.json"
HOLDOUT_OUT = ROOT / "data" / "holdout_selection.json"

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


def pick_holdout(pool: list[int], n: int, seed: int) -> list[int]:
    """Чистая выборка: весь недетерминизм собран здесь и проверяем без файлов."""
    return sorted(random.Random(seed).sample(pool, n))


def selftest() -> int:
    """Оракул отложенной выборки. Красное здесь = проверка кодбука недействительна."""
    pool = list(range(1000, 1200))
    a1 = pick_holdout(pool, 40, 20260729)
    a2 = pick_holdout(pool, 40, 20260729)
    assert a1 == a2, "тот же посев дал другую выборку — §14 нарушен"
    assert pick_holdout(pool, 40, 1) != a1, "разные посевы дали одинаковую выборку"
    assert len(set(a1)) == 40, "в выборке повторы"

    # Главное свойство: пилот не может попасть в отложенное.
    pilot = set(range(1000, 1100))
    clean = sorted(set(pool) - pilot)
    h = pick_holdout(clean, 40, 20260729)
    assert not (set(h) & pilot), "состав пилота протёк в отложенную выборку"

    try:
        pick_holdout(clean, 1000, 1)
        raise AssertionError("запрос больше пула обязан падать, а не усекаться молча")
    except ValueError:
        pass
    print("самопроверка отложенной выборки пройдена: 5 утверждений")
    return 0


def holdout(eligible: set[int], by_id: dict, n: int, seed: int) -> int:
    """Отложенная выборка: материал, в который НИКТО не смотрел (Р5, §8).

    Зачем она вообще. Кодбук v1.1 выведен из девяти расхождений на 57 строках
    пилота. Перепрогон тех же 57 покажет, что код делает написанное в кодбуке,
    и ничего больше: расхождения там упадут почти наверняка, потому что правила
    стали подробнее, а подробность снижает разброс независимо от правильности.
    Отличить «правила поймали класс случаев» от «правила запомнили девять штук»
    можно только на материале, которого правила не видели. §8 свода требует
    ровно этого, и до сих пор не был применён ни разу.

    Почему СЛУЧАЙНАЯ, в отличие от пилота. Пилот брал равномерный шаг, чтобы
    покрыть предмет по квотам. Здесь задача обратная: выборка должна быть
    представительной для КОРПУСА, а не для нашего представления о нём.
    Посев фиксирован и записан в файл — воспроизводимость §14 сохраняется,
    а систематический сдвиг равномерного шага (например, по дате через BillID)
    не переносится на проверку.

    ВЫБОРКА ОДНОРАЗОВАЯ. Как только расхождения на ней прочитаны человеком,
    она перестала быть отложенной. Для проверки следующей версии кодбука нужна
    новая, из нетронутого остатка — поэтому берём ровно столько, сколько нужно
    сейчас, и печатаем, сколько осталось в резерве.
    """
    pilot = set(json.loads(OUT.read_text(encoding="utf-8"))["selected"]) if OUT.exists() else set()
    pool = sorted(eligible - pilot)
    if n > len(pool):
        print(f"§23 ОТКАЗ: просят {n}, в нетронутом пуле {len(pool)}", file=sys.stderr)
        return 1
    picked = pick_holdout(pool, n, seed)

    print(f"отложенная выборка: {n} из нетронутого пула {len(pool)}"
          f" (ядро {len(eligible)} минус пилот {len(pilot)})")
    print(f"   посев {seed} записан в файл — выборка воспроизводима (§14)")
    print(f"   РЕЗЕРВ после этой выборки: {len(pool) - n} законопроектов")
    print("   в состав НЕ СМОТРИМ до прогона: взгляд на материал до правил —")
    print("   это ровно то, что §3 запрещает делать с критериями.")

    HOLDOUT_OUT.write_text(json.dumps(
        {"seed": seed, "n": n, "selected": picked,
         "pool_size": len(pool), "reserve_after": len(pool) - n,
         "excluded_pilot": len(pilot),
         "stop_rule": "расхождений по общему знаку 4-9 → добрать 60 из резерва; "
                      "меньше 4 или больше 9 → не добирать. Объявлено ДО прогона."},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{HOLDOUT_OUT.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", type=int, default=0,
                    help="собрать отложенную выборку размера N вместо состава пилота")
    ap.add_argument("--seed", type=int, default=20260729,
                    help="посев отложенной выборки; записывается в файл")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

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

    if a.holdout:
        return holdout(eligible, by_id, a.holdout, a.seed)

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
    # Первый прогон дал 0 из 9: рядом лежат десятки ЗАКОНОПРОЕКТОВ с почти
    # одинаковыми именами, а validation_set называет принятые АКТЫ.
    # Различитель структурный и общеязыковой, а не подобранный под корпус:
    # «הצעת חוק» буквально «предложение закона». Принятый акт этого слова
    # не несёт. Правило добавлено ПОСЛЕ первого прогона и это записано здесь,
    # чтобы не выглядело как подгонка задним числом (§20, §22): менялось
    # правило ОТОЖДЕСТВЛЕНИЯ публично названного акта, а не критерий отбора
    # и не ожидаемый знак. Ожидаемые знаки взяты из keyvotes.yaml и не
    # трогались ни разу.
    oracle, unpinned = [], []
    for (date, expect), phrases in ORACLE_PINS.items():
        year = date[:4]
        cand = [b for b in eligible
                if all(p in by_id[b]["name"] for p in phrases)
                and not by_id[b]["name"].lstrip().startswith("הצעת")
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
