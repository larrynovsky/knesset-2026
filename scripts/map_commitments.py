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
    ssh larry@studio 'cd ~/knesset && python3 -u scripts/map_commitments.py --agreement CA37-Shas.txt'
Самопроверка (без сети; нужны OCR и текущие commitment_map_*.json):
    python3 scripts/map_commitments.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from validate_cards import load_yaml_ish

ROOT = Path(__file__).resolve().parent.parent
RULE = ROOT / "criteria" / "budget_mapping.yaml"
RULE_REL = "criteria/budget_mapping.yaml"
TAKANOT = ROOT / "data" / "budget_takanot.json"
CHANGES = ROOT / "data" / "budget_changes.json"
PERIODS = ROOT / "criteria" / "periods.yaml"

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


def slug(agreement: dict) -> str:
    return Path(agreement["file"]).stem.removeprefix("CA37-").lower()


def ca36_entries() -> list[dict]:
    declared = json.loads((ROOT / "criteria/agreements_ca36.json").read_text())
    if declared["budget_years"] != [2021, 2022] or declared["government"] != 36:
        raise SystemExit("§11: CA36 must use 2021–2022")
    return [dict(a, budget_years=declared["budget_years"],
                 candidate_lines_expected=declared["candidate_lines_expected"],
                 reason_if_unchecked=declared["reason_if_unchecked"])
            for a in declared["agreements"] if a["file"] != "CA36-KaveiYesod.txt"]


def validate_agreement(a: dict) -> None:
    if isinstance(a, dict) and a.get("file", "").startswith("CA36-"):
        if a not in ca36_entries():
            raise SystemExit("§1/§11: CA36 declaration mismatch")
        return
    required = ("file", "period_id", "faction_id", "party_he", "budget_years",
                "candidate_lines_expected")
    if not isinstance(a, dict) or any(k not in a for k in required):
        raise SystemExit(f"ОТКАЗ: agreements требует поля {', '.join(required)} (§23)")
    if not isinstance(a["file"], str) or not re.fullmatch(r"CA37-[A-Za-z0-9-]+\.txt", a["file"]):
        raise SystemExit("ОТКАЗ: file должен быть именем CA37-<slug>.txt")
    if not isinstance(a["party_he"], str) or not a["party_he"].strip():
        raise SystemExit("ОТКАЗ: party_he пуст")
    expected = a["candidate_lines_expected"]
    if type(expected) is not int or expected < 0:
        raise SystemExit("§23 ОТКАЗ: candidate_lines_expected должен быть целым >= 0")
    periods = load_yaml_ish(PERIODS)["periods"]
    period = next((p for p in periods if p["id"] == a["period_id"]), None)
    if period is None:
        raise SystemExit(f"§1 ОТКАЗ: period_id {a['period_id']} отсутствует в criteria/periods.yaml")
    if a["faction_id"] != period["faction_id"]:
        raise SystemExit("§1 ОТКАЗ: faction_id не соответствует периоду")
    start = dt.date.fromisoformat(period["start"]).year
    finish = dt.date.fromisoformat(period["finish"]).year if period["finish"] else dt.date.today().year
    years = a["budget_years"]
    if (not isinstance(years, list) or not years or
            any(type(y) is not int or not start <= y <= finish for y in years) or
            len(set(years)) != len(years)):
        raise SystemExit(f"§11 ОТКАЗ: budget_years {years} вне периода {start}–{finish} или повторены")


def agreement_entries(text: str) -> list[dict]:
    # Общие поля правила содержат YAML вне подмножества карточного парсера.
    # Повторно используем его только для структурированного списка agreements.
    block = re.search(r"^agreements:[^\n]*\n(?:(?:[ \t]+[^\n]*|#[^\n]*|)\n?)*", text, re.M)
    if not block:
        raise SystemExit("§3 ОТКАЗ: в правиле нет списка agreements; требуется criteria-revision")
    entries = load_yaml_ish(RULE, text=block.group())["agreements"]
    if not isinstance(entries, list) or not entries:
        raise SystemExit("ОТКАЗ: agreements должен быть непустым списком")
    for a in entries:
        validate_agreement(a)
    if len({slug(a) for a in entries}) != len(entries):
        raise SystemExit("ОТКАЗ: повтор имени выхода в agreements")
    return entries


def cli_args():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--agreement", help="имя файла из agreements в правиле")
    group.add_argument("--ca36", action="store_true", help="government 36, declared by user v28")
    group.add_argument("--all", action="store_true", help="все объявленные соглашения")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not (args.selftest or args.agreement or args.all or args.ca36):
        parser.error("укажите --agreement FILE или --all")
    return args


def select_agreements(text: str, args) -> list[dict]:
    entries = agreement_entries(text)
    selected = [a for a in entries if args.all or a["file"] == args.agreement]
    if not selected:
        raise SystemExit(f"§3 ОТКАЗ: {args.agreement} не объявлено в agreements")
    return selected


def require_quotes(items: list[dict]) -> None:
    for item in items:
        if not isinstance(item.get("quote_he"), str) or not item["quote_he"].strip():
            raise SystemExit(f"§12 ОТКАЗ: quote_he отсутствует, строка {item.get('line')}")


