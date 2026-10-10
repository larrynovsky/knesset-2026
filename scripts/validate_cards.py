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
# §7 (ред. 01.08.2026): четыре взаимно исключающих статуса экспозиции.
# no_record удалён намеренно — он схлопывал три состояния в одно.
EXPOSURE_STATUSES = ("not_exposed", "source_missing", "lineage_unresolved")
STATUS = ("observed",) + EXPOSURE_STATUSES   # has_record переименован в observed
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
def load_yaml_ish(path: Path, *, text: str | None = None) -> dict:
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
            if ":" not in s:
                # Продолжение многострочного скаляра без `>-`. Разборщик его
                # не склеивает, а прежняя редакция молча превращала такую
                # строку в пустой ключ и ТЕРЯЛА хвост значения. Обнаружено
                # 31.07 рендером: `holdout_checked.outcome` в отчёте обрывался
                # на слове «поэтому». Ровно класс §23 — операция отчиталась
                # об успехе и вернула правдоподобный неполный результат.
                raise ValueError(
                    f"строка без ключа: {s[:60]!r}. Многострочное значение "
                    "обязано объявляться через `>-` — иначе хвост теряется")
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
            if len(sub_lines) > 1:
                raise ValueError(
                    f"элемент списка {sub_lines[0][1][:40]!r} продолжается "
                    "следующими строками — объедини значение в одну строку, "
                    "например `- первая строка вторая строка`")
            return scalar(sub_lines[0][1]), i
        val, _ = parse(sub_lines, 0, sub_lines[0][0])
        return val, i

    def scalar(s: str):
        s = s.strip()
        if s in ("null", "~", ""):
            return None
        if s in ("true", "false"):
            return s == "true"
        # Ведущие нули несущие: 0022010203 — код, а не количество.
        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", s):
            return int(s)
        if re.fullmatch(r"[+-]?(?:0|[1-9][0-9]*)\.[0-9]+", s):
            return float(s)
        if s.startswith("[") and not s.endswith("]"):
            # Тот же класс: список в потоковой форме, разорванный переносом.
            # `[553, 557,` разбирался как СТРОКА, и шесть номеров из
            # семнадцати исчезали, не оставив следа.
            raise ValueError(f"незакрытый список: {s[:60]!r}. Потоковый "
                             "список обязан умещаться в одну строку")
        if s.startswith("[") and s.endswith("]"):
            try:
                return ast.literal_eval(s)
            except Exception:  # noqa: BLE001
                return [x.strip().strip("'\"") for x in s[1:-1].split(",") if x.strip()]
        return s.strip("'\"")

    raw = []
    for ln in (path.read_text(encoding="utf-8") if text is None else text).splitlines():
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
def quote_in_ocr(quote: str, lines: list[str], line: int, pad: int = 2) -> bool:
    """quote_he обязана быть подстрокой OCR в окне line±pad после схлопывания
    пробелов. Буквы, кавычки, цифры не исправляются: исправленный OCR —
    реконструкция, не цитата. Ревью 10.10: валидатор принимал выдуманную
    цитату — восемь из двадцати двух цитат РС/ЯТ были «подправлены»."""
    q = " ".join((quote or "").split())
    lo, hi = max(0, int(line) - 1 - pad), int(line) + pad
    window = " ".join(" ".join(l.split()) for l in lines[lo:hi])
    return bool(q) and q in window


def ocr_by_period() -> dict:
    """period_id → список файлов OCR (как списки строк), по разделу agreements
    criteria/budget_mapping.yaml. Без pyyaml (на Studio его нет): пары
    `- file:` / `period_id:` читаются регулярным выражением."""
    out: dict = {}
    rule = ROOT / "criteria" / "budget_mapping.yaml"
    if not rule.exists():
        return out
    text = rule.read_text(encoding="utf-8")
    for m in re.finditer(r"^  - file: (\S+)\n(?:    (?!period_id:).*\n)*?    period_id: (\S+)",
                         text, re.M):
        f = ROOT / "data" / "agreements_ocr" / m.group(1)
        if f.exists():
            # у одного периода может быть несколько файлов (ЯТ + приложение)
            out.setdefault(m.group(2), []).append(f.read_text(encoding="utf-8").split("\n"))
    return out


