#!/usr/bin/env python3
"""Обзор бюллетеня в ПРИНЯТОЙ форме (design/mockup_v5), заполненный тем, что есть.

Урок 13.08 (docs/explanation/why_design_was_invisible_2026-08-13.md): целевая
форма была принята 01.08 и две недели оставалась невидимой. Здесь она впервые
становится источником: CSS и разметка НЕ копируются в код, а читаются из
макета при сборке. Разошёлся макет — разошёлся вывод, и это видно.

ЧЕСТНЫЙ ПЕРВЫЙ ВЫПУСК. Клетка обзора несёт НАПРАВЛЕНИЕ: укрепляла, ослабляла,
и туда и обратно, искали-не-нашли, не дошли. Направления у нас почти нет:
классификация встала на 15 сильных актах из 55, и только 2 из них имеют
голосования наблюдаемых фракций. Поэтому почти все клетки честно получают
«мы сюда не дошли» — состояние, для которого макет и завёл фактуру.

Число заполненных клеток из 64 — это и есть замер. Базовая линия сегодня,
прирост меряется тем же числом.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from build_report import esc, fingerprint, render_commitment, money, Refuse
from validate_cards import budget_index

ROOT = Path(__file__).resolve().parent.parent
MOCK = ROOT / "design" / "mockup_v5" / "index.html"
MATRIX = ROOT / "data" / "coverage_matrix.json"
OUT = ROOT / "site" / "index.html"

# Закрытый список пяти значений клетки — канон D2 из приёмки 01.08.
CELL = {"up": ("↑", "укрепляла", ""), "down": ("↓", "ослабляла", ""),
        "both": ("↕", "и туда и обратно", ""),
        "none": ("", "искали, не нашли", "tx-none"),
        "miss": ("", "мы сюда не дошли", "tx-miss")}


def css_from_mockup() -> str:
    """CSS берётся из макета, а не копируется в код: один дом у формы."""
    m = re.search(r"<style>(.*?)</style>", MOCK.read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit("ОТКАЗ: в макете не найден <style> — форма не читается")
    return m.group(1)


def cell(kind: str, label: str) -> str:
    a, word, tx = CELL[kind]
    cls = "v nd " + tx if tx else "v"
    arrow = f'<span class=a>{a}</span>&#8201;' if a else ""
    return (f'<span class="{cls}">{arrow}{esc(word)}'
            f'<span class=lb> · {esc(label)}</span></span>')


FRAME = """<div class=note id=frame data-frame=full>
<p class=dim style="margin-top:0"><b>Темы выбрал автор.</b> Не данные подсказали,
о чём говорить, — человек решил. Тема здесь одна: что фракция делала с судом,
парламентом и свободами.</p>
<p class=dim><b>Оценок здесь нет.</b> Ни баллов, ни звёзд, ни «лучшая-худшая».
Партии стоят в порядке черновика преемственности. Мы рассказываем, что
произошло; вывод — ваш.</p>
<p class=dim><b>Это первый выпуск на живых данных.</b> Почти все клетки ниже
пусты, и пустота эта — про нас, а не про партии: направление голосований мы
считать пока не умеем. Что известно про каждую фракцию — на её странице.</p>
<p class=dim style="margin-bottom:0"><b>Автор — частное лицо,</b> проект никто
не финансирует и ни с кем не согласовывал. Ошибки тут авторские.</p>
</div>"""


def alpha_ok(ax: dict) -> bool:
    """Можно ли ПУБЛИКОВАТЬ эту стрелку: согласие при ней, а не при расчёте.

    Отказ по альфе стоял в direction_confidence.cell, то есть на границе
    ВЫЧИСЛЕНИЯ. Готовая карточка проходила мимо: кто её посчитал и при каком
    согласии, рендер не спрашивал. Правило объявляло «стрелка не публикуется
    вовсе», а публикация была единственным местом без проверки. Нашёл Кодекс
    в состязательном ревью 07.10, проверено своим входом.

    Карточка БЕЗ поля alpha отвергается: отсутствие числа — не разрешение.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import arrow_rule
    try:
        return float(ax.get("alpha")) >= float(arrow_rule()["tentative"])
    except (TypeError, ValueError):
        return False


def rows(m: dict, cards: dict | None = None) -> tuple[str, int, int]:
    """Строки обзора. Возвращает разметку, число клеток и число заполненных."""
    cards = cards or {}
    out, total, filled = [], 0, 0
    for r in m["lines"]:
        a, b = r["a"]["status"], r["b"]["status"]
        who = (f'<td class=who><a href="f-{r["anchor_id"]}.html">{esc(r["line"][:44])}</a>')
        if b == "not_exposed":
            who += ('<span class=norec>ни разу не была в правительстве</span>')
        who += "</td>"
        # Колонка «суд, парламент, свободы»: направление берётся из РЕШЕНИЯ
        # карточки, а не считается здесь — генератор ничего не выводит сам.
        # Строка без установленной связи с фракцией стрелки не получает НИ
        # ПРИ КАКОМ решении: там неизвестно, чья это фракция, и наследование
        # запрещено (§7, lineage_unresolved — отдельное состояние, а не
        # «мы не дошли»).
        ax = (cards.get(r["anchor_id"]) or {}).get("axis_institutions") or {}
        # Запрет наследования касается НЕ ТОЛЬКО значка. Текст решения
        # утверждает направление теми же словами, что стрелка; взятый у
        # строки без установленной связи, он обходит запрет через подпись.
        if a != "observed":
            ax = {}
        if ax.get("arrow") in ("up", "down", "both") and not alpha_ok(ax):
            ax = {}
        k1 = ax.get("arrow", "miss")
        if k1 not in CELL:
            raise SystemExit(f"ОТКАЗ: стрелка {k1!r} вне закрытого списка "
                             f"{tuple(CELL)} — макет других значений не несёт")
        lab1 = ax.get("text") or "голосования по теме правового государства"
        c1 = cell(k1, lab1)
        total += 1
        if k1 not in ("miss", "none"):
            filled += 1
        # Колонка «деньги»: здесь состояние ЕСТЬ и оно различено §7.
        k2 = {"observed": "none", "not_exposed": "none",
              "source_missing": "miss", "lineage_unresolved": "miss"}[b]
        lab = ("коалиционного соглашения не подписывала"
               if b == "not_exposed" else "обязательства против бюджета")
        c2 = cell(k2, lab)
        total += 1
        if k2 not in ("miss", "none"):
            filled += 1
        out.append(f"<tr>{who}\n<td class=c-inst "
                   f'data-l="суд, парламент, свободы">{c1}</td>\n'
                   f'<td class=c-eq data-l="деньги">{c2}</td>\n</tr>')
    return "\n".join(out), total, filled


