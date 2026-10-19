#!/usr/bin/env python3
"""Временные срезы: как фракции строки бюллетеня голосовали в 20–24-м Кнессете.

Владелец 19.10: «насколько менялась позиция партии по каденциям, начиная с 2016».
Прибор тот же, что у 25-го: theme_arrows.theme_arrows (compose, порог 2/3,
отсев единогласных) — меняются только голоса (data/votes_N.json) и знаки
(criteria/slice_signs_K<N>.json). Своей арифметики здесь нет.

Входы:
  criteria/slice_lineage_2026-10-19.json — какая фракция N-го Кнессета чья (решение владельца);
  data/periods_N.yaml — кто был в правительстве (генерирован из источника build_periods.py).
Выход: data/slices.json — строка бюллетеня × Кнессет × тема → слово по каждому звену.

Роль (в правительстве/в оппозиции) печатается рядом со словом: смена роли — не смена
взглядов (Ликуд в 24-м голосовал против законов правительства Беннета).
"""
from __future__ import annotations
import json, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
KNESSETS = (20, 21, 22, 23, 24)
THEMES4 = ("rule_of_law", "economy", "religion_state", "security")
LINEAGE = ROOT / "criteria" / "slice_lineage_2026-10-19.json"
OUT = ROOT / "data" / "slices.json"
MIN_GOV_DAYS = 30   # звено в правительстве, если фракция жила в нём ≥30 дней (артефакты однодневных фракций)


def load_signs(n: int, theme: str) -> dict | None:
    p = ROOT / "criteria" / f"slice_signs_K{n}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))["signs"].get(theme, {})
    return {int(k): int(v["sign"] if isinstance(v, dict) else v) for k, v in d.items()}


def gov_days(n: int) -> dict[int, int]:
    """FactionID → дней в правительстве в N-м Кнессете (пересечение с жизнью фракции)."""
    p = ROOT / "data" / f"periods_{n}.yaml"
    t = p.read_text(encoding="utf-8")
    life = {r["Id"]: (r["StartDate"][:10], (r.get("FinishDate") or r["StartDate"])[:10])
            for r in json.loads((ROOT / "data" / "kns_faction_20_24.json").read_text(encoding="utf-8"))}
    out: dict[int, int] = {}
    for fid, s, f in re.findall(r"faction_id: (\d+)\n.*?\n\s+government: \d+\n\s+start: (\S+)\n\s+finish: (\S+)", t):
        fid = int(fid)
        a, b = life.get(fid, (s, f))
        lo, hi = max(s, a), min(f if f != "null" else b, b)
        if lo < hi:
            out[fid] = out.get(fid, 0) + (date.fromisoformat(hi) - date.fromisoformat(lo)).days
    return out


def role(days: int, life_days: int) -> str:
    """Доля жизни фракции в правительстве: ≥80% — в правительстве, ≤20% — в оппозиции.
    Ликуд в 24-м: два месяца переходного правительства из девятнадцати — оппозиция."""
    share = days / max(life_days, 1)
    if days < MIN_GOV_DAYS or share <= 0.2:
        return "оппозиция"
    return "правительство" if share >= 0.8 else "часть срока в правительстве"


def check_lineage(lin: dict, factions: dict[int, int]) -> None:
    """Звено обязано указывать на фракцию ТОГО ЖЕ Кнессета: чужой Кнессет = чужие голоса."""
    for let, by_k in lin["lines"].items():
        for k, links in by_k.items():
            for link in links:
                fid = link[0]
                if factions.get(fid) != int(k):
                    raise SystemExit(f"ОТКАЗ: строка {let}, Кнессет {k}: фракция {fid} "
                                     f"из Кнессета {factions.get(fid)}")


def compute() -> dict:
    from theme_arrows import theme_arrows, personal_votes
    lin = json.loads(LINEAGE.read_text(encoding="utf-8"))
    fac_rows = json.loads((ROOT / "data" / "kns_faction_20_24.json").read_text(encoding="utf-8"))
    factions = {r["Id"]: r["KnessetNum"] for r in fac_rows}
    life = {r["Id"]: max(1, (date.fromisoformat((r.get("FinishDate") or r["StartDate"])[:10])
                             - date.fromisoformat(r["StartDate"][:10])).days) for r in fac_rows}
    check_lineage(lin, factions)
    out = {"knessets": {}, "lines": {}}
    for n in KNESSETS:
        vp = ROOT / "data" / f"votes_{n}.json"
        if not vp.exists():
            out["knessets"][str(n)] = {"status": "нет выгрузки"}
            continue
        votes = json.loads(vp.read_text(encoding="utf-8"))
        gd = gov_days(n)
        arrows, have = {}, []
        for th in THEMES4:
            signs = load_signs(n, th)
            if signs is None:
                continue
            have.append(th)
            arrows[th] = theme_arrows(th, votes, signs=signs)
        signed = {b for th in have for b, sg in (load_signs(n, th) or {}).items() if sg}
        voted_bills = {r["bill_id"] for r in votes["rows"]}
        out["knessets"][str(n)] = {"status": "ok" if have else "нет знаков", "themes": have,
                                   "signed_bills": len(signed & voted_bills),
                                   "rows": len(votes["rows"]),
                                   "bills": len({r["bill_id"] for r in votes["rows"]})}
        for let, by_k in lin["lines"].items():
            cell = {"links": []}
            coalition = lin.get("coalition_without_ministers", {}).get(str(n), [])
            for fid, typ, *note in by_k.get(str(n), []):
                voted = sum(1 for r in votes["rows"] if any(k.split("|")[0] == str(fid) for k in r["by_faction"]))
                if not voted:
                    # фракция возникла после последнего голосования (роспуск 30.06.2022) — голосов нет
                    continue
                cell["links"].append({
                    "fid": fid, "type": typ, "note": note[0] if note else "", "votes": voted,
                    "role": "коалиция без министров" if fid in coalition else role(gd.get(fid, 0), life[fid]),
                    "themes": {th: {k: arrows[th].get(fid, {}).get(k) for k in ("arrow", "up", "down")}
                               for th in have}})
            members = {s: m for s, m in lin.get("personal_ids", {}).get(let, {}).items()}
            if members and have:
                try:
                    pv, stats = personal_votes(votes, cache=ROOT / "data" / "named_votes_cache_slices",
                                               members={s: tuple(m) for s, m in members.items()})
                    cell["personal"] = {"stats": {s: st["votes"] for s, st in stats.items()},
                                        "themes": {th: {k: theme_arrows(th, pv, signs=load_signs(n, th)).get("yashar", {}).get(k)
                                                        for k in ("arrow", "up", "down")} for th in have}}
                except ValueError as exc:
                    cell["personal"] = {"none": str(exc)}
            out["lines"].setdefault(let, {})[str(n)] = cell
    return out


def selftest() -> int:
    fac = {882: 20, 962: 24}
    check_lineage({"lines": {"x": {"20": [[882, "party"]], "24": [[962, "party"]]}}}, fac)
    try:
        check_lineage({"lines": {"x": {"20": [[962, "party"]]}}}, fac)
    except SystemExit:
        pass
    else:
        raise AssertionError("фракция 24-го под 20-м Кнессетом не поймана")
    assert role(0, 1000) == "оппозиция" and role(29, 1000) == "оппозиция"
    assert role(900, 1000) == "правительство" and role(300, 1000) == "часть срока в правительстве"
    assert role(68, 588) == "оппозиция", "два месяца переходного правительства не делают партию правительственной"
    print("самопроверка slice_arrows пройдена: 7 утверждений")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    res = compute()
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["knessets"], ensure_ascii=False))
