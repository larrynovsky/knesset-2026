#!/usr/bin/env python3
"""Динамика внутри 25-го Кнессета по полугодиям (владелец 19.10, вариант «в»).

Для каждой фракции 25-го (и личных голосов Яшар!) по каждой из четырёх тем и
каждому полугодию: сколько законов фракция двинула в одну сторону (up) и в
другую (down). Прибор тот же, что у стрелок обзора: direction_confidence.compose,
те же знаки законов (ось суда — build_line_cards.axis_directions, темы —
criteria/theme_signs_*.json), та же таблица смысла «за». Своей арифметики нет.

Закон учитывается в полугодии, где по нему голосовали; голосовали в двух — в обоих.
Роль (в правительстве) — из criteria/periods.yaml, справочника, построенного из источника.
Выход: data/dynamics_25.json.
"""
from __future__ import annotations
import json, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "dynamics_25.json"
THEMES4 = ("rule_of_law", "economy", "religion_state", "security")


def halves(window: list[str]) -> list[tuple[str, str]]:
    from render_time_page import periods
    return [(str(a), str(b)) for a, b in periods(window, 6)]


def count(rows: list[dict], signs: dict, table: dict, rule: dict) -> dict:
    from direction_confidence import compose
    per, _, _ = compose(rows, signs, table, rule)
    return {str(k).split("|")[0]: [int(v.get("up", 0)), int(v.get("down", 0))] for k, v in per.items()}


def gov_spans() -> dict[str, list[list[str]]]:
    t = (ROOT / "criteria" / "periods.yaml").read_text(encoding="utf-8")
    out: dict[str, list] = {}
    for fid, s, f in re.findall(r"faction_id: (\d+)\n.*?\n\s+government: \d+\n\s+start: (\S+)\n\s+finish: (\S+)", t):
        out.setdefault(fid, []).append([s, "2026-09-01" if f == "null" else f])
    return out


def compute(votes: dict | None = None) -> dict:
    from build_line_cards import axis_directions, _arrow_split
    from direction_confidence import arrow_rule, sign_table
    from render_method import ARROW, VOTES
    from theme_arrows import load_signs, personal_votes
    votes = votes or json.loads(VOTES.read_text(encoding="utf-8"))
    rule = arrow_rule(); rule["split_below"] = float(_arrow_split())
    table = sign_table()
    signs = {"rule_of_law": axis_directions(ARROW)[0]}
    signs.update({th: load_signs(th) for th in THEMES4[1:]})
    pv, _ = personal_votes(votes)
    bins = halves(votes["window"])
    series: dict = {}
    for src in (votes, pv):
        for i, (a, b) in enumerate(bins):
            rows = [r for r in src["rows"] if a <= r["date"][:10] < b]
            for th in THEMES4:
                for fid, ud in count(rows, signs[th], table, rule).items():
                    s = series.setdefault(fid, {}).setdefault(th, [[0, 0] for _ in bins])
                    s[i] = ud
    return {"bins": bins, "series": series, "gov": gov_spans(),
            "note": "up/down — число законов темы по полугодию голосования; тот же прибор, что стрелки обзора"}


def selftest() -> int:
    assert halves(["2022-11-15T00:00:00Z", "2023-08-01T00:00:00Z"]) == [
        ("2022-11-15", "2023-01-01"), ("2023-01-01", "2023-07-01"), ("2023-07-01", "2023-08-01")]
    # полугодия покрывают окно 25-го без дыр
    w = json.loads((ROOT / "data" / "votes_25.json").read_text(encoding="utf-8"))["window"]
    b = halves(w)
    assert b[0][0] == w[0][:10] and b[-1][1] == w[1][:10]
    assert all(x[1] == y[0] for x, y in zip(b, b[1:])), "полугодия не смыкаются"
    print("самопроверка dynamics пройдена: 3 утверждения")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    res = compute()
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(res["bins"]), "полугодий,", len(res["series"]), "фракций")