def other_themes() -> str:
    """Блок «ещё три темы» со ссылкой на страницу осей.

    Рамка объявляет четыре темы, а таблица показывает одну — читателю это
    надо сказать на том же экране, а не оставить догадываться. Состояние
    каждой темы берётся там же, где живёт само объявление: второго дома
    рамке не положено, поэтому и состояние считает render_axes.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_axes import axis_state, counts_from_repo, load_themes
    themes = load_themes()
    counts = counts_from_repo()
    rest = [t for t in sorted(themes["themes"], key=lambda t: t["rank"])
            if t.get("role") != "РЕШАЮЩАЯ"]
    li = "".join(f'<li><b>{esc(t["title_ru"])}</b> — '
                 f'{esc(axis_state(t, counts)[1])}</li>' for t in rest)
    return (f'<h2>Ещё {len(rest)} темы</h2>'
            f'<p>Они не менее важные — просто по ним мы не вычёркиваем. '
            f'Разница ровно в этом. Если бы вычёркивали по всем '
            f'{len(rest) + 1}, промах нашёлся бы у каждого списка, и '
            f'вычеркнуть пришлось бы весь бюллетень целиком.</p>'
            f'<ul class=dim>{li}</ul>'
            f'<p><a href="axes.html">Что мы меряем и почему именно это</a> — '
            f'там про каждую тему отдельно. '
            f'<a href="time.html">Как менялась доля расхождений с залом</a> — '
            f'по полугодиям, без объяснений. '
            f'<a href="method.html">Как мы считаем</a>.</p>')


def grounds_block() -> str:
    """Ссылка на основания — только если пометки владельца существуют.
    Без них блок не рисуется: обзор не обещает того, чего нет."""
    marks = sorted((ROOT / "criteria").glob("owner_marks_*.yaml"))
    if not marks:
        return ""
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_grounds import read_marks
    m = read_marks(marks[-1])
    n_bad = sum(1 for v in m.values() if v["mark"] == "недопустимо")
    return (f'<h2 id="grounds">Основания</h2>'
            f'<p>Автор прочитал {len(m)} актов, не видя, кто как голосовал, '
            f'и пометил {n_bad} как недопустимые. '
            f'<a href="grounds.html">Кто за эти акты голосовал — по актам и '
            f'по строкам бюллетеня</a>. Документ не говорит «вычеркнуть»; '
            f'он показывает, кто проголосовал за то, что прочитано и помечено.</p>')


def build(m: dict, cards: dict | None = None) -> tuple[str, int, int]:
    body, total, filled = rows(m, cards)
    miss = total - filled
    doc = f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Что фракции делали — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<h1>Что фракции делали на самом деле</h1>
<p class=lead>27 октября в бюллетене будет около двенадцати списков. Этот
документ нужен для одного: вычеркнуть два-три из них и уметь объяснить себе
почему — не «они мне не нравятся», а «вот закон, вот дата, вот как они
проголосовали».</p>
<p>Мы смотрим на поступки, а не на заявления. Слова перед выборами стоят ноль;
голос в Кнессете записан поимённо и никуда не денется.</p>
{FRAME}
{grounds_block()}
<h2>Сначала о том, чего мы не знаем</h2>
<p>Клеток в таблице ниже — <b class=big>{total}</b>. Заполнены {filled};
в остальных {miss} мы либо не дошли, либо смотрели и вернулись пустыми.</p>
<p>Это разные вещи, и подписаны они по-разному.
<b class=tx-miss>«Не дошли»</b> значит, что мы туда не смотрели вовсе.
<b class=tx-none>«Искали, не нашли»</b> — что смотрели и вернулись пустыми.
И ни то, ни другое не значит «к этой партии вопросов нет». Пустая клетка
рассказывает про нас, а не про партию.</p>
<h2>Шестнадцать строк бюллетеня</h2>
<p>Стрелка показывает, в какую сторону фракция двигала то, что написано в
заголовке колонки, — а не «хорошо это или плохо». <b>↑</b> укрепляла,
<b>↓</b> ослабляла, <b>↕</b> ходила и туда и обратно.</p>
<table class=ov><thead><tr>
<th scope=col class=who>фракция</th>
<th scope=col class=c-inst>суд, парламент, свободы</th>
<th scope=col class=c-eq>деньги</th></tr></thead><tbody>
{body}
</tbody></table>
{other_themes()}
<div class=foot><p>Первый выпуск на живых данных, 13.08.2026.
Форма принята 01.08.2026 (design/mockup_v5). Снимок голосований:
{esc(m.get("source", {}).get("votes_at", "не объявлен"))}.</p></div>
</body></html>"""
    return doc, total, filled


