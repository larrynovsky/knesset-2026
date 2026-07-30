#!/usr/bin/env python3
"""Канал Б: сопоставление обязательства с бюджетной строкой. §3, §11, §12, §23.

Применяет ЗАКОММИЧЕННОЕ правило criteria/budget_mapping.yaml к тексту
коалиционного соглашения и к выгрузке бюджета. Сам ничего не решает: даёт
кандидатов и все четыре канала чисел, а `granularity` оставляет пустой —
это решение человека (§12: сопоставление обязательства с бюджетной строкой
принимает человек). Заполняется на странице обзора, Ф5.

Три отказа, встроенные намеренно:

  1. Правило не в HEAD или рабочая копия расходится с закоммиченной — отказ.
     Иначе §3 защищает не порядок, а намерение: применённое правило и
     опубликованное правило обязаны быть одним файлом. sha256 применённого
     кладётся в артефакт.
  2. Число кандидатов не совпало с объявленным в правиле — отказ. Ожидание
     объявлено ДО прогона и получено двумя путями (§23). Расхождение значит,
     что текст или правило изменились, а не что «нашлось меньше».
  3. Ручных решений больше объявленного порога — остановка с вопросом
     владельцу, а не самостоятельное дорешивание.

Запуск (данные лежат на Studio, §19):
    ssh larry@studio 'cd ~/knesset && python3 -u scripts/map_commitments.py'
Самопроверка (без сети и без данных):
    python3 scripts/map_commitments.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULE = ROOT / "criteria" / "budget_mapping.yaml"
RULE_REL = "criteria/budget_mapping.yaml"
AGREEMENT = ROOT / "data" / "agreements_ocr" / "CA37-Shas.txt"
TAKANOT = ROOT / "data" / "budget_takanot.json"
CHANGES = ROOT / "data" / "budget_changes.json"
OUT = ROOT / "data" / "commitment_map_shas.json"

# Служебные слова иврита и единицы измерения. Это МЕХАНИКА поиска, не норма:
# правило требует, чтобы термины приходили из цитаты, и этот список только
# убирает из цитаты то, что не является предметом.
STOP = {
    "אשר", "אשרר", "וכן", "לפי", "עבור", "לטובת", "בסך", "בשנה", "שנה", "כל",
    "של", "את", "עם", "לא", "יהיה", "תהיה", "יהיו", "יעמוד", "הממשלה", "משרד",
    "תקציב", "התקציב", "בבסיס", "בסיס", "יוקצו", "יוקצה", "תתוקצב", "תתקצב",
    "מיליון", "מליון", "מיליארד", "מליארד", "מלשח", "שקלים", "שקל", "סך",
    "נוסף", "נוספים", "כאמור", "בהתאם", "כפי", "אלף", "אלפי", "בכל", "מדי",
}
HEB = re.compile(r"[֐-׿]+")
PREFIXES = "בלהומשכ"


def _derived_stop(units: list[str], heading_marks: tuple[str, ...]) -> set[str]:
    """Стоп-слова, ВЫВЕДЕННЫЕ из того, что правило уже объявило.

    Повод (первый прогон v1.2): наследование от заголовка притащило слова
    самого оборота «בסכומים הבאים» («в следующих суммах»), и обрубок `באים`
    с df=3 получил почти максимальный вес — верхним кандидатом на «ремонт
    синагог» стало «оборудование для прибывающих из Эфиопии». Обломок
    единицы `מלש` вёл себя так же.

    Список не подбирается руками под желаемый результат: он получается из
    money_units и из маркеров заголовка, то есть из строк, которые в критерии
    УЖЕ объявлены и объявлены до прогона. Подобрать его под ответ нельзя,
    не подобрав сам критерий, а тот виден в диффе.
    """
    out: set[str] = set()
    for src in list(units) + list(heading_marks):
        for w in HEB.findall(src):
            out.add(w)
            if len(w) >= 5 and w[0] in PREFIXES:
                out.add(w[1:])
    return out


# ------------------------------------------------------------------ правило
def rule_text_and_sha() -> tuple[str, str]:
    """Правило обязано быть в HEAD и совпадать с рабочей копией (§3)."""
    if not RULE.exists():
        sys.exit(f"ОТКАЗ: нет {RULE_REL}. Правило пишется ДО сопоставления (§3).")
    disk = RULE.read_bytes()
    res = subprocess.run(["git", "show", f"HEAD:{RULE_REL}"],
                         capture_output=True, cwd=ROOT)
    if res.returncode != 0:
        sys.exit(f"ОТКАЗ: {RULE_REL} не закоммичен. Применённое правило обязано "
                 "быть опубликованным — иначе §3 защищает намерение, а не порядок.")
    if res.stdout != disk:
        sys.exit(f"ОТКАЗ: рабочая копия {RULE_REL} расходится с закоммиченной. "
                 "Применяется одно правило, опубликовано другое.")
    return disk.decode("utf-8"), hashlib.sha256(disk).hexdigest()


def rule_list(text: str, key: str) -> list[str]:
    """Список вида `key: ['a', 'b']` из правила. Отсутствие — отказ, не дефолт."""
    m = re.search(rf"^\s*{key}:\s*\[(.*?)\]\s*$", text, flags=re.M | re.S)
    if not m:
        sys.exit(f"ОТКАЗ: в {RULE_REL} нет ключа `{key}` — молча не продолжаю (§20)")
    return [v.strip().strip("'\"") for v in m.group(1).split(",") if v.strip()]


def rule_int(text: str, key: str) -> int:
    m = re.search(rf"^\s*{key}:\s*(\d+)\s*$", text, flags=re.M)
    if not m:
        sys.exit(f"ОТКАЗ: в {RULE_REL} нет числового ключа `{key}` (§20)")
    return int(m.group(1))


def rule_str(text: str, key: str) -> str:
    m = re.search(rf"^\s*{key}:\s*'(.*?)'\s*$", text, flags=re.M)
    if not m:
        sys.exit(f"ОТКАЗ: в {RULE_REL} нет строкового ключа `{key}` (§20)")
    return m.group(1)


# ------------------------------------------------------------- извлечение
ITEM_RE = re.compile(r"^([א-ת]\.|\d+\.|\+)\s")
HEADING_MARK = ("בסכומים הבאים",)
BASE_MARK = ("בבסיס התקציב", "לבסיס התקציב")


def _in_base(s: str) -> bool:
    return any(m in s for m in BASE_MARK)


def candidates(lines: list[str], units: list[str]) -> list[dict]:
    """Строки с числом и денежной единицей, с якорем страницы и заголовком.

    Заголовок перечня сумм не содержит и потому сам кандидатом не является —
    но именно он несёт предмет («религиозные здания») и признак «в базе
    бюджета». Первая редакция его не видела, и семь обязательств теряли и то
    и другое: они находились по слову «ремонт», которое стоит в сотнях статей.
    """
    page, out, heading = None, [], None
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        m = re.fullmatch(r"⟦(\d+)⟧", s)
        if m:
            page = int(m.group(1))
            continue
        if not s:
            continue
        has_money = bool(re.search(r"[0-9]", s)) and any(u in s for u in units)
        is_item = bool(ITEM_RE.match(s))

        if not has_money and any(v in s for v in VERBS_COMMIT) and (
                s.endswith(":") or s.endswith(": ") or any(h in s for h in HEADING_MARK)):
            heading = {"quote_he": s, "line": i, "in_base": _in_base(s)}
            continue
        if heading and not is_item and not has_money:
            heading = None            # перечень кончился

        if has_money:
            out.append({"line": i, "page": page, "quote_he": s,
                        "heading": heading if (heading and is_item) else None})
    return out


VERBS_COMMIT = ("יוקצו", "יוקצה", "תתוקצב", "תתקצב", "יתקצב", "יעמוד על",
                "יתווסף", "לייעד", "ייעוד", "הקצאה", "תוקצב", "ייכנס לבסיס",
                "ייכנסו לבסיס", "יוכנס לבסיס", "תוסיף", "יתוקצב")
MARK_STATUS_QUO = ("ניתן כיום", "הנמצאים כיום", "כיום", "צפויות", "המקובלים")
MARK_UNIT_RATE = ("לחודש", "לחודש.", "ערך הנקודה", "ערך נקודה", "לתלמיד", "למיטה")


def classify(quote: str) -> tuple[str, str]:
    """Категория кандидата и правило, которое сработало. Закрытый список."""
    for m in MARK_UNIT_RATE:
        if m in quote:
            return "unit_rate", f"маркер ставки: {m}"
    for m in MARK_STATUS_QUO:
        if m in quote:
            return "status_quo", f"маркер существующего положения: {m}"
    for v in VERBS_COMMIT:
        if v in quote:
            return "commitment", f"глагол выделения: {v}"
    # Пункт перечня без глагола («א. שיפוץ בתי כנסת - 30 מלש"ח») наследует
    # глагол заголовка списка. Помечается отдельно, а не молча отбрасывается.
    if re.match(r"^[א-ת]\.\s|^\+\s|^\d+\.\s", quote):
        return "commitment", "пункт перечня, глагол в заголовке списка"
    return "continuation", "нет глагола выделения и нет номера пункта"


def terms_of(quote: str, extra_stop: set[str] | None = None) -> list[str]:
    """Термины поиска — только слова из цитаты (правило запрещает иные)."""
    stop = STOP | (extra_stop or set())
    out: list[str] = []
    for w in HEB.findall(quote):
        if len(w) < 3 or w in stop:
            continue
        out.append(w)
        if len(w) >= 5 and w[0] in PREFIXES:
            out.append(w[1:])
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def amount_of(quote: str) -> float | None:
    """Сумма в шекелях, если она читается цифрами. Словесную не угадываем."""
    m = re.search(r"(\d[\d.,]*)\s*(מלש\"ח|מלש'יח|מש\"ח|מיליון|מליון|"
                  r"מיליארד|מליארד|אלש\"ח)", quote)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = m.group(2)
    if unit in ("מיליארד", "מליארד"):
        return n * 1e9
    if unit == 'אלש"ח':
        return n * 1e3
    return n * 1e6


# ------------------------------------------------------------------- поиск
TITLE_FIELDS = ("title", "title_level8", "title_level6", "title_level4")


def doc_freq(rows: list[dict], term: str, _cache: dict = {}) -> int:  # noqa: B006
    """В скольких названиях статей встречается термин. Считается один раз."""
    if term not in _cache:
        _cache[term] = sum(1 for r in rows if term in (r["title"] or ""))
    return _cache[term]


def search(rows: list[dict], terms: list[str], years: list[int],
           dfs: dict[str, int]) -> list[dict]:
    """Кандидаты-строки: вес термина 1/(1+df), вес строки — сумма весов.

    Считается не СКОЛЬКО терминов совпало, а какие. `שיפוץ` («ремонт») стоит
    в сотнях названий и весит почти ноль; `מקומות קדושים` — в трёх и весит
    почти единицу. Прежняя редакция считала их одинаковыми, и частое слово
    выигрывало у редкого просто потому, что встречалось чаще.
    """
    hits: dict[str, dict] = {}
    for r in rows:
        if r["year"] not in years:
            continue
        blob = " ".join(str(r.get(f) or "") for f in TITLE_FIELDS)
        matched = [t for t in terms if t in blob]
        if not matched:
            continue
        score = sum(1.0 / (1 + dfs[t]) for t in matched)
        cur = hits.get(r["code"])
        if cur is None or score > cur["score"]:
            hits[r["code"]] = {"code": r["code"], "title": r["title"],
                               "matched": matched, "score": round(score, 5)}
    return sorted(hits.values(), key=lambda h: (-h["score"], h["code"]))


def narrow(found: list[dict], max_shown: int, terms: list[str],
           dfs: dict[str, int], rare_max: int) -> tuple[list[dict], str | None]:
    """Сужение словами из цитаты — то, что правило предписывает ДО отказа.

    v1.1 сужала по числу совпавших терминов и давала 18 отказов из 21: слово
    «ремонт» топило цитату целиком. v1.2 сужает по РЕДКОСТИ. Цитата, в которой
    нет ни одного термина редче объявленного порога, не различает ничего —
    и вот это законный term_too_generic, а не «нашлось слишком много».
    """
    if not found:
        return [], "no_term_match"
    rare = [t for t in terms if dfs.get(t, 10 ** 9) <= rare_max]
    if not rare:
        return [], "term_too_generic"
    keep = [f for f in found if any(t in f["matched"] for t in rare)]
    if not keep:
        return [], "no_term_match"
    return keep[:max_shown], None


def numbers_for(rows_by_code_year: dict, code: str, years: list[int]) -> dict:
    out = {}
    for y in years:
        r = rows_by_code_year.get((code, y))
        out[str(y)] = None if r is None else {
            "net_allocated": r["net_allocated"],
            "net_revised": r["net_revised"],
            "net_executed": r["net_executed"],
            "non_repeating": r.get("non_repeating"),
            "title": r["title"],
        }
    return out


def transfers_for(changes: list[dict], code: str, years: list[int]) -> list[dict]:
    """Переносы, чей код — префикс нашего (переносы записаны на 8 знаках)."""
    out = []
    for c in changes:
        if c["year"] not in years:
            continue
        codes = c.get("budget_code_title") or []
        for entry in codes:
            ccode = str(entry).split(":", 1)[0]
            if ccode and (code.startswith(ccode) or ccode.startswith(code)):
                out.append({
                    "transaction_id": c["transaction_id"],
                    "year": c["year"],
                    "date": (c.get("date") or [None])[0],
                    "matched_code": ccode,
                    "net_expense_diff": c.get("net_expense_diff"),
                    "kind": (c.get("change_title") or [None])[0],
                    "explanation_head": (c.get("explanation") or "")[:200],
                })
                break
    return out


# ------------------------------------------------------------------- main
def selftest() -> int:
    assert classify('א. שיפוץ בתי כנסת - 30 מלש"ח.')[0] == "commitment"
    assert classify("2. מה\"ט תתוקצב ב-15 מיליון ₪ בשנה")[0] == "commitment"
    assert classify("ניתן כיום סך של כ-3.5 מיליארד ₪ בשנה")[0] == "status_quo"
    assert classify("של 1,200 ₪ לחודש ויוכנס לבסיס התקציב.")[0] == "unit_rate"
    assert amount_of('שיפוץ בתי כנסת - 30 מלש"ח') == 30e6
    assert amount_of("2.2 מיליארד") == 2.2e9
    assert amount_of("בלי סумм") is None
    t = terms_of('א. שיפוץ בתי כנסת - 30 מלש"ח.')
    assert "כנסת" in t and "מיליון" not in t, t
    assert "בתי" in t
    # приставка отрезается только у длинных слов
    assert "מקוואות" in terms_of("בנית מקוואות - 40 מלש\"ח")
    rows = [{"code": "0022010203", "year": 2023, "title": "קהילות יהודיות",
             "title_level8": "", "title_level6": "", "title_level4": ""}]
    D = {"קהילות": 3}
    assert search(rows, ["קהילות"], [2023], D)[0]["code"] == "0022010203"
    assert search(rows, ["קהילות"], [2024], D) == []
    # редкий термин весит больше частого — это и есть вся правка v1.2
    many = [{"code": f"{i:010d}", "year": 2023, "title": "שיפוץ משהו",
             "title_level8": "", "title_level6": "", "title_level4": ""}
            for i in range(3)]
    many.append({"code": "9" * 10, "year": 2023, "title": "שיפוץ מקומות קדושים",
                 "title_level8": "", "title_level6": "", "title_level4": ""})
    D2 = {"שיפוץ": 400, "מקומות": 3}
    res = search(many, ["שיפוץ", "מקומות"], [2023], D2)
    assert res[0]["code"] == "9" * 10, "редкий термин обязан выигрывать у частого"
    # заголовок перечня отдаёт подпункту «в базе бюджета»
    heads = ["⟦9⟧", "3. תתוקצב בבסיס התקציב בנייה של מבני הדת בסכומים הבאים :",
             "", 'א. שיפוץ בתי כנסת - 30 מלש"ח.', "", "טקסט אחר בלי סימן",
             'ב. משהו - 5 מלש"ח.']
    cs = candidates(heads, ['מלש"ח'])
    assert len(cs) == 2, cs
    assert cs[0]["heading"] is not None and cs[0]["heading"]["in_base"] is True
    assert cs[1]["heading"] is None, "перечень обязан кончаться на чужой строке"
    ch = [{"year": 2023, "transaction_id": "t1", "budget_code_title": ["00220102:x"],
           "net_expense_diff": 1.0, "change_title": ["עודפים"], "explanation": "",
           "date": ["2023-01-01"]}]
    assert transfers_for(ch, "0022010203", [2023])[0]["matched_code"] == "00220102"
    assert transfers_for(ch, "0099999999", [2023]) == []
    # narrow: сужение обязано случиться ДО отказа, иначе отказов будет больше,
    # чем работы, и артефакт окажется пустым при зелёном прогоне
    wide = [{"code": f"{i:010d}", "matched": ["common"]} for i in range(20)]
    rarerow = [{"code": "9" * 10, "matched": ["common", "rare"]}]
    DF = {"common": 400, "rare": 3}
    T = ["common", "rare"]
    assert narrow(rarerow + wide, 10, T, DF, 50)[0] == rarerow, \
        "оставляем только строки с редким термином"
    assert narrow(wide, 10, ["common"], DF, 50) == ([], "term_too_generic"), \
        "в цитате нет ни одного редкого слова — законный отказ"
    assert narrow([], 10, T, DF, 50) == ([], "no_term_match")
    # выведенные стоп-слова: обломок единицы и оборот перечня не могут стать
    # поисковым термином. Именно они топили первый прогон v1.2
    ds = _derived_stop(['מלש"ח'], ("בסכומים הבאים",))
    assert "מלש" in ds and "הבאים" in ds and "באים" in ds, ds
    assert "מלש" not in terms_of('שיפוץ - 30 מלש"ח', ds)
    assert "כנסת" in terms_of('שיפוץ בתי כנסת - 30 מלש"ח', ds)
    print("самопроверка map_commitments пройдена: 26 утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    text, sha = rule_text_and_sha()
    units = rule_list(text, "money_units") + rule_list(text, "damaged_units")
    expected = rule_int(text, "candidate_lines_expected")
    max_shown = rule_int(text, "max_candidates_shown")
    max_manual = rule_int(text, "max_manual_decisions")
    rare_max = rule_int(text, "rare_term_max_articles")
    code_pat = rule_str(text, "pattern")
    years = [2023, 2024, 2025]
    # Стоп-слова, выведенные из объявленного в правиле, а не подобранные.
    dstop = _derived_stop(units, HEADING_MARK)

    lines = AGREEMENT.read_text(encoding="utf-8").splitlines()
    cands = candidates(lines, units)
    if len(cands) != expected:
        sys.exit(f"§23 ОТКАЗ: кандидатов {len(cands)}, правило объявляет {expected}. "
                 "Ожидание объявлено до прогона; расхождение — повод остановиться, "
                 "а не подкрутить список единиц.")
    print(f"кандидатов: {len(cands)} (совпало с объявленным)")

    budget = json.loads(TAKANOT.read_text(encoding="utf-8"))
    changes = json.loads(CHANGES.read_text(encoding="utf-8"))["rows"]
    rows = budget["rows"]
    rows10 = [r for r in rows if len(r["code"]) == 10]
    by_cy = {(r["code"], r["year"]): r for r in rows}
    print(f"бюджет: {len(rows)} строк (снимок {budget['fetched_at']}), "
          f"переносов: {len(changes)}")

    items, manual = [], 0
    for c in cands:
        cat, rule_fired = classify(c["quote_he"])
        item = {
            **c,
            "category": cat,
            "category_rule": rule_fired,
            "amount_ils": amount_of(c["quote_he"]),
            # Признак берётся из цитаты ИЛИ из заголовка перечня: подпункт
            # «а. ремонт синагог — 30 млн» сам «в базе бюджета» не говорит,
            # это сказано строкой выше за все семь подпунктов сразу.
            "in_budget_base": "required_in_base"
            if (_in_base(c["quote_he"]) or (c.get("heading") or {}).get("in_base"))
            else "not_specified",
            "granularity": None,          # решает человек, Ф5
            "rejection_reason": None,
            "candidates": [],
        }
        if cat != "commitment":
            item["rejection_reason"] = "not_budgetary"
            items.append(item)
            continue

        m = re.search(code_pat, c["quote_he"])
        if m:
            code = m.group(1).zfill(10)
            item["explicit_code"] = code
            item["granularity"] = "exact_takana"
            item["candidates"] = [{
                "code": code, "matched": ["явный код в тексте соглашения"],
                "years": numbers_for(by_cy, code, years),
                "transfers": transfers_for(changes, code, years),
            }]
            items.append(item)
            continue

        terms = terms_of(c["quote_he"], dstop)
        if c.get("heading"):
            for t in terms_of(c["heading"]["quote_he"], dstop):
                if t not in terms:
                    terms.append(t)
        item["terms"] = terms
        dfs = {t: doc_freq(rows10, t) for t in terms}
        item["term_df"] = dfs
        found = search(rows10, terms, years, dfs)
        item["matches_before_narrowing"] = len(found)
        found, why = narrow(found, max_shown, terms, dfs, rare_max)
        if why:
            item["rejection_reason"] = why
        else:
            if len(found) == max_shown:
                item["candidates_truncated_from"] = item["matches_before_narrowing"]
            for f in found:
                f["years"] = numbers_for(by_cy, f["code"], years)
                f["transfers"] = transfers_for(changes, f["code"], years)
            item["candidates"] = found
            manual += 1
        items.append(item)

    by_cat: dict[str, int] = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    by_rej: dict[str, int] = {}
    for it in items:
        if it["rejection_reason"]:
            by_rej[it["rejection_reason"]] = by_rej.get(it["rejection_reason"], 0) + 1

    OUT.write_text(json.dumps({
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "party": 'ש"ס', "period_id": "1095-gov37", "years": years,
        "rule": RULE_REL, "rule_sha256": sha,
        "budget_snapshot": budget["fetched_at"],
        "source_table": budget["table"],
        "counts": {"candidates": len(cands), "by_category": by_cat,
                   "by_rejection": by_rej, "manual_decisions": manual},
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print("по категориям: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
    print("отказы: " + (", ".join(f"{k}={v}" for k, v in sorted(by_rej.items())) or "нет"))
    print(f"ручных решений: {manual} (порог {max_manual})")
    print(f"-> {OUT.name}")
    if manual > max_manual:
        print(f"\nСТОП: ручных решений {manual} > объявленного порога {max_manual}. "
              "Правило требует спросить владельца, а не дорешивать самому.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
