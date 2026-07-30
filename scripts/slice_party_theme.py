#!/usr/bin/env python3
"""Срез «партия × ось чек-листа» из собранных голосований — вход в карточку.

Это ещё НЕ карточка: карточке нужен второй канал (обязательство и бюджетная
строка), которого пока нет. Здесь только канал А, доведённый до вида, в котором
он что-то говорит о партии, а не о законе.

§10 соблюдён буквально: рядом с каждым голосом печатается ForOptionDesc.
«За» в одном голосовании означает «принять закон», в другом — «отклонить
предложение», и таблица без этой колонки читалась бы неверно.

§1: партия берётся вместе с периодом из criteria/periods.yaml — голос до
выхода партии из правительства и после относятся к разным наблюдениям.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOTES = ROOT / "data" / "votes_25.json"
PERIODS = ROOT / "criteria" / "periods.yaml"


def load_periods(faction: int) -> list[dict]:
    """Мини-разбор periods.yaml без внешних зависимостей: yaml на Studio нет."""
    txt = PERIODS.read_text(encoding="utf-8")
    out, cur = [], None
    for line in txt.splitlines():
        if line.startswith("  - id:"):
            cur = {"id": line.split(":", 1)[1].strip()}
            out.append(cur)
        elif cur is not None and line.startswith("    "):
            k, _, v = line.strip().partition(":")
            cur[k] = v.strip().strip('"')
    return [p for p in out if p.get("faction_id") == str(faction)]


def period_of(periods: list[dict], date: str) -> str:
    d = date[:10]
    for p in periods:
        fin = p.get("finish") or "null"
        if p.get("start", "") <= d and (fin == "null" or d <= fin):
            return p["id"]
    return "вне-правительства"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", type=int, default=1095, help="1095 = ШАС")
    ap.add_argument("--axis", default="", help="фильтр по оси чек-листа, напр. C_надзор")
    ap.add_argument("--limit", type=int, default=12)
    a = ap.parse_args()

    d = json.loads(VOTES.read_text(encoding="utf-8"))
    periods = load_periods(a.faction)
    pref = f"{a.faction}|"
    rows = [r for r in d["rows"] if any(k.startswith(pref) for k in r["by_faction"])]
    if a.axis:
        rows = [r for r in rows if a.axis in (r.get("groups") or [])]

    print(f"голосований, где фракция {a.faction} участвовала: {len(rows)}")
    print(f"периодов участия в правительстве: {[p['id'] for p in periods]}\n")

    by_axis = collections.Counter()
    by_period = collections.Counter()
    stance = collections.Counter()
    for r in rows:
        cell = next(v for k, v in r["by_faction"].items() if k.startswith(pref))
        pid = period_of(periods, r["date"])
        by_period[pid] += 1
        for g in (r.get("groups") or []):
            by_axis[g] += 1
        top = max(cell.items(), key=lambda x: x[1])[0] if cell else "—"
        stance[top] += 1

    print("по осям чек-листа:", dict(by_axis))
    print("по периодам:      ", dict(by_period))
    print("преобладающая позиция фракции:", dict(stance), "\n")

    print("строки (§10: смысл «за» печатается рядом, иначе таблица врёт):\n")
    for r in rows[:a.limit]:
        cell = next(v for k, v in r["by_faction"].items() if k.startswith(pref))
        pid = period_of(periods, r["date"])
        name = re.sub(r"\s+", " ", str(r["bill_name"]))[:52]
        print(f"  {r['date'][:10]} · {pid:14} · {name}")
        print(f"      ШАС: {cell}   оси: {r.get('groups')}")
        print(f"      «за» здесь означает: {str(r['for_option_desc'])[:64]}")
    if len(rows) > a.limit:
        print(f"\n  … ещё {len(rows) - a.limit} строк (лимит показа, не выборка)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