def jargon(page: str) -> str | None:
    """Наш внутренний язык на странице читателя: фрагмент или None.

    Список слов и правило живут в scripts/check_report_canon.py — он
    существует с 01.08.2026 и зовётся только из Makefile, то есть защищал
    вызов, а не правило (§24). Первый за два месяца прогон 07.10 нашёл
    90 попаданий на всех пятнадцати страницах фракций: генератор написан
    13.08, уже ПОСЛЕ проверки, и ни разу ею не проверялся. Поэтому страж
    стоит здесь, где разметка рождается, и зовётся из main на каждой
    настоящей странице, а не только на образцах самопроверки.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_report_canon import FORBIDDEN
    t = re.sub(r"<style>.*?</style>", " ", page, flags=re.S)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t).lower()
    for rule in FORBIDDEN:
        m = re.search(rule, t)
        if m:
            return f"«{t[max(0, m.start() - 30):m.end() + 30].strip()}» по правилу {rule!r}"
    return None


def selftest() -> int:
    m = {"lines": [
        {"anchor_id": 1, "line": "правившая",
         "a": {"status": "observed"}, "b": {"status": "source_missing"}},
        {"anchor_id": 2, "line": "неправившая",
         "a": {"status": "observed"}, "b": {"status": "not_exposed"}},
        {"anchor_id": 3, "line": "без связи",
         "a": {"status": "lineage_unresolved"}, "b": {"status": "source_missing"}}],
        "source": {"votes_at": "2026-07-31"}}
    # ── ЧИСЛИТЕЛЬНОЕ СОГЛАСУЕТСЯ С ЧИСЛОМ ────────────────────────────────
    # «2 обязательств» и «остальные не разобраны» при полном разборе — язык
    # сборщика, а не документа; страница Оцма (2 из 2) показала оба 10.10.
    assert [ru_plural(n, "о", "а", "в") for n in (1, 2, 5, 11, 13, 21, 22)] == \
        ["о", "а", "в", "в", "в", "о", "а"], "склонение «обязательство» сломано"
    # ── ДУБЛЬ НЕ СЧИТАЕТСЯ ОБЯЗАТЕЛЬСТВОМ ───────────────────────────────
    # Пометка duplicate_of в записи обязана доехать до счётчика: иначе
    # график 700/800/950 из трёх строк читается как три обещания.
    _dup_card = {"period_id": "t", "data_fingerprint": None, "coverage": {"commitments_total": 2},
                 "snapshots": {"x": "2026"},
                 "commitments": [{"id": "a", "amount_ils": 1, "quote_he": "א", "quote_ru": "а",
                                  "conclusion": "x", "readings": [], "granularity": "exact_takana",
                                  "codes": [], "confidence": "low"},
                                 {"id": "b", "amount_ils": 1, "quote_he": "ב", "quote_ru": "б",
                                  "conclusion": "y", "readings": [], "granularity": "exact_takana",
                                  "codes": [], "confidence": "low", "duplicate_of": "a"}]}
    import unittest.mock as _m
    with _m.patch(__name__ + ".fingerprint", lambda *_a: None):
        _html = budget_block([_dup_card], {}, [])
    assert "Самостоятельных обязательств 1" in _html, "дубль не дошёл до счётчика"
    assert "Разобрано 2 записи" in _html, _html[:200]
    doc, total, filled = build(m)
    assert total == 6, f"клеток {total}, а строк три по две колонки"
    assert filled == 0, "без решения в карточке клетка не имеет права заполниться"

    # ── СТРЕЛКА ИЗ КАРТОЧКИ ДОХОДИТ ДО КЛЕТКИ, И ТОЛЬКО ОТТУДА ────────────
    cards_ok = {1: {"axis_institutions": {"arrow": "down", "level": "moderate",
                                          "alpha": 0.81,
                                          "alpha": 0.81,
        "text": "вероятно ослабляла; у нас 23 актов из 40"}}}
    doc2, total2, filled2 = build(m, cards_ok)
    assert (total2, filled2) == (6, 1), f"решение не доехало до клетки: {filled2}"
    assert "вероятно ослабляла" in doc2, "формулировка карточки не дошла до обзора"
    # ── РАМКА ОБЪЯВЛЯЕТ ЧЕТЫРЕ ТЕМЫ, ТАБЛИЦА ПОКАЗЫВАЕТ ОДНУ ─────────────
    # Если страница осей есть, а из обзора на неё не попасть, читатель её не
    # найдёт — и решит, что тема в документе одна. Проверяется НАЛИЧИЕ пути,
    # не понятность текста: понятность мерит только слепое чтение (§26).
    assert 'href="axes.html"' in doc2, "из обзора нет пути к странице тем"
    from render_axes import load_themes
    for t in load_themes()["themes"]:
        if t.get("role") != "РЕШАЮЩАЯ":
            assert t["title_ru"] in doc2, \
                f"тема {t['id']} объявлена, но в обзоре не названа"
    assert "↓" in doc2, "знак стрелки не дошёл до клетки"
    # строка без связи с фракцией стрелки не получает НИ ПРИ КАКОМ решении
    cards_lin = {3: {"axis_institutions": {"arrow": "up", "level": "high",
                                           "text": "укрепляла"}}}
    doc3, _, filled3 = build(m, cards_lin)
    assert filled3 == 0, \
        "строка со статусом lineage_unresolved получила стрелку — §7 обойдён"
    # значение вне закрытого списка макета — отказ, а не тихая отрисовка
    try:
        build(m, {1: {"axis_institutions": {"arrow": "сильно вниз"}}})
        raise AssertionError("значение вне пяти принятых проехало в клетку")
    except SystemExit as e:
        assert "вне закрытого списка" in str(e)
    assert "<script" not in doc, "§13: в выводе появился JavaScript"
    assert 'content="noindex, nofollow"' in doc, "§16: нет noindex"
    assert doc.index("data-frame=full") < doc.index("<table"), \
        "§17: рамка обязана стоять раньше первой таблицы"
    assert "ни разу не была в правительстве" in doc, \
        "§7: неправившая строка обязана нести пометку, иначе её пустота " \
        "неотличима от нашей недоработки"
    assert doc.count("tx-miss") >= 2 and doc.count("tx-none") >= 2, \
        "две фактуры обязаны различаться: «не дошли» и «искали, не нашли» — " \
        "разные состояния, и слить их значит выдать нашу дыру за факт"
    # Ловим ЗАПРОС, а не упоминание. Первая редакция запрещала подстроку
    # «http» — и краснела на xmlns='http://www.w3.org/2000/svg' внутри data:
    # URL фоновой текстуры, то есть на пространстве имён, которое никуда не
    # ходит. Мина, названная в приёмке 01.08, другая: @import шрифтов Google
    # из дизайн-системы _ds. Её и стережём.
    assert "@import" not in doc, \
        "@import в выводе: приёмка 01.08 назвала это миной — шрифты Google " \
        "тянут внешний запрос, а файл обязан открываться с диска"
    assert not re.search(r"url\(\s*['\"]?https?://", doc), \
        "внешний ресурс по url(): файл обязан открываться с диска"
    assert not re.search(r"(src|href)\s*=\s*['\"]?https?://", doc), \
        "внешняя ссылка в src/href: файл обязан открываться с диска"
    # §13 — ярлыки ищутся ВНЕ рамки. Первая редакция сканировала документ
    # целиком и покраснела на собственной рамке: там написано «ни баллов, ни
    # звёзд, ни лучшая-худшая», то есть проверка поймала своё же отрицание.
    # Ровно это уже случалось 27.07 с §9, когда grep на имя запрещённого
    # эндпоинта заблокировал коммит, вводивший сам запрет.
    # Стиль тоже вырезается: §13 про то, что ЧИТАЕТ читатель. В комментарии
    # палитры принятого макета стоит «худшая соседняя пара ΔE 20.2» — про
    # контраст красок, а не про партии. Сканируя CSS, проверка объявила бы
    # нарушением сам принятый дизайн; это второй случай за один прогон, когда
    # грубая проверка запрещает то, что защищает.
    body_only = re.sub(r"<style>.*?</style>", "", doc, flags=re.S)
    body_only = re.sub(r"<div class=note id=frame.*?</div>", "", body_only, flags=re.S)
    for bad in ("лучшая", "худшая", "рейтинг", "балл", "звёзд"):
        assert bad not in body_only.lower(), \
            f"§13: оценочный ярлык «{bad}» вне рамки — рамка его отрицает, " \
            "остальной документ не имеет права его употреблять"
    assert "лучшая-худшая" in doc, \
        "отрицание ярлыков исчезло из рамки: без него сканирование вне рамки " \
        "проходило бы и на документе, где §13 просто не объявлен читателю"

    # --- страница фракции: те же нормы, что у обзора, плюс крошки и §12.
    fcard = {"faction_id": 1110,
             "party_ru": "Тест", "party_he": "\u05e4", "conclusion": "вывод",
             "confidence": "low", "confidence_reason": "базовая линия",
             "what_would_falsify": "если доля изменится",
             "readings": [{"type": "weakening", "text": "раз"},
                          {"type": "reframing", "text": "два"}],
             "counter_search": {"searched_where": ["выгрузка"], "outcome": "nothing",
                                "note": "искали устройство, не поведение"},
             "votes": {"theme_caveat_ru": "по вопросам правового государства",
                       "census": {"votes": 2, "acts": 2, "from": "2022-12-13",
                                  "to": "2026-07-14",
                                  "acts_without_participation": 1}}}
    frow = {"a": {"status": "observed"},
            "b": {"status": "not_exposed", "note": "соглашения не подписывала"}}
    fv = [{"date": "2022-12-13", "name_ru": "Законопроект",
           "name_he": "\u05d4\u05e6\u05e2\u05ea", "for_option_desc": "\u05dc\u05d4\u05e2\u05d1\u05d9\u05e8",
           "pos": "против 5"}]
    fp = faction_page(fcard, frow, fv)
    # ── §7: СТРОКА БЕЗ СВЯЗИ НЕ ПОЛУЧАЕТ СТРЕЛКУ НИ ОТ КАКОЙ КАРТОЧКИ ────
    # not_transferred.связь запрещает заполнять клетку у lineage_unresolved:
    # там неизвестно, ЧЬЯ это фракция. Валидатор смотрит card.status, а
    # источник статуса здесь другой — строка coverage_matrix, и до 07.10
    # обе потребительские функции запрет не исполняли. Нашёл Кодекс,
    # проверено здесь своим входом.
    ax_live = {"arrow": "down", "level": "high", "acts": 20, "theme_total": 20,
               "coverage": 1.0, "down": 20, "up": 0, "alpha": 0.81,
               "text": "Тест по вопросам правового государства: ослабляла"}
    # Метка вместо слова «ослабляла»: это слово стоит в легенде КАЖДОЙ
    # страницы, и проверка по нему краснела бы на пояснении значков — то
    # есть запрещала бы ровно то, что защищает. В этом проекте так
    # случалось уже пять раз; ищем текст решения, а не слово канона.
    MARK = "РЕШЕНИЕ-ИЗ-КАРТОЧКИ"
    ax_live["text"] = MARK
    fcard_ax = dict(fcard, axis_institutions=ax_live)
    unres = {"a": {"status": "lineage_unresolved"}, "b": frow["b"]}
    fp_u = faction_page(fcard_ax, unres, fv)
    assert MARK not in fp_u, \
        "страница фракции поставила стрелку строке без установленной связи"
    assert "мы сюда не дошли" in fp_u, fp_u[:200]
    mk_m = lambda st: {"lines": [{"anchor_id": 1110, "line": "строка",
                                  "a": {"status": st}, "b": {"status": "observed"}}]}
    mu, _, fl_u = rows(mk_m("lineage_unresolved"), {1110: fcard_ax})
    assert MARK not in mu and fl_u == 0, \
        "обзор взял текст решения у строки без установленной связи"
    mo, _, fl_o = rows(mk_m("observed"), {1110: fcard_ax})
    assert MARK in mo and fl_o == 1, \
        "обзор потерял решение у строки, где связь установлена"
    # ── ГРАНИЦА ПУБЛИКАЦИИ, А НЕ ТОЛЬКО ВЫЧИСЛЕНИЯ ──────────────────────
    # Правило объявило «при альфе ниже порога стрелка не публикуется
    # вовсе». Отказ стоял в расчёте; готовая карточка проходила мимо, и
    # публикация была единственным местом без проверки.
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import arrow_rule
    TENT = float(arrow_rule()["tentative"])
    for bad, why in ((0.10, "альфа 0.10"), (TENT - 0.001, "чуть ниже порога"),
                     (None, "альфы нет вовсе")):
        axb = dict(ax_live)
        if bad is None:
            axb.pop("alpha")
        else:
            axb["alpha"] = bad
        cb = dict(fcard, axis_institutions=axb)
        mb, _, fb = rows(mk_m("observed"), {1110: cb})
        assert MARK not in mb and fb == 0, f"опубликована стрелка: {why}"
        fpb = faction_page(cb, {"a": {"status": "observed"}, "b": frow["b"]}, fv)
        assert MARK not in fpb, f"страница фракции опубликовала стрелку: {why}"
    axe = dict(ax_live, alpha=TENT)
    _, _, fe = rows(mk_m("observed"), {1110: dict(fcard, axis_institutions=axe)})
    assert fe == 1, "ровно на пороге стрелка обязана публиковаться"
    # ── §7: ПРОЗА ТОЖЕ НЕ УТВЕРЖДАЕТ НАПРАВЛЕНИЕ ────────────────────────
    cpr = dict(fcard_ax, conclusion="ослабляла и ещё как",
               readings=[{"type": "weakening", "text": "МЕТКА-ПРОЗЫ"}])
    fpu = faction_page(cpr, unres, fv)
    assert "МЕТКА-ПРОЗЫ" not in fpu and "ослабляла и ещё как" not in fpu, \
        "проза карточки утверждает направление у строки без связи"
    assert "не установили" in fpu, "состояние §7 не названо читателю"
    assert 'href="c-1110-inst.html"' in fp, \
        "со страницы фракции нет пути к разбору по правилам отсева"
    assert "<script" not in fp, "§13: скрипт на странице фракции"
    assert 'content="noindex, nofollow"' in fp, "§16: нет noindex на странице фракции"
    assert fp.index("data-frame=short") < fp.index("<h1"), \
        "§17: короткая рамка обязана стоять ДО заголовка — читатель, пришедший " \
        "по прямой ссылке, встречает её раньше всего остального"
    assert "<bdi>" in fp and "dir=rtl" in fp, "§12: иврит без bdi/rtl переставляется"
    assert "\u05dc\u05d4\u05e2\u05d1\u05d9\u05e8" in fp, "§10: смысл «за» не дошёл до страницы"
    assert "искали, не нашли" in fp, "§7: не экспонирована — не «не дошли»"
    assert fp.count("по вопросам правового государства") >= 1, \
        "оговорка о теме не дошла до страницы фракции"

    # Наш внутренний язык на странице читателя. Правило и список слов живут в
    # scripts/check_report_canon.py — он существует с 01.08 и имеет вызов
    # только в Makefile, то есть защищал вызов, а не правило (§24). Утром
    # 07.10 его первый за два месяца прогон нашёл 90 попаданий на всех
    # пятнадцати страницах фракций. Проверка переносится ТУДА, ГДЕ РОЖДАЕТСЯ
    # разметка, чтобы её нельзя было не позвать.
    # страница фракции со стрелкой: уровень и формулировка обязаны доехать,
    # а внутренний язык — не появиться вместе с ними
    fcard2 = dict(fcard)
    fcard2["axis_institutions"] = {
        "arrow": "down", "level": "moderate", "acts": 23, "theme_total": 40,
        "down": 19, "up": 4,
        "alpha": 0.81,
        "text": "вероятно ослабляла; у нас 23 актов из 40"}
    fp2 = faction_page(fcard2, frow, fv)
    assert "вероятно ослабляла" in fp2 and "умеренная" in fp2, \
        "решение или уровень не дошли до страницы фракции"
    # Стиль вырезается ПЕРЕД проверкой: в комментарии палитры принятого
    # макета стоит «штриховка = мы сюда не дошли» — про фактуру, не про
    # клетку. Первая редакция этой провокации покраснела на нём, то есть
    # проверка ловила макет вместо вывода. Тот же класс промаха уже был
    # дважды за 01.08 и один раз за 13.08 — грубая проверка запрещает то,
    # что защищает.
    axis_cell = re.sub(r"<style>.*?</style>", " ", fp2, flags=re.S) \
        .split("</details>")[0]
    assert "мы сюда не дошли" not in axis_cell, \
        "клетка со стрелкой всё ещё говорит «не дошли»"
    assert "ослабляла" in axis_cell, "знак стрелки не дошёл до клетки оси"
    assert jargon(fp2) is None, "внутренний язык приехал вместе со стрелкой"

    assert jargon(doc) is None and jargon(fp) is None, "жаргон на образцах"
    # МУТАНТ: страж обязан краснеть. Зелёный страж и мёртвый страж выглядят
    # одинаково, отличить их по выводу нельзя — только подлогом.
    assert jargon(fp.replace("<h1", "<p>Так решил валидатор.</p><h1", 1)) \
        is not None, "страж внутреннего языка мёртв: подложенный «валидатор» не найден"
    # Доставка существующей карточки: пропуск загрузчиком тоже ломает тест.
    import copy
    import tempfile
    from validate_cards import REF_NUM
    bc = copy.deepcopy(load_cards("party_period")[1095])
    # Число разборов — из самой карточки (coverage), не константа: 10.10 их
    # стало 21, и зашитая «4» уронила бы проверку на правильном входе.
    n_c = bc[0]["coverage"]["commitments_analysed"]
    assert len(bc) == 1 and len(bc[0]["commitments"]) == n_c, \
        (len(bc[0]["commitments"]), n_c)
    idx = {(code, int(year)): {"net_allocated": 123000, "net_executed": 456000}
           for c in bc[0]["commitments"]
           for code, year, _ in REF_NUM.findall(c["conclusion"])}
    bc[0]["data_fingerprint"] = fingerprint(bc[0], idx, [])
    block = budget_block(bc, idx, [])
    shas = faction_page(fcard, frow, fv, block)
    check_budget_page(shas, bc, idx, [])
    assert "123 000 ₪" in shas and "{0022010213" not in shas
    assert jargon(shas) is None, jargon(shas)

    def rejects(label, action):
        try:
            action()
        except Refuse as exc:
            print(f"КРАСНЫЙ (пойман), {label}: {exc}")
        else:
            raise AssertionError(f"мёртвый оракул: {label}")

    rejects("бюджетный блок удалён", lambda: check_budget_page(
        shas.replace(block, ""), bc, idx, []))
    print("ЗЕЛЁНЫЙ: четыре бюджетных разбора доставлены на страницу")
    changed = copy.deepcopy(idx)
    next(iter(changed.values()))["net_allocated"] += 1
    rejects("подмена числа", lambda: budget_block(bc, changed, []))
    bidi = copy.deepcopy(bc)
    bidi[0]["commitments"][0]["quote_he"] += "\u202e"
    rejects("Bidi в цитате", lambda: budget_block(bidi, idx, []))
    state = state_page(dict(anchor_id=1097, line="הציונות הדתית",
                            a={"status": "lineage_unresolved", "note": "нет связи"}))
    assert "Наследование запрещено" in state and "Это не значит" in state
    assert "Религиозный сионизм" in state and "הציונות הדתית" in state
    assert "c-1097-inst" not in state and jargon(state) is None
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        site = Path(tmp)
        (site / "index.html").write_text(doc, encoding="utf-8")
        for name in ("f-1.html", "f-2.html", "f-3.html", "axes.html", "grounds.html", "time.html", "method.html"):
            (site / name).write_text(state, encoding="utf-8")
        n = check_index_links(site)
        (site / "index.html").write_text(doc + '<a href="missing.html">нет</a>', encoding="utf-8")
        rejects("несуществующий href", lambda: check_index_links(site))
        (site / "index.html").write_text(doc, encoding="utf-8")
        assert check_index_links(site) == n
        print(f"ЗЕЛЁНЫЙ: все {n} href разрешаются внутри site/")
    if OUT.exists():
        print(f"ЗЕЛЁНЫЙ: site/index.html, {check_index_links(OUT.parent)} href")

    sys.path.insert(0, str(ROOT / "scripts"))
    from classify_direction import n_asserts
    print(f"самопроверка render_overview: {n_asserts(selftest)} утверждений "
          "(включая мутант стража внутреннего языка)")
    return 0


def load_cards(unit="faction_knesset") -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_cards import load_yaml_ish
    out = {}
    for f in sorted((ROOT / "cards").glob("*.yaml")):
        c = load_yaml_ish(f)
        if (c.get("unit") or "party_period") == unit:
            if unit == "party_period":
                fid = int(c["period_id"].split("-", 1)[0])
                out.setdefault(fid, []).append(c)
            else:
                out[int(c["faction_id"])] = c
    return out


def votes_for(fid: int) -> list:
    """Голосования фракции с переводом названия. Отказ, а не пустота."""
    src = ROOT / "data" / "votes_25.json"
    # Берётся САМЫЙ ПОЗДНИЙ справочник переводов, а не прибитая дата: после
    # перевыгрузки состав актов меняется, и зашитое имя файла означало бы
    # отказ §12 на каждом новом акте при том, что перевод уже написан.
    trs = sorted((ROOT / "docs" / "reference").glob("vote_names_ru_*.json"))
    if not trs:
        raise SystemExit("ОТКАЗ §12: справочника переводов названий нет — "
                         "страница была бы нечитаема для владельца")
    tr = json.loads(trs[-1].read_text(encoding="utf-8"))["names"]
    POS = {"for": "за", "against": "против", "abstain": "воздержались",
           "present": "присутствовали, не голосовали"}
    out = []
    for r in json.loads(src.read_text(encoding="utf-8"))["rows"]:
        cell = next((v for k, v in (r.get("by_faction") or {}).items()
                     if k.split("|", 1)[0] == str(fid)), None)
        if cell is None:
            continue
        t = tr.get(str(r["bill_id"]))
        if not t or not r["bill_name"].startswith(t["he_head"]):
            raise SystemExit(f"ОТКАЗ §12: перевод акта {r['bill_id']} отсутствует "
                             "или устарел — страница нечитаема для владельца")
        out.append({"date": r["date"][:10], "name_ru": t["ru"],
                    "name_he": r["bill_name"],
                    "for_option_desc": r.get("for_option_desc") or "",
                    "pos": ", ".join(f"{POS.get(k, k)} {n}" for k, n in cell.items())})
    out.sort(key=lambda x: x["date"])
    return out


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    """1 обязательство, 2–4 обязательства, 5+ обязательств (и 11–14 — many)."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def budget_block(cards: list, idx: dict, titles: list) -> str:
    """§11: проверка и подстановка читают один индекс; старый CLI не вызывается."""
    out = []
    for card in cards:
        if card.get("data_fingerprint") != fingerprint(card, idx, titles):
            raise Refuse(f"§11: data_fingerprint не совпал: {card['period_id']}")
        cov = card.get("coverage") or {}
        n, total = len(card.get("commitments") or []), cov.get("commitments_total")
        tail = "весь список разобран" if n == total else "остальные не разобраны"
        # Дубли (duplicate_of) — записи, а не самостоятельные обязательства:
        # счётчик обязан это различать, иначе график из трёх строк считается
        # за три обещания (ревью 18.10, F-07).
        dups = [c for c in card.get("commitments") or [] if c.get("duplicate_of")]
        uniq = n - len(dups)
        dup_note = ("" if not dups else
                    f" Самостоятельных обязательств {uniq}: "
                    f"{len(dups)} {ru_plural(len(dups), 'запись', 'записи', 'записей')} — "
                    "продолжение другого пункта (помечено в самой записи).")
        out.append(f'<section data-budget="{esc(card["period_id"])}">'
                   f'<p>Период: {esc(card["period_id"])}. Разобрано '
                   f'{n} {ru_plural(n, "запись", "записи", "записей")} из '
                   f'{esc(total)}; {tail}.{esc(dup_note)}</p>')
        out.append('<p>Снимки источников: ' + esc(
            "; ".join(f"{k} — {v}" for k, v in sorted(card["snapshots"].items()))) + '</p>')
        for c in card.get("commitments") or []:
            out.append(f'<article id="{esc(c["id"])}"><p>Сумма в соглашении: '
                       f'{money(c["amount_ils"])}</p>'
                       + render_commitment(c, idx, titles, []) + '</article>')
        out.append('<p>Журнал исправлений:</p><ul>' + ''.join(
            f'<li>{esc(r["date"])} · версия {esc(r["version"])}: '
            f'{esc(r["what"])} — {esc(r["why"])}</li>'
            for r in card.get("revisions") or []) + '</ul></section>')
    return "".join(out)


