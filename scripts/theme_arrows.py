#!/usr/bin/env python3
"""Стрелки фракций по описательным темам (экономика, религия, безопасность).

Покрытие вместо точности (владелец 19.10): знак закона по теме — из
criteria/theme_signs_<theme>.json (ставят Claude/Codex), голоса — те же
поимённые голосования, что у решающей оси; арифметика — та же compose()
из direction_confidence, порог направления — две трети, как в
build_line_cards.arrows.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = {"economy": "Экономика", "religion_state": "Государство и религия",
          "security": "Безопасность и конфликт"}


def load_signs(theme: str) -> dict:
    p = ROOT / "criteria" / f"theme_signs_{theme}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))["signs"]
    return {int(k): int(v["sign"] if isinstance(v, dict) else v) for k, v in d.items()}


def arrow_of(up: int, down: int) -> str | None:
    n = up + down
    if not n:
        return None
    share = down / n
    return "down" if share >= 2 / 3 else "up" if share <= 1 / 3 else "both"


def theme_arrows(theme: str, votes: dict | None = None) -> dict:
    """fid -> {arrow, up, down, acts}; пусто, если знаков темы нет."""
    signs = load_signs(theme)
    if not signs:
        return {}
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import arrow_rule, compose, sign_table
    from build_line_cards import _arrow_split
    rule = arrow_rule()
    rule["split_below"] = float(_arrow_split())
    votes = votes or json.loads((ROOT / "data" / "votes_25.json").read_text(encoding="utf-8"))
    rows = [r for r in votes["rows"] if r.get("bill_id") in signs]
    per, _, _ = compose(rows, signs, sign_table(), rule)
    out = {}
    for fac, entry in per.items():
        fid = int(str(fac).split("|")[0])
        up, down = int(entry.get("up", 0)), int(entry.get("down", 0))
        out[fid] = {"arrow": arrow_of(up, down), "up": up, "down": down}
    return out


def selftest() -> int:
    assert arrow_of(1, 9) == "down" and arrow_of(9, 1) == "up" and arrow_of(5, 5) == "both"
    assert arrow_of(0, 0) is None
    print("самопроверка theme_arrows пройдена")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    for t in THEMES:
        print(t, theme_arrows(t))