def validate_mapping(d: dict, a: dict, sha: str) -> None:
    validate_agreement(a)
    require_quotes(d["items"])
    if d["period_id"] != a["period_id"] or d["years"] != a["budget_years"] or d["party"] != a["party_he"]:
        raise SystemExit("ОТКАЗ: период, годы или партия карты расходятся с agreements")
    if d["rule_sha256"] != sha:
        raise SystemExit("§3 ОТКАЗ: rule_sha256 карты расходится с текущим правилом")
    actual, expected = len(d["items"]), a["candidate_lines_expected"]
    if (expected is not None and actual != expected) or d["counts"]["candidates"] != actual:
        raise SystemExit(f"§23 ОТКАЗ: кандидатов {actual}, правило объявляет {expected}, counts={d['counts']['candidates']}")


# ------------------------------------------------------------- извлечение
ITEM_RE = re.compile(r"^([א-ת]\.|\d+\.|\+)\s")
HEADING_MARK = ("בסכומים הבאים",)
BASE_MARK = ("בבסיס התקציב", "לבסיס התקציב")


def _in_base(s: str) -> bool:
    return any(m in s for m in BASE_MARK)


# CA36-only revision: explicit funding/approval, never generic support for a budget.
CA36_ACTION = re.compile(r"(?<![א-ת])(?:ו)?(?:לתקצב|תקצוב|תאשר|תאמצ|לאישור תכנית)(?![א-ת])")
CA36_FUNDING = re.compile(r"לתקצב|תקצוב|יתוקצב|תתוקצב|להפנות תקציב|יוקצ[וה] תקציב")
CA36_BUDGET = re.compile(r"תקציב|תקצוב|לתקצב|יתוקצב|תתוקצב")


def candidates(lines: list[str], units: list[str], ca36: bool = False) -> list[dict]:
    """Строки с числом и денежной единицей, с якорем страницы и заголовком.

    Заголовок перечня сумм не содержит и потому сам кандидатом не является —
    но именно он несёт предмет («религиозные здания») и признак «в базе
    бюджета». Первая редакция его не видела, и семь обязательств теряли и то
    и другое: они находились по слову «ремонт», которое стоит в сотнях статей.
    """
    # Общий объект пункта видит и глагол ПОСЛЕ строки с суммой.
    # Пустая строка сбрасывает пункт; маркер страницы не участвует.
    # Глагол ищется в тексте пункта, СКЛЕЕННОМ пробелами (v1.4, уточнение
    # 18.10): OCR рвёт «שיעמוד / על סך» по строкам, построчный поиск слеп.
    # Совпадение — по границам слова (verb_in): «ייעודיות» и «המתוקצבות» —
    # прилагательное и причастие, не глаголы выделения.
    paragraphs, paragraph, members = {}, {}, []

    def _close() -> None:
        if not members:
            return
        joined = " ".join(t for _, t in members)
        verb = verb_in(joined)
        if ca36:
            extra = CA36_ACTION.search(joined)
            verb = verb or (extra.group() if extra else None)
        if verb:
            first = next((n for n, t in members if verb.split()[0] in t), members[0][0])
            paragraph.update(verb=verb, line=first,
                             quote_he=next(t for n, t in members if n == first))

    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if re.fullmatch(r"⟦(\d+)⟧", s):
            continue
        if not s:
            _close()
            paragraph, members = {}, []
            continue
        if ca36 and re.match(r"^(?:[א-ת]\.|\d+\.|\+)\s|^\d+\s+(?:הממשלה|הצדדים|סיעת)", s):
            _close()
            paragraph, members = {}, []
        paragraphs[i] = paragraph
        members.append((i, s))
    _close()

    page, out, heading = None, [], None
    funded_paragraphs = set()
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        m = re.fullmatch(r"⟦(\d+)⟧", s)
        if m:
            page = int(m.group(1))
            continue
        if not s:
            continue
        has_money = bool(re.search(r"[0-9]", s)) and any(u in s for u in units)
        budget_only = False
        if ca36:
            has_money = amount_of(s, ca36=True) is not None and bool(HEB.search(s))
            budget_only = bool(CA36_BUDGET.search(s)) and not has_money
            # A funding verb next to a sum belongs to that sum, not a second promise.
            if budget_only and any(amount_of(t.strip(), ca36=True) is not None
                                   for n, t in enumerate(lines, 1)
                                   if paragraphs.get(n) is paragraphs[i]):
                budget_only = False
        is_item = bool(ITEM_RE.match(s))

        if not has_money and any(v in s for v in VERBS_HEADING) and (
                s.endswith(":") or s.endswith(": ") or any(h in s for h in HEADING_MARK)):
            heading = {"quote_he": s, "line": i, "in_base": _in_base(s)}
            continue
        if heading and not is_item and not has_money:
            heading = None            # перечень кончился

        if ca36 and budget_only and CA36_FUNDING.search(s):
            paragraph_id = id(paragraphs[i])
            if paragraph_id in funded_paragraphs:
                continue
            funded_paragraphs.add(paragraph_id)
        if has_money or budget_only:
            out.append({"line": i, "page": page, "quote_he": s,
                        "heading": heading if (heading and is_item) else None,
                        "paragraph_verb": paragraphs[i] or None})
    return out