def check_budget_page(page: str, cards: list, idx: dict, titles: list) -> None:
    """Отсутствие любого готового разбора — отказ, даже если остальная страница цела."""
    for card in cards:
        for date in card["snapshots"].values():
            if esc(date) not in page:
                raise Refuse("дата снимка бюджетного разбора потеряна")
        for c in card.get("commitments") or []:
            if money(c["amount_ils"]) not in page:
                raise Refuse(f"сумма обязательства {c['id']} потеряна")
            if render_commitment(c, idx, titles, []) not in page:
                raise Refuse(f"бюджетный разбор {c['id']} потерян на странице")


class IndexLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        self.hrefs.extend(v for k, v in attrs if k == "href" and v is not None)


def check_index_links(site: Path) -> int:
    """Каждый href ведёт в существующий файл внутри site, включая ссылки-якоря."""
    parser = IndexLinks()
    parser.feed((site / "index.html").read_text(encoding="utf-8"))
    if not parser.hrefs:
        raise Refuse("index.html не содержит ссылок — выборка пуста")
    for href in parser.hrefs:
        url = urlsplit(href)
        target = (site / (unquote(url.path) or "index.html")).resolve()
        if (url.scheme or url.netloc or not target.is_relative_to(site.resolve())
                or not target.is_file()):
            raise Refuse(f"href не разрешается в файл внутри site/: {href}")
    return len(parser.hrefs)


