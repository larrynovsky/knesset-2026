#!/usr/bin/env python3
"""Состав пилота структурированного диффа — из данных, а не из памяти сессии.

Объявлено раньше: criteria/declared_before_structdiff_2026-08-13.yaml.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Двенадцать номеров актов были посчитаны разовым кодом
в сессии 13.08 и жили только в переписке. Ровно так же однажды жил вердикт
«канал А не даёт направления»: число в чате, механизма нет, из чистого клона
не получается (§14). Здесь то же лечение, что тогда, — счёт переезжает в репо
и обзаводится оракулом.

ОРАКУЛ (P44) — не «скрипт отработал без ошибки», а СОВПАДЕНИЕ с объявленным:
состав, вычисленный из data/direction_v3.json и data/bill_texts, обязан быть
равен списку composition.acts из файла критериев, включая числа операций по
видам. Красное означает одно из двух, и оба важны: либо регулярка операций
уехала, либо объявление и код разошлись. Второе — как раз то, ради чего §3
требует коммитить критерии раньше данных.

ПОЧЕМУ КАТЕГОРИЯ БЕРЁТСЯ ИЗ ПРИЧИНЫ, А НЕ ИЗ ЧИСЕЛ. Соблазн был разложить
акты по m["overlap"] < 0.30 самостоятельно. Это завело бы вторую копию
порогов direction_confidence, и правка там молча разошлась бы с правкой
здесь. Причина — объявленный §6 контракт verdict(): уровень несёт названную
причину. Три синтетических случая в самопроверке прогоняются через настоящий
verdict(), поэтому смена формулировки причины красит здесь, а не через месяц.

    python3 scripts/select_structdiff_pilot.py --selftest
    python3 scripts/select_structdiff_pilot.py            # пишет data/
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import n_asserts          # noqa: E402
from direction_confidence import verdict          # noqa: E402
from resolve_law_ref import operative             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIRECTION = ROOT / "data" / "direction_v3.json"
TEXTDIR = ROOT / "data" / "bill_texts"
CRIT = ROOT / "criteria" / "declared_before_structdiff_2026-08-13.yaml"
OUT = ROOT / "data" / "structdiff_pilot.json"
PAIR = ("anthropic", "openai")

# Кавычки трёх начертаний: ASCII, ивритский гершаим U+05F4, типографская U+201D.
# Разнобой не косметика: в одном и том же акте встречаются оба вида, и класс,
# знающий только ASCII, теряет операции молча — без исключения и без нуля.
Q = "\"״”"
RX = {
    "replace": re.compile(
        rf"במקום\s+[{Q}]([^{Q}\n]{{2,200}})[{Q}]\s*יבוא\s+[{Q}]([^{Q}\n]{{2,400}})[{Q}]"),
    "insert": re.compile(
        rf"(?:אחרי|בסוף|לפני)\s+[{Q}]?([^{Q}\n]{{0,120}})[{Q}]?\s*יבוא\s+[{Q}]([^{Q}\n]{{2,600}})[{Q}]"),
    "delete": re.compile(r"^\s*(.{2,200}?)\s+[–\-]\s*בטל\s*\.?\s*$", re.M),
}
KINDS = ("replace", "insert", "delete")

# Причина verdict() -> категория объявления. Ключ — отличительная подстрока.
# Порядок проверки значим: «не нашёл ни одной нормы» и «ни один вендор» оба
# означают неизвлечение, но формулировки разные.
CATEGORY = (
    ("не нашёл ни одной нормы", "пусто"),
    ("ни один вендор", "пусто"),
    ("чтении", "чтение"),
    ("разные множества", "разные_множества"),
)


def category(why: str) -> str | None:
    """Категория слабости по названной причине. None — причина неизвестна."""
    for needle, name in CATEGORY:
        if needle in why:
            return name
    return None


def count_ops(text: str) -> dict:
    """Операции в ОПЕРАТИВНОЙ части акта. Пояснительная записка цитирует те
    же обороты и дала бы фантомные операции — режем её resolve_law_ref."""
    body = operative(text)
    return {k: len(RX[k].findall(body)) for k in KINDS}


def select(direction: dict, textdir: Path) -> tuple[list, dict]:
    """Слабые акты пары с хотя бы одной извлекаемой операцией."""
    chosen, tally = [], {"weak": 0, "no_text": 0, "no_ops": 0, "unknown_reason": 0}
    for r in direction["rows"]:
        vs = r.get("verdicts", {})
        if any(vs.get(v, {}).get("status") != "ok" for v in PAIR):
            continue
        lvl, why, _ = verdict(*(vs[v].get("norms", []) for v in PAIR))
        if lvl not in ("low", "none"):
            continue
        tally["weak"] += 1
        cat = category(why)
        if cat is None:                 # причина, которой код не знает, — не
            tally["unknown_reason"] += 1  # «прочее», а названный отказ строки
            continue
        p = textdir / f"{r['bill']}.txt"
        if not p.exists():
            tally["no_text"] += 1
            continue
        ops = count_ops(p.read_text(encoding="utf-8"))
        if not sum(ops.values()):
            tally["no_ops"] += 1
            continue
        chosen.append({"bill": r["bill"], "category": cat, "ops": ops,
                       "name": r.get("name", "")})
    chosen.sort(key=lambda x: (x["category"] != "пусто", x["bill"]))
    return chosen, tally


def declared(text: str) -> dict:
    """composition.acts из объявления. Разбор регуляркой, а не PyYAML:
    зависимость ради двенадцати строк — пятая ступень лестницы наоборот."""
    block = text.split("  acts:", 1)
    if len(block) < 2:
        return {}
    out = {}
    for line in block[1].splitlines()[1:]:
        m = re.match(r"\s{4}(\d+):\s*\[([^\]]+)\]", line)
        if not m:
            break
        cat, *nums = [x.strip() for x in m.group(2).split(",")]
        out[int(m.group(1))] = {"category": cat,
                                "ops": dict(zip(KINDS, (int(n) for n in nums)))}
    return out


def _n(q, s=0):
    return {"quote_he": q, "sign": s}


def selftest() -> int:
    # --- операции трёх видов, включая ивритский гершаим вместо ASCII-кавычки.
    repl = 'בסעיף 15, במקום "שר האוצר" יבוא "הממשלה".'
    repl2 = 'בסעיף 3, במקום ״שנתיים״ יבוא ״שלוש שנים״.'
    ins = 'אחרי סעיף 15 יבוא "15א. ועדה מייעצת תמונה בידי השר".'
    dele = 'סעיף 22 – בטל.'
    assert count_ops(repl)["replace"] == 1, "замена с ASCII-кавычками не найдена"
    assert count_ops(repl2)["replace"] == 1, \
        "замена с гершаим ״ обязана считаться так же, как с ASCII: в одном " \
        "акте встречаются оба начертания, и класс из одной кавычки теряет " \
        "операции МОЛЧА — без исключения и без нуля"
    assert count_ops(ins)["insert"] == 1, "вставка после статьи не найдена"
    assert count_ops(dele)["delete"] == 1, "отмена статьи не найдена"
    assert sum(count_ops("סעיף 15 יעמוד בתוקפו.").values()) == 0, \
        "текст без операций не имеет права дать операцию"

    # --- пояснительная записка не источник операций. Без этого случая вызов
    # operative() ничем не оправдан: снятие его не роняло бы самопроверку.
    with_note = repl.replace("במקום", "לפי") + "\nדברי הסבר\n" + repl
    assert count_ops(with_note)["replace"] == 0, \
        "операция из пояснительной записки — фантом, там цитируют те же обороты"

    # --- категория берётся из НАСТОЯЩЕГО verdict(), не из копии порогов.
    lvl_a, why_a, _ = verdict([], [_n("אאא", 1)])
    lvl_b, why_b, _ = verdict([], [])
    lvl_c, why_c, _ = verdict([_n("אאא", 1), _n("בבב", -1)],
                              [_n("אאא", -1), _n("בבב", 1)])
    lvl_d, why_d, _ = verdict([_n("אאא", 1), _n("בבב", -1), _n("גגג", 0)],
                              [_n("דדד", 1)])
    for lvl in (lvl_a, lvl_b, lvl_c, lvl_d):
        assert lvl in ("low", "none"), f"случай самопроверки не слаб: {lvl}"
    assert category(why_a) == "пусто", why_a
    assert category(why_b) == "пусто", why_b
    assert category(why_c) == "чтение", why_c
    assert category(why_d) == "разные_множества", why_d
    assert category("причина, которой в коде нет") is None, \
        "неизвестная причина обязана быть None: молчаливое «прочее» спрятало " \
        "бы новый режим отказа внутри старой категории"

    # --- объявление читается, и в нём ровно двенадцать актов.
    dec = declared(CRIT.read_text(encoding="utf-8"))
    assert len(dec) == 12, f"в объявлении не двенадцать актов, а {len(dec)}"
    assert set(d["category"] for d in dec.values()) == {"пусто", "разные_множества"}, \
        "категории объявления разошлись с кодом"

    print(f"логика: {n_asserts(selftest)} утверждений — зелено")

    # --- P44: состав из данных обязан совпасть с объявленным.
    if not (DIRECTION.exists() and TEXTDIR.exists()):
        print("P44 НЕ ПРОВЕРЕН: нет data/direction_v3.json или data/bill_texts.")
        print("  Здесь это ОТКАЗ, а не пропуск: главный оракул файла — сверка")
        print("  с объявлением, и без данных самопроверка неполна (§21 —")
        print("  проверки исполняются там, где лежат данные, то есть на Studio).")
        return 2
    chosen, tally = select(json.loads(DIRECTION.read_text(encoding="utf-8")), TEXTDIR)
    got = {c["bill"]: {"category": c["category"], "ops": c["ops"]} for c in chosen}
    if got != dec:
        only_got = sorted(set(got) - set(dec))
        only_dec = sorted(set(dec) - set(got))
        diff = [b for b in set(got) & set(dec) if got[b] != dec[b]]
        print("P44 КРАСНОЕ: состав разошёлся с объявлением.")
        print(f"  лишние в замере: {only_got}")
        print(f"  пропали из замера: {only_dec}")
        for b in sorted(diff):
            print(f"  {b}: объявлено {dec[b]} · получено {got[b]}")
        return 1
    print(f"P44 зелено: {len(chosen)} актов совпали с объявленным составом, "
          f"включая числа операций. Слабых всего {tally['weak']}.")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not DIRECTION.exists():
        print(f"нет {DIRECTION} — состав не считается. Запускать на Studio.")
        return 2
    chosen, tally = select(json.loads(DIRECTION.read_text(encoding="utf-8")), TEXTDIR)
    OUT.write_text(json.dumps(
        {"criteria": CRIT.name, "pair": list(PAIR), "tally": tally,
         "acts": chosen}, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in chosen:
        print(f"{c['bill']}  {c['category']:<18} {c['ops']}")
    print(f"{len(chosen)} актов -> {OUT}")
    print("слабых всего {weak}; без текста {no_text}; без операций {no_ops}; "
          "причина неизвестна {unknown_reason}".format(**tally))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
