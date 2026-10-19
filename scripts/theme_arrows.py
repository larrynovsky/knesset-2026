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


def arrow_of(up: int, down: int, min_acts: int = 3) -> str | None:
    n = up + down
    if n < min_acts:
        return None
    share = down / n
    return "down" if share >= 2 / 3 else "up" if share <= 1 / 3 else "both"


def names_ru_path() -> Path:
    return sorted((ROOT / "docs" / "reference").glob("vote_names_ru_*.json"))[-1]


def theme_arrows(theme: str, votes: dict | None = None) -> dict:
    """fid -> направление, счётчики законов и до двух примеров с каждой стороны."""
    signs = load_signs(theme)
    if not signs:
        return {}
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import arrow_rule, compose, sign_table, lopsided
    from build_line_cards import _arrow_split
    rule = arrow_rule()
    rule["split_below"] = float(_arrow_split())
    votes = votes or json.loads((ROOT / "data" / "votes_25.json").read_text(encoding="utf-8"))
    rows = [r for r in votes["rows"] if r.get("bill_id") in signs]
    per, _, _ = compose(rows, signs, sign_table(), rule)
    # Самый поздний справочник переводов: в 08-13 нет актов тем, и примеры
    # выходили на иврите посреди русского текста (замечено глазами 19.10).
    translations = json.loads(names_ru_path().read_text(encoding="utf-8"))["names"]
    names = {r["bill_id"]: translations.get(str(r["bill_id"]), {}).get("ru") or r["bill_name"]
             for r in rows}
    # Закон считается один раз; любое различающее чтение исключает его
    # из consensus для всех фракций. Нулевое участие не является голосом.
    consensus_bills, retained = {}, set()
    for r in rows:
        bid, bf = r["bill_id"], r.get("by_faction") or {}
        fors = sum(int(c.get("for", 0)) for c in bf.values())
        against = sum(int(c.get("against", 0)) for c in bf.values())
        if not lopsided(fors, against, rule["drop_below"]):
            retained.add(bid)
        elif fors + against and signs[bid] in (-1, 1):
            for fac, c in bf.items():
                if any(int(c.get(k, 0)) > 0 for k in ("for", "against", "abstain")):
                    consensus_bills.setdefault(fac, set()).add(bid)
    out = {}
    for fac in per.keys() | consensus_bills.keys():
        entry = per.get(fac, {})
        fid = int(str(fac).split("|")[0])
        up, down = int(entry.get("up", 0)), int(entry.get("down", 0))
        consensus = len(consensus_bills.get(fac, set()) - retained)
        out[fid] = {"arrow": arrow_of(up, down), "up": up, "down": down,
                    "consensus": consensus,
                    "text": (f"со всеми ({consensus})"
                             if consensus >= 3 else f"мало законов ({up + down})"),
                    "examples": {side: [names[b] for b in entry.get(side + "_bills", [])[:2]]
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
             patch(__name__ + ".names_ru_path", return_value=names):
            result = theme_arrows("security", {"rows": rows})[1]
            unanimous = [{"bill_id": b, "vote_id": i, "bill_name": "test",
                          "for_option_desc": "test",
                          "by_faction": {"1|A": {"for": 10}, "2|B": {"for": 10},
                                         "3|Absent": {"for": 0}}}
                         for i, b in enumerate((1, 1, 2, 3))]
            agreed = theme_arrows("security", {"rows": unanimous})
            assert agreed[1]["consensus"] == agreed[2]["consensus"] == 3
            assert 3 not in agreed
            assert agreed[1]["arrow"] is None and agreed[1]["up"] == agreed[1]["down"] == 0
            text = "со всеми (3)"
            assert agreed[1]["text"] == text
            # Проходим настоящие рендеры, а не проверяем только поле данных.
            import render_overview as view
            sample = {t: {1096: agreed[1]} for t in THEMES}
            matrix = {"lines": [{"anchor_id": 1096, "line": "test", "a": {"status": "observed"}}]}
            with patch.dict(view._THEME_CACHE, sample, clear=True), \
                 patch("theme_arrows.theme_arrows", return_value={1096: agreed[1]}), \
                 patch.object(view, "party_names", return_value={1096: "test"}), \
                 patch.object(view, "load_ballot", return_value={"unmapped_factions": {}, "lists": [{
                     "factions": [1096], "absent": [], "ru": "test", "he": "test", "leaders": "test"}]}), \
                 patch.object(view, "owner_law_positions", return_value=[{
                     "name": "test", "labels": {view._al(1096): "нет позиции", view._al(1108): "нет позиции"}, "counts": {view._al(1096): "за 0", view._al(1108): "за 0"}, "positions": {view._al(1096): "нет позиции", view._al(1108): "нет позиции"}}] * 4):
                assert text in view._theme_lines({"anchor_id": 1096})
                assert f"<td>{text}</td>" in view.theme_table(matrix, {})
                assert text in view.ballot_table(matrix, {})
                for counts in ((9, 3), (9, 9)):
                    entries = {fid: dict(agreed[1], consensus=n, text=f"со всеми ({n})")
                               for fid, n in zip((1096, 1108), counts)}
                    with patch("theme_arrows.theme_arrows", return_value=entries), \
                         patch.object(view, "party_names", return_value={1096: "A", 1108: "B"}), \
                         patch.object(view, "load_ballot", return_value={"unmapped_factions": {}, "lists": [{
                             "factions": [1096, 1108], "absent": [], "ru": "test", "he": "test", "leaders": "test"}]}):
                        assert f"со всеми ({counts[0]}/{counts[1]})" in view.ballot_table(matrix, {})
            for n in (0, 1, 2):
                small = theme_arrows("security", {"rows": unanimous[:0] if n == 0 else
                                                    [r for r in unanimous if r["bill_id"] <= n]})
                if n:
                    assert small[1]["consensus"] == n
                    assert small[1]["text"] == "мало законов (0)"
                else:
                    assert small == {}
            mixed = theme_arrows("security", {"rows": unanimous + rows})[1]
            assert mixed["consensus"] == 0, "различающие чтения исключают закон целиком"
            empty = [dict(r, by_faction={"1|A": {"abstain": 10}}) for r in unanimous]
            assert theme_arrows("security", {"rows": empty}) == {}, "нет за/против — не единогласие"

        assert result["examples"] == {"up": ["Русское название"], "down": ["חוק 2"]}
        assert result["arrow"] is None and result["up"] + result["down"] == 2
    print("самопроверка theme_arrows пройдена")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    for t in THEMES:
        print(t, theme_arrows(t))
