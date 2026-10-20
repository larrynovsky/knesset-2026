#!/usr/bin/env python3
"""Разведка добора (владелец 20.10: «где не собрали — исследовать, можно ли собрать»).

Вопрос: сколько законопроектов КАЖДОГО Кнессета 20–25 голосовались в пленуме поимённо,
а не только отобранных по ключевым словам институциональных групп (scan_bills).
Тот же прямой ключ, что в fetch_votes (SessionID, ItemID → ItemTypeID=2 → BillID),
те же шапки (fetch_headers, §23 через guarded_fetch). Поимённые голоса НЕ качаются:
только перечень «голосование → законопроект». Выход: data/voted_bills_<N>.json.
"""
from __future__ import annotations
import collections, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_votes as F                      # noqa: E402
from guarded_fetch import fetch_all          # noqa: E402


def names(n: int) -> dict[int, str]:
    p = ROOT / "data" / f"bills_all_names_{n}.json"
    if p.exists():
        return {b["id"]: b["name"] for b in json.loads(p.read_text(encoding="utf-8"))}
    rows = fetch_all("KNS_Bill", flt=f"KnessetNum eq {n}", select="Id,Name")
    p.write_text(json.dumps([{"id": r["Id"], "name": r["Name"]} for r in rows], ensure_ascii=False), encoding="utf-8")
    return {r["Id"]: r["Name"] for r in rows}


def run(n: int) -> dict:
    F.use_knesset(n)
    heads = F.fetch_headers()
    typ = F.session_item_types(heads)
    nm = names(n)
    cls, out = collections.Counter(), []
    for h in heads:
        ts = typ.get((h.get("SessionID"), h.get("ItemID")))
        k = "нет пункта" if ts is None else "неоднозначно" if len(ts) > 1 else "законопроект" if 2 in ts else "не законопроект"
        cls[k] += 1
        if k == "законопроект":
            out.append({"vote_id": h["Id"], "bill_id": h["ItemID"], "date": h["VoteDateTime"][:10],
                        "name": nm.get(h["ItemID"]), "for": h.get("ForOptionDesc"), "against": h.get("AgainstOptionDesc"),
                        "title": h.get("VoteTitle")})
    assert sum(cls.values()) == len(heads)
    have = {r["bill_id"] for r in json.loads((ROOT / "data" / f"votes_{n}.json").read_text(encoding="utf-8"))["rows"]}
    res = {"knesset": n, "heads": len(heads), "classes": dict(cls), "bill_votes": len(out),
           "bills_voted": len({r["bill_id"] for r in out}), "bills_have": len(have),
           "bills_missing": len({r["bill_id"] for r in out} - {int(b) for b in have}), "rows": out}
    (ROOT / "data" / f"voted_bills_{n}.json").write_text(json.dumps(res, ensure_ascii=False, indent=0), encoding="utf-8")
    print(n, {k: v for k, v in res.items() if k != "rows"}, flush=True)
    return res


if __name__ == "__main__":
    for n in [int(x) for x in sys.argv[1:]] or [21, 22, 23, 24, 20, 25]:
        run(n)
