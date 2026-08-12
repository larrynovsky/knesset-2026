#!/usr/bin/env python3
"""Даты законопроектов из реестра — запасной источник, когда текст молчит.

Объём и ожидания объявлены ДО выгрузки:
criteria/declared_before_billdates_2026-08-12.yaml (7491 запись).

ЗАЧЕМ. Дата акта берётся из его подписи («(19.12.2022)»), но у 23 актов из 88
её нет в тексте вовсе — и 62 адреса из 203 выпадают из выгрузки базовых
текстов. Без даты нельзя выбрать редакцию закона, а взять свежую — это риск
R1, ради которого вся подсистема и строится.

ГРАНИЦА ВЕЛИЧИНЫ, и её нельзя стирать. PublicationDate — дата публикации
ПРЕДЛОЖЕНИЯ, а не внесения. Для выбора редакции это допустимо: между
внесением и публикацией дни, а редакции закона меняются месяцами. Но величина
другая, и в артефакте она называется своим именем — потребитель обязан знать,
чем он пользуется.

ПОРЯДОК ИСТОЧНИКОВ НЕ СЛУЧАЕН. Дата в подписи принадлежит САМОМУ ДОКУМЕНТУ,
дата в реестре — записи о нём. Поэтому реестр запасной, а не основной, и
подменять им текст там, где текст говорит, запрещено.

    python3 scripts/fetch_bill_dates.py --selftest
    python3 scripts/fetch_bill_dates.py
"""
from __future__ import annotations

import inspect
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "bill_dates.json"
DECLARED = ROOT / "criteria" / "declared_before_billdates_2026-08-12.yaml"
EXPECTED = 7491


def as_date(v: str | None) -> str | None:
    """ISO-дата из отметки времени реестра. Пусто — None, а не сегодня."""
    if not v or not isinstance(v, str) or len(v) < 10:
        return None
    d = v[:10]
    return d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else None


def selftest() -> int:
    assert as_date("2022-12-19T00:00:00") == "2022-12-19"
    assert as_date(None) is None, \
        "пустая дата обязана остаться пустой: подстановка сегодняшней — это "\
        "ровно R1, взять не ту редакцию закона"
    assert as_date("") is None and as_date("нет") is None
    assert as_date("2022-13-45T00:00:00") == "2022-13-45", \
        "проверка формата, а не календаря: чинить чужие даты молча хуже, "\
        "чем отдать их как есть и увидеть в замере"
    print(f"самопроверка fetch_bill_dates пройдена: "
          f"{sum(1 for _ in re.finditer('assert ', inspect.getsource(selftest)))} утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not DECLARED.exists():
        print(f"нет {DECLARED.name} — объём не объявлен, выгрузка запрещена (§23)")
        return 2

    # Ключ законопроекта в OData **v4** называется Id, а не BillID: BillID —
    # это имя из легаси-эндпоинта v3, где и схема другая. Первая редакция
    # взяла имена полей из v3 и получила HTTP 400 с внятным сообщением
    # «Could not find a property named 'BillID'». Два эндпоинта с разными
    # схемами — известная ловушка проекта (инвариант source_is_odatav4).
    rows = fetch_all("KNS_Bill", flt="KnessetNum eq 25",
                     select="Id,PublicationDate,LastUpdatedDate,StatusID",
                     expected=EXPECTED)
    dates = {}
    have_pub = 0
    for r in rows:
        pub = as_date(r.get("PublicationDate"))
        have_pub += bool(pub)
        dates[str(r["Id"])] = {
            "publication": pub,
            "last_updated": as_date(r.get("LastUpdatedDate")),
            "status": r.get("StatusID"),
        }
    OUT.write_text(json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(),
         "entity": "KNS_Bill", "filter": "KnessetNum eq 25",
         "expected": EXPECTED, "got": len(rows),
         "note": "publication = дата публикации ПРЕДЛОЖЕНИЯ, не внесения",
         "dates": dates}, ensure_ascii=False), encoding="utf-8")
    print(f"выгружено {len(rows)} записей (объявлено {EXPECTED})")
    print(f"с непустой PublicationDate: {have_pub} ({100*have_pub/len(rows):.0f}%)")
    print(f"\n{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