VERBS_COMMIT = ("יוקצו", "יוקצה", "תתוקצב", "תתקצב", "יתקצב", "יעמוד על",
                "יתווסף", "לייעד", "ייעוד", "הקצאה", "תוקצב", "ייכנס לבסיס",
                "ייכנסו לבסיס", "יוכנס לבסיס", "תוסיף", "יתוקצב")
# v1.4 не меняет наследование предмета и базы от заголовка перечня.
VERBS_HEADING = VERBS_COMMIT
VERBS_COMMIT += ("תקצה", "יקצה", "יתוקצבו", "מתקצבים", "הקצאת", "יועבר",
                 "יועברו", "לא יפחת", "לא יפחתו", "תנתן תוספת",
                 "תינתן תוספת", "יקבל תוספת")
# При вложенных формах фиксируем полную встретившуюся форму.
VERBS_COMMIT = tuple(sorted(VERBS_COMMIT, key=len, reverse=True))
MARK_ESTIMATE = ("המשמעות התקציבית", "עלותו התקציבית", "אנו מניחים", "שלא יעלה על")
# Префиксы-клитики, после которых начинается глагол: ו, ש, וש, כש. Слово
# обязано КОНЧАТЬСЯ глаголом: суффикс превращает его в другую часть речи.
_VERB_RE = {v: re.compile(r"(?<![\w])(?:וש|כש|ו|ש)?" + re.escape(v) + r"(?![\w])")
            for v in VERBS_COMMIT}


def verb_in(text: str) -> str | None:
    """Глагол выделения в тексте по границам слова; самая длинная форма первой."""
    for v in VERBS_COMMIT:
        if _VERB_RE[v].search(text):
            return v
    return None
MARK_STATUS_QUO = ("ניתן כיום", "הנמצאים כיום", "כיום", "צפויות", "המקובלים")
MARK_UNIT_RATE = ("לחודש", "לחודש.", "ערך הנקודה", "ערך נקודה", "לתלמיד", "למיטה")


def classify(quote: str, paragraph_verb: dict | None = None) -> tuple[str, str]:
    """Категория кандидата и правило, которое сработало. Закрытый список."""
    for m in MARK_UNIT_RATE:
        if m in quote:
            return "unit_rate", f"маркер ставки: {m}"
    for m in MARK_STATUS_QUO:
        if m in quote:
            return "status_quo", f"маркер существующего положения: {m}"
    for m in MARK_ESTIMATE:
        if m in quote:
            return "estimate", f"маркер оценки: {m}"
    v = verb_in(quote)
    if v:
        return "commitment", f"глагол выделения: {v}"
    # Пункт перечня без глагола («א. שיפוץ בתי כנסת - 30 מלש"ח») наследует
    # глагол заголовка списка. Помечается отдельно, а не молча отбрасывается.
    if re.match(r"^[א-ת]\.\s|^\+\s|^\d+\.\s", quote):
        return "commitment", "пункт перечня, глагол в заголовке списка"
    if paragraph_verb:
        return "commitment", (f"глагол пункта: {paragraph_verb['verb']} "
                              f"(стр. {paragraph_verb['line']})")
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


def amount_of(quote: str, ca36: bool = False) -> float | None:
    """Сумма в шекелях, если она читается цифрами. Словесную не угадываем."""
    if ca36:
        normalized = quote.translate(str.maketrans({'״': '"', '“': '"', '”': '"', '׳': "'"}))
        normalized = re.sub(r"מלש['\"](?:י)?ח", 'מלש"ח', normalized)
        normalized = re.sub(r"מיליאר[רך]", "מיליארד", normalized)
        normalized = re.sub(r"(?<=\d)\s*[-–—־]\s*", " ", normalized)
        parsed = amount_of(normalized)
        if parsed is not None:
            return parsed
        direct = re.search(r'(?<![\w.])(\d[\d.,]*)\s*(?:₪|ש"ח|שייח|שח)(?![א-ת])', normalized)
        if direct:
            try:
                return float(direct.group(1).replace(',', ''))
            except ValueError:
                return None
        return None
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