def state_page(row: dict) -> str:
    """§7: отсутствие связи — отдельная страница, без наследования карточек."""
    names = json.loads((ROOT / "criteria/wikidata_crosscheck.json").read_text(encoding="utf-8"))
    ru = next((n["mine"] for group in ("agree", "differ", "missing")
               for n in names[group] if n["he"] == row["line"]), None)
    if not ru:
        raise Refuse(f"§12: нет перевода названия строки {row['anchor_id']}")
    return f'''<!doctype html><html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Связь не установлена</title>
<style>{css_from_mockup()}</style></head><body>
<nav class=crumbs><a href="index.html">Все фракции</a></nav>{SHORT_FRAME}
<h1>Строка {esc(row["anchor_id"])}: {esc(ru)} <span lang=he dir=rtl><bdi>{esc(row["line"])}</bdi></span></h1>
<p class=lead>Связь строки бюллетеня с фракцией не установлена.</p>
<p>Причина: {esc(row["a"].get("note"))}.</p>
<p>Преемственность остаётся неразрешённой. Наследование запрещено:
этой строке нельзя приписывать голосования, бюджетные выводы или поступки
людей других фракций.</p>
<p>Это не значит, что партия не голосовала, не была в правительстве или
что к ней нет вопросов. Это также не обвинение: мы не установили связь,
необходимую для таких выводов.</p></body></html>'''


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not MATRIX.exists():
        print(f"нет {MATRIX} — сначала scripts/coverage_matrix.py"); return 2
    m = json.loads(MATRIX.read_text(encoding="utf-8"))
    # Обновляем подписи из решений, не записывая производный снимок в data/.
    from coverage_matrix import channel_b, commitment_maps
    maps = commitment_maps()
    for row in m["lines"]:
        if row["anchor_id"] in maps:
            row["b"]["status"], row["b"]["note"] = channel_b(row["anchor_id"], set(), maps)
    cards = load_cards()
    budgets = load_cards("party_period")
    idx, titles = budget_index() if budgets else ({}, [])
    doc, total, filled = build(m, cards)
    bad = jargon(doc)
    if bad:
        print(f"ОТКАЗ: внутренний язык в обзоре: {bad}")
        return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    pages = 0
    for r in m["lines"]:
        c = cards.get(r["anchor_id"])
        if r["a"]["status"] == "lineage_unresolved":
            page = state_page(r)
        elif not c:
            raise Refuse(f"нет карточки наблюдаемой строки {r['anchor_id']}")
        else:
            bc = budgets.get(r["anchor_id"], [])
            budget = budget_block(bc, idx, titles) if bc else ""
            page = faction_page(c, r, votes_for(r["anchor_id"]), budget)
            check_budget_page(page, bc, idx, titles)
        bad = jargon(page)
        if bad:
            print(f"ОТКАЗ: внутренний язык на f-{r['anchor_id']}.html: {bad}")
            return 1
        (OUT.parent / f"f-{r['anchor_id']}.html").write_text(page, encoding="utf-8")
        pages += 1
    print(f"обзор + {pages} страниц фракций -> {OUT.parent}")
    print(f"ЗАМЕР: клеток {total}, заполнено {filled}, пусто {total - filled}")
    return 0