def check_card(card: dict, name: str, periods: set[str], idx: dict,
               titles: list[str], ocr: dict | None = None) -> None:
    def bad(rule: str, msg: str) -> None:
        fail(f"{name}: {rule} — {msg}")

    # §1 — единица наблюдения. Поправка свода 01.08 объявила, что единица
    # РАЗЛИЧАЕТСЯ по каналам: канал Б — партия × период в правительстве,
    # канал А — фракция × действие × дата. Валидатор до 13.08 знал только
    # первую и требовал period_id у любой карточки. Следствие: карточку
    # фракции, никогда не бывшей в правительстве, построить было НЕЛЬЗЯ —
    # у неё нет периода по устройству предмета. То есть механизм запрещал
    # ровно тот случай, ради которого §7 написан.
    pid = card.get("period_id")
    unit = card.get("unit") or "party_period"
    if unit == "faction_knesset":
        if not card.get("faction_id") or not card.get("knesset"):
            bad("§1", "unit: faction_knesset требует faction_id и knesset")
        if pid:
            bad("§1", "unit: faction_knesset и period_id одновременно — "
                      "единица наблюдения обязана быть одна")
    elif not pid:
        bad("§1", "нет period_id")
    elif periods and pid not in periods:
        bad("§1", f"period_id {pid!r} отсутствует в criteria/periods.yaml")

    # §2 — тип карточки объявлен, типы не смешиваются
    if card.get("card_type") not in CARD_TYPES:
        bad("§2", f"card_type обязан быть из {CARD_TYPES}")

    # §7 — словарь статусов закрыт. Прежде константа STATUS существовала и НЕ
    # проверялась ничем: карточка со статусом "banana" проходила молча.
    if card.get("status") not in STATUS:
        bad("§7", f"status обязан быть из {STATUS}, получено {card.get('status')!r}")

    # §7 — ноль периодов правления ⇒ матрица экспозиции, а не базовая ставка.
    # Прежняя редакция требовала здесь единственный статус no_record. Он
    # схлопывал три РАЗНЫХ состояния в одно: «партия не могла быть наблюдаема»,
    # «источник не отдал данные» и «преемственность не установлена». При таком
    # схлопывании сломанная выгрузка неотличима от отсутствия полномочий, и
    # технический дефект превращается в политический вывод.
    #
    # 13.08: блок применяется ТОЛЬКО к единице «партия × период». Продолжение
    # той же ошибки, что в §1: правило написано для канала Б и навязывало
    # карточке канала А статус not_exposed на том основании, что у фракции
    # ноль периодов в правительстве, — при том что предмет такой карточки
    # ровно противоположный, 162 НАБЛЮДЁННЫХ голосования. Экспозиция
    # различается по каналам и живёт в матрице покрытия, а не в карточке.
    n = card.get("periods_in_government")
    if unit == "faction_knesset" and n is not None:
        bad("§7", "periods_in_government в карточке канала А: поле чужого "
                  "канала, экспозиция по каналам живёт в матрице покрытия")
    if unit == "party_period" and n == 0:
        st = card.get("status")
        if st == "no_record":
            bad("§7", "no_record запрещён: схлопывает not_exposed / "
                      "source_missing / lineage_unresolved в одно состояние")
        elif st not in EXPOSURE_STATUSES:
            bad("§7", f"periods_in_government == 0 ⇒ статус из {EXPOSURE_STATUSES}, "
                      f"получено {st!r}")
        elif st == "not_exposed" and not card.get("exposure_evidence"):
            # «Ноль периодов» обязан быть ДОКАЗАН, а не постулирован: иначе
            # not_exposed — человеческое утверждение в машинном значке.
            bad("§7", "not_exposed без exposure_evidence — ноль постулирован, "
                      "а не доказан")
    if "base_rate" in card:
        bad("§7", "base_rate в карточке партии: базовая ставка — характеристика "
                  "канала, а не партии, и живёт на странице методологии")

    # §11 — снимки покрывают источники
    snaps = card.get("snapshots") or {}
    if not snaps:
        bad("§11", "нет snapshots — дата снимка каждого источника обязательна")

    # --- КАНАЛ А. Тематическая оговорка как механизм, а не как намерение.
    #
    # Выгрузка голосований — 258 из 7562 за 25-й Кнессет, то есть 3,4%, и это
    # перепись по ОДНОЙ объявленной теме. Фраза «фракция голосовала так-то»
    # без оговорки заставляет читателя достроить остальные 96,6% самому.
    # В реестре замысла это стояло как designed_not_built с 31.07 и было
    # долгом ровно до тех пор, пока карточек канала А не существовало.
    #
    # Оговорка требуется НЕ на карточке, а В САМОМ УТВЕРЖДЕНИИ. Причина
    # прикладная: утверждения путешествуют отдельно от документов — их
    # цитируют абзацем, показывают скриншотом, пересказывают. Оговорка,
    # оставшаяся в шапке карточки, до этих мест не доезжает.
    # ── Решение по оси: закрытые списки, иначе клетка покажет что угодно ──
    ax = card.get("axis_institutions")
    if ax:
        ARROWS = ("up", "down", "both", "none", "miss")
        GRADES = ("high", "moderate", "low", "very_low")
        if ax.get("arrow") not in ARROWS:
            bad("§13", f"axis_institutions.arrow: {ax.get('arrow')!r} вне "
                       f"закрытого списка {ARROWS} — принятый макет других "
                       f"значений в клетке не несёт")
        if ax.get("level") not in GRADES:
            bad("§6", f"axis_institutions.level: {ax.get('level')!r} вне "
                      f"{GRADES} — уровень определённости объявлен четырьмя")
        if ax.get("arrow") in ("up", "down", "both") \
                and not (ax.get("text") or "").strip():
            bad("§6", "стрелка есть, а формулировки при ней нет: читатель "
                      "увидит знак без того, на чём он стоит")
        if not card.get("votes"):
            bad("§А", "решение по оси без блока votes: стрелка стоит на "
                      "голосованиях, которых карточка не предъявляет")
        if card.get("status") == "lineage_unresolved":
            bad("§7", "стрелка у строки без установленной связи с фракцией — "
                      "наследование чужих голосований запрещено")

    votes = card.get("votes")
    if votes:
        theme = (votes.get("theme") or "").strip()
        cav = (votes.get("theme_caveat_ru") or "").strip()
        if not theme:
            bad("§А", "votes без theme — тема переписи обязана быть названа")
        if not cav:
            bad("§А", "votes без theme_caveat_ru — утверждение о голосованиях "
                      "без оговорки о теме достраивается читателем")
        # §14 — карточка держит РЕШЕНИЕ и ССЫЛКУ, а не данные. Полторы сотни
        # голосований, вписанных в карточку, разошлись бы с выгрузкой молча,
        # как разошлись бы кэшированные бюджетные числа. Поэтому законны две
        # формы: ссылка на выгрузку (для настоящих карточек) либо inline-items
        # (для случаев, где данные не из выгрузки). Ни одной из двух — отказ.
        if not votes.get("items"):
            if not (votes.get("source") and votes.get("faction_id")):
                bad("§14", "votes без items обязан нести source и faction_id: "
                           "иначе карточка утверждает о голосованиях, не "
                           "указывая, где их проверить")
        for i, v in enumerate(votes.get("items") or []):
            where = f"votes.items[{i}]"
            if not (v.get("for_option_desc") or "").strip():
                bad("§10", f"{where}: нет for_option_desc — смысл «за» "
                           "предполагается, а не читается")
            if not (v.get("name_he") or "").strip():
                bad("§12", f"{where}: нет name_he")
            if not (v.get("name_ru") or "").strip():
                bad("§12", f"{where}: нет name_ru")
        # §4 §5 §6 НА УРОВНЕ КАРТОЧКИ. Дыра, найденная тем, что первые две
        # карточки канала А прошли валидатор целиком: поиск опровержения,
        # два прочтения и уровень уверенности проверялись ТОЛЬКО внутри
        # блока обязательств, которого у карточки голосований нет. То есть
        # три несущих правила свода не сторожили её вовсе, а зелёный отчёт
        # выглядел ровно так же, как у охраняемой карточки. Это и есть тот
        # «структурно полный, но пустой по существу» артефакт, о котором
        # §24 говорит как о честной границе, — только здесь дело хуже:
        # граница была не названа, а не замечена.
        rd = card.get("readings") or []
        if len(rd) < 2:
            bad("§5", "меньше двух прочтений в карточке канала А")
        elif all(x.get("type") == "weakening" for x in rd):
            bad("§5", "все прочтения ослабляющие: равномерный скепсис — такое "
                      "же искажение, как некритичность")
        for x in rd:
            if x.get("type") not in READING_TYPES:
                bad("§5", f"тип прочтения {x.get('type')!r} вне {READING_TYPES}")
        cs = card.get("counter_search") or {}
        if not cs.get("searched_where"):
            bad("§4", "нет области поиска опровержения: «искал, не нашёл» без "
                      "названной области — не отчёт")
        if cs.get("outcome") not in ("found", "nothing", "contradictory"):
            bad("§4", "outcome обязан быть found | nothing | contradictory")
        if card.get("confidence") not in CONFIDENCE:
            bad("§6", f"confidence вне {CONFIDENCE}")
        if not (card.get("confidence_reason") or "").strip():
            bad("§6", "уровень уверенности без названной причины — украшение")
        if not (card.get("what_would_falsify") or "").strip():
            bad("§4", "нет what_would_falsify")

        concl = card.get("conclusion") or ""
        if "голосов" in concl and cav and cav not in concl:
            bad("§А", "вывод опирается на голосования, но не несёт оговорку "
                      "о теме ПРИ СЕБЕ: оговорка в шапке не путешествует "
                      "вместе с процитированным абзацем")
    elif "голосов" in (card.get("conclusion") or ""):
        bad("§А", "вывод говорит о голосованиях, а блока votes нет — "
                  "утверждение не опирается на предъявленные данные")

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
        # §12 — цитата дословна: OCR в окне line±2, без исправления букв
        files = (ocr or {}).get(card.get("period_id"))
        if files and c.get("line") and not any(
                quote_in_ocr(c.get("quote_he"), lines, c["line"]) for lines in files):
            fail(f"{p}: §12 — quote_he не найдена дословно в OCR в строках "
                 f"{c['line']}±2; исправленный OCR — реконструкция, не цитата")

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
        "| §7 | ноль периодов ⇒ статус экспозиции, не `no_record`; нет `base_rate` |",
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


