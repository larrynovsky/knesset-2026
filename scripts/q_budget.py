#!/usr/bin/env python3
"""Справочный просмотр книги бюджета для ручного сопоставления (канал Б).

    python3 scripts/q_budget.py 'find:דייג' 'find:פנימי@0020' 'branch:00045213' 'show:0004521320'

Только чтение data/budget_takanot.json; ничего не пишет. Числа — allocated /
revised / executed в тысячах ₪ по годам снимка.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROWS = json.load(open(ROOT / "data" / "budget_takanot.json", encoding="utf-8"))["rows"]
BY: dict = {}
for r in ROWS:
    BY.setdefault(r["code"], {})[r["year"]] = r


def show(c: str) -> None:
    ys = BY.get(c, {})
    if not ys:
        print(" ", c, "MISSING")
        return
    t = next(iter(ys.values()))["title"]
    print(f"  {c} {t[:50]:50s} " + " | ".join(
        f"{y}: a{int(ys[y]['net_allocated'] or 0)//1000:,}k r{int(ys[y]['net_revised'] or 0)//1000:,}k "
        f"e{int(ys[y]['net_executed'] or 0)//1000:,}k" for y in sorted(ys)))


def find(term: str, prefix: str = "", limit: int = 12) -> None:
    cs = sorted({r["code"] for r in ROWS if term in (r["title"] or "") and r["code"].startswith(prefix)})
    print(f"== '{term}' prefix={prefix or '-'}: {len(cs)}")
    for c in cs[:limit]:
        show(c)


def branch(prefix: str, depth: int = 10) -> None:
    cs = sorted({r["code"] for r in ROWS if r["code"].startswith(prefix) and len(r["code"]) == depth})
    print(f"== ветка {prefix} depth{depth}: {len(cs)}")
    for c in cs:
        show(c)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        if arg.startswith("find:"):
            t, _, p = arg[5:].partition("@")
            find(t, p)
        elif arg.startswith("branch:"):
            p, _, dd = arg[7:].partition("@")
            branch(p, int(dd) if dd else 10)
        elif arg.startswith("show:"):
            show(arg[5:])
