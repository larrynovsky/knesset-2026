#!/usr/bin/env python3
"""Контракт карточки. CLAUDE.md §1, §2, §4–§8, §11–§13, §15.

Схема карточки НЕ живёт отдельным файлом. Она уже записана в своде: у каждого
эпистемического правила есть строка `*Механизм:*`, и это и есть требование к
карточке. Второй дом для одного знания породил бы расхождение, которое некому
заметить. Поэтому здесь — единственная реализация схемы, а
`docs/reference/card_schema.md` ГЕНЕРИРУЕТСЯ отсюда (`--emit-schema`), как уже
сделано с ENFORCEMENT.md.

Честная граница, названная сразу и дословно из §24: проверки ловят отсутствие
носителя, а не его качество. Структурно полная карточка с бессодержательным
поиском опровержения пройдёт всё до одной. Это не дефект реализации — это
предел механической проверки. Единственный оракул на содержание — человек,
и вопрос, который он себе задаёт, взят у Баха: выглядела бы эта карточка так
же, если бы за ней не было думания?

Вывод: 0 — карточки годны · 1 — нарушение · 2 — внутренняя ошибка (блок).
    python3 scripts/validate_cards.py
    python3 scripts/validate_cards.py --selftest
    python3 scripts/validate_cards.py --emit-schema
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "cards"
PERIODS = ROOT / "criteria" / "periods.yaml"
TAKANOT = ROOT / "data" / "budget_takanot.json"
SCHEMA_DOC = ROOT / "docs" / "reference" / "card_schema.md"

CONFIDENCE = ("high", "medium", "low", "none")
READING_TYPES = ("weakening", "strengthening", "reframing")
GRANULARITY = ("exact_takana", "subset_of_line", "spread_over_lines",
               "not_found", "not_budgetary")
STATUS = ("has_record", "no_record")
CARD_TYPES = ("party", "figure")

# §13: ярлыки, которые превращают раскрытие в оценку. Список ЗАВЕДОМО НЕПОЛОН
# и здесь это сказано вслух: он ловит прямые формулировки, а не намерение.
# Оценочность в общем виде машинно неотличима — как и осмысленность (§24).
VERDICT_WORDS = ("выполнен", "не выполнен", "невыполн", "провалил", "нарушил",
                 "худш", "лучш", "успешн", "обманул", "сдержал слово")

# Ссылка на число: {код:год:канал}. Ссылка на отсутствие: {absent:термин}.
REF_NUM = re.compile(r"\{(\d{10}):(\d{4}):(allocated|revised|executed|transfers)\}")
REF_ABSENT = re.compile(r"\{absent:([^}]+)\}")
# Третья форма, добавлена сразу после первой же попытки написать карточку:
# `{absent:термин}` ищет термин в НАЗВАНИЯХ статей, а утверждение «статьи с
# таким кодом не существует» — про код, а не про название. Я написал
# {absent:0022010203} и проверка молча прошла, потому что кода в названиях
# нет по построению. Форма, которая всегда истинна, ничего не доказывает.
REF_NOCODE = re.compile(r"\{nocode:(\d{10})\}")

problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


# ----------------------------------------------------------- мини-разборщики
def load_yaml_ish(path: Path) -> dict:
    """Разбор подмножества YAML без внешних зависимостей (на Studio нет pyyaml).

    Поддерживает то, что реально нужно карточке: вложенные словари по отступам,
    списки словарей через `- `, скаляры, блочные строки `>-` и `|`.
    Не универсальный парсер — и не претендует: неизвестная конструкция должна
    ронять разбор, а не молча пропускаться.
    """
    import ast

    def parse(lines: list[tuple[int, str]], i: int, indent: int):
        out: dict | list = {}
        while i < len(lines):
            ind, s = lines[i]
            if ind < indent:
                break
            if s.startswith("- "):
                if not isinstance(out, list):
                    if out:
                        break
                    out = []
                item, i = parse_item(lines, i, ind)
                out.append(item)
                continue
            if not isinstance(out, dict):
                break
            key, _, rest = s.partition(":")
            key, rest = key.strip(), rest.strip()
            if rest in (">-", ">", "|", "|-"):
                buf, i = [], i + 1
                while i < len(lines) and lines[i][0] > ind:
                    buf.append(lines[i][1])
                    i += 1
                out[key] = " ".join(buf).strip()
                continue
            if rest == "":
                sub, i = parse(lines, i + 1, ind + 1)
                out[key] = sub
                continue
            out[key] = scalar(rest)
            i += 1
        return out, i

    def parse_item(lines, i, ind):
        ind0, s = lines[i]
        body = s[2:]
        sub_lines = [(ind0 + 2, body)] if body else []
        i += 1
        while i < len(lines) and (lines[i][0] > ind0
                                  or (lines[i][0] == ind0 and not lines[i][1].startswith("- "))):
            if lines[i][0] <= ind0:
                break
            sub_lines.append(lines[i])
            i += 1
        if not sub_lines:
            return None, i
        if ":" not in sub_lines[0][1]:
            return scalar(sub_lines[0][1]), i
        val, _ = parse(sub_lines, 0, sub_lines[0][0])
        return val, i

    def scalar(s: str):
        s = s.strip()
        if s in ("null", "~", ""):
            return None
        if s in ("true", "false"):
            return s == "true"
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        if s.startswith("[") and s.endswith("]"):
            try:
                return ast.literal_eval(s)
            except Exception:  # noqa: BLE001
                return [x.strip().strip("'\"") for x in s[1:-1].split(",") if x.strip()]
        return s.strip("'\"")

    raw = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        raw.append((len(ln) - len(ln.lstrip()), ln.strip()))
    data, _ = parse(raw, 0, 0)
    return data


def known_periods() -> set[str]:
    if not PERIODS.exists():
        return set()
    return set(re.findall(r"^\s*-\s*id:\s*(\S+)", PERIODS.read_text(encoding="utf-8"),
                          flags=re.M))


def budget_index() -> tuple[dict, list[str]]:
    """(код,год) -> строка, и все названия статей — для проверки ссылок."""
    if not TAKANOT.exists():
        return {}, []
    rows = json.loads(TAKANOT.read_text(encoding="utf-8"))["rows"]
    idx = {(r["code"], r["year"]): r for r in rows}
    titles = [r["title"] or "" for r in rows if len(r["code"]) == 10]
    return idx, titles


# --------------------------------------------------------------- 14 проверок
def check_card(card: dict, name: str, periods: set[str], idx: dict,
               titles: list[str]) -> None:
    def bad(rule: str, msg: str) -> None:
        fail(f"{name}: {rule} — {msg}")

    # §1 — период из справочника
    pid = card.get("period_id")
    if not pid:
        bad("§1", "нет period_id")
    elif periods and pid not in periods:
        bad("§1", f"period_id {pid!r} отсутствует в criteria/periods.yaml")

    # §2 — тип карточки объявлен, типы не смешиваются
    if card.get("card_type") not in CARD_TYPES:
        bad("§2", f"card_type обязан быть из {CARD_TYPES}")

    # §7 — ноль периодов правления ⇒ только no_record
    n = card.get("periods_in_government")
    if n == 0 and card.get("status") != "no_record":
        bad("§7", "periods_in_government == 0, но статус не no_record")

    # §11 — снимки покрывают источники
    snaps = card.get("snapshots") or {}
    if not snaps:
        bad("§11", "нет snapshots — дата снимка каждого источника обязательна")

    # §15 — журнал правок растёт вместе с версией
    revs = card.get("revisions") or []
    ver = card.get("card_version") or 0
    if len(revs) < ver:
        bad("§15", f"версия {ver}, а записей в журнале {len(revs)} — "
                   "изменение вывода обязано быть видимым")

    # §8 — holdout пуст ⇒ уверенность не может быть high (на уровне карточки)
    hold = card.get("holdout_checked") or {}
    holdout_empty = not hold.get("period")

    for c in card.get("commitments") or []:
        cid = c.get("id") or "?"
        p = f"{name}[{cid}]"

        # §12 — оба языка цитаты
        if not (c.get("quote_he") or "").strip():
            fail(f"{p}: §12 — quote_he пуст")
        if not (c.get("quote_ru") or "").strip():
            fail(f"{p}: §12 — quote_ru пуст")

        # гранулярность из закрытого списка (criteria/budget_mapping.yaml)
        g = c.get("granularity")
        if g not in GRANULARITY:
            fail(f"{p}: гранулярность {g!r} вне закрытого списка")

        # §11 — план и факт одного года
        if c.get("plan_year") != c.get("fact_year"):
            fail(f"{p}: §11 — plan_year {c.get('plan_year')} != "
                 f"fact_year {c.get('fact_year')}")

        # §4 — отчёт о поиске опровержения, с НАЗВАННОЙ областью поиска
        cs = c.get("counter_search") or {}
        where = cs.get("searched_where")
        if not where:
            fail(f"{p}: §4 — counter_search.searched_where пуст. "
                 "«Искал, не нашёл» без области поиска не отчёт")
        if cs.get("outcome") not in ("found", "nothing", "contradictory"):
            fail(f"{p}: §4 — outcome обязан быть found | nothing | contradictory")

        # §5 — минимум два прочтения, и не все ослабляющие
        readings = c.get("readings") or []
        if len(readings) < 2:
            fail(f"{p}: §5 — прочтений {len(readings)}, требуется минимум два")
        else:
            kinds = [r.get("type") for r in readings]
            if any(k not in READING_TYPES for k in kinds):
                fail(f"{p}: §5 — тип прочтения вне {READING_TYPES}")
            elif all(k == "weakening" for k in kinds):
                fail(f"{p}: §5 — все прочтения ослабляющие. Систематический крен "
                     "в скепсис — такое же искажение, как некритичность")

        # §6 — уверенность с названной причиной
        conf = c.get("confidence")
        if conf not in CONFIDENCE:
            fail(f"{p}: §6 — confidence {conf!r} вне {CONFIDENCE}")
        if not (c.get("confidence_reason") or "").strip():
            fail(f"{p}: §6 — оговорка без причины это украшение")

        # §8 — holdout не проверялся ⇒ high запрещён
        if holdout_empty and conf == "high":
            fail(f"{p}: §8 — holdout не проверялся, high недопустим")

        # чем опровергается — поле, отсутствие которого само есть нарушение
        if not (c.get("what_would_falsify") or "").strip():
            fail(f"{p}: нет what_would_falsify. Утверждение, которое нечем "
                 "опровергнуть, читатель проверить не может")

        # §13 — вывод описательный, а не оценочный
        concl = c.get("conclusion") or ""
        if not concl.strip():
            fail(f"{p}: §13 — пустой conclusion")
            continue
        low = concl.lower()
        for w in VERDICT_WORDS:
            if w in low:
                fail(f"{p}: §13 — оценочный ярлык {w!r} в выводе. Карточка "
                     "сообщает, что произошло с деньгами; вывод делает читатель")
                break

        # каждая фраза опирается на проверяемое: число ИЛИ отсутствие
        nums = REF_NUM.findall(concl)
        absents = REF_ABSENT.findall(concl)
        nocodes = REF_NOCODE.findall(concl)
        for c10 in nocodes:
            if idx and any(k[0] == c10 for k in idx):
                fail(f"{p}: заявлено отсутствие кода {c10}, но он есть "
                     "в выгрузке — утверждение неверно")
        if not nums and not absents and not nocodes:
            fail(f"{p}: вывод без единой ссылки {{код:год:канал}} или "
                 "{{absent:термин}} — не опирается ни на что проверяемое")
        for code, year, _chan in nums:
            if idx and (code, int(year)) not in idx:
                fail(f"{p}: ссылка на несуществующую строку {code} за {year}")
        for term in absents:
            if titles and any(term in t for t in titles):
                fail(f"{p}: заявлено отсутствие {term!r}, но оно есть "
                     "в названиях статей — утверждение неверно")

        # §14 — карточка хранит решение и ссылки, не числа
        for k in ("net_allocated", "net_revised", "net_executed", "amount_fact"):
            if k in c:
                fail(f"{p}: §14 — поле {k} кэширует число из выгрузки. "
                     "Карточка хранит решение и ссылки; числа берутся при "
                     "рендере, иначе копия разъедется с источником")


def emit_schema() -> str:
    lines = [
        "# Схема карточки — что проверяется и каким правилом",
        "",
        "**Файл СГЕНЕРИРОВАН** `scripts/validate_cards.py --emit-schema`.",
        "Руками не править: схема живёт в валидаторе, потому что второй дом",
        "для одного знания порождает расхождение, которое некому заметить.",
        "",
        "| § | что обязано быть в карточке |",
        "|---|---|",
        "| §1 | `period_id` из `criteria/periods.yaml` |",
        "| §2 | `card_type`: party или figure |",
        "| §4 | `counter_search.searched_where` непусто + `outcome` |",
        "| §5 | минимум два `readings`, не все `weakening` |",
        "| §6 | `confidence` из перечисления + `confidence_reason` |",
        "| §7 | ноль периодов правления ⇒ `status: no_record` |",
        "| §8 | пустой `holdout_checked` ⇒ `confidence` не `high` |",
        "| §11 | `snapshots` непусто; `plan_year == fact_year` |",
        "| §12 | `quote_he` и `quote_ru` оба непусты |",
        "| §13 | `conclusion` без оценочных ярлыков |",
        "| §14 | числа из выгрузки НЕ кэшируются в карточке |",
        "| §15 | записей в `revisions` не меньше, чем `card_version` |",
        "| — | `granularity` из закрытого списка |",
        "| — | `what_would_falsify` непусто |",
        "| — | каждая ссылка `{код:год:канал}` резолвится в выгрузке |",
        "| — | каждое `{absent:термин}` проверено по названиям статей |",
        "| §11 | `data_fingerprint` — свёртка прочитанных карточкой ячеек |",
        "",
        "Последняя строка проверяется НЕ здесь, а `scripts/build_report.py`,",
        "и это не оплошность: валидатор гоняется на MacBook, где `data/`",
        "заигнорен и выгрузки нет, — сверять отпечаток ему не с чем. Проверка",
        "живёт там, где может исполниться. Из того же следует граница,",
        "которую надо знать: на MacBook валидатор НЕ проверяет ссылки на",
        "числа вовсе и говорит об этом в stderr. Зелёный прогон на MacBook",
        "означает меньше, чем зелёный прогон на Studio.",
        "",
        "Честная граница (§24 дословно): всё перечисленное ловит отсутствие",
        "носителя, а не его качество. Структурно полная карточка с",
        "бессодержательным поиском опровержения пройдёт все проверки.",
    ]
    return "\n".join(lines) + "\n"


def selftest() -> int:
    """Каждая из проверок обязана краснеть на своём нарушении."""
    base = {
        "card_version": 1, "period_id": "1095-gov37", "card_type": "party",
        "periods_in_government": 1, "status": "has_record",
        "snapshots": {"raw_budget": "2026-07-30"},
        "holdout_checked": {"period": "gov36"},
        "revisions": [{"version": 1}],
        "commitments": [{
            "id": "t1", "quote_he": "טקסט", "quote_ru": "текст",
            "granularity": "exact_takana", "plan_year": 2023, "fact_year": 2023,
            "counter_search": {"searched_where": ["raw_budget 2026-07-30"],
                               "outcome": "nothing"},
            "readings": [{"type": "weakening"}, {"type": "strengthening"}],
            "confidence": "medium", "confidence_reason": "неполнота периода",
            "what_would_falsify": "если статья возобновлена под другим кодом",
            "conclusion": "в базе {0022010213:2023:allocated} ноль",
        }],
    }
    idx = {("0022010213", 2023): {}}
    titles = ["הקמת מוסדות דת שוטף"]
    P = {"1095-gov37"}

    def run(mut) -> int:
        problems.clear()
        import copy
        c = copy.deepcopy(base)
        mut(c)
        check_card(c, "t", P, idx, titles)
        return len(problems)

    assert run(lambda c: None) == 0, f"чистая карточка не должна падать: {problems}"

    cases = [
        ("§1", lambda c: c.update(period_id="нетакого")),
        ("§2", lambda c: c.update(card_type="что-то")),
        ("§7", lambda c: c.update(periods_in_government=0)),
        ("§11 snapshots", lambda c: c.update(snapshots={})),
        ("§15", lambda c: c.update(card_version=3)),
        ("§12 he", lambda c: c["commitments"][0].update(quote_he="")),
        ("§12 ru", lambda c: c["commitments"][0].update(quote_ru="")),
        ("гранулярность", lambda c: c["commitments"][0].update(granularity="x")),
        ("§11 годы", lambda c: c["commitments"][0].update(fact_year=2024)),
        ("§4 область", lambda c: c["commitments"][0]["counter_search"].update(
            searched_where=[])),
        ("§4 исход", lambda c: c["commitments"][0]["counter_search"].update(
            outcome="может быть")),
        ("§5 мало", lambda c: c["commitments"][0].update(readings=[{"type": "weakening"}])),
        ("§5 все ослабляющие", lambda c: c["commitments"][0].update(
            readings=[{"type": "weakening"}, {"type": "weakening"}])),
        ("§6 шкала", lambda c: c["commitments"][0].update(confidence="уверен")),
        ("§6 причина", lambda c: c["commitments"][0].update(confidence_reason="")),
        ("§8 high", lambda c: (c.update(holdout_checked={}),
                               c["commitments"][0].update(confidence="high"))),
        ("опровержение", lambda c: c["commitments"][0].update(what_would_falsify="")),
        ("§13 ярлык", lambda c: c["commitments"][0].update(
            conclusion="обещание не выполнено {0022010213:2023:allocated}")),
        ("ссылка ни на что", lambda c: c["commitments"][0].update(
            conclusion="денег стало меньше")),
        ("битая ссылка", lambda c: c["commitments"][0].update(
            conclusion="ноль {9999999999:2023:allocated}")),
        ("ложное отсутствие", lambda c: c["commitments"][0].update(
            conclusion="нет такого {absent:מוסדות דת}")),
        ("ложное отсутствие кода", lambda c: c["commitments"][0].update(
            conclusion="статьи нет {nocode:0022010213}")),
        ("§14 кэш числа", lambda c: c["commitments"][0].update(net_allocated=1)),
    ]
    bad = [name for name, mut in cases if run(mut) == 0]
    if bad:
        print(f"САМОПРОВЕРКА ПРОВАЛЕНА: не покраснели {bad}", file=sys.stderr)
        return 1
    problems.clear()
    print(f"самопроверка карточки пройдена: {len(cases)} нарушений, "
          "каждое поймано своим правилом")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--emit-schema" in sys.argv:
        SCHEMA_DOC.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_DOC.write_text(emit_schema(), encoding="utf-8")
        print(f"-> {SCHEMA_DOC.relative_to(ROOT)}")
        return 0

    cards = sorted(CARDS.glob("*.yaml")) if CARDS.exists() else []
    if not cards:
        print("карточек нет — проверять нечего, но проверка НЕ отключена (§20)")
        return 0
    periods, (idx, titles) = known_periods(), budget_index()
    if not idx:
        print("ВНИМАНИЕ: нет data/budget_takanot.json — ссылки на числа "
              "не проверяются, это дыра, а не «всё хорошо»", file=sys.stderr)
    for f in cards:
        try:
            card = load_yaml_ish(f)
        except Exception as exc:  # noqa: BLE001
            fail(f"{f.name}: не разобрался — {exc}")
            continue
        check_card(card, f.name, periods, idx, titles)

    if problems:
        print(f"НАРУШЕНИЯ КОНТРАКТА КАРТОЧКИ ({len(problems)}):", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1
    print(f"карточки годны: {len(cards)}. Напоминание: проверено НАЛИЧИЕ, "
          "не содержание (§24)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # блокируем, а не пропускаем
        print(f"ОШИБКА ВАЛИДАТОРА (это блок, не warn): {exc}", file=sys.stderr)
        sys.exit(2)
