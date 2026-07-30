#!/usr/bin/env python3
"""Канал Б, первый вход: коалиционные соглашения 25-го Кнессета (§12, §23).

Замысел проекта прямо называет непроверенным допущение «часть PDF может
оказаться сканами». Это первая неизвестность канала Б, и она решается
не рассуждением, а скачиванием одного файла.

Три вещи взяты из ретро перевода книги (kegan-iooh), где тот же класс задач
уже проходили на 144 тысячах слов:

1. STAGE 0 ДЕТЕРМИНИРОВАННЫЙ. Никакого LLM на извлечении. «Only deterministic,
   reversible-in-principle fixes; when unsure — keep original.» Модель не должна
   касаться текста, по которому потом цитируют обязательства партии.

2. ЯКОРЯ СТРАНИЦ ⟦N⟧. В книге они дали сверку с бумажной копией и детект
   потерь линтером. Здесь они нужнее: §12 требует ивритский оригинал рядом
   с переводом, а §14 — воспроизводимости. Цитата из соглашения с номером
   страницы проверяется читателем за минуту; без номера — не проверяется.

3. GARBAGE_SCORE ВМЕСТО ФИЛЬТРА ДЛИНЫ. В книге доля не-буквенных символов
   ловила страницы-картинки. У нас ровно на этом уже обожглись: Основной закон
   об изучении Торы извлёкся титульным листом в 717 знаков, и фильтр длины
   его пропустил. Длина says «текст есть», доля мусора says «текста нет».

§23: ожидание объёма берётся из Content-Length до чтения тела; расхождение —
отказ, а не предупреждение.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_bill_texts import repair_rtl               # noqa: E402  тот же RTL-ремонт

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "agreements"
OUT = ROOT / "data" / "agreements_index.json"
CTX = ssl.create_default_context()
UA = {"User-Agent": "knesset-research/0.1"}

# Первичный источник: сборник коалиционных соглашений 25-го Кнессета, сайт
# Кнессета. Вторичный (IDI) сознательно НЕ берётся: у него своя редактура,
# а цитировать партию нужно по документу, который она подписала.
SOURCES = {
    "cagreement25": "https://m.knesset.gov.il/mk/government/documents/cagreement25.pdf",
}


def garbage_score(line: str) -> float:
    """Доля символов, не похожих на текст. Урок kegan-iooh: длина обманывает,
    доля мусора — нет. Иврит, латиница, цифры и обычная пунктуация — «не мусор»."""
    s = line.strip()
    if not s:
        return 0.0
    ok = sum(1 for c in s if c.isalpha() or c.isdigit() or c in " ,.'\"-;:()?!/–—%")
    return 1.0 - ok / len(s)


def download(url: str, expected: int | None = None) -> bytes:
    """§23: ожидание берётся из Content-Length ДО чтения тела."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
        declared = r.headers.get("Content-Length")
        blob = r.read()
    if declared is not None and int(declared) != len(blob):
        raise RuntimeError(f"§23 ТИХИЙ НЕДОБОР: заявлено {declared} байт, "
                           f"получено {len(blob)} — данные не отдаются наверх")
    if expected is not None and abs(len(blob) - expected) > expected * 0.2:
        raise RuntimeError(f"§23: объявлено ~{expected} байт, получено {len(blob)}")
    return blob


def pages_with_anchors(blob: bytes) -> list[str]:
    """Постранично, чтобы поставить якоря ⟦N⟧. Номер — страница PDF.

    Смещения «страница PDF → страница документа» здесь НЕТ и оно не изобретается:
    в книге PAGE_OFFSET выверялся вручную по одной известной странице. Для
    соглашения такой сверки не проводилось, поэтому якорь честно означает
    страницу файла, а не печатную страницу.
    """
    from pdfminer.high_level import extract_text            # noqa: PLC0415
    from pdfminer.pdfpage import PDFPage                    # noqa: PLC0415
    n = sum(1 for _ in PDFPage.get_pages(BytesIO(blob)))
    out = []
    for i in range(n):
        t = extract_text(BytesIO(blob), page_numbers=[i]) or ""
        t, _ = repair_rtl(t)
        out.append(f"⟦{i + 1}⟧\n{t}")
    return out


def verdict(pages: list[str]) -> dict:
    """Текст или скан — по доле мусора и плотности букв, не по длине."""
    stats, empty, dirty = [], 0, 0
    for p in pages:
        body = [l for l in p.split("\n") if l.strip()][1:]      # без строки якоря
        chars = sum(len(l) for l in body)
        g = sum(garbage_score(l) for l in body) / max(len(body), 1)
        stats.append({"chars": chars, "garbage": round(g, 3)})
        if chars < 200:
            empty += 1
        if g > 0.08:
            dirty += 1
    total = sum(s["chars"] for s in stats)
    return {
        "pages": len(pages), "chars_total": total,
        "chars_per_page": round(total / max(len(pages), 1)),
        "pages_empty": empty, "pages_dirty": dirty,
        "is_scan": empty > len(pages) * 0.5,
        "per_page": stats,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-bytes", type=int, default=None,
                    help="§23: объявленный ДО скачивания размер (грубо)")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    index = {}

    for name, url in SOURCES.items():
        print(f"\n=== {name} ===\n{url}")
        blob = download(url, a.expect_bytes)
        pdf_path = RAW / f"{name}.pdf"
        pdf_path.write_bytes(blob)
        print(f"скачано: {len(blob):,} байт → {pdf_path.name}")

        pages = pages_with_anchors(blob)
        v = verdict(pages)
        txt_path = RAW / f"{name}.txt"
        txt_path.write_text("\n\n".join(pages), encoding="utf-8")

        print(f"страниц: {v['pages']} · знаков: {v['chars_total']:,} "
              f"(~{v['chars_per_page']} на страницу)")
        print(f"пустых страниц: {v['pages_empty']} · грязных (мусор >8%): {v['pages_dirty']}")
        print("ВЕРДИКТ: " + ("СКАН — текстового слоя нет, нужен OCR"
                             if v["is_scan"] else
                             "ТЕКСТОВЫЙ СЛОЙ ЕСТЬ — OCR не нужен"))
        index[name] = {"url": url, "bytes": len(blob), **{k: v[k] for k in
                       ("pages", "chars_total", "chars_per_page",
                        "pages_empty", "pages_dirty", "is_scan")}}

    OUT.write_text(json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(), "sources": index},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{OUT}")
    return 0


def selftest() -> int:
    """Оракул: garbage_score обязан отличать текст от мусора OCR."""
    assert garbage_score("הסכם קואליציוני בין סיעת הליכוד לסיעת ש\"ס") < 0.05, \
        "нормальный ивритский текст помечен мусором"
    assert garbage_score("~@#$%^&*<>|\\{}[]_=+~@#$%") > 0.8, "мусор не опознан"
    assert garbage_score("") == 0.0, "пустая строка не должна давать мусор"
    assert garbage_score("2. תיקון סעיף 15 (א)") < 0.1, "нумерация принята за мусор"
    print("самопроверка fetch_agreements пройдена: 4 утверждения")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