# ────────────────────────────────────── страницы фракций (форма f-*.html)
SHORT_FRAME = ('<p class=frame data-frame=short>Темы выбрал автор · оценок и '
               'баллов нет · данные — поимённые голосования Кнессета · автор — '
               'частное лицо, без финансирования. '
               '<a href="index.html#frame">Полная рамка</a></p>')
CERT = {"high": "⊕⊕⊕⊕ высокая", "medium": "⊕⊕⊕◯ средняя",
        "low": "⊕⊕◯◯ низкая", "none": "◯◯◯◯ нет"}
# Четыре уровня GRADE из объявленного правила стрелки. Отдельно от CERT:
# тот про уверенность карточки целиком, этот — про одну клетку оси.
CERT_GRADE = {"high": "⊕⊕⊕⊕ высокая", "moderate": "⊕⊕⊕◯ умеренная",
              "low": "⊕⊕◯◯ низкая", "very_low": "⊕◯◯◯ очень низкая"}
READ_RU = {"weakening": "ослабляющее прочтение",
           "strengthening": "усиливающее прочтение",
           "reframing": "переформатирующее прочтение"}


def det(summary: str, cert: str, inner: str, open_: bool = False) -> str:
    o = " open" if open_ else ""
    return (f'<details class=cell{o}><summary>{summary}'
            f'<span class=cert>{esc(cert)}</span></summary>'
            f'<div class=inner>{inner}</div></details>')


