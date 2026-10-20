#!/usr/bin/env python3
"""Траектория строк бюллетеня через Кнессеты 20→25 с ролью по дате голосования.

Правило — criteria/trajectory_2026-10-20.json (объявлено до расчёта, решения владельца 20.10).
Прибор тот же, что у обзора и срезов: theme_arrows (compose, отсев единогласных, 2/3, ≥3 законов).
Новое здесь одно: голоса фракции делятся по дате на «в коалиции» и «в оппозиции»
(интервалы правительства — data/periods_N.yaml через slice_arrows.gov_spans и
criteria/periods.yaml через dynamics.gov_spans), и каждая часть даёт свою точку.
Выход: data/trajectory.json.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
RULES = ROOT / "criteria" / "trajectory_2026-10-20.json"
OUT = ROOT / "data" / "trajectory.json"
THEMES4 = ("rule_of_law", "economy", "religion_state", "security")
KNS = ("20", "21", "22", "23", "24", "25")


def in_spans(day: str, spans) -> bool:
    return any(a <= day < b for a, b in spans)


def transition(k: str) -> tuple[str, str]:
    """От присяги Кнессета до присяги первого правительства, сформированного в нём (владелец 20.10, вопрос 5)."""
    import re
    from fetch_votes import WINDOWS
    lo, hi = (x[:10] for x in WINDOWS[int(k)])
    src = ROOT / "criteria" / "periods.yaml" if k == "25" else ROOT / "data" / f"periods_{k}.yaml"
    pairs = [(int(g), s) for g, s in re.findall(r"government: (\d+)\n\s+start: (\S+)", src.read_text(encoding="utf-8"))]
    g0 = max((g for g, s in pairs if s <= lo), default=min(g for g, _ in pairs) - 1)
    new = [s for g, s in pairs if g > g0 and lo < s < hi]
    return lo, (min(new) if new else hi)


TRANSITION: dict = {}
COVERAGE: dict = {}   # Кнессет → сколько голосований источника и сколько из них в расчёте


def segments(rows: list, fid, spans, transition=None) -> list:
    """Строки, где фракция голосовала, по времени → непрерывные куски одной роли [(role, rows)].
    transition = (начало, конец) — от присяги Кнессета до присяги первого правительства (если включено)."""
    key = str(fid)
    mine = sorted((r for r in rows if any(k.split("|")[0] == key for k in r["by_faction"])), key=lambda r: r["date"])
    out = []
    for r in mine:
        d = r["date"][:10]
        role = "trans" if transition and transition[0] <= d < transition[1] else ("gov" if in_spans(d, spans) else "opp")
        if out and out[-1][0] == role:
            out[-1][1].append(r)
        else:
            out.append((role, [r]))
    return out


def verdict(points: list) -> tuple[str, int]:
    """points: [(arrow, role)] в порядке времени → (метка, число ясных точек). Правило — RULES['rules']['verdict'].
    Точки переходного периода (role='trans') в вывод не входят."""
    points = [(a, r) for a, r in points if r in ("gov", "opp")]
    clear = [(a, r) for a, r in points if a in ("up", "down")]
    if len(clear) < 2:
        mixed = sum(1 for a, _ in points if a == "both")
        return ("mixed" if mixed >= 2 else "few"), len(clear)
    dirs = {a for a, _ in clear}
    roles = {r for _, r in clear}
    if len(dirs) == 1:
        if roles == {"gov", "opp"}:
            return "steady", len(clear)
        other = {"gov", "opp"} - roles
        if any(a == "both" and r in other for a, r in points):
            return "holds_" + next(iter(roles)), len(clear)
        return "one_role_" + next(iter(roles)), len(clear)
    by = {}
    for a, r in clear:
        by.setdefault(r, set()).add(a)
    if set(by) == {"gov", "opp"} and all(len(v) == 1 for v in by.values()) and by["gov"] != by["opp"]:
        return "by_role", len(clear)
    return "shifts", len(clear)


_OLD: dict = {}


def old_signs_any() -> dict:
    """Прежние знаки из всех файлов всех Кнессетов: закон, перешедший из Кнессета в Кнессет, сохраняет
    уже выверенный знак (правило keep_existing; пример — 2168881, знак по полному тексту)."""
    if _OLD:
        return _OLD
    from slice_arrows import load_signs as ls
    import theme_arrows as TA
    import build_line_cards as BLC
    lt = TA.load_signs
    TA.USE_FULL = BLC.USE_FULL = False      # прежние знаки — без полной разметки (вопрос 6 добавил её в загрузчики)
    out = {th: {} for th in THEMES4}
    for n in (20, 21, 22, 23, 24):
        for th in THEMES4:
            out[th].update(ls(n, th) or {})
    for th in THEMES4[1:]:
        out[th].update(lt(th))
    from build_line_cards import axis_directions
    from render_method import ARROW
    out["rule_of_law"].update({int(b): int(v) for b, v in axis_directions(ARROW)[0].items()})
    TA.USE_FULL = BLC.USE_FULL = True
    _OLD.update(out)
    return _OLD


def full_signs(k: str) -> dict:
    """Новая разметка по всем голосованным законам (criteria/full_signs_K<n>.json); прежний знак любого файла главнее."""
    p = ROOT / "criteria" / f"full_signs_K{k}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))["signs"]
    old = old_signs_any()
    return {th: {int(b): old[th].get(int(b), int(v)) for b, v in d.get(th, {}).items()} for th in THEMES4}


def merge_signs(old: dict, new: dict) -> dict:
    out = {}
    for th in THEMES4:
        m = dict(new.get(th, {}))
        m.update(old.get(th) or {})
        out[th] = m
    return out


def votes_path(k: str) -> Path:
    """Полная выгрузка (все голосованные законы, владелец 20.10), если она есть; иначе прежняя выборка."""
    full = ROOT / "data" / f"votes_full_{k}.json"
    return full if full.exists() else ROOT / "data" / f"votes_{k}.json"


def load_knesset(k: str):
    """→ (votes, signs по теме, интервалы правительства по fid, личные голоса или None)."""
    if k == "25":
        from build_line_cards import axis_directions
        from render_method import ARROW, VOTES
        from theme_arrows import load_signs, personal_votes
        from dynamics import gov_spans as g25
        vp = votes_path(k)
        votes = json.loads(vp.read_text(encoding="utf-8"))
        signs = {"rule_of_law": axis_directions(ARROW)[0]}
        signs.update({th: load_signs(th) for th in THEMES4[1:]})
        signs = merge_signs(signs, full_signs(k))
        spans = {fid: [tuple(x) for x in v] for fid, v in g25().items()}
        cache = ROOT / "data" / ("named_votes_cache_full" if vp.name.startswith("votes_full") else "named_votes_cache")
        pv, _ = personal_votes(votes, cache=cache)
        return votes, signs, spans, pv
    from slice_arrows import gov_spans, load_signs
    n = int(k)
    lin = json.loads((ROOT / "criteria" / "slice_lineage_2026-10-19.json").read_text(encoding="utf-8"))
    votes = json.loads(votes_path(k).read_text(encoding="utf-8"))
    signs = merge_signs({th: load_signs(n, th) for th in THEMES4}, full_signs(k))
    gd = {str(f): v for f, v in gov_spans(n).items()}
    for fid, sp in lin.get("gov_override", {}).get(k, {}).items():
        gd[str(fid)] = [tuple(x) for x in sp]
    for fid in lin.get("coalition_without_ministers", {}).get(k, []):
        gd[str(fid)] = [("0000-01-01", "9999-12-31")]
    return votes, signs, gd, None


def compute() -> dict:
    from theme_arrows import theme_arrows
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    tracks = rules["tracks"]
    need = {}
    for let, trs in tracks.items():
        for t in trs:
            for k, fids in t["links"].items():
                need.setdefault(k, set()).update(str(f) for f in fids)
    points: dict = {}          # (k, fid) -> [point]
    for k in KNS:
        if k not in need:
            continue
        votes, signs, spans, pv = load_knesset(k)
        TRANSITION.setdefault(k, transition(k))
        vb = ROOT / "data" / f"voted_bills_{k}.json"
        if vb.exists():
            v = json.loads(vb.read_text(encoding="utf-8"))
            COVERAGE[k] = {"heads": v["heads"], "bill_votes": v["bill_votes"], "classes": v["classes"],
                           "in_calc": len(votes["rows"]), "source": votes_path(k).name}
        cache = {}
        for fid in sorted(need[k]):
            src = pv if fid == "yashar" else votes
            sp = spans.get("1110" if fid == "yashar" else fid, [])   # правило personal
            pts = []
            for role, rows in segments(src["rows"], fid, sp, TRANSITION.get(k)):
                themes = {}
                for th in THEMES4:
                    if not signs.get(th):
                        continue
                    ck = (fid == "yashar", role, th, tuple(r["vote_id"] for r in rows))   # личные строки ≠ строки фракций (Codex v87)
                    if ck not in cache:
                        cache[ck] = theme_arrows(th, {"rows": rows}, signs=signs[th])
                    a = cache[ck].get(int(fid) if fid.isdigit() else fid, {})
                    themes[th] = {x: a.get(x) for x in ("arrow", "up", "down", "consensus")}
                pts.append({"k": k, "fid": fid, "role": role, "from": rows[0]["date"][:10], "to": rows[-1]["date"][:10],
                            "votes": len(rows), "themes": themes})
            points[(k, fid)] = sorted(pts, key=lambda p: p["from"])
    out = {"rules_version": rules["version"], "transition": dict(TRANSITION), "coverage": COVERAGE, "lines": {}}
    for let, trs in tracks.items():
        out["lines"][let] = []
        for t in trs:
            seq = [p for k in KNS for f in t["links"].get(k, []) for p in points.get((k, str(f)), [])]
            seq.sort(key=lambda p: (p["k"], p["from"]))
            verd = {th: dict(zip(("label", "clear"), verdict([(p["themes"].get(th, {}).get("arrow"), p["role"]) for p in seq])))
                    for th in THEMES4}
            out["lines"][let].append({"name": t["name"], "links": t["links"], "points": seq, "verdict": verd})
    return out


def selftest() -> int:
    assert verdict([("down", "gov"), ("down", "opp")]) == ("steady", 2)
    assert verdict([("down", "gov"), ("both", "opp"), ("down", "gov")]) == ("holds_gov", 2)
    assert verdict([("down", "gov"), ("down", "gov")]) == ("one_role_gov", 2)
    assert verdict([("down", "gov"), ("up", "opp"), ("down", "gov")]) == ("by_role", 3)
    assert verdict([("down", "gov"), ("up", "gov")]) == ("shifts", 2)
    assert verdict([("down", "gov"), (None, "opp")]) == ("few", 1)
    assert verdict([("both", "gov"), ("both", "opp"), ("up", "gov")]) == ("mixed", 1)
    rows = [{"date": "2021-07-01T10:00", "by_faction": {"962|x": {}}}, {"date": "2021-05-01T10:00", "by_faction": {"962|x": {}}},
            {"date": "2021-07-01T10:00", "by_faction": {"963|y": {}}}, {"date": "2022-01-01T10:00", "by_faction": {"962|x": {}}}]
    s = segments(rows, 962, [("2021-04-06", "2021-06-13")])
    assert [(r, len(x)) for r, x in s] == [("gov", 1), ("opp", 2)], s          # сортировка по дате, слияние соседей
    s = segments(rows, 962, [("2021-04-06", "2021-06-13")], ("2021-04-06", "2021-06-13"))
    assert [r for r, _ in s] == ["trans", "opp"], s
    assert in_spans("2021-06-13", [("2021-04-06", "2021-06-13")]) is False   # правая граница не включена
    assert transition("25") == ("2022-11-15", "2022-12-29"), transition("25")
    assert transition("24") == ("2021-04-06", "2021-06-13"), transition("24")
    assert transition("21") == ("2019-04-30", "2019-10-03"), transition("21")   # правительство не сформировано
    print("самопроверка trajectory пройдена: 13 утверждений")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    d = compute()
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUT, sum(len(t["points"]) for v in d["lines"].values() for t in v), "точек")
