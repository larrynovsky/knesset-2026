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
    d = json.loads(p.read_text(encoding="utf-8"))["signs"]
    return {int(k): int(v["sign"] if isinstance(v, dict) else v) for k, v in d.items()}


def arrow_of(up: int, down: int) -> str | None:
    n = up + down
    if n < 3:
        return None
    share = down / n
    return "down" if share >= 2 / 3 else "up" if share <= 1 / 3 else "both"


def theme_arrows(theme: str, votes: dict | None = None) -> dict:
    """fid -> направление, счётчики законов и до двух примеров с каждой стороны."""
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
    from build_report import NAMES_RU
    translations = json.loads(NAMES_RU.read_text(encoding="utf-8"))["names"]
    names = {r["bill_id"]: translations.get(str(r["bill_id"]), {}).get("ru") or r["bill_name"]
             for r in rows}
    out = {}
    for fac, entry in per.items():
        fid = int(str(fac).split("|")[0])
        up, down = int(entry.get("up", 0)), int(entry.get("down", 0))
        out[fid] = {"arrow": arrow_of(up, down), "up": up, "down": down,
                    "examples": {side: [names[b] for b in entry[side + "_bills"][:2]]
                                 for side in ("up", "down")}}
    return out


def selftest() -> int:
    assert arrow_of(1, 9) == "down" and arrow_of(9, 1) == "up" and arrow_of(5, 5) == "both"
    assert all(arrow_of(n, 0) is None for n in range(3))
    assert arrow_of(3, 0) == "up"
    for theme in THEMES:
        assert load_signs(theme), f"нет знаков темы {theme}"
    from unittest.mock import patch
    from tempfile import TemporaryDirectory
    # Удалённый вход обязан остановить расчёт, а не означать нулевое покрытие.
    with TemporaryDirectory() as tmp, patch(__name__ + ".ROOT", Path(tmp)):
        try:
            load_signs("security")
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("пропажа theme_signs_security.json не обнаружена")
    # Позиция против инвертирует плюс; повторные чтения не удваивают закон;
    # противоречивые чтения исключаются и из счётчика, и из примеров.
    from direction_confidence import compose
    rows = [{"bill_id": bid, "vote_id": i, "for_option_desc": "test",
             "by_faction": {"1|A": {position: 10}, "2|B": {"against" if position == "for" else "for": 10}}}
            for i, (bid, position) in enumerate([(1, "for"), (1, "for"), (2, "against"),
                                                (3, "for"), (3, "against")])]
    per, _, _ = compose(rows, {1: 1, 2: 1, 3: 1}, {"test": {"sign": "carries"}},
                        {"split_below": 0.5, "drop_below": 0.1})
    assert per["1|A"]["up_bills"] == [1] and per["1|A"]["down_bills"] == [2]
    assert per["1|A"]["up"] == per["1|A"]["down"] == 1
    for row in rows:
        row["bill_name"] = "חוק " + str(row["bill_id"])
    with TemporaryDirectory() as tmp:
        names = Path(tmp) / "names.json"
        names.write_text(json.dumps({"names": {"1": {"ru": "Русское название"}}}))
        with patch(__name__ + ".load_signs", return_value={1: 1, 2: 1, 3: 1}), \
             patch("direction_confidence.sign_table", return_value={"test": {"sign": "carries"}}), \
             patch("build_report.NAMES_RU", names):
            result = theme_arrows("security", {"rows": rows})[1]
        assert result["examples"] == {"up": ["Русское название"], "down": ["חוק 2"]}
        assert result["arrow"] is None and result["up"] + result["down"] == 2
    print("самопроверка theme_arrows пройдена")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    for t in THEMES:
        print(t, theme_arrows(t))
