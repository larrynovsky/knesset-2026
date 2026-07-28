#!/usr/bin/env python3
"""ШАГ 0 пилота классификации: есть ли у законопроектов достижимый текст.

Решение Р1 (`plans/PLAN_pilot_direction_2026-07-28.md`): планка доказательности
выбирается ПОСЛЕ замера, а не вслепую. Этот скрипт даёт число, на котором
решение принимается.

Почему шаг блокирующий. `criteria/keyvotes.yaml` требует
`required_evidence: цитата из текста закона плюс номер пункта чек-листа`.
Название законопроекта нормы не содержит: «הצעת חוק-יסוד: השפיטה (תיקון מס' 4)»
не говорит, ЧТО меняет поправка №4. Модель, получив такое название, всё равно
вернёт знак — достроив его из общего представления об эпохе. Знак будет
правдоподобен и взят не из источника. Это подделка required_evidence, а не
пониженная уверенность (§6 про неопределённость вывода, не про отсутствие
источника).

Замер в двух частях, потому что «запись есть» и «текст читается» — разные вещи:
  (A) МЕТАДАННЫЕ — у скольких из ядра есть запись в KNS_DocumentBill, каких
      типов и форматов. Через guarded_fetch (§23).
  (B) ДОСТИЖИМОСТЬ — выборка файлов реально скачивается и проверяется на
      машинночитаемость. Без (B) часть (A) была бы ровно тем классом отказа,
      против которого написан §23: правдоподобное число, которое не значит
      того, что кажется. HTTP 200 на .doc ещё не означает извлекаемый текст.

§23-примечание: часть (B) ходит НЕ в OData, а на файловый хост
fs.knesset.gov.il. Это не выгрузка сущности и не пагинируемый список —
объём известен точно (длина выборки), сверять не с чем. Пометка оставлена
явно, чтобы отсутствие сверки здесь было произнесённым, а не случайным.
"""
from __future__ import annotations

import collections
import json
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "data" / "bills_scan.json"
OUT = ROOT / "data" / "bill_texts_probe.json"

# Нижняя граница по BillID: минимальный id в matched минус запас.
# Не «оптимизация», а необходимость: KNS_DocumentBill целиком — 111 692 записи.
# Граница объявлена здесь, а не подобрана по результату.
BILLID_FLOOR = 1_040_000
SAMPLE = 12
UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()


def norm(path: str) -> str:
    """FilePath приходит с обратными слэшами: https://host/\\25\\law\\x.doc"""
    return (path or "").replace("\\", "/")


def probe_file(url: str, timeout: int = 45) -> dict:
    """Скачать голову файла. Возвращает наблюдение, не вердикт."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            head = r.read(8192)
            return {"ok": True, "status": r.status,
                    "ctype": r.headers.get("Content-Type", ""),
                    "clen": r.headers.get("Content-Length", ""),
                    "magic": head[:8].hex(),
                    "looks": sniff(head)}
    except Exception as e:                     # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {e}"[:160]}


def sniff(head: bytes) -> str:
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc-ole2"          # legacy binary Word: нужен конвертер
    if head.startswith(b"PK\x03\x04"):
        return "docx-zip"
    if head.lstrip()[:5].lower() in (b"<html", b"<!doc"):
        return "html"              # почти наверняка страница ботозащиты
    return "unknown"


def main() -> int:
    if not SCAN.exists():
        print(f"нет {SCAN.relative_to(ROOT)} — сначала scan_bills.py (на Studio)",
              file=sys.stderr)
        return 2
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    core = set(scan["core_ids"])
    matched = {m["id"] for m in scan["matched"]}
    print(f"ядро {len(core)} · весь чек-лист {len(matched)}")

    docs = fetch_all("KNS_DocumentBill", flt=f"BillID ge {BILLID_FLOOR}",
                     select="Id,BillID,GroupTypeDesc,ApplicationDesc,FilePath")
    print(f"KNS_DocumentBill с BillID ≥ {BILLID_FLOOR}: {len(docs)}")

    by_bill: dict[int, list[dict]] = collections.defaultdict(list)
    for d in docs:
        by_bill[d["BillID"]].append(d)

    core_with = core & set(by_bill)
    matched_with = matched & set(by_bill)
    print(f"\nПОКРЫТИЕ МЕТАДАННЫМИ")
    print(f"   ядро:          {len(core_with)}/{len(core)}"
          f"  = {len(core_with) * 100 // max(len(core), 1)}%")
    print(f"   весь чек-лист: {len(matched_with)}/{len(matched)}"
          f"  = {len(matched_with) * 100 // max(len(matched), 1)}%")

    kinds = collections.Counter()
    apps = collections.Counter()
    for bid in core_with:
        for d in by_bill[bid]:
            kinds[d.get("GroupTypeDesc") or "?"] += 1
            apps[d.get("ApplicationDesc") or "?"] += 1
    print("\n   типы документов у ядра:")
    for k, n in kinds.most_common(10):
        print(f"      {n:5d}  {k}")
    print("   форматы:", dict(apps))

    # --- (B) достижимость. Выборка детерминирована: первые SAMPLE по возрастанию
    #     BillID. Не случайная — случайность сделала бы прогон невоспроизводимым,
    #     а §14 требует воспроизводимости.
    print(f"\nДОСТИЖИМОСТЬ — выборка {SAMPLE} файлов (детерминированная)")
    sample_ids = sorted(core_with)[:SAMPLE]
    sample_out = []
    for bid in sample_ids:
        d = by_bill[bid][0]
        url = norm(d["FilePath"])
        r = probe_file(url)
        sample_out.append({"bill": bid, "url": url, **r})
        mark = r.get("looks", "—") if r["ok"] else "ОШИБКА"
        print(f"   {bid:>9}  {mark:<10} {r.get('ctype', r.get('err', ''))[:60]}")

    ok = [s for s in sample_out if s.get("ok")]
    readable = [s for s in ok if s.get("looks") in ("pdf", "docx-zip", "doc-ole2")]
    html = [s for s in ok if s.get("looks") == "html"]
    print(f"\n   скачалось {len(ok)}/{len(sample_ids)}"
          f" · похоже на документ {len(readable)}"
          f" · похоже на ботозащиту {len(html)}")
    if any(s.get("looks") == "doc-ole2" for s in ok):
        print("   ⚠ формат .doc (OLE2) — двоичный Word, нужен конвертер;"
              " 'файл скачался' ≠ 'текст извлекается'")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "core_total": len(core), "core_with_doc": len(core_with),
        "matched_total": len(matched), "matched_with_doc": len(matched_with),
        "kinds": dict(kinds), "apps": dict(apps),
        "billid_floor": BILLID_FLOOR,
        "sample": sample_out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{OUT.relative_to(ROOT)}")

    # Вердикта скрипт НЕ выносит: планку выбирает владелец (Р1).
    # Скрипт обязан только не соврать о числе.
    return 0


if __name__ == "__main__":
    sys.exit(main())
