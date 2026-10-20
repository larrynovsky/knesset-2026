#!/usr/bin/env python3
"""Выгрузка и извлечение текстов законопроектов. Вход жёсткой планки Р1.

Решение Р1 (подтверждено владельцем 2026-07-28): нет текста — нет знака.
Значит этот модуль решает, у какого законопроекта знак вообще может появиться,
и его отказ — не сбой, а результат. Отказы считаются и печатаются: без счётчика
жёсткая планка сама превращается в тихий недобор (§23).

Почему отдельно от классификатора: выгрузка и суждение — разные единицы отказа.
Слить их значит потерять возможность перепрогнать одно, не трогая другое.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ: не решает, какой знак. Он отвечает ровно на вопрос
«есть ли извлекаемая норма на иврите» и обязан отвечать честно, в том числе «нет».

§23 — три сверки, каждая объявлена до результата:
  1. выгрузка KNS_DocumentBill идёт через guarded_fetch (независимый счётчик);
  2. каждый скачанный файл сверяется с Content-Length, если сервер его дал;
  3. извлечённый текст проверяется на долю ивритских букв. Пустой или
     нечитаемый результат при HTTP 200 — ровно тот класс отказа, ради которого
     написан §23: операция отчиталась об успехе и вернула правдоподобный мусор.

§24-примечание про КЭШ: `data/document_bill.json` переиспользуется между
прогонами, потому что полная выгрузка идёт ~18 минут. Это устаревшая копия
по построению, и молчаливое её использование было бы дефектом того же класса,
что двойной data/ на двух машинах. Поэтому возраст кэша печатается ГРОМКО
при каждом прогоне, а `--refresh` перевыгружает.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "data" / "bills_scan.json"
DOCCACHE = ROOT / "data" / "document_bill.json"
TEXTDIR = ROOT / "data" / "bill_texts"
INDEX = ROOT / "data" / "bill_texts_index.json"
BILLID_FLOOR = 1_040_000

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
HEB = re.compile(r"[֐-׿]")
MIN_CHARS = 200          # короче — почти наверняка не норма, а обложка
MIN_HEB_RATIO = 0.25     # ниже — извлеклись цифры и латиница, но не текст

BILL_TEXT_PREFIXES = ("הצעת חוק", "חוק -", "חוק-")

# Предпочтение редакции. Знак присваивается ЗАКОНОПРОЕКТУ один раз, значит из
# нескольких редакций нужна одна. Берём самую полную: опубликованный закон
# полнее текста ко второму-третьему чтению, тот полнее первого, тот полнее
# предварительного. Порядок объявлен здесь, а не выбран по результату.
# Осознанная потеря: законопроект мог измениться между чтениями, и партия
# голосовала за более раннюю редакцию. Для знака направления это приемлемо —
# он про предмет, а не про формулировку; для цитаты в карточке это придётся
# помнить, и потому редакция сохраняется в индексе рядом с текстом.
PREFERENCE = [
    "חוק - פרסום ברשומות",
    "חוק - נוסח לא רשמי",
    "הצעת חוק לקריאה השנייה והשלישית",
    "הצעת חוק לקריאה השניה והשלישית",
    "הצעת חוק לקריאה הראשונה",
    "הצעת חוק לדיון מוקדם",
]


def is_bill_text(d: dict) -> bool:
    k = (d.get("GroupTypeDesc") or "").strip()
    return any(k.startswith(p) for p in BILL_TEXT_PREFIXES)


def rank(d: dict) -> int:
    k = (d.get("GroupTypeDesc") or "").strip()
    for i, p in enumerate(PREFERENCE):
        if k.startswith(p):
            return i
    return len(PREFERENCE)


def norm(path: str) -> str:
    return (path or "").replace("\\", "/")


# --- извлечение ------------------------------------------------------------
# Три формата, три пути, и один из них может отсутствовать на машине.
# Отсутствие конвертера — это НЕ «текста нет», это «мы не смогли». Разные
# состояния, и смешивать их значит записать в дыру покрытия то, что чинится
# установкой пакета.

def extract(blob: bytes, url: str) -> tuple[str, str]:
    """Возвращает (text, method). Пустой text = не извлеклось."""
    if blob.startswith(b"%PDF"):
        return _pdf(blob), "pdf"
    if blob.startswith(b"PK\x03\x04"):
        return _docx(blob), "docx"
    if blob.startswith(b"\xd0\xcf\x11\xe0"):
        return _ole2(blob), "doc-ole2"
    return "", f"unknown:{blob[:4].hex()}"


def _docx(blob: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(blob)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:                                   # noqa: BLE001
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _pdf(blob: bytes) -> str:
    try:
        from pdfminer.high_level import extract_text     # noqa: PLC0415
    except ImportError:
        return ""
    try:
        return extract_text(BytesIO(blob)) or ""
    except Exception:                                   # noqa: BLE001
        return ""


def _ole2(blob: bytes) -> str:
    """Двоичный Word. Конвертер внешний; если его нет — честное 'не смогли'."""
    tmp = TEXTDIR / "_tmp.doc"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(blob)
    for cmd in (["antiword", "-m", "UTF-8.txt", str(tmp)], ["textutil", "-convert", "txt", "-stdout", str(tmp)]):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.decode("utf-8", "replace")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ""


def heb_ratio(t: str) -> float:
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return 0.0
    return len(HEB.findall("".join(letters))) / len(letters)


# --- визуальный порядок RTL ---------------------------------------------------
# Найдено 2026-07-29 при замере длин: тексты ПРИНЯТЫХ актов («ספר החוקים», PDF)
# извлекались pdfminer'ом в ВИЗУАЛЬНОМ порядке — каждая строка посимвольно
# перевёрнута. «רשומות» превращалось в «תומושר», и это не портило вид настолько,
# чтобы кто-то заметил глазами: ивритский текст остаётся ивритским текстом.
#
# Что от этого ломалось, по возрастанию тяжести:
#  · счёт статей и формул правки давал НОЛЬ на всех принятых актах — регулярки
#    искали «תיקון סעיף» в тексте, где написано «ןוקית ףיעס»;
#  · цитаты моделей не находились в исходнике (13 и 13 из пилота);
#  · 21 знак направления поставлен по перевёрнутому тексту, и среди них ВСЕ
#    семь актов оракула отбора. То есть «оракул пройден 7/7» означало
#    «модель угадала по названию» — ровно риск R1, принятый за успех.
#
# Реверс строки восстанавливает буквы и ЛОМАЕТ числа: в визуальном порядке
# числа лежат уже слева направо, поэтому их разворачиваем обратно.
# Библиотека python-bidi решает обратную задачу (логический → визуальный)
# и тянет зависимость ради десяти строк — не берём.
_REV_MARK = ("תומושר", "קוח תעצה", "םיקוחה", "תסנכה", "ןוקית", "קוח")
_FWD_MARK = ("רשומות", "הצעת חוק", "החוקים", "הכנסת", "תיקון", "חוק")
_DIGITS = re.compile(r"\d+")


def looks_reversed(t: str) -> bool:
    """Перевёрнут ли текст. Считаем маркеры, а не гадаем по одному слову."""
    head = " ".join((t or "").split())[:2000]
    return sum(m in head for m in _REV_MARK) > sum(m in head for m in _FWD_MARK)


def unbidi(t: str) -> str:
    """Визуальный порядок → логический. Построчно, с возвратом чисел."""
    out = []
    for line in (t or "").splitlines():
        r = line[::-1]
        out.append(_DIGITS.sub(lambda m: m.group(0)[::-1], r))
    return "\n".join(out)


def repair_rtl(t: str) -> tuple[str, bool]:
    """Чинит, если перевёрнуто. Возвращает (текст, чинили ли).

    U+FEFF внутри строки — не BOM, а разделитель слов в этих PDF: без замены
    «ספר החוקים» остаётся склеенным и не находится поиском.
    """
    t = (t or "").replace("﻿", " ")
    if not looks_reversed(t):
        return t, False
    return unbidi(t), True



def download(url: str, timeout: int = 60) -> tuple[bytes | None, str]:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            blob = r.read()
            declared = r.headers.get("Content-Length")
            # §23, сверка 2: второй путь к величине, если сервер его дал.
            if declared and int(declared) != len(blob):
                return None, f"ТИХИЙ НЕДОБОР ФАЙЛА: обещано {declared}, получено {len(blob)}"
            return blob, ""
    except Exception as e:                              # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"[:120]


def load_docs(refresh: bool) -> list[dict]:
    if DOCCACHE.exists() and not refresh:
        c = json.loads(DOCCACHE.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(c["fetched_at"])
        age = (datetime.now(timezone.utc) - at).total_seconds() / 3600
        print(f"⚠ КЭШ KNS_DocumentBill: {len(c['docs'])} записей, возраст {age:.1f} ч "
              f"(снят {c['fetched_at']}). Это устаревшая копия по построению — "
              f"перевыгрузить: --refresh")
        return c["docs"]
    docs = fetch_all("KNS_DocumentBill", flt=f"BillID ge {BILLID_FLOOR}",
                     select="Id,BillID,GroupTypeDesc,ApplicationDesc,FilePath")
    DOCCACHE.parent.mkdir(parents=True, exist_ok=True)
    DOCCACHE.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).isoformat(),
         "filter": f"BillID ge {BILLID_FLOOR}", "docs": docs},
        ensure_ascii=False), encoding="utf-8")
    return docs


def load_docs_for(bills: list[int], cache: Path) -> list[dict]:
    """Документы ровно этих законопроектов: фильтр BillID eq … or …, по 15 в запросе.

    Полная выгрузка от BILLID_FLOOR не покрывает законопроекты 20-го Кнессета (id ниже порога),
    а выгрузка всего архива — ~час. Каждый кусок идёт через guarded fetch_all (§23 счётчик).
    """
    if cache.exists():
        c = json.loads(cache.read_text(encoding="utf-8"))
        if sorted(c["bills"]) == sorted(bills):
            print(f"⚠ КЭШ {cache.name}: {len(c['docs'])} документов, снят {c['fetched_at']}")
            return c["docs"]
    docs = []
    for i in range(0, len(bills), 15):
        part = bills[i:i + 15]
        docs += fetch_all("KNS_DocumentBill", flt="(" + " or ".join(f"BillID eq {b}" for b in part) + ")",
                          select="Id,BillID,GroupTypeDesc,ApplicationDesc,FilePath")
    cache.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "bills": bills,
                                 "docs": docs}, ensure_ascii=False), encoding="utf-8")
    return docs


def selftest() -> int:
    """Оракул RTL. Красное здесь = тексты принятых актов снова читаются задом наперёд."""
    # Вход взят из реального файла data/bill_texts/2207472.txt (акт об отмене
    # стандарта разумности): БУКВЫ перевёрнуты, ЧИСЛА стоят правильно —
    # так работает визуальный порядок, и поэтому после реверса строки числа
    # приходится доворачивать обратно. Первая редакция теста этого не учла
    # и покраснела на верном коде: направление реверса чисел проверяемо
    # только на настоящем входе, не на придуманном.
    rev = "תומושר\n2023 ילויב 26\nהטיפשה :דוסי-קוח"
    fixed, did = repair_rtl(rev)
    assert did, "перевёрнутый текст не опознан"
    assert "רשומות" in fixed, f"буквы не восстановлены: {fixed!r}"
    assert "26 ביולי 2023" in fixed, f"числа не восстановлены: {fixed!r}"
    assert "חוק-יסוד: השפיטה" in fixed, f"составное название не собралось: {fixed!r}"

    fwd = "רשומות\nספר החוקים\nחוק-יסוד: השפיטה (תיקון מס' 3)"
    same, did2 = repair_rtl(fwd)
    assert not did2, "нормальный текст ошибочно признан перевёрнутым"
    assert "חוק-יסוד" in same, "нормальный текст испорчен"

    # U+FEFF как разделитель слов, а не BOM
    glued, _ = repair_rtl("ספר﻿החוקים")
    assert "ספר החוקים" in glued, f"FEFF не разделил слова: {glued!r}"
    print("самопроверка RTL пройдена: 3 случая (перевёрнутый, нормальный, склейка)")
    return 0


def fix_existing() -> int:
    """Разовый проход по уже выгруженным текстам той же функцией, что и выгрузка.

    Отдельная реализация была бы вторым источником правды: починенное на месте
    разошлось бы с починенным при перевыгрузке. Здесь один код, два входа.
    """
    files = sorted(TEXTDIR.glob("*.txt"))
    fixed = 0
    for p in files:
        before = p.read_text(encoding="utf-8")
        after, did = repair_rtl(before)
        if did:
            p.write_text(after, encoding="utf-8")
            fixed += 1
            print(f"   починен {p.stem} ({len(before)} симв)")
    print(f"\nпочинено {fixed} из {len(files)}")
    # §23: объявленное ожидание. Повторный проход обязан не найти ничего.
    again = sum(1 for p in files if repair_rtl(p.read_text(encoding="utf-8"))[1])
    if again:
        print(f"§23 ОТКАЗ: после починки {again} файлов всё ещё опознаются "
              f"перевёрнутыми — операция не идемпотентна", file=sys.stderr)
        return 1
    print("повторный проход не нашёл перевёрнутых — операция идемпотентна")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="оракул RTL, без сети")
    ap.add_argument("--fix-existing", action="store_true",
                    help="починить уже выгруженные тексты, без сети")
    ap.add_argument("--limit", type=int, default=0,
                    help="сколько законопроектов взять (0 = все). Для прогонов на осуществимость.")
    ap.add_argument("--refresh", action="store_true", help="перевыгрузить KNS_DocumentBill")
    ap.add_argument("--stratify", action="store_true",
                    help="выборка по форматам поровну, а не подряд — чтобы .doc точно попал")
    ap.add_argument("--from-selection", action="store_true",
                    help="брать ровно состав пилота из data/pilot_selection.json")
    ap.add_argument("--from-votes", action="store_true",
                    help="join-first: брать акты, за которые фракции РЕАЛЬНО "
                         "голосовали (data/votes_25.json). Прежние режимы брали "
                         "корпус, отобранный другим правилом, и пересечение с "
                         "голосованиями оказалось 3 акта из 55 — классификация "
                         "шла по актам, за которые никто из наблюдаемых не "
                         "голосовал.")
    ap.add_argument("--bills", type=Path, default=None,
                    help="JSON-список bill_id: брать ровно их; индекс — <файл>.index.json, кэш документов — <файл>.docs.json")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.fix_existing:
        return fix_existing()

    index = INDEX
    if a.bills:
        core = set(json.loads(a.bills.read_text(encoding="utf-8")))
        index = a.bills.with_suffix(".index.json")
        have = sum((TEXTDIR / f"{b}.txt").exists() for b in core)
        print(f"ОЖИДАНИЕ (§23): законопроектов в списке {len(core)}, текст уже есть у {have}")
    else:
        core = set(json.loads(SCAN.read_text(encoding="utf-8"))["core_ids"])
    if a.from_selection:
        sel = json.loads((ROOT / "data" / "pilot_selection.json").read_text(encoding="utf-8"))
        core = set(sel["selected"])
        print(f"состав пилота из pilot_selection.json: {len(core)}")
    if a.from_votes:
        v = json.loads((ROOT / "data" / "votes_25.json").read_text(encoding="utf-8"))
        core = {r["bill_id"] for r in v["rows"] if r.get("bill_id")}
        have = len([p for p in (ROOT / "data" / "bill_texts").glob("*.txt")
                    if p.stem.isdigit() and int(p.stem) in core])
        # §23: ожидание объявлено ДО выгрузки, вторым путём — по самой
        # выгрузке голосований, а не по обещанию скрипта.
        print(f"ОЖИДАНИЕ (§23): актов с голосованиями {len(core)}, "
              f"текст уже есть у {have}, значит цель — {len(core) - have}. "
              f"Сколько из них имеют документ нормы, неизвестно: это и меряем.")
    docs = load_docs_for(sorted(core), a.bills.with_suffix(".docs.json")) if a.bills else load_docs(a.refresh)

    best: dict[int, dict] = {}
    for d in docs:
        b = d["BillID"]
        if b not in core or not is_bill_text(d):
            continue
        if b not in best or rank(d) < rank(best[b]):
            best[b] = d
    print(f"ядро {len(core)} · с текстом нормы {len(best)}"
          f" · без текста {len(core) - len(best)} ← жёсткая планка Р1 отсекает их")

    targets = sorted(best)
    if a.stratify:
        by_app: dict[str, list[int]] = collections.defaultdict(list)
        for b in targets:
            by_app[best[b].get("ApplicationDesc") or "?"].append(b)
        per = max((a.limit or len(targets)) // max(len(by_app), 1), 1)
        targets = [b for lst in by_app.values() for b in lst[:per]]
        print(f"   выборка по форматам: " +
              ", ".join(f"{k}×{min(len(v), per)}" for k, v in by_app.items()))
    elif a.limit:
        step = max(len(targets) // a.limit, 1)
        targets = targets[::step][:a.limit]
    print(f"берём {len(targets)}\n")

    TEXTDIR.mkdir(parents=True, exist_ok=True)
    rows, stats = [], collections.Counter()
    for i, b in enumerate(targets, 1):
        d = best[b]
        url = norm(d["FilePath"])
        blob, err = download(url)
        if blob is None:
            rows.append({"bill": b, "status": "download_failed", "err": err, "url": url})
            stats["download_failed"] += 1
            print(f"   [{i}/{len(targets)}] {b} ✗ {err[:70]}")
            continue
        text, method = extract(blob, url)
        text, repaired = repair_rtl(text)          # визуальный RTL → логический
        text = re.sub(r"[ \t]+", " ", text).strip()
        ratio = heb_ratio(text)
        if len(text) < MIN_CHARS or ratio < MIN_HEB_RATIO:
            # НЕ «текста нет» — «мы его не получили». Разные состояния.
            rows.append({"bill": b, "status": "extract_failed", "method": method,
                         "chars": len(text), "heb": round(ratio, 2), "url": url,
                         "kind": d.get("GroupTypeDesc")})
            stats[f"extract_failed:{method}"] += 1
            print(f"   [{i}/{len(targets)}] {b} ✗ {method} → {len(text)} симв, иврит {ratio:.0%}")
            continue
        (TEXTDIR / f"{b}.txt").write_text(text, encoding="utf-8")
        rows.append({"bill": b, "status": "ok", "method": method, "chars": len(text),
                     "heb": round(ratio, 2), "kind": d.get("GroupTypeDesc"), "url": url,
                     "rtl_repaired": repaired})
        stats[f"ok:{method}"] += 1
        if repaired:
            stats["rtl_repaired"] += 1
        print(f"   [{i}/{len(targets)}] {b} ✓ {method} {len(text)} симв, иврит {ratio:.0%}")
        time.sleep(0.2)

    ok = sum(v for k, v in stats.items() if k.startswith("ok:"))
    print(f"\nИТОГ: извлечено {ok}/{len(targets)}")
    for k, v in sorted(stats.items()):
        print(f"   {k:<28} {v}")
    if ok != len(targets):
        print("\n⚠ Разница между «файл есть» и «текст извлёкся» — это НЕ дыра покрытия,")
        print("  пока не выяснено, отсутствует конвертер или отсутствует норма.")

    index.write_text(json.dumps(
        {"core_total": len(core), "with_bill_text": len(best),
         "attempted": len(targets), "extracted": ok,
         "stats": dict(stats), "preference": PREFERENCE,
         "min_chars": MIN_CHARS, "min_heb_ratio": MIN_HEB_RATIO,
         "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{index.resolve().relative_to(ROOT)} · тексты в {TEXTDIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