def doc_freq(rows: list[dict], term: str, _cache: dict | None = None) -> int:
    """Кеш принадлежит одному сопоставлению, а не всем соглашениям процесса."""
    cache = {} if _cache is None else _cache
    if term not in cache:
        cache[term] = sum(1 for r in rows if term in (r["title"] or ""))
    return cache[term]


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
    # Подложенные входы. Мутанты обязаны отказать тем же путём, что CLI.
    from copy import deepcopy
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    import io
    import contextlib
    import render_mapping_review as review
    import probe_placebo as placebo

    declared = """agreements:
  - file: CA37-Shas.txt
    period_id: 1095-gov37
    faction_id: 1095
    party_he: ש"ס
    budget_years: [2023, 2024, 2025]
    candidate_lines_expected: 42
  - file: CA37-Fixture.txt
    period_id: 1105-gov37
    faction_id: 1105
    party_he: בדיקה
    budget_years: [2024]
    candidate_lines_expected: 1
"""
    rule = RULE.read_text(encoding="utf-8")
    # Не подменяем будущий production-список: тестовый блок разбирается отдельно.
    shas, other = agreement_entries(declared + "source:\n  table: raw_budget\n")
    assert slug(shas) == "shas" and slug(other) == "fixture"
    budget = {"fetched_at": "fixture", "table": "raw_budget", "rows": [
        {"code": "0012345601", "year": 2024, "title": "קהילות", "net_allocated": 11,
         "net_revised": 12, "net_executed": 9},
        {"code": "0098765401", "year": 2024, "title": "זר", "net_allocated": 1,
         "net_revised": 2, "net_executed": 0}]}
    lines = ['יוקצו 15 מיליון לקהילות']
    good = build_map(rule, "fixture-sha", other, lines, budget, [])
    validate_mapping(good, other, "fixture-sha")
    assert good["years"] == [2024] and good["period_id"] == "1105-gov37"
    assert set(good["items"][0]["candidates"][0]["years"]) == {"2024"}
    print("GREEN: второе соглашение — собственные период, годы, выход fixture")

    def refuses(name, operation, *messages):
        try:
            operation()
        except SystemExit as exc:
            message = str(exc)
            assert all(m in message for m in messages), message
            print(f"RED: {name}: {message}")
        else:
            raise AssertionError(f"мутант выжил: {name}")

    refuses("нет quote_he", lambda: require_quotes([{"category": "commitment"}]), "quote_he")
    with patch.dict(globals(), candidates=lambda *_: [{"line": 1}]):
        refuses("нет quote_he при извлечении", lambda: build_map(
            rule, "fixture-sha", other, lines, budget, []), "quote_he")
    for name, change, message in [
        ("чужой период", {"period_id": "missing-gov37"}, "criteria/periods.yaml"),
        ("год до периода", {"budget_years": [2021]}, "budget_years"),
        ("расхождение числа", {"candidate_lines_expected": 2}, "кандидатов 1, правило объявляет 2"),
    ]:
        bad = dict(other, **change)
        refuses(name, lambda: build_map(rule, "fixture-sha", bad, lines, budget, []), message)
    refuses("нет ожидания в agreements", lambda: agreement_entries(
        declared.replace("    candidate_lines_expected: 1\n", "")), "candidate_lines_expected")
    refuses("нет agreements", lambda: agreement_entries("extraction:\n  candidate_lines_expected: 42\n"), "agreements")
    refuses("повтор соглашения", lambda: agreement_entries(declared + declared.split("agreements:\n")[1]), "повтор")
    broken = deepcopy(good)
    del broken["items"][0]["quote_he"]
    refuses("рендер без оригинала", lambda: review.render(broken), "quote_he")
    refuses("карта другого правила", lambda: validate_mapping(good, other, "wrong-sha"), "rule_sha256")
    good["items"][0]["quote_ru"] = "Перевод <проверка>"
    page = review.render(good)
    assert '<td>2024</td><td>11</td><td>12</td><td>9</td>' in page
    assert "2023" not in page and "2025" not in page
    assert review.esc(lines[0]) in page and "Перевод &lt;проверка&gt;" in page
    assert page.index(review.esc(lines[0])) < page.index("Перевод &lt;проверка&gt;")
    assert 'בדיקה' in page and 'ШАС' not in page
    assert "15 000 000 ₪" in page
    print("GREEN: HTML — иврит, перевод, сумма, кандидат и только объявленный год")
    with TemporaryDirectory() as tmp:
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            assert placebo.probe(other, good, budget["rows"], Path(tmp)) == 0
        assert "настоящая 00123456" in log.getvalue()
        assert "ветка 00987654" in log.getvalue()
        print("GREEN: плацебо использует найденную ветку 00123456 и контроль 00987654")
        refuses("плацебо без контроля", lambda: placebo.probe(
            other, good, budget["rows"][:1], Path(tmp)), "контрольных веток")
        leaky = deepcopy(budget["rows"])
        leaky[1]["title"] = "קהילות"
        with contextlib.redirect_stdout(io.StringIO()):
            assert placebo.probe(other, good, leaky, Path(tmp)) == 1
        print("RED: плацебо, совпадения на чужой ветке — exit 1")
    assert doc_freq([{"title": "קהילות"}], "קהילות") == 1
    assert doc_freq([{"title": "זר"}], "קהילות") == 0
    print("GREEN: кеш частот не протекает между бюджетами")

    # Тот же CLI --all пишет разные карты и страницы.
    with TemporaryDirectory() as tmp:
        data = Path(tmp)
        (data / "agreements_ocr").mkdir()
        (data / "agreements_ocr" / shas["file"]).write_text("\n".join(lines * 42), encoding="utf-8")
        (data / "agreements_ocr" / other["file"]).write_text("\n".join(lines), encoding="utf-8")
        (data / TAKANOT.name).write_text(json.dumps(dict(budget, rows=[])), encoding="utf-8")
        (data / CHANGES.name).write_text('{"rows": []}', encoding="utf-8")
        args = argparse.Namespace(ca36=False, selftest=False, all=True, agreement=None, data_dir=data, output_dir=data)
        fixture_rule = declared + "\n" + rule
        fixture_sha = hashlib.sha256(fixture_rule.encode()).hexdigest()
        with patch.dict(globals(), cli_args=lambda: args,
                        rule_text_and_sha=lambda: (fixture_rule, fixture_sha)):
            with contextlib.redirect_stdout(io.StringIO()):
                assert main() == 0
        for entry in (shas, other):
            d = json.loads((data / f"commitment_map_{slug(entry)}.json").read_text())
            validate_mapping(d, entry, fixture_sha)
        with patch.object(review.mc, "cli_args", return_value=args), \
                patch.object(review.mc, "rule_text_and_sha", return_value=(fixture_rule, fixture_sha)):
            with contextlib.redirect_stdout(io.StringIO()):
                assert review.main() == 0
        assert (data / "mapping_review_shas.html").exists()
        assert (data / "mapping_review_fixture.html").exists()
        print("GREEN: CLI --all — два JSON и две HTML-страницы, разные имена и метаданные")

    # v1.4: тот же build_map, что в CLI, без запросов к книге бюджета.
    cases = [
        (["טקסט", "50 מיליון"], "continuation", None),
        (["א. טקסט", "50 מיליון"], "continuation", None),
        (["יוקצו", "המשמעות התקציבית 50 מיליון"], "estimate", None),
        (["יוקצו", "50 מיליון"], "commitment", "глагол пункта: יוקצו (стр. 1)"),
        (["50 מיליון", "⟦2⟧", "יוקצו"], "commitment", "глагол пункта: יוקצו (стр. 3)"),
        (["יוקצו", "  ", "50 מיליון"], "continuation", None),
        (["50 מיליון", "", "יוקצו"], "continuation", None),
        (["⟦2⟧", "50 מיליון"], "continuation", None),
    ]
    empty_budget = {"fetched_at": "fixture", "table": "raw_budget", "rows": []}
    for fixture, category, reason in cases:
        with contextlib.redirect_stdout(io.StringIO()):
            result = build_map(rule, "fixture-sha", other, fixture, empty_budget, [])
        item = result["items"][0]
        assert item["category"] == category, (fixture, item)
        if reason:
            assert item["category_rule"] == reason, item
        if category != "commitment":
            assert item["rejection_reason"] == "not_budgetary", item
    for verb in ("תקצה", "יקצה", "יתוקצבו", "מתקצבים", "הקצאת", "יועבר",
                 "יועברו", "לא יפחת", "לא יפחתו", "תנתן תוספת",
                 "תינתן תוספת", "יקבל תוספת"):
        assert classify(f"{verb} 50 מיליון") == ("commitment", f"глагол выделения: {verb}")
    for marker in MARK_ESTIMATE:
        assert classify(f"א. יוקצו {marker} 50 מיליון")[0] == "estimate"
        assert classify(f"כיום {marker} 50 מיליון")[0] == "status_quo"
        assert classify(f"לחודש כיום {marker} 50 מיליון")[0] == "unit_rate"
    assert classify("א. 50 מיליון", {"verb": "יוקצו", "line": 1})[1].startswith("пункт перечня")
    with contextlib.redirect_stdout(io.StringIO()):
        duplicates = build_map(rule, "fixture-sha", dict(other, candidate_lines_expected=2),
                               ["יוקצו", "50 מיליון", "50 מיליון"], empty_budget, [])
    assert [i["line"] for i in duplicates["items"]] == [2, 3]
    assert all(i["category"] == "commitment" for i in duplicates["items"])
    assert classify("יוקצו 50 מיליון", {"verb": "תקצה", "line": 1})[1] == "глагол выделения: יוקצו"
    # границы слова: прилагательное/причастие — не глагол; клитика — глагол
    assert verb_in("תכניות ייעודיות 50") is None
    assert verb_in("שעות הלימוד המתוקצבות 50") is None
    assert verb_in("תקציב שיעמוד על סך של 500") == "יעמוד על"
    assert verb_in("ויוקצו 50") == "יוקצו"
    with contextlib.redirect_stdout(io.StringIO()):
        split = build_map(rule, "fixture-sha", other, ["תקציב שיעמוד", "על סך של 500 מיליון"], empty_budget, [])
    assert split["items"][0]["category_rule"] == "глагол пункта: יעמוד על (стр. 1)", split["items"][0]
    print("GREEN: v1.4 — границы пунктов, маркеры страниц, оба направления, формы и приоритеты")

    ca36 = ca36_entries()[0]
    with contextlib.redirect_stdout(io.StringIO()):
        absent = build_map(rule, "fixture-sha", ca36,
                           ['⟦1⟧', 'יוקצו 50 מיליון תקנה תקציבית 22010203'], budget, [])
    assert absent["years"] == [2021, 2022]
    assert absent["budget_missing_years"] == [2021, 2022]
    assert absent["items"][0]["rejection_reason"] == "budget_years_missing"
    assert absent["items"][0]["candidates"] == []
    assert absent["items"][0]["granularity"] is None
    refuses("CA36 future budget year", lambda: validate_agreement(dict(ca36, budget_years=[2023])),
            "declaration mismatch")
    print("GREEN: CA36 missing years cannot become a match, even with explicit code")

    # v31 oracle: the user's independently supplied five amounts, actual OCR.
    raam = next(a for a in ca36_entries() if a["file"] == "CA36-Raam.txt")
    raam_lines = (ROOT / "data/agreements_ocr" / raam["file"]).read_text().splitlines()
    expected_amounts = {30e9, 2.5e9, 20e9, 1e9, 100e6}
    with contextlib.redirect_stdout(io.StringIO()):
        actual = build_map(rule, "fixture-sha", raam, raam_lines, empty_budget, [])
    assert expected_amounts <= {i["amount_ils"] for i in actual["items"]
                               if i["category"] == "commitment"}, "CA36 Raam recall"
    original_candidates = candidates
    with patch.dict(globals(), candidates=lambda lines, units, **kw: original_candidates(lines, units)):
        with contextlib.redirect_stdout(io.StringIO()):
            mutant = build_map(rule, "fixture-sha", raam, raam_lines, empty_budget, [])
    try:
        assert expected_amounts <= {i["amount_ils"] for i in mutant["items"]
                                   if i["category"] == "commitment"}, "CA36 Raam recall"
    except AssertionError:
        print("RED caught: old extraction rule loses Raam 30 billion")
    else:
        raise AssertionError("v31 recall oracle survived old-rule mutation")
    for quote, amount in [('יוקצו 100-מלש״ח', 100e6), ('יוקצו 2.5 מיליארר', 2.5e9),
                          ('יוקצו 100 שייח', 100), ('יוקצו 100 ₪', 100),
                          ('יוקצו 100 ש"ח', 100), ('יוקצו 100 מלש"ח', 100e6)]:
        with contextlib.redirect_stdout(io.StringIO()):
            result = build_map(rule, "fixture-sha", raam, [quote], empty_budget, [])
        assert result["items"][0]["amount_ils"] == amount, quote
        assert result["items"][0]["quote_he"] == quote
        assert result["items"][0]["category"] == "commitment"
    for quote, count in [('הממשלה יתוקצב', 1), ('הממשלה תפעל באמצעות תקצוב', 1),
                         ('לקדם ולתקצב תוכנית לצפון', 1), ('תקציב המדינה שיועברו', 0),
                         ('הוועדה לתקציב הבטחון', 0), ('לא יתוקצב הפרויקט', 0), ('כיום תקצוב הפרויקט', 0),
                         ('03 ₪ 39', 0), ('קרקעות בשטתי 6. הכו6 ₪', 0)]:
        with contextlib.redirect_stdout(io.StringIO()):
            result = build_map(rule, "fixture-sha", raam, [quote], empty_budget, [])
        assert sum(i["category"] == "commitment" for i in result["items"]) == count, quote
    for fixture, count in [(["1. לתקצב תוכנית לצפון", "2. לתקצב תוכנית לדרום"], 2),
                           (["1. יתוקצבו צעדים", "תקצוב החינוך"], 1),
                           (["1. להפנות תקציבים למימון תכניות"], 1)]:
        with contextlib.redirect_stdout(io.StringIO()):
            result = build_map(rule, "fixture-sha", raam, fixture, empty_budget, [])
        assert sum(i["category"] == "commitment" for i in result["items"]) == count
    for n, words in [(1, "1 денежное обещание"), (4, "4 денежных обещания"),
                     (5, "5 денежных обещаний"), (11, "11 денежных обещаний"),
                     (21, "21 денежное обещание"), (24, "24 денежных обещания"),
                     (0, "0 — правило извлечения ничего не нашло; это не значит, что обещаний нет")]:
        assert words in ca36_summary(n, "сопоставление требует проверки")
    # Exercise the actual CLI loader, not a fixture that supplies the right budget.
    with TemporaryDirectory() as tmp:
        args = argparse.Namespace(ca36=True, selftest=False, all=False, agreement=None,
                                  data_dir=ROOT / "data", output_dir=Path(tmp))
        with patch.dict(globals(), cli_args=lambda: args):
            with contextlib.redirect_stdout(io.StringIO()):
                assert main() == 0
        for a in ca36_entries():
            mapped = json.loads((Path(tmp) / f"commitment_map_{slug(a)}.json").read_text())
            assert mapped["budget_missing_years"] == [], a["file"]
            assert "budget_years_missing" not in mapped["counts"]["by_rejection"]
            for item in mapped["items"]:
                for candidate in item["candidates"]:
                    assert set(candidate["years"]) == {"2021", "2022"}
    print("GREEN: v31 actual CA36 CLI budget, five Raam amounts, OCR, negatives, Russian plurals")

    # Контрольная выборка v1.3 зашита: живые карты пересобраны под v1.4 и
    # прежней выборкой служить не могут (ревью Кодекса 18.10).
    baseline_counts = {"shas": (42, 21), "rz": (27, 13), "otzma": (10, 2),
                       "noam": (5, 3), "yt": (25, 9), "app-ay": (0, 0),
                       "unity": (0, 0), "u-right": (1, 0)}
    baseline_v13 = {
        "shas": {551, 553, 555, 557, 559, 561, 563, 573, 717, 824, 892, 912,
                 1518, 1644, 1645, 1646, 1653, 1660, 1682, 1696, 1699},
        "rz": {532, 535, 576, 603, 608, 650, 676, 737, 741, 742, 745, 799, 837},
        "otzma": {415, 420}, "noam": {78, 83, 486},
        "yt": {408, 731, 945, 949, 995, 1512, 1516, 1527, 1547},
        "app-ay": set(), "unity": set(), "u-right": set(),
    }
    assert all(len(baseline_v13[k]) == v[1] for k, v in baseline_counts.items())
    entries = agreement_entries(rule)
    assert {slug(a) for a in entries} == set(baseline_counts)
    for entry in entries:
        key = slug(entry)
        data = ROOT / "data"
        old = json.loads((data / f"commitment_map_{key}.json").read_text(encoding="utf-8"))
        source_lines = (data / "agreements_ocr" / entry["file"]).read_text(encoding="utf-8").splitlines()
        with contextlib.redirect_stdout(io.StringIO()):
            result = build_map(rule, "fixture-sha", entry, source_lines, empty_budget, [])
        expected, previous = baseline_counts[key]
        assert old["counts"]["candidates"] == result["counts"]["candidates"] == expected
        old_items = {i["line"]: i for i in old["items"]}
        new_items = {i["line"]: i for i in result["items"]}
        assert len(old_items) == len(new_items) == expected
        assert old_items.keys() == new_items.keys(), key
        preserved = baseline_v13[key]
        assert preserved <= new_items.keys(), (key, preserved - new_items.keys())
        for line, item in old_items.items():
            assert item["quote_he"] == new_items[line]["quote_he"], (key, line)
            assert item.get("heading") == new_items[line].get("heading"), (key, line)
            assert item["category"] == new_items[line]["category"], (key, line)
        lost = [l for l in preserved if new_items[l]["category"] != "commitment"]
        assert not lost, (key, lost)
        added = [i for i in result["items"] if i["category"] == "commitment"
                 and i["line"] not in preserved]
        print(f"GREEN: {entry['file']}: candidates={expected}; сохранено commitment={previous}; "
              f"новых commitment={len(added)}; строки={[i['line'] for i in added]}")
        for item in added:
            print(f"  NEW {item['line']}: {item['category_rule']}")
        for item in result["items"]:
            if item["category"] == "estimate":
                assert item["rejection_reason"] == "not_budgetary"
                print(f"  ESTIMATE {item['line']}: {item['category_rule']}")
    print("самопроверка канала Б пройдена: базовые проверки, мутанты, v1.4, 48 прежних commitment")
    return 0


