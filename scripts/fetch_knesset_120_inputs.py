#!/usr/bin/env python3
"""Входы оракула 120: две таблицы в data/, через guarded_fetch (§23, §24).

Оракул `check_knesset_120.py` с 2026-10-08 в сеть не ходит — он читает
`data/KNS_Faction.json` и `data/KNS_PersonToPosition_54.json`. Этот скрипт
единственный, кто их пишет. Разделение намеренное: сторож, который сам
выгружает, превращал обрыв источника в вывод о данных (см. guarded_fetch._get).

Где запускать: там, где источник отвечает. 2026-10-10 Studio получает
303 → maintenance-page-geo (гео-заглушка), MacBook — 200. Файлы data/*
не в git, перенос на Studio — scp, запись в манифест идёт с именем хоста.

Оракул этого скрипта — сам check_knesset_120.py: exit 0 после выгрузки,
exit 2 до неё. Отдельного теста нет и не нужно: два вызова библиотеки.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"
POSITION_MK = 54


def main() -> int:
    OUT.mkdir(exist_ok=True)
    fac = fetch_all("KNS_Faction", select="Id,Name,KnessetNum")
    mem = fetch_all("KNS_PersonToPosition", flt=f"PositionID eq {POSITION_MK}",
                    select="PersonID,FactionID,KnessetNum,PositionID")
    (OUT / "KNS_Faction.json").write_text(
        json.dumps(fac, ensure_ascii=False), encoding="utf-8")
    (OUT / "KNS_PersonToPosition_54.json").write_text(
        json.dumps(mem, ensure_ascii=False), encoding="utf-8")
    print(f"KNS_Faction: {len(fac)} · KNS_PersonToPosition(54): {len(mem)} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
