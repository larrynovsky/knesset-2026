#!/usr/bin/env python3
"""CLAUDE.md §23 — выгрузка, которая не может тихо недобрать.

Класс отказа, ради которого написан модуль: операция отчитывается об успехе,
возвращает правдоподобный результат, и он неполон. `$top=200` отдаёт 100 строк
с HTTP 200 и без предупреждения; сто фракций — совершенно нормальное число,
из него получаются аккуратные и ложные выводы.

Единственное, что реально ловит такое, — ожидание объёма, полученное ДРУГИМ
путём, и сверка до использования данных.

⚠️ Честная граница этой защиты: `?$count=true` идёт на тот же сервер с тем же
фильтром. Проверка независима от МОЕЙ логики пагинации, но НЕ независима от
серверной логики фильтрации. Если сервер неверно применит $filter, счётчик
соврёт согласованно с выборкой, и §23 этого не заметит. Это не лечится здесь.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"
MANIFEST = Path(__file__).resolve().parent.parent / "data" / "MANIFEST.json"


class ShortRead(RuntimeError):
    """Выгрузка вернула не столько, сколько обещал независимый счётчик."""


def _get(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read())


def count(entity: str, flt: str = "") -> int:
    """Независимый путь к величине. Форма `/$count` отдаёт 404 — только эта."""
    url = f"{BASE}/{entity}?$format=json&$count=true&$top=0"
    if flt:
        url += "&$filter=" + urllib.parse.quote(flt)
    r = _get(url)
    if "@odata.count" not in r:
        raise ShortRead(f"{entity}: сервер не вернул @odata.count — ожидание неполучаемо")
    return int(r["@odata.count"])


def fetch_all(
    entity: str,
    flt: str = "",
    select: str = "",
    expected: int | None = None,
    unchecked_reason: str = "",
    pause: float = 0.35,
) -> list[dict]:
    """Полная выгрузка со сверкой объёма.

    Семантика (первая редакция была неверна — см. ниже):
      expected=int  — сверять с этим числом;
      expected=None — ДЕФОЛТ: взять ожидание независимым путём через count();
      unchecked_reason="..." — единственный способ обойти сверку, и он громкий.

    Первая редакция требовала unchecked_reason при expected=None, из-за чего
    безопасный путь (авто-count) был недостижим: корректный вызов падал.
    Защита, блокирующая правильное использование, — не защита, а поломка;
    это зеркало слишком широкого grep'а в §9-правиле (2026-07-27).
    """
    if unchecked_reason:
        print(f"   §23 СВЕРКА ПРОПУЩЕНА для {entity}: {unchecked_reason}")
        expected = None
    elif expected is None:
        expected = count(entity, flt)

    params = ["$format=json"]
    if flt:
        params.append("$filter=" + urllib.parse.quote(flt))
    if select:
        params.append("$select=" + select)
    url = f"{BASE}/{entity}?" + "&".join(params)

    out: list[dict] = []
    pages = 0
    while url:
        r = _get(url)
        out.extend(r.get("value", []))
        url = r.get("@odata.nextLink")
        pages += 1
        if url:
            time.sleep(pause)

    if expected is not None and len(out) != expected:
        raise ShortRead(
            f"§23 ТИХИЙ НЕДОБОР: {entity} — ожидалось {expected}, получено {len(out)} "
            f"за {pages} стр. Данные НЕ отдаются наверх. "
            f"Фильтр: {flt or '(нет)'}"
        )

    _record(entity, flt, expected, len(out), pages)
    return out


def _record(entity: str, flt: str, expected: int, got: int, pages: int) -> None:
    """Манифест выгрузки: обе цифры рядом, чтобы расхождение было видно глазом."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    except Exception:  # noqa: BLE001
        data = {}
    data[f"{entity}|{flt}"] = {
        "expected": expected,
        "got": got,
        "pages": pages,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # Самопроверка §23: механизм обязан краснеть, а не рассказывать о себе.
    print("самопроверка guarded_fetch")

    n = count("KNS_Faction")
    print(f"  независимый счётчик KNS_Faction: {n}")

    rows = fetch_all("KNS_Faction", select="Id,Name,KnessetNum")
    print(f"  полная выгрузка: {len(rows)} — сверка пройдена")

    print("  провокация: подсовываю заведомо неверное ожидание...")
    try:
        fetch_all("KNS_Faction", select="Id,Name", expected=100)
        print("  ПРОВАЛ САМОПРОВЕРКИ: недобор не пойман")
        raise SystemExit(1)
    except ShortRead as e:
        print(f"  OK, поймано: {str(e)[:90]}...")

    print("  обход сверки обязан быть громким и попадать в манифест...")
    fetch_all("KNS_Position", unchecked_reason="проверка громкости обхода")
    rec = json.loads(MANIFEST.read_text()).get("KNS_Position|")
    if rec and rec.get("expected") is None:
        print(f"  OK, записано как непроверенное: {rec}")
    else:
        print(f"  ПРОВАЛ САМОПРОВЕРКИ: обход не отмечен в манифесте: {rec}")
        raise SystemExit(1)

    print("самопроверка пройдена")
