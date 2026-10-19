#!/usr/bin/env python3
"""OCR коалиционных соглашений: скан → текст с якорями ⟦N⟧ (§12, §14, §23).

Все восемь соглашений 37-го правительства — сканы без текстового слоя. Без этого
шага канал Б не собирается: цитировать обязательство партии нечем.

ДЕТЕРМИНИРОВАННО И БЕЗ LLM. Правило перенесено из kegan-iooh дословно: «only
deterministic, reversible-in-principle fixes; when unsure — keep original».
Модель не касается текста, по которому потом цитируют партию: иначе цитата,
проверенная поиском по этому же тексту, доказывала бы только саму себя.

ЧИНИМ РОВНО ОДИН КЛАСС ОШИБОК, И ОН ИЗМЕРЕН. Замер на 37 страницах соглашения
с ШАС (12 921 слово): конечная мем `ם` систематически читается как самех `ס`.
447 слов на `יס` против 700 правильных на `ים` — 39% множественных чисел
искажены. Обратите внимание: garbage-score, перенесённый из книжного конвейера
с порогом 0,08, не срабатывает ЗДЕСЬ НИ РАЗУ (медиана 0,005, максимум 0,032) —
подменённые символы валидны, доля мусора не меняется. Признак из чужого проекта
не поймал бы ни одного случая; порог откалиброван на наших сканах заново.

ЧЕГО СКРИПТ НЕ ДЕЛАЕТ. Не восстанавливает таблицы и схемы — по правилу из того
же ретро они идут на перенабор с бумаги, и их страницы перечислены в отчёте.
Не переводит. Не сопоставляет обязательства с бюджетом.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "agreements"
OUT = ROOT / "data" / "agreements_ocr"
REPORT = ROOT / "data" / "agreements_ocr_report.json"
BREW = "/opt/homebrew/bin"          # ssh без login-шелла не видит Homebrew в PATH
DPI = 300

# МОДЕЛЬ РАСПОЗНАВАНИЯ — tessdata_best, а не то, что пришло с Homebrew.
#
# Замер на странице 10 соглашения с ШАС (560 слов): модель из пакета
# tesseract-lang 4.1.0 дала 35 слов с ошибкой конечной мем, tessdata_best — 8.
# В четыре с лишним раза меньше, и «חרדיים», «הקריטריונים», «שקלים» читаются
# верно там, где быстрая модель ставила самех. Это ступень «нативная
# возможность вместо своего кода»: лучшая модель убирает большую часть того,
# что я собирался чинить регулярками.
#
# §14: путь к модели, её URL и контрольная сумма зафиксированы здесь, чтобы
# прогон из чистого клона давал тот же текст. Без версии модели «воспроизводимо»
# означало бы «воспроизводимо, если у вас случайно та же модель».
TESSDATA = Path.home() / "tessdata_best"
HEB_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/heb.traineddata"
HEB_SHA256 = "dbaa827aea6bc21215638447f17783a1004987c2d0bf5573d111fee397abdae5"


HEB = re.compile(r"[א-ת]")
WORD = re.compile(r"[א-ת]+")
# Слова, которые ЗАКОННО кончаются на «יס» и не должны чиниться. Список короткий
# и открытый: если встретится ещё одно — оно попадёт в отчёт как исправленное,
# и это будет видно при вычитке. Молча угадывать тут нечего.
KEEP_YS = {"פיס", "מפעלהפיס", "טניס", "אטלס", "בסיס", "כיס", "ניס", "פיסיס"}


def fix_final_mem(text: str) -> tuple[str, int]:
    """`…יס` → `…ים`. Единственная автоправка, и она измерена (39% мн. ч.)."""
    n = 0

    def sub(m: re.Match) -> str:
        nonlocal n
        w = m.group(0)
        # Служебные буквы приклеиваются к слову спереди (ה, ו, ב, ל, כ, מ, ש):
        # «הפיס» — это «פיס» с артиклем, и он тоже законный.
        #
        # Снимаем НЕ БОЛЕЕ ДВУХ ведущих букв, а не все подряд. Первая редакция
        # делала lstrip до упора, и «בבסיס» («в базе», как в «בבסיס התקציב» —
        # в базе бюджета) обрезалось до «סיס», в списке не находилось и чинилось
        # в «בבסים». Поймано не тестом, а глазами на прогоне: словосочетание
        # «в базе бюджета» стоит ровно в денежных обязательствах, ради которых
        # весь канал Б и существует. Жадное правило испортило самое нужное место.
        if w in KEEP_YS or w[1:] in KEEP_YS or w[2:] in KEEP_YS or len(w) < 3:
            return w
        n += 1
        return w[:-1] + "ם"

    return WORD.sub(lambda m: sub(m) if m.group(0).endswith("יס") else m.group(0), text), n


# --- гершаим: кавычка в аббревиатуре читается как двойной йод ---------------
#
# ПОЧЕМУ СПИСОК, А НЕ ПРАВИЛО. Позиционное правило «יי перед последней буквой»
# ловит аббревиатуры (יוייר → יו"ר) вместе с законными словами: מתחייב
# («обязуется» — слово из каждого обязательства!), חיילים («солдаты»),
# האוכלוסייה, התעשייה, בנייה. Отсев по последней букве (ם/ן/ה/ת/ע) убирает часть,
# но מתחייב, יחייב и חייל остаются. Автоправка по позиции испортила бы глагол,
# на котором держится смысл обязательства.
#
# ОТКУДА СПИСОК. Частотный проход по всем 146 страницам: 156 кандидатов,
# 587 вхождений. Верхушка размечена по контексту — тот же приём, которым
# в kegan-iooh собирался глоссарий: словарь выводится из документа, а не
# берётся готовым. Здесь нужны аббревиатуры ЭТИХ восьми документов, а не иврита.
#
# ЧЕГО В СПИСКЕ НЕТ И ПОЧЕМУ. «שייש» встречается и как ש"ש (недельные часы),
# и внутри «שיישוב» (что поселение) — неоднозначно, оставлено как есть.
# «חייל», «מתחייב», «יחייב», «להתחייב» — законные слова, не трогаются.
# tesseract --user-words проверен и не помогает: LSTM-движок его игнорирует.
ABBREV = {
    "יוייר": "יו\"ר", "מנכייל": "מנכ\"ל", "מלשייח": "מלש\"ח", "יוייש": "יו\"ש",
    "חייכ": "ח\"כ", "עייי": "ע\"י", "שייח": "ש\"ח", "צהייל": "צה\"ל",
    "דוייח": "דו\"ח", "הנייל": "הנ\"ל", "בינייל": "בינ\"ל", "בסייד": "בס\"ד",
    "תנייך": "תנ\"ך", "עייפ": "ע\"פ", "הרשייפ": "הרש\"פ", "מהייט": "מה\"ט",
    "מגייב": "מג\"ב", "שבייכ": "שב\"כ", "רוהיימ": "רוה\"מ", "רהיימ": "רה\"מ",
    "חבייד": "חב\"ד", "בלוייש": "בלו\"ש", "רוייח": "רו\"ח", "המוכשייר": "המוכש\"ר",
}
PREFIXES = ("", "ו", "ל", "מ", "כ", "ב", "ה", "ש", "ול", "וב", "לה", "מה")
# Годы по еврейскому счёту: התשפייג → התשפ"ג. Форма устойчивая и не пересекается
# с обычными словами, поэтому здесь правило, а не перечисление.
YEAR_RE = re.compile(r"\b((?:ה?ת)ש[א-ת]?)יי([א-ת])\b")


def fix_gershayim(text: str) -> tuple[str, int]:
    """Восстановить кавычку в аббревиатурах по списку. Ничего не угадывать."""
    n = 0

    def one(w: str) -> str:
        nonlocal n
        for p in PREFIXES:
            if p and not w.startswith(p):
                continue
            stem = w[len(p):]
            if stem in ABBREV:
                n += 1
                return p + ABBREV[stem]
        return w

    out = WORD.sub(lambda m: one(m.group(0)), text)
    out, k = YEAR_RE.subn(r'\1"\2', out)
    return out, n + k


def garbage_score(line: str) -> float:
    s = line.strip()
    if not s:
        return 0.0
    ok = sum(1 for c in s if c.isalpha() or c.isdigit() or c in " ,.'\"-;:()?!/–—%")
    return 1.0 - ok / len(s)


def ensure_model() -> None:
    """Модель на месте и та самая. Иначе прогон не воспроизводим (§14)."""
    import hashlib
    import urllib.request
    p = TESSDATA / "heb.traineddata"
    if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == HEB_SHA256:
        return
    TESSDATA.mkdir(parents=True, exist_ok=True)
    print(f"скачиваю модель распознавания: {HEB_URL}")
    urllib.request.urlretrieve(HEB_URL, p)
    got = hashlib.sha256(p.read_bytes()).hexdigest()
    if got != HEB_SHA256:
        raise RuntimeError(f"контрольная сумма модели не сошлась: {got}")


def ocr_pdf(pdf: Path, workdir: Path) -> list[str]:
    """Постранично: pdftoppm → tesseract -l heb. Якорь ⟦N⟧ = страница файла."""
    env = {"TESSDATA_PREFIX": str(TESSDATA), "PATH": BREW}
    subprocess.run([f"{BREW}/pdftoppm", "-r", str(DPI), "-png", str(pdf),
                    str(workdir / "pg")], check=True, timeout=1800)
    pages = []
    for png in sorted(workdir.glob("pg-*.png")):
        base = png.with_suffix("")
        subprocess.run([f"{BREW}/tesseract", str(png), str(base), "-l", "heb",
                        "--psm", "6"], check=True, capture_output=True,
                       timeout=300, env=env)
        raw = base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
        pages.append(raw)
    return pages


def analyse(pages: list[str]) -> dict:
    """Признаки качества, откалиброванные на наших сканах, а не взятые извне."""
    per_page, empty, manual = [], [], []
    words = fixed = 0
    for i, t in enumerate(pages, 1):
        body = [l for l in t.split("\n") if l.strip()]
        chars = sum(len(l) for l in body)
        g = sum(garbage_score(l) for l in body) / max(len(body), 1)
        ws = WORD.findall(t)
        words += len(ws)
        heb_share = sum(1 for c in t if HEB.match(c)) / max(chars, 1)
        per_page.append({"page": i, "chars": chars, "garbage": round(g, 3),
                         "words": len(ws), "heb_share": round(heb_share, 2)})
        if chars < 200:
            empty.append(i)
        # Страница с текстом, но низкой долей иврита — таблица или схема.
        # По правилу kegan такие идут на ПЕРЕНАБОР С БУМАГИ, а не в перевод.
        if 200 <= chars and heb_share < 0.55:
            manual.append(i)
    return {"pages": len(pages), "words": words, "pages_empty": empty,
            "pages_manual_retype": manual, "per_page": per_page}


def validate_corpus(report: dict, out: Path, expected: dict) -> None:
    """§23/§24: each declared file and every page anchor must exist."""
    if set(report["files"]) != set(expected) or report["total_pages"] != sum(expected.values()):
        raise SystemExit("§23: OCR report corpus/page count mismatch")
    for name, count in expected.items():
        path = out / (name + ".txt")
        if not path.exists():
            raise SystemExit(f"§24: missing OCR {path.name}")
        anchors = re.findall(r"^⟦(\d+)⟧$", path.read_text(), re.M)
        if anchors != [str(i) for i in range(1, count + 1)] or report["files"][name]["pages"] != count:
            raise SystemExit(f"§23: page anchors mismatch: {name}")
        if report["files"][name].get("text_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise SystemExit(f"§14: OCR hash mismatch: {name}")


def main() -> int:
    global TESSDATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--government", choices=("36", "37"), default="37")
    ap.add_argument("--tessdata", type=Path, help="explicit alternate model; SHA recorded")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--only", default="", help="обработать один файл по имени")
    ap.add_argument("--expect-pages", type=int, default=None,
                    help="§23: ожидаемое суммарное число страниц, объявляется ДО прогона")
    a = ap.parse_args()

    expected = {}
    report_path = REPORT if a.government == "37" else REPORT.with_name("agreements_ocr_report_ca36.json")
    if a.government == "36":
        manifest = json.loads((ROOT / "criteria/agreements_ca36.json").read_text())
        expected = {Path(v["file"]).stem: v["pages"] for v in manifest["agreements"]}
        if a.only:
            expected = {k: v for k, v in expected.items() if a.only in k}
        if not expected:
            raise SystemExit("No declared OCR inputs")
    if a.verify and a.government != "36":
        ap.error("--verify requires --government 36")
    if a.verify:
        validate_corpus(json.loads(report_path.read_text()), OUT, expected)
        print("GREEN: OCR corpus verified")
        return 0
    if a.tessdata:
        TESSDATA = a.tessdata.resolve()
        if not (TESSDATA / "heb.traineddata").exists():
            raise SystemExit("Missing Hebrew model")
    else:
        ensure_model()
    OUT.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(RAW.glob(f"CA{a.government}-*.pdf"))
    if a.only:
        pdfs = [p for p in pdfs if a.only in p.name]
    if not pdfs:
        print("нет PDF в data/agreements — сначала scripts/fetch_agreements.py")
        return 1

    if expected and {p.stem for p in pdfs} != set(expected):
        raise SystemExit("§23: PDF corpus mismatch")
    index, total_pages, total_fixed = {}, 0, 0
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        with tempfile.TemporaryDirectory() as td:
            pages = ocr_pdf(pdf, Path(td))
        if expected and len(pages) != expected[pdf.stem]:
            raise SystemExit(f"§23: wrong page count: {pdf.name}")
        stats = analyse(pages)
        out_pages, fixed_here, gersh_here = [], 0, 0
        for i, t in enumerate(pages, 1):
            t2, n = fix_final_mem(t)
            t2, g = fix_gershayim(t2)
            fixed_here += n
            gersh_here += g
            out_pages.append(f"⟦{i}⟧\n{t2}")
        (OUT / f"{pdf.stem}.txt").write_text("\n\n".join(out_pages), encoding="utf-8")
        total_pages += stats["pages"]
        total_fixed += fixed_here
        print(f"страниц {stats['pages']} · слов {stats['words']} · "
              f"починено יס→ים {fixed_here} · гершаим {gersh_here}")
        print(f"   пустых: {stats['pages_empty'] or '—'} · "
              f"на перенабор с бумаги: {stats['pages_manual_retype'] or '—'}")
        index[pdf.stem] = {**stats, "fixed_final_mem": fixed_here,
                           "fixed_gershayim": gersh_here,
                           "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                           "text_sha256": hashlib.sha256((OUT / f"{pdf.stem}.txt").read_bytes()).hexdigest()}

    print(f"\nВСЕГО: страниц {total_pages} · автоправок יס→ים {total_fixed}")
    if a.expect_pages is not None:
        ok = total_pages == a.expect_pages
        print(f"§23: объявлено {a.expect_pages} — "
              f"{'в пределах' if ok else '⚠ ВНЕ объявленного'}")
    if a.expect_pages is not None and not ok:
        raise SystemExit("§23: total pages mismatch")
    manual = {k: v["pages_manual_retype"] for k, v in index.items() if v["pages_manual_retype"]}
    if manual:
        print("\n⚠ НА ПЕРЕНАБОР С БУМАГИ (таблицы и схемы, OCR их не берёт):")
        for k, v in manual.items():
            print(f"   {k}: страницы {v}")
        print("   Это не сбой: правило перенесено из ретро kegan — таблицы")
        print("   со скана не восстанавливаются, их набирают руками.")

    report_path.write_text(json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(), "dpi": DPI, "lang": "heb",
         "model_sha256": hashlib.sha256((TESSDATA / "heb.traineddata").read_bytes()).hexdigest(),
         "model_path": str(TESSDATA),
         "tesseract": subprocess.run([f"{BREW}/tesseract", "--version"],
                                     capture_output=True, text=True).stdout.split("\n")[0],
         "total_pages": total_pages, "fixed_final_mem": total_fixed,
         "expected_pages": sum(expected.values()) if expected else a.expect_pages, "files": index},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if expected:
        validate_corpus(json.loads(report_path.read_text()), OUT, expected)
    print(f"\n{OUT}\n{report_path}")
    return 0


def selftest() -> int:
    """Оракул автоправки. Красное = либо чиним лишнее, либо не чиним нужное."""
    t, n = fix_final_mem("הצדדיס והתפקידיס יסכימו")
    assert "הצדדים" in t and "התפקידים" in t, f"мн. число не починено: {t}"
    assert n == 2, f"счётчик правок неверен: {n}"
    assert "יסכימו" in t, "слово, начинающееся на יס, не должно трогаться"

    keep, n2 = fix_final_mem("מפעל הפיס בסיס בבסיס התקציב")
    assert keep == "מפעל הפיס בסיס בבסיס התקציב", f"законные слова на יס испорчены: {keep}"
    assert n2 == 0, "счётчик сработал на законных словах"
    # «בבסיס התקציב» — в базе бюджета. Стоит в денежных обязательствах, то есть
    # ровно там, ради чего канал Б собирается. Жадный lstrip портил его молча.

    assert fix_final_mem("יס")[1] == 0, "двухбуквенное слово трогать нельзя"

    # Гершаим: аббревиатуры чинятся, законные слова — нет. Второе важнее:
    # «מתחייבות» («обязуются») стоит в каждом обязательстве, ради которого
    # канал Б собирается, и позиционное правило его бы испортило.
    g, gn = fix_gershayim("יוייר הוועדה ומנכייל המשרד יקבלו 15 מלשייח")
    assert 'יו"ר' in g and 'ומנכ"ל' in g and 'מלש"ח' in g, f"аббревиатуры не починены: {g}"
    assert gn == 3, f"счётчик гершаим неверен: {gn}"

    safe, sn = fix_gershayim("הסיעות מתחייבות לתמוך, חיילים באוכלוסייה, התעשייה ובנייה")
    assert safe == "הסיעות מתחייבות לתמוך, חיילים באוכלוסייה, התעשייה ובנייה", \
        f"законные слова испорчены: {safe}"
    assert sn == 0, "счётчик сработал на законных словах"

    yr, yn = fix_gershayim("התשפייג")
    assert yr == 'התשפ"ג' and yn == 1, f"год не починен: {yr}"

    assert garbage_score("הסכם קואליציוני בין סיעת הליכוד") < 0.05, "иврит принят за мусор"
    assert garbage_score("~@#$%^&*<>|\\{}[]_=+") > 0.8, "мусор не опознан"

    # Модель: сумма зафиксирована и совпадает с тем, чем распознавали.
    # Красное здесь = текст соглашений получен другой моделью, чем записано,
    # и «воспроизводимо из репозитория» перестало быть правдой (§14).
    import hashlib
    p = TESSDATA / "heb.traineddata"
    if p.exists():
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        assert got == HEB_SHA256, f"модель на диске не та, что записана: {got}"
    assert len(HEB_SHA256) == 64 and HEB_URL.endswith("heb.traineddata"), \
        "константы модели повреждены"

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        sample = out / "CA36-BW.txt"
        sample.write_text("⟦1⟧\nבדיקה")
        report = {"total_pages": 1, "files": {"CA36-BW": {
            "pages": 1, "text_sha256": hashlib.sha256(sample.read_bytes()).hexdigest()}}}
        validate_corpus(report, out, {"CA36-BW": 1})
        sample.unlink()
        try:
            validate_corpus(report, out, {"CA36-BW": 1})
        except SystemExit as exc:
            assert "missing OCR" in str(exc)
            print("RED caught: deleted OCR txt")
        else:
            raise AssertionError("deleted OCR accepted")
    print("самопроверка ocr_agreements пройдена: corrections + missing OCR mutation")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