def load_yaml_ish_ok() -> bool:
    """Корректная карточка обязана разбираться. Отказ, введённый выше, легко
    сделать слишком широким — эта проверка держит его границу."""
    import tempfile
    f = Path(tempfile.mkdtemp()) / "c.yaml"
    f.write_text("a: 1\nb:\n  c: текст\n  d: >-\n    длинное\n    значение\n"
                 "e: [1, 2, 3]\nf:\n  - g: >-\n      много\n      строк\n",
                 encoding="utf-8")
    d = load_yaml_ish(f)
    return (d["b"]["d"] == "длинное значение" and d["e"] == [1, 2, 3]
            and d["f"][0]["g"] == "много строк")


def selftest() -> int:
    """Каждая из проверок обязана краснеть на своём нарушении."""
    base = {
        "card_version": 1, "period_id": "1095-gov37", "card_type": "party",
        "periods_in_government": 1, "status": "observed",
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

    # §12 — дословность цитаты: окно OCR line±2, пробелы схлопнуты, буквы — нет
    ocr = {"1095-gov37": [["", "א", "ב. טקסט   ארוך", "ג", "ד", "ה", "ו", "ז", "ח"]]}
    def run_ocr(mut) -> int:
        problems.clear()
        import copy
        c = copy.deepcopy(base)
        c["commitments"][0].update(quote_he="טקסט ארוך", line=3)
        mut(c)
        check_card(c, "t", P, idx, titles, ocr)
        return len(problems)
    assert run_ocr(lambda c: None) == 0, f"дословная цитата со схлопнутыми пробелами отвергнута: {problems}"
    assert run_ocr(lambda c: c["commitments"][0].update(quote_he="טקסט ארוך מזויף")) == 1, \
        "вымышленная добавка к цитате прошла"
    assert run_ocr(lambda c: c["commitments"][0].update(quote_he='ב. טקסט "ארוך')) == 1, \
        "исправленная кавычка OCR прошла как цитата"
    assert run_ocr(lambda c: c["commitments"][0].update(line=8)) == 1, \
        "цитата вне окна ±2 прошла"

    # Карточка канала А: единица — фракция × Кнессет, периода нет по
    # устройству предмета. Сначала убеждаемся, что ЧИСТАЯ такая карточка
    # проходит: правило, которое не пропускает законный случай, бесполезнее
    # отсутствующего, а прежняя редакция §1 не пропускала его вовсе.
    CAV = "по вопросам правового государства"
    votes_card = {
        "card_version": 1, "card_type": "party", "unit": "faction_knesset",
        "faction_id": 1103, "knesset": 25,
        "status": "observed",
        "snapshots": {"votes_25": "2026-07-31"},
        "holdout_checked": {"period": None},
        "revisions": [{"version": 1}],
        "conclusion": f"фракция участвовала в голосованиях {CAV}",
        "readings": [{"type": "weakening"}, {"type": "reframing"}],
        "counter_search": {"searched_where": ["votes_25 целиком"],
                           "outcome": "nothing"},
        "confidence": "medium", "confidence_reason": "неполнота периода",
        "what_would_falsify": "если доля участия упадёт на второй теме",
        "votes": {"theme": "rule_of_law", "theme_caveat_ru": CAV,
                  "items": [{"for_option_desc": "להעביר לוועדה",
                             "name_he": "הצעת חוק", "name_ru": "Законопроект"}]},
    }

    def run_votes(mut) -> int:
        problems.clear()
        import copy
        c = copy.deepcopy(votes_card)
        mut(c)
        check_card(c, "v", P, idx, titles)
        return len(problems)

    assert run_votes(lambda c: None) == 0, \
        f"карточка канала А без периода обязана проходить: {problems}"
    votes_cases = [
        ("нет faction_id", lambda c: c.update(faction_id=None)),
        ("две единицы сразу", lambda c: c.update(period_id="1095-gov37")),
        ("нет темы", lambda c: c["votes"].update(theme="")),
        ("нет оговорки", lambda c: c["votes"].update(theme_caveat_ru="")),
        ("нет смысла «за» (§10)",
         lambda c: c["votes"]["items"][0].update(for_option_desc="")),
        ("нет иврита (§12)",
         lambda c: c["votes"]["items"][0].update(name_he="")),
        ("нет перевода (§12)",
         lambda c: c["votes"]["items"][0].update(name_ru="")),
        ("оговорка не при утверждении",
         lambda c: c.update(conclusion="фракция голосовала против")),
        ("вывод о голосованиях без данных",
         lambda c: (c.pop("votes"), c.update(conclusion="голосовала против"))),
        ("ни items, ни ссылки на выгрузку (§14)",
         lambda c: c["votes"].pop("items")),
        ("поле чужого канала в карточке канала А",
         lambda c: c.update(periods_in_government=0)),
        ("одно прочтение (§5)", lambda c: c.update(readings=[{"type": "reframing"}])),
        ("все прочтения ослабляющие (§5)",
         lambda c: c.update(readings=[{"type": "weakening"}] * 2)),
        ("нет области поиска опровержения (§4)",
         lambda c: c["counter_search"].update(searched_where=[])),
        ("исход поиска вне перечисления (§4)",
         lambda c: c["counter_search"].update(outcome="вроде норм")),
        ("уверенность вне шкалы (§6)", lambda c: c.update(confidence="уверен")),
        ("уверенность без причины (§6)",
         lambda c: c.update(confidence_reason="")),
        ("нечем опровергнуть", lambda c: c.update(what_would_falsify="")),
        # Решение по оси: пять значений клетки и четыре уровня — закрытые
        # списки. Шестое значение нарисовалось бы в макете чем угодно.
        ("стрелка вне пяти значений",
         lambda c: c.update(axis_institutions={
             "arrow": "сильно вниз", "level": "moderate", "text": "т"})),
        ("уровень вне четырёх",
         lambda c: c.update(axis_institutions={
             "arrow": "down", "level": "очень высокая", "text": "т"})),
        ("стрелка без формулировки",
         lambda c: c.update(axis_institutions={
             "arrow": "down", "level": "moderate", "text": "  "})),
        ("стрелка у строки без связи с фракцией",
         lambda c: (c.update(status="lineage_unresolved"),
                    c.update(axis_institutions={
                        "arrow": "down", "level": "moderate", "text": "т"}))),
    ]
    # Число провокаций закреплено. Провокация, удалённая молча, — это снятая
    # защита, и снятие видно только диффом, если счётчик стоит рядом. Ровно
    # так уже врал счётчик утверждений в classify_direction: считал строки,
    # а не разбор.
    assert len(votes_cases) == 22, \
        f"подлогов канала А стало {len(votes_cases)}, а было 22: провокация " \
        "не удаляется без правки этого числа"
    for why, mut in votes_cases:
        assert run_votes(mut) > 0, f"канал А: подлог «{why}» прошёл незамеченным"

    cases = [
        ("§1", lambda c: c.update(period_id="нетакого")),
        ("§2", lambda c: c.update(card_type="что-то")),
        ("§7", lambda c: c.update(periods_in_government=0)),
        # три отдельных подлога: схлопывание, недоказанный ноль, базовая ставка
        ("§7", lambda c: c.update(periods_in_government=0, status="no_record")),
        ("§7", lambda c: c.update(periods_in_government=0, status="not_exposed",
                                  exposure_evidence=None)),
        ("§7", lambda c: c.update(base_rate=0.27)),
        ("§7", lambda c: c.update(status="banana")),
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
    # §7 — ПОЛОЖИТЕЛЬНАЯ сторона. Подлоги выше проверяют, что негодное
    # отвергается; без этого блока не проверено, что годное проходит, — а
    # правило, отвергающее в том числе законные карточки, останавливает работу
    # так же надёжно, как пропускающее незаконные.
    def _sev(**over) -> list:
        """Нарушения §7 у карточки с подменёнными полями."""
        run(lambda c: c.update(over))
        return [p for p in problems if "§7" in p]

    assert not _sev(periods_in_government=0, status="not_exposed",
                    exposure_evidence={"governments": [36, 37], "portfolios": 0}), \
        f"законная карточка экспозиции отвергнута: {problems}"
    for st in ("source_missing", "lineage_unresolved"):
        assert not _sev(periods_in_government=0, status=st), \
            f"статус {st} обязан быть законным при нуле периодов: {problems}"
    assert _sev(periods_in_government=0, status="observed"), \
        "observed при нуле периодов обязан отвергаться: наблюдать было нечего"
    assert _sev(base_rate=0.0), \
        "base_rate=0.0 обязан отвергаться так же, как ненулевая: проверяется " \
        "наличие поля, а не его истинность"

    # Разборщик обязан ОТКАЗЫВАТЬ на том, чего не умеет, а не усекать молча.
    import tempfile
    parser_cases = [
        ("многострочный скаляр без >-", "a: начало\n  продолжение\n"),
        ("разорванный потоковый список", "a: [1, 2,\n   3]\n"),
        ("элемент списка с продолжением", "a:\n  - раз\n    два\n"),
        ("блочный скаляр элемента списка", "a:\n  - >-\n    первая строка\n    вторая строка\n"),
    ]
    for pname, text in parser_cases:
        f = Path(tempfile.mkdtemp()) / "c.yaml"
        f.write_text(text, encoding="utf-8")
        try:
            load_yaml_ish(f)
            print(f"САМОПРОВЕРКА ПРОВАЛЕНА: разборщик проглотил {pname!r}",
                  file=sys.stderr)
            return 1
        except ValueError as exc:
            if pname == "блочный скаляр элемента списка":
                advice = re.findall(r"`([^`]+)`", str(exc))
                assert len(advice) == 1, "нет однозначного примера в подсказке"
                f.write_text("a:\n  " + advice[0] + "\n", encoding="utf-8")
                assert load_yaml_ish(f) == {"a": ["первая строка вторая строка"]}, \
                    "подсказка разборщика не сохраняет полный элемент списка"
    # Положительные числа и похожие на них строки: проверяем и тип, и значение.
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "scalar.yaml"
        for raw, expected in [
            ("0.800", 0.8), ("-12.50", -12.5), ("+0.25", 0.25),
            ("0.0", 0.0), ("2026-10-07", "2026-10-07"),
            ("1.2.3", "1.2.3"), ("25", 25), ("0", 0), ("-25", -25),
            ("0022010203", "0022010203"), ("00.800", "00.800"),
            ("-01.2", "-01.2"), ("+01.2", "+01.2"),
            ('"0.800"', "0.800"), ("'0022010203'", "0022010203"),
        ]:
            f.write_text(f"knesset: {raw}\nitems:\n  - {raw}\n", encoding="utf-8")
            d = load_yaml_ish(f)
            for actual in (d["knesset"], d["items"][0]):
                assert type(actual) is type(expected) and actual == expected, \
                    f"скаляр {raw!r}: получено {actual!r} ({type(actual).__name__}), " \
                    f"ожидалось {expected!r} ({type(expected).__name__})"
    assert load_yaml_ish_ok(), "разборщик перестал понимать корректный YAML"

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
    ocr = ocr_by_period()
    if not ocr:
        print("ВНИМАНИЕ: нет data/agreements_ocr — дословность цитат "
              "не проверяется, это дыра, а не «всё хорошо»", file=sys.stderr)
    if not idx:
        print("ВНИМАНИЕ: нет data/budget_takanot.json — ссылки на числа "
              "не проверяются, это дыра, а не «всё хорошо»", file=sys.stderr)
    for f in cards:
        try:
            card = load_yaml_ish(f)
        except Exception as exc:  # noqa: BLE001
            fail(f"{f.name}: не разобрался — {exc}")
            continue
        check_card(card, f.name, periods, idx, titles, ocr)

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