def build_map(text: str, sha: str, agreement: dict, lines: list[str],
              budget: dict, changes: list[dict]) -> dict:
    """Сопоставление на явных входах; запись остаётся только в CLI."""
    validate_agreement(agreement)
    units = rule_list(text, "money_units") + rule_list(text, "damaged_units")
    expected = agreement["candidate_lines_expected"]
    max_shown = rule_int(text, "max_candidates_shown")
    max_manual = rule_int(text, "max_manual_decisions")
    rare_max = rule_int(text, "rare_term_max_articles")
    code_pat = rule_str(text, "pattern")
    years = agreement["budget_years"]
    # Стоп-слова, выведенные из объявленного в правиле, а не подобранные.
    dstop = _derived_stop(units, HEADING_MARK)

    ca36 = agreement["file"].startswith("CA36-")
    cands = candidates(lines, units, ca36=True) if ca36 else candidates(lines, units)
    # §23-exempt: unread scans have no independent monetary-line census.
    # This exemption is explicit in the pre-OCR CA36 declaration.
    if expected is None and not agreement.get("reason_if_unchecked"):
        raise SystemExit("§23: missing candidate count or exemption")
    if expected is not None and len(cands) != expected:
        sys.exit(f"§23 ОТКАЗ: кандидатов {len(cands)}, правило объявляет {expected}. "
                 "Ожидание объявлено до прогона; расхождение — повод остановиться, "
                 "а не подкрутить список единиц.")
    print(f"кандидатов: {len(cands)}; ожидание: {expected}; причина: {agreement.get('reason_if_unchecked', '—')}")

    rows = budget["rows"]
    missing_years = sorted(set(years) - {r["year"] for r in rows})
    rows10 = [r for r in rows if len(r["code"]) == 10]
    by_cy = {(r["code"], r["year"]): r for r in rows}
    print(f"бюджет: {len(rows)} строк (снимок {budget['fetched_at']}), "
          f"переносов: {len(changes)}")

    items, manual = [], 0
    df_cache = {}
    for c in cands:
        require_quotes([c])
        cat, rule_fired = classify(c["quote_he"], c.get("paragraph_verb"))
        if ca36 and amount_of(c["quote_he"], ca36=True) is None:
            funding = CA36_FUNDING.search(c["quote_he"])
            if not funding or re.search(r"לא\s+(?:יתוקצב|תתוקצב)", c["quote_he"]):
                cat, rule_fired = "continuation", "упоминание бюджета без явного выделения"
            elif funding and cat not in ("unit_rate", "status_quo", "estimate"):
                cat, rule_fired = "commitment", f"финансирование без суммы: {funding.group()}"
        item = {
            **c,
            "category": cat,
            "category_rule": rule_fired,
            "amount_ils": amount_of(c["quote_he"], ca36=ca36),
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

        if agreement["file"].startswith("CA36-") and missing_years:
            item["rejection_reason"] = "budget_years_missing"
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
        dfs = {t: doc_freq(rows10, t, df_cache) for t in terms}
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

    result = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "party": agreement["party_he"], "period_id": agreement["period_id"], "years": years,
        "rule": RULE_REL, "rule_sha256": sha,
        "budget_snapshot": budget["fetched_at"],
        "budget_missing_years": missing_years,
        "budget_status": "бюджет этих лет не выгружен" if missing_years else "сопоставление требует проверки",
        "faction_id": agreement["faction_id"],
        "agreement_file": agreement["file"],
        "candidate_count_exemption": agreement.get("reason_if_unchecked"),
        "source_table": budget["table"],
        "counts": {"candidates": len(cands), "by_category": by_cat,
                   "by_rejection": by_rej, "manual_decisions": manual},
        "items": items,
    }

    print("по категориям: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
    print("отказы: " + (", ".join(f"{k}={v}" for k, v in sorted(by_rej.items())) or "нет"))
    print(f"ручных решений: {manual} (порог {max_manual})")
    if manual > max_manual:
        print(f"\nСТОП: ручных решений {manual} > объявленного порога {max_manual}. "
              "Правило требует спросить владельца, а не дорешивать самому.",
              file=sys.stderr)
        raise SystemExit(1)
    return result



def ca36_summary(n: int, status: str) -> str:
    from build_report import plural_ru
    noun = plural_ru(n, "денежное обещание", "денежных обещания", "денежных обещаний")
    count = (f"{n} {noun}" if n else
             "0 — правило извлечения ничего не нашло; это не значит, что обещаний нет")
    return f"в соглашении 2021 года найдено {count}; {status}"


def ca36_summaries() -> dict:
    """Required CA36 inputs; missing map/OCR must stop publication (§24)."""
    from ocr_agreements import validate_corpus
    data = ROOT / "data"
    declared = json.loads((ROOT / "criteria/agreements_ca36.json").read_text())
    validate_corpus(json.loads((data / "agreements_ocr_report_ca36.json").read_text()),
                    data / "agreements_ocr",
                    {Path(a["file"]).stem: a["pages"] for a in declared["agreements"]})
    out = {}
    for a in ca36_entries():
        d = json.loads((data / f"commitment_map_{slug(a)}.json").read_text())
        validate_mapping(d, a, hashlib.sha256(RULE.read_bytes()).hexdigest())
        if d["ocr_sha256"] != hashlib.sha256((data / "agreements_ocr" / a["file"]).read_bytes()).hexdigest():
            raise SystemExit("§14: stale CA36 map")
        if d["declaration_sha256"] != hashlib.sha256((ROOT / "criteria/agreements_ca36.json").read_bytes()).hexdigest():
            raise SystemExit("§14: stale CA36 declaration")
        n = sum(i["category"] == "commitment" for i in d["items"])
        status = d["budget_status"]
        out[a["faction_id"] or slug(a)] = ca36_summary(n, status)
    return out


def main() -> int:
    args = cli_args()
    if args.selftest:
        return selftest()
    text, sha = rule_text_and_sha()
    selected = ca36_entries() if args.ca36 else select_agreements(text, args)
    if args.ca36:
        from ocr_agreements import validate_corpus
        declaration = json.loads((ROOT / "criteria/agreements_ca36.json").read_text())
        expected = {Path(a["file"]).stem: a["pages"] for a in declaration["agreements"]}
        validate_corpus(json.loads((args.data_dir / "agreements_ocr_report_ca36.json").read_text()),
                        args.data_dir / "agreements_ocr", expected)
    budget_name = "budget_takanot_2021_2022.json" if args.ca36 else TAKANOT.name
    budget = json.loads((args.data_dir / budget_name).read_text(encoding="utf-8"))
    if args.ca36 and (budget["table"] != "raw_budget" or
                      {r["year"] for r in budget["rows"]} != {2021, 2022}):
        raise SystemExit("§11: CA36 budget must be raw_budget, years 2021–2022")
    changes = json.loads((args.data_dir / CHANGES.name).read_text(encoding="utf-8"))["rows"]
    for agreement in selected:
        lines = (args.data_dir / "agreements_ocr" / agreement["file"]).read_text(
            encoding="utf-8").splitlines()
        result = build_map(text, sha, agreement, lines, budget, changes)
        if args.ca36:
            result["government_period"] = [declaration["period_start"], declaration["period_finish"]]
            result["period_basis"] = "criteria/agreements_ca36.json; full government, not truncated Knesset-25 exposure"
        result["ocr_sha256"] = hashlib.sha256((args.data_dir / "agreements_ocr" / agreement["file"]).read_bytes()).hexdigest()
        if args.ca36:
            result["declaration_sha256"] = hashlib.sha256((ROOT / "criteria/agreements_ca36.json").read_bytes()).hexdigest()
        out = (args.output_dir or args.data_dir) / f"commitment_map_{slug(agreement)}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
