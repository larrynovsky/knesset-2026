#!/usr/bin/env python3
"""Разведка форм запросов OData v4 Кнессета: как считать и как фильтровать.

probe_phase0.py получил 404 на `/$count` и 400 на `$filter=KnessetNum eq N`.
Значит либо путь счётчика другой, либо поле называется иначе. Выясняем.

§23-exempt: смысл скрипта — звать СЫРЫЕ формы запросов и смотреть, какие
из них падают. guarded_fetch скрыл бы ровно то, что здесь изучается.
Ожидание объёма тут неприменимо: выборка заведомо одна строка ($top=1).
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"


def get(url: str):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode()


def fields(entity: str) -> list[str]:
    st, body = get(f"{BASE}/{entity}?$top=1&$format=json")
    print(f"\n### {entity}  HTTP {st}")
    if st != 200:
        print("   ", body[:200].decode("utf-8", "replace"))
        return []
    try:
        vals = json.loads(body).get("value", [])
        if not vals:
            print("    пусто")
            return []
        keys = list(vals[0].keys())
        for k in keys:
            v = str(vals[0][k])[:40]
            print(f"    {k:<30} = {v}")
        return keys
    except Exception as e:  # noqa: BLE001
        print("    parse:", e)
        return []


def try_count(entity: str, flt: str | None = None) -> None:
    """Три формы счётчика — какая работает."""
    forms = {
        "path /$count": f"{BASE}/{entity}/$count",
        "query $count=true": f"{BASE}/{entity}?$count=true&$top=0&$format=json",
    }
    for name, url in forms.items():
        if flt:
            sep = "?" if "?" not in url else "&"
            url = url + sep + "$filter=" + urllib.parse.quote(flt)
        st, body = get(url)
        txt = body[:120].decode("utf-8", "replace").replace("\n", " ")
        print(f"    {name:<22} HTTP {st}  {txt}")


for ent in ("KNS_Faction", "KNS_PlenumVote", "KNS_Bill", "KNS_Position",
            "KNS_PersonToPosition", "KNS_KnessetDates"):
    ks = fields(ent)
    print("    -- формы счётчика --")
    try_count(ent)
    cand = [k for k in ks if "knesset" in k.lower()]
    if cand:
        print(f"    -- фильтр по {cand[0]} --")
        try_count(ent, f"{cand[0]} eq 25")