def faction_page(card: dict, row: dict, votes: list, budget: str = "") -> str:
    """Страница фракции. Клетка оси — details, как в макете; счёт
    голосований уходит ВНУТРЬ раскрытия, а не вываливается на страницу."""
    ru, he = card.get("party_ru"), card.get("party_he")
    v = card.get("votes") or {}
    cen = v.get("census") or {}
    cav = v.get("theme_caveat_ru", "")
    ax = card.get("axis_institutions") or {}
    # §7: строка без установленной связи не получает стрелку НИ ПРИ КАКОМ
    # решении карточки — там неизвестно, чья это фракция. Валидатор карточек
    # смотрит на card.status, а здесь источник статуса другой — строка
    # coverage_matrix, и до 07.10 эта страница запрет не исполняла.
    if row["a"]["status"] != "observed":
        ax = {}
    if ax.get("arrow") in ("up", "down", "both") and not alpha_ok(ax):
        ax = {}
    # §7: у строки без установленной связи нечего утверждать и прозой — она
    # утверждает направление теми же словами, что стрелка. Запрет касался
    # только блока оси, и проза его обходила.
    if row["a"]["status"] != "observed":
        card = dict(card, conclusion=(
            "кто стоит за этой строкой бюллетеня, мы не установили: "
            "преемственность не разрешена, и приписать ей поступки чьей-то "
            "фракции значило бы угадать. Это другое состояние, чем «мы сюда "
            "не дошли»."), readings=[])
    if ax.get("arrow") in ("up", "down", "both"):
        inner1 = (f'<p><b>что мы увидели</b> {esc(ax.get("text"))}</p>'
                  f'<p><b>из чего</b> {esc(ax.get("acts"))} актов из '
                  f'{esc(ax.get("theme_total"))}, в сторону ослабления '
                  f'{esc(ax.get("down"))}, в сторону укрепления '
                  f'{esc(ax.get("up"))}.</p>'
              f'<p><b>на чём стояла бы</b> на {esc(cen.get("votes"))} '
              f'голосованиях по {esc(cen.get("acts"))} актам, {esc(cav)}, '
                  f'{esc(cen.get("from"))} — {esc(cen.get("to"))}. Актов темы без '
                  f'участия фракции: {esc(cen.get("acts_without_participation"))}.</p>')
        head1 = (f'Суд, парламент, свободы — '
                 f'<b>{CELL[ax["arrow"]][0]} {CELL[ax["arrow"]][1]}</b>')
        cert1 = ("насколько мы в этом уверены: "
                 + CERT_GRADE.get(ax.get("level"), "значения нет"))
    else:
        inner1 = (f'<p><b>почему пусто</b> направление голосований мы считать '
                  f'пока не умеем: классификация встала на объявленном '
                  f'пороге. Пустота здесь про нас, а не про фракцию.</p>'
                  f'<p><b>на чём стояла бы</b> на {esc(cen.get("votes"))} '
                  f'голосованиях по {esc(cen.get("acts"))} актам, {esc(cav)}, '
                  f'{esc(cen.get("from"))} — {esc(cen.get("to"))}. Актов темы без '
                  f'участия фракции: {esc(cen.get("acts_without_participation"))}.</p>')
        head1 = ('Суд, парламент, свободы — '
                 '<b class=tx-miss>мы сюда не дошли</b>')
        cert1 = "насколько мы в этом уверены: значения нет"
    # Путь к разбору: без него страница решения не находится ниоткуда, а
    # именно там сказано, сколько голосований отсеялось и каким правилом.
    inner1 += (f'<p><a href="c-{card.get("faction_id")}-inst.html">Что из '
               f'голосований вообще считается</a> — разбор по правилам '
               f'отсева.</p>')
    cells = [det(head1, cert1, inner1, True)]
    if budget:
        s2, c2 = "Деньги — разбор обязательств", row["b"]["note"]
    elif row["b"]["status"] == "not_exposed":
        s2, c2 = ('Деньги — <b class=tx-none>искали, не нашли</b>',
                  "не экспонирована: канал покрывает только подписавших соглашение")
    else:
        s2, c2 = ('Деньги — <b class=tx-miss>мы сюда не дошли</b>',
                  "сопоставление обязательств не построено")
    cells.append(det(s2, c2, budget or f'<p>{esc(row["b"]["note"])}</p>'))
    body = [f'<p class=lead>{esc(card.get("conclusion"))}</p>']
    for r in card.get("readings") or []:
        body.append(f'<p><b>{esc(READ_RU.get(r.get("type"), ""))}.</b> '
                    f'{esc(r.get("text"))}</p>')
    cs = card.get("counter_search") or {}
    where = "".join(f"<li>{esc(w.get('источник') if isinstance(w, dict) else w)}</li>"
                    for w in cs.get("searched_where") or [])
    body.append(f'<div class=note><p><b>Искали, чем это опровергнуть:</b> '
                f'{esc(cs.get("outcome"))}</p><ul class=dim>{where}</ul>'
                f'<p class=dim>{esc(cs.get("note", ""))}</p>'
                f'<p><b>Уверенность:</b> {esc(CERT.get(card.get("confidence")))} — '
                f'{esc(card.get("confidence_reason"))}</p>'
                f'<p><b>Чем это опровергается.</b> '
                f'{esc(card.get("what_would_falsify"))}</p></div>')
    acts = "".join(
        f'<tr><td data-l="дата">{esc(x["date"])}</td>'
        f'<td data-l="акт">{esc(x["name_ru"])}'
        f'<span class="he" lang=he dir=rtl><bdi>{esc(x["name_he"])}</bdi></span></td>'
        f'<td data-l="«за» означало"><span class=he lang=he dir=rtl>'
        f'<bdi>{esc(x["for_option_desc"])}</bdi></span></td>'
        f'<td data-l="фракция">{esc(x["pos"])}</td></tr>' for x in votes)
    body.append(det(f"Все {len(votes)} голосований этой фракции — {esc(cav)}",
                    "здесь все голосования, которые мы учли; "
                    "внутри темы мы ничего не отбирали",
                    '<table class=acts><thead><tr><th scope=col>дата</th>'
                    '<th scope=col>акт</th><th scope=col>«за» означало</th>'
                    f'<th scope=col>фракция</th></tr></thead><tbody>{acts}'
                    '</tbody></table>'))
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{esc(ru)} — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<nav class=crumbs><a href="index.html">Все фракции</a> · {esc(ru)}</nav>
{SHORT_FRAME}
<h1>{esc(ru)} <span class=he lang=he dir=rtl><bdi>{esc(he)}</bdi></span></h1>
{''.join(cells)}
{''.join(body)}
<div class=foot><p>Первый выпуск на живых данных, 13.08.2026. Форма принята
01.08.2026. Снимок голосований: 2026-07-31.</p></div>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
