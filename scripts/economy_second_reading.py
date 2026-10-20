#!/usr/bin/env python3
"""Второе прочтение экономики по полным текстам → criteria/economy_second_reading_2026-10-20.json.

Правило — criteria/declared_before_economy_reread_2026-10-20.yaml (объявлено до чтения, d750f6d):
знак по названию остаётся, если ни один из двух читателей полного текста не дал другого числового знака;
иначе — 0 (снят, не перевёрнут). null — не довод против. Нет текста — знак остаётся, считается отдельно.
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "criteria" / "economy_second_reading_2026-10-20.json"
REV = ROOT / "reviews" / "econ2"


def decide(title: int, readers: list) -> str:
    nums = [r for r in readers if r is not None]
    if any(r != title for r in nums):
        return "flipped" if len(nums) == 2 and all(r == -title for r in nums) else "removed"
    return "kept" if nums else "kept_unread"


def readings(prefix: str) -> dict:
    out = {}
    for f in sorted(glob.glob(str(REV / f"{prefix}_part*.out.json"))):
        for b, v in json.loads(Path(f).read_text(encoding="utf-8")).items():
            s = v.get("sign")
            out[int(b)] = None if s is None else int(s)
    return out


def main() -> int:
    universe = json.loads((REV / "universe.json").read_text(encoding="utf-8"))
    title = {}
    for f in sorted(glob.glob(str(ROOT / "criteria" / "full_signs_K*.json"))):
        for b, v in json.loads(Path(f).read_text(encoding="utf-8"))["signs"].get("economy", {}).items():
            if int(v):                           # знак по названию — ненулевой, как в определении universe (v96: 2195309 — 0 в K24, −1 в K25)
                title.setdefault(int(b), int(v))
    cl, cx = readings("claude"), readings("codex")
    missing = [b for b in universe if b not in cl or b not in cx]
    if missing:                                  # §23: неполное чтение — отказ, а не тихий «kept»
        print(f"ОТКАЗ: нет чтения у {len(missing)} законопроектов, например {missing[:5]}")
        return 1
    notext = {b for b in universe if not (ROOT / "data" / "bill_texts" / f"{b}.txt").exists()}
    res = {b: ("kept_notext" if b in notext else decide(title[b], [cl[b], cx[b]])) for b in universe}
    c = Counter(res.values())
    OUT.write_text(json.dumps({
        "ГРАНИЦА_§3": ("ВИДЕЛ до записи: знаки по названиям (full_signs), выводы траектории по экономике (16/19 «ясной линии нет») и отчёт Codex v94. "
                       "НЕ ВИДЕЛ: эффекта этого файла на стрелки и траекторию — правило снятия объявлено до выгрузки текстов (d750f6d); "
                       "читатели не видели знака по названию."),
        "rule": "criteria/declared_before_economy_reread_2026-10-20.yaml",
        "counts": dict(c), "universe": len(universe),
        "agree_numeric": sum(cl[b] is not None and cl[b] == cx[b] for b in universe),
        "both_numeric": sum(cl[b] is not None and cx[b] is not None for b in universe),
        "removed": sorted(b for b, r in res.items() if r in ("removed", "flipped")),
        "bills": {str(b): {"title": title[b], "claude": cl[b], "codex": cx[b], "result": res[b]} for b in universe},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT.relative_to(ROOT), dict(c))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        assert decide(1, [1, None]) == "kept" and decide(1, [None, None]) == "kept_unread"
        assert decide(1, [0, 1]) == "removed" and decide(-1, [1, 1]) == "flipped" and decide(-1, [1, None]) == "removed"
        print("самопроверка economy_second_reading пройдена: 5 случаев")
        sys.exit(0)
    sys.exit(main())
