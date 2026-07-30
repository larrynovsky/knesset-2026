#!/usr/bin/env python3
"""Разведка-4: откуда взять периоды участия ШАС в правительстве (§1, periods.yaml).

§23-exempt: выясняется, из каких полей вообще выводится «партия в правительстве».

§1 требует единицу «партия × период участия в правительстве» и приводит ШАС
как канонический пример: 2023 и вторая половина 2025 — два разных наблюдения.
Даты нельзя брать из памяти: periods.yaml — файл критериев, он опирается
на источник, а не на пересказ.
"""
from __future__ import annotations

import collections
import json
import ssl
import urllib.parse
import urllib.request

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"
SHAS = 1095


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=90, context=CTX) as r:
        return json.loads(r.read())


def page(entity: str, flt: str = "", limit: int = 20000):
    url = f"{BASE}/{entity}?$format=json"
    if flt:
        url += "&$filter=" + urllib.parse.quote(flt)
    out = []
    while url and len(out) < limit:
        r = get(url)
        out.extend(r.get("value", []))
        url = r.get("@odata.nextLink")
    return out


def main() -> int:
    print("=== позиции ШАС в 25-м Кнессете ===")
    rows = page("KNS_PersonToPosition", f"KnessetNum eq 25 and FactionID eq {SHAS}")
    print(f"записей: {len(rows)}\n")
    kinds = collections.Counter((r.get("PositionID"), r.get("DutyDesc")) for r in rows)
    for (pid, duty), n in kinds.most_common():
        print(f"   PositionID {pid!s:>5} · {str(duty)[:44]:46} × {n}")

    print("\n=== министерские позиции (GovMinistryID заполнен) ===")
    gov = [r for r in rows if r.get("GovMinistryID")]
    print(f"записей с министерством: {len(gov)}")
    for r in sorted(gov, key=lambda x: (x.get("StartDate") or "")):
        print(f"   {str(r.get('StartDate'))[:10]} … {str(r.get('FinishDate'))[:10]:10} "
              f"gov#{r.get('GovernmentNum')} {str(r.get('GovMinistryName'))[:28]:30} "
              f"PersonID {r.get('PersonID')}")

    print("\n=== границы по датам (что станет periods.yaml) ===")
    starts = sorted({(r.get("StartDate") or "")[:10] for r in gov if r.get("StartDate")})
    fins = sorted({(r.get("FinishDate") or "")[:10] for r in gov if r.get("FinishDate")})
    print(f"   уникальные начала:   {starts}")
    print(f"   уникальные окончания:{fins}")

    print("\n=== KNS_Government: есть ли сущность с составами правительств ===")
    for e in ("KNS_Government", "KNS_GovMinistry", "KNS_Position"):
        try:
            v = get(f"{BASE}/{e}?$format=json").get("value", [])
            print(f"   {e:20} поля: {list(v[0].keys()) if v else 'пусто'}")
        except Exception as ex:                              # noqa: BLE001
            print(f"   {e:20} нет ({type(ex).__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
