#!/usr/bin/env python3
"""Чек-лист «все голосовавшиеся законопроекты» для fetch_votes --full (владелец 20.10).

Вход: data/voted_bills_<n>.json (probe_voted_bills). Выход: data/bills_scan_full_<n>.json
в форме bills_scan (matched[]), чтобы fetch_votes читал его без изменений.
Заодно засевает data/named_votes_cache_full уже скачанными поимёнными (тот же vote_id —
та же перекличка), чтобы не качать их второй раз.
"""
from __future__ import annotations
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(n: int) -> int:
    vb = json.loads((ROOT / "data" / f"voted_bills_{n}.json").read_text(encoding="utf-8"))
    seen, matched = set(), []
    for r in vb["rows"]:
        if r["bill_id"] in seen:
            continue
        seen.add(r["bill_id"])
        matched.append({"kind": "bill", "id": r["bill_id"], "name": r["name"] or r["title"] or "", "groups": {}})
    out = {"matched": matched, "bills_total": len(matched), "source": f"data/voted_bills_{n}.json"}
    (ROOT / "data" / f"bills_scan_full_{n}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    full = ROOT / "data" / "named_votes_cache_full"
    full.mkdir(exist_ok=True)
    seeded = 0
    for r in vb["rows"]:
        if (full / f"{r['vote_id']}.json").exists():
            continue
        for src in ("named_votes_cache", "named_votes_cache_slices"):
            f = ROOT / "data" / src / f"{r['vote_id']}.json"
            if f.exists():
                shutil.copyfile(f, full / f.name); seeded += 1
                break
    print(n, "законопроектов", len(matched), "голосований", len(vb["rows"]), "засеяно из кэша", seeded)
    return 0


if __name__ == "__main__":
    for n in sys.argv[1:]:
        build(int(n))
