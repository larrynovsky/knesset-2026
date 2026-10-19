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

from build_report import esc, fingerprint, render_commitment, money, Refuse, OUTCOME_RU
from validate_cards import budget_index

ROOT = Path(__file__).resolve().parent.parent
MOCK = ROOT / "design" / "mockup_v5" / "index.html"
MATRIX = ROOT / "data" / "coverage_matrix.json"
OUT = ROOT / "site" / "index.html"

# Канон D2; решение владельца 19.10: денежное покрытие N из M.
CELL = {"up": ("↑", "укрепляла", ""), "down": ("↓", "ослабляла", ""),
        "both": ("↕", "и туда и обратно", ""),
        "none": ("", "искали, не нашли", "tx-none"),
        "miss": ("", "мы сюда не дошли", "tx-miss"),
        "reviewed": ("", "в бюджете нашлась строка под {n} из {m} обещаний", "tx-rev")}


def css_from_mockup() -> str:
    """CSS берётся из макета, а не копируется в код: один дом у формы."""
    m = re.search(r"<style>(.*?)</style>", MOCK.read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit("ОТКАЗ: в макете не найден <style> — форма не читается")
    return m.group(1)


def cell(kind: str, label: str, value: str | None = None) -> str:
    a, word, tx = CELL[kind]
    word = value or word
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
<p class=dim><b>Это первая, грубая итерация.</b> Направление посчитано по
голосам фракций и знаку каждого закона по большинству трёх моделей; точность
будем повышать следующим шагом. Что известно про каждую фракцию — на её
странице.</p>
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


def rows(m: dict, cards: dict | None = None,
         budgets: dict | None = None) -> tuple[str, int, int]:
    """Строки обзора. Возвращает разметку, число клеток и число заполненных.

    budgets — денежное покрытие N из M по разобранным карточкам фракций."""
    cards = cards or {}
    budgets = budgets or {}
    names = party_names(m, cards)
    out, total, filled = [], 0, 0
    for r in m["lines"]:
        a, b = r["a"]["status"], r["b"]["status"]
        who = (f'<td class=who><a href="f-{r["anchor_id"]}.html">{esc(names[r["anchor_id"]])}</a><span class=norec lang=he dir=rtl><bdi>{esc(r["line"])}</bdi></span>')
        if b == "not_exposed":
            # R23: горизонт назван — справочник составов охватывает 25-й Кнессет
            who += ('<span class=norec>в 25-м Кнессете в правительстве не была</span>')
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
        if b == "observed" and r["anchor_id"] in budgets:
            k2 = "reviewed"
        elif b == "observed":
            # R19-F01: карта извлечения есть, разбора нет. Пустая — смотрели и
            # вернулись пустыми; непустая без разбора — не дошли.
            k2 = "none" if r["b"].get("commitments") == 0 else "miss"
        lab = ("коалиционного соглашения не подписывала"
               if b == "not_exposed" else
               "обязательства против бюджета — по записям на странице фракции"
               if k2 == "reviewed" else
               "денежных обещаний в соглашении не найдено"
               if b == "observed" and k2 == "none" else
               "обязательства против бюджета")
        c2 = cell(k2, lab, budgets.get(r["anchor_id"]) if k2 == "reviewed" else None)
        total += 1
        if k2 not in ("miss", "none", "reviewed"):
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
            f'Разница ровно в этом.</p>'
            f'<ul class=dim>{li}</ul>'
            f'<p><a href="axes.html">Что мы меряем и почему именно это</a> — '
            f'там про каждую тему отдельно. '
            f'<a href="time.html">Как менялась доля расхождений с залом</a> — '
            f'по полугодиям, без объяснений. '
            f'<a href="method.html">Как мы считаем</a>.</p>')


# Лидеры фракций в 25-м Кнессете (владелец 19.10: название + лидер или лидеры).
# По памяти Claude на июнь 2026; не сверено с источником.
LEADERS = {1095: "Арье Дери", 1096: "Биньямин Нетаньяху", 1097: "Бецалель Смотрич",
           1098: "Бени Ганц", 1099: "Мансур Аббас", 1100: "Мерав Михаэли, затем Яир Голан",
           1101: "Моше Гафни, Ицхак Гольдкнопф", 1102: "Яир Лапид",
           1103: "Айман Уде, Ахмад Тиби", 1104: "Авигдор Либерман",
           1105: "Бецалель Смотрич", 1106: "Итамар Бен-Гвир", 1107: "Ави Маоз",
           1108: "Гидеон Саар", 1109: "Идан Роль", 1110: "Бени Ганц"}


def with_leader(fid, name: str) -> str:
    """«Название (лидер)», если лидера ещё нет в названии."""
    lead = LEADERS.get(int(fid)) if str(fid).isdigit() else None
    if not lead or lead.split()[-1].split(",")[0] in name:
        return name
    return f"{name} — {lead}"


def party_names(matrix: dict, cards: dict) -> dict:
    """Те же переводы, что у faction_page и state_page."""
    names = json.loads((ROOT / "criteria/wikidata_crosscheck.json").read_text(encoding="utf-8"))
    by_he = {n["he"]: n["mine"] for group in ("agree", "differ", "missing") for n in names[group]}
    return {r["anchor_id"]: with_leader(r["anchor_id"], cards.get(r["anchor_id"], {}).get("party_ru")
                             or by_he.get(r["line"], r["line"])) for r in matrix["lines"]}


def owner_law_positions(fids: list[str]) -> list[dict]:
    """Единые последние стадии и позиции для обзора и сводок фракций."""
    from render_grounds import MARKS, read_marks, load_all, act_votes, vote_table
    votes, names, _, _, table, split = load_all()
    marked = [b for b, mark in read_marks(MARKS).items() if mark["mark"] == "недопустимо"]
    latest = {}
    for bill in marked:
        vs = act_votes(votes["rows"], bill, table)
        if not vs:
            raise Refuse(f"акт {bill}: нет последней стадии")
        latest[bill] = vote_table(vs[-1], table, {}, fids, split)
    return [dict(bill=b, name=names[str(b)]["ru"], date=latest[b]["date"],
                 positions={fid: "за" if _al(fid) in latest[b]["groups"]["for"] else
                            "против" if _al(fid) in latest[b]["groups"]["against"] else
                            "нет позиции" for fid in fids}) for b in marked]


def _al(fid) -> str:
    """Строка бюллетеня → фракция, чьи голоса она несёт (ALIAS)."""
    return str(ALIAS.get(int(fid), fid))


def grounds_block(matrix: dict, cards: dict) -> str:
    """Последняя стадия: общий источник со сводками фракций."""
    laws = owner_law_positions([str(r["anchor_id"]) for r in matrix["lines"]])
    ru = party_names(matrix, cards)
    heads = ''.join(f'<th scope=col><a href="grounds.html#a{law["bill"]}">{esc(law["name"])}</a>'
                    f'<span class=norec>{law["date"]}</span></th>' for law in laws)
    rows = []
    for r in matrix["lines"]:
        fid = str(r["anchor_id"])
        cells = [f'<td>{law["positions"][fid]}</td>' for law in laws]
        # владелец 19.10: партии на двух языках
        rows.append(f'<tr data-owner-fid="{fid}"><th scope=row><a href="f-{fid}.html">{esc(ru[r["anchor_id"]])}</a>'
                    f' <span class=he lang=he dir=rtl><bdi>{esc(r["line"])}</bdi></span></th>{"".join(cells)}</tr>')
    return ('<h2 id="grounds">Фракции и четыре закона владельца</h2>'
            '<p>Четыре акта, помеченные владельцем «недопустимо». Позиция на последней стадии; '
            '<a href="grounds.html">все стадии и основания</a>.</p>'
            '<table class="owner-laws"><thead><tr><th scope=col>Фракция</th>' + heads +
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')


def build(m: dict, cards: dict | None = None,
          budgets: dict | None = None) -> tuple[str, int, int]:
    body, total, filled = rows(m, cards, budgets)
    rev = body.count("tx-rev")
    miss = total - filled - rev
    doc = f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Что фракции делали — 25-й Кнессет</title>
<style>{css_from_mockup()}
.owner-laws{{width:100%;table-layout:fixed}} .owner-laws th,.owner-laws td{{padding:9px 6px;overflow-wrap:anywhere}} .owner-laws th{{font-size:13px}} .owner-laws td{{font-size:14px}}
</style></head><body>
<h1>Что фракции делали на самом деле</h1>
<p class=lead>27 октября в бюллетене будет около двенадцати списков. Этот
документ нужен для одного: вычеркнуть два-три из них и уметь объяснить себе
почему — не «они мне не нравятся», а «вот закон, вот дата, вот как они
проголосовали».</p>
<p>Мы смотрим на поступки, а не на заявления. Слова перед выборами стоят ноль;
голос в Кнессете записан поимённо и никуда не денется.</p>
{FRAME}
{grounds_block(m, cards or {})}
<h2>Сначала о том, чего мы не знаем</h2>
<p>Клеток в таблице ниже — <b class=big>{total}</b>С итоговым выводом — {filled};
в {rev} показано покрытие обещаний бюджетными строками; в остальных {miss} нужный разбор не
проведён или искомого не нашли — что именно, сказано на странице фракции.</p>
<p>Это разные вещи, и подписаны они по-разному.
<b class=tx-miss>«Не дошли»</b> значит, что нужный разбор ещё не проведён.
Предмет указан в подписи клетки; подробности — на странице фракции.
<b class=tx-none>«Искали, не нашли»</b> — что не найдено то, что названо в
подписи (например, соглашение или денежные обещания в нём), а не «нарушений
не нашли».
В денежных клетках указано, под сколько самостоятельных обещаний нашлась
строка бюджета. Разбор каждого обещания — на странице фракции.
Ни одно из этих состояний не значит «к этой партии вопросов нет». Пустая клетка
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
<div class=foot><p>Первая грубая итерация, 19.10.2026.
Форма принята 01.08.2026 (design/mockup_v5). Снимок голосований:
{esc(str(m.get("source", {}).get("votes_at", "не объявлен"))[:10])}.</p></div>
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


def _fixture_signs(extra: dict) -> None:
    """Selftest: настоящий справочник плюс смыслы опций фикстуры."""
    from direction_confidence import sign_table
    _SIGNS.clear()
    _SIGNS.update(sign_table())
    _SIGNS.update(extra)


def selftest() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    _fixture_signs({"\u05dc\u05d4\u05e2\u05d1\u05d9\u05e8": {"gloss_ru": "передать акт дальше"}})
    m = {"lines": [
        {"anchor_id": 1, "line": "правившая",
         "a": {"status": "observed"}, "b": {"status": "source_missing"}},
        {"anchor_id": 2, "line": "неправившая",
         "a": {"status": "observed"}, "b": {"status": "not_exposed"}},
        {"anchor_id": 3, "line": "без связи",
         "a": {"status": "lineage_unresolved"}, "b": {"status": "source_missing"}}],
        "source": {"votes_at": "2026-07-31"}}
    # Решение 19.10: считаем самостоятельные деньги; все три вида найденных строк.
    cs = [{"granularity": g} for g in ("exact_takana", "subset_of_line", "spread_over_lines",
                                       "not_found", "not_budgetary")]
    cs.append({"granularity": "exact_takana", "duplicate_of": "first"})
    assert budget_summary([{"commitments": cs}]) == "в бюджете нашлась строка под 3 из 4 обещаний"
    live_matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    live_cards = load_cards()
    owner = grounds_block(live_matrix, live_cards)
    assert owner.count('data-owner-fid=') == 16 and owner.count('<td>') == 64
    assert '<td>раскол</td>' not in owner and '<td>воздержались</td>' not in owner
    assert 'grounds.html#a2199044' not in owner
    # У Еш Атид на последней стадии 2207472 позиции нет, прежнее «против» не наследуем.
    ya = re.search(r'<tr data-owner-fid="1102">(.*?)</tr>', owner).group(1)
    assert re.findall(r'<td>(.*?)</td>', ya) == ['против', 'нет позиции', 'нет позиции', 'против']
    assert 'Религиозный сионизм' in owner and 'Ликуд' in owner
    live_doc, _, _ = build(live_matrix, live_cards)
    assert live_doc.index('data-frame=full') < live_doc.index('class="owner-laws"') < live_doc.index('Сначала о том')
    # Оракул сводки: все 16 строк, 64 позиции и непосредственное место под h1.
    laws = owner_law_positions([str(r["anchor_id"]) for r in live_matrix["lines"]])
    assert len(live_matrix["lines"]) == 16 and len(laws) == 4
    for row in live_matrix["lines"]:
        fid = row["anchor_id"]
        card = live_cards.get(fid, {})
        brief = faction_summary(row, card, "покрытие для проверки", laws)
        assert brief.count('<p>') == 4
        expected = re.findall(r'<td>(.*?)</td>', re.search(
            rf'<tr data-owner-fid="{fid}">(.*?)</tr>', owner).group(1))
        assert re.findall(r': <b>(.*?)</b>', brief) == expected
        assert 'Деньги:</b> покрытие для проверки' in brief
        page = (state_page(row, brief) if fid == 1097 else
                faction_page(card, row, [], brief=brief))
        assert re.search(r'</h1>\s*<section class="faction-summary"', page)
        assert page.count('class="faction-summary"') == 1
        if fid == 1105:
            assert '↓ из ' in brief and ' — в сторону ослабления' in brief
            assert 'да: 2022-12-29 — окончание не указано' in brief
        if fid == 1103:
            assert '↑ из ' in brief and ' — в сторону укрепления' in brief
            assert 'Кнессете:</b> нет' in brief
            assert 'коалиционного соглашения не подписывала' in faction_summary(row, card, "", laws)
        if fid == 1097:
            assert 'направление не установлено' in brief and 'да: 2022-12-29' in brief
    assert 'денежных обещаний не найдено' in faction_summary(
        dict(row, b={"status": "observed", "commitments": 0}), card, "", laws)
    # ── ЧИСЛИТЕЛЬНОЕ СОГЛАСУЕТСЯ С ЧИСЛОМ ────────────────────────────────
    # «2 обязательств» и «остальные не разобраны» при полном разборе — язык
    # сборщика, а не документа; страница Оцма (2 из 2) показала оба 10.10.
    assert [ru_plural(n, "о", "а", "в") for n in (1, 2, 5, 11, 13, 21, 22)] == \
        ["о", "а", "в", "в", "в", "о", "а"], "склонение «обязательство» сломано"
    # ── ДУБЛЬ НЕ СЧИТАЕТСЯ ОБЯЗАТЕЛЬСТВОМ ───────────────────────────────
    # Пометка duplicate_of в записи обязана доехать до счётчика: иначе
    # график 700/800/950 из трёх строк читается как три обещания.
    # Ложный денежный кандидат (not_budgetary) — тоже не обещание денег (F-06):
    # основной + дубль + ложный кандидат = 3 записи / 1 денежное обязательство.
    _dup_card = {"period_id": "t", "data_fingerprint": None, "coverage": {"commitments_total": 3},
                 "snapshots": {"x": "2026"},
                 "commitments": [{"id": "a", "amount_ils": 1, "quote_he": "א", "quote_ru": "а",
                                  "conclusion": "x", "readings": [], "granularity": "exact_takana",
                                  "codes": [], "confidence": "low"},
                                 {"id": "b", "amount_ils": 1, "quote_he": "ב", "quote_ru": "б",
                                  "conclusion": "y", "readings": [], "granularity": "exact_takana",
                                  "codes": [], "confidence": "low", "duplicate_of": "a"},
                                 {"id": "c", "amount_ils": None, "quote_he": "ג", "quote_ru": "в",
                                  "conclusion": "z", "readings": [], "granularity": "not_budgetary",
                                  "codes": [], "confidence": "low"}]}
    import unittest.mock as _m
    with _m.patch(__name__ + ".fingerprint", lambda *_a: None):
        _html = budget_block([_dup_card], {}, [])
    assert "Самостоятельных денежных обязательств 1" in _html, "дубль/ложный кандидат не дошли до счётчика"
    assert "1 запись — продолжение" in _html and "1 запись — без собственной суммы" in _html, _html[:400]
    assert "Разобрано 3 записи" in _html, _html[:200]
    _dup_card["commitments"][2]["granularity"] = "exact_takana"
    with _m.patch(__name__ + ".fingerprint", lambda *_a: None):
        _html = budget_block([_dup_card], {}, [])
    assert "Самостоятельных денежных обязательств 2" in _html, "снятие not_budgetary не сдвинуло счётчик"
    doc, total, filled = build(m)
    # R27-F11: никакого заранее вынесенного «промаха» у всех списков
    assert "промах" not in doc, "рамка снова выносит приговор всем спискам"
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
    assert "в 25-м Кнессете в правительстве не была" in doc, \
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
                                  "acts_without_participation": 1}},
             "snapshots": {"votes_25": "2099-01-02T00:00:00"}}
    frow = {"a": {"status": "observed"},
            "b": {"status": "not_exposed", "note": "соглашения не подписывала"}}
    fv = [{"date": "2022-12-13", "name_ru": "Законопроект",
           "name_he": "\u05d4\u05e6\u05e2\u05ea", "for_option_desc": "\u05dc\u05d4\u05e2\u05d1\u05d9\u05e8",
           "pos": "против 5"}]
    fp = faction_page(fcard, frow, fv)
    # R27-F09: у «за» русский смысл рядом с оригиналом
    assert "передать акт дальше<span class=he" in fp, "у опции голосования нет русского смысла"
    # R8-F10/F11: дата снимка — из карточки, исход поиска — по-русски
    assert "Снимок голосований: 2099-01-02" in fp, "дата снимка в подвале не из карточки"
    assert "честный поиск ничего не дал" in fp and ">nothing<" not in fp \
        and "опровергнуть:</b> nothing" not in fp, "исход поиска выведен служебным ключом"
    # ожидание записано буквально, не берётся из того же словаря (R15-F03)
    for oc, ru in (("found", "контрсвидетельство найдено и включено"),
                   ("contradictory", "свидетельства противоречивы, доминирующего вывода нет")):
        fc = dict(fcard, counter_search=dict(fcard["counter_search"], outcome=oc))
        assert f"опровергнуть:</b> {ru}" in faction_page(fc, frow, fv), \
            f"исход {oc} не переведён"
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
    # R8-F04, решение владельца 18.10: разобранная партия — не «пустая».
    # Ожидаемые слова записаны здесь, а не взяты из CELL: мутант словаря
    # обязан покраснеть.
    mr, _, fl_r = rows(mk_m("observed"), {1110: fcard_ax}, {1110: "в бюджете нашлась строка под 1 из 2 обещаний"})
    assert "в бюджете нашлась строка под 1 из 2 обещаний" in mr and "искали, не нашли" not in mr, \
        "разобранная партия показана как «искали, не нашли»"
    assert fl_r == fl_o, "«разобрано — без вывода» посчитано как заполненная клетка"
    assert "разобрано" not in mo, "партия без карточки разбора получила «разобрано»"
    mz_m = mk_m("observed")
    mz_m["lines"][0]["b"]["commitments"] = 0
    mz, _, _ = rows(mz_m, {1110: fcard_ax})
    assert "искали, не нашли" in mz and "денежных обещаний в соглашении не найдено" in mz, \
        "R19-F01: пустая карта извлечения показана не как «искали, не нашли»"
    mz_m["lines"][0]["b"]["commitments"] = 3
    mn, _, _ = rows(mz_m, {1110: fcard_ax})
    assert "мы сюда не дошли" in mn and "искали" not in mn, \
        "извлечённые, но не разобранные обещания показаны как «искали, не нашли»"
    # R19-F01: обзор и страница отвечают одним значением
    _pg = lambda w: f"<summary>Деньги — <b class=tx-none>{w}</b></summary>"
    check_money_same(mz, _pg("искали, не нашли"), 1110)
    try:
        check_money_same(mz, _pg("мы сюда не дошли"), 1110)
    except Refuse:
        pass
    else:
        raise AssertionError("обзор «искали» и страница «не дошли» прошли вместе")
    # R19-F02 (M06): проводка обзора — разобранная строка без клетки
    # «разобрано» и неразобранная с ней отвергаются.
    check_overview_money(mr, {1110}, {1110})
    try:
        check_overview_money(mr.replace("под 1 из 2", "под 2 из 2"),
                             {1110: "в бюджете нашлась строка под 1 из 2 обещаний"})
    except Refuse:
        pass
    else:
        raise AssertionError("подменённое денежное число прошло")
    # R22-F02 (W04b): строка без денежной клетки и чужая клетка отвергаются
    no_eq = re.sub(r"<td class=c-eq[^>]*>.*?</td>", "", mo, flags=re.S)
    for bad_doc, bad_set, lines in ((mo, {1110}, {1110}), (mr, set(), {1110}),
                                    (no_eq, set(), {1110}), (mo, set(), {1110, 1111})):
        try:
            check_overview_money(bad_doc, bad_set, lines)
        except Refuse:
            pass
        else:
            raise AssertionError("обзор с потерянной проводкой разборов прошёл")
    dr, tr, fr = build(mk_m("observed"), {1110: fcard_ax}, {1110: "в бюджете нашлась строка под 1 из 2 обещаний"})
    assert f"в 1 показано покрытие обещаний бюджетными строками; в остальных {tr - fr - 1}" in dr, \
        "счёт пустых клеток включил разобранную"
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
    assert "она его не подписывала" in fp, "R21: у ненаблюдаемой партии не назван предмет поиска"
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
           # все поля, не только conclusion: ссылки в прочтениях и в области
           # поиска тоже подставляются (b1ca545, R6-F08)
           for code, year, _ in REF_NUM.findall(repr(c))}
    bc[0]["data_fingerprint"] = fingerprint(bc[0], idx, [])
    block = budget_block(bc, idx, [])
    shas = faction_page(fcard, frow, fv, block, budget_summary(bc))
    # R18-F02: журнал правок Ноам (why версии с «блок noam-p2-79») доходит
    # до читателя через budget_block переведённым — снятый вызов
    # reader_terms у why краснеет здесь, а не только в отдельной функции.
    nb = copy.deepcopy(load_cards("party_period")[1107])
    nidx = {(code, int(year)): {"net_allocated": 1000, "net_executed": 2000}
            for c in nb[0]["commitments"] for code, year, _ in REF_NUM.findall(repr(c))}
    nidx.update({(code, int(year)): {"net_allocated": 1000, "net_executed": 2000}
                 for code, year, _ in REF_NUM.findall(repr(nb[0]))})
    nb[0]["data_fingerprint"] = fingerprint(nb[0], nidx, [])
    nvis = re.sub(r"<[^>]+>", " ", budget_block(nb, nidx, []))
    assert "блок запись строки 79" in nvis and "noam-p2-79" not in nvis, \
        "журнал правок Ноам показал читателю внутренний ID"
    check_budget_page(shas, bc, idx, [])
    assert "123 000 ₪" in shas and "{0022010213" not in shas
    assert jargon(shas) is None, jargon(shas)
    # Перевод — только отдельного слова; имена файлов, `код` и «цитата» целы
    assert reader_terms("Исправлено поле coverage.why.") == \
        "Исправлено поле пояснение к охвату.", reader_terms("Исправлено поле coverage.why.")
    for keep in ("файл conclusion.py", "ключ readings_extra", "not_found_count=2",
                 "код `coverage.why`", "буквально «human_undecided»",
                 "xconclusion", "`conclusion + 1`", "`x = coverage.why + 1`",
                 "«conclusion изменено»", "«поле coverage.why изменено»",
                 '"coverage.why"', "conclusion.PY"):
        assert reader_terms(keep) == keep, (keep, reader_terms(keep))
    assert reader_terms("дубль noam-p2-79") == "дубль запись строки 79"
    # R18-F01/F02: ID и имена файлов в буквальных формах сохраняются целиком;
    # каждое семейство ID в прозе переводится. Ожидания записаны руками.
    for keep in ("«дубль noam-p2-79»", '"дубль shas-p32-1653"', "`rz-p10-477`",
                 "noam-p2-79.pdf", "conclusion.sql", "conclusion.png",
                 "prefix-noam-p2-79-suffix", "prefix-noam-p2-79", "noam-p2-79-x",
                 "файл otzma-p7-420.json"):
        assert reader_terms(keep) == keep, (keep, reader_terms(keep))
    for raw, want in (("дубль shas-p32-1653.", "дубль запись строки 1653."),
                      ("см. rz-p10-477", "см. запись строки 477"),
                      ("и yt-p5-945,", "и запись строки 945,"),
                      ("(otzma-p7-420)", "(запись строки 420)"),
                      ("блок noam-p2-79", "блок запись строки 79"),
                      ("uright-p1-12 —", "запись строки 12 —"),
                      ("поле coverage.why.", "поле пояснение к охвату.")):
        assert reader_terms(raw) == want, (raw, reader_terms(raw))
    # R13-F02/R15-F04: поле выгрузки не выдаётся за порядковую глубину
    assert reader_terms("в title_level6") == "в название родительского узла", \
        reader_terms("в title_level6")
    assert "уровень" not in reader_terms("title_level6 и title_level4")
    # R18-F03: направление родства — точный текст, не отсутствие слова
    # (цепочка 0054500124 → 00545001 → 005450 проверена по JSON)
    assert reader_terms("title_level4") == "название узла уровнем выше", \
        reader_terms("title_level4")
    # Ключи схемы не доходят до читателя ни в выводах, ни в журнале правок
    # (R10-F07): журнал ШАС содержит «coverage.why» — без перевода краснеет.
    import html as _html
    vis = _html.unescape(re.sub(r"<[^>]+>", " ", shas))
    for key in ("coverage.why", "subset_of_line", "not_budgetary", "quote_ru",
                "title_level6", "human_undecided", "absence_is_about"):
        assert key not in vis, f"служебный ключ {key!r} виден читателю"

    def rejects(label, action):
        try:
            action()
        except Refuse as exc:
            print(f"КРАСНЫЙ (пойман), {label}: {exc}")
        else:
            raise AssertionError(f"мёртвый оракул: {label}")

    _amts = [c.get("amount_ils") for c in bc[0]["commitments"]]
    c0 = next(c for c in bc[0]["commitments"]
              if c.get("amount_ils") and _amts.count(c["amount_ils"]) > 1)
    t0 = f'<article id="{esc(c0["id"])}">'
    a0 = shas.find(t0)
    lab0 = f"Сумма в соглашении: {money(c0['amount_ils'])}"
    cut = shas[:a0] + shas[a0:].replace(lab0, "Сумма в соглашении: ?", 1)
    rejects("сумма удалена у своего обязательства", lambda: check_budget_page(
        cut, bc, idx, []))
    rejects("бюджетный блок удалён", lambda: check_budget_page(
        shas.replace(block, ""), bc, idx, []))
    rejects("старая проза канала денег", lambda: check_budget_page(
        shas + "<p>партия правила, сопоставление обязательств не построено</p>", bc, idx, []))
    rejects("сырой счёт ожиданий", lambda: check_budget_page(
        shas + "<p>ожидают решения о сопоставлении: 24</p>", bc, idx, []))
    rejects("клетка «разобрано» снята", lambda: check_budget_page(
        shas.replace(budget_summary(bc), "разбор обязательств"), bc, idx, []))
    # R22-F02 (W03): та же строка заголовка вне <summary> не считается
    rejects("заголовок вынесен из summary абзацем", lambda: check_budget_page(
        shas.replace(f"<summary>Деньги — <b class=tx-rev>{budget_summary(bc)}</b>",
                     f"<p>Деньги — <b class=tx-rev>{budget_summary(bc)}</b></p>"
                     "<summary>Деньги — <b class=tx-none>искали, не нашли</b>"), bc, idx, []))
    rejects("заголовок клетки подменён, фраза осталась абзацем", lambda: check_budget_page(
        shas.replace(f"Деньги — <b class=tx-rev>{budget_summary(bc)}</b>",
                     "Деньги — <b class=tx-none>искали, не нашли</b>")
        + "<p>разобрано — без вывода</p>", bc, idx, []))
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


ALIAS = {1097: 1105}   # строка бюллетеня → фракция с теми же голосами (владелец 19.10)
ALIAS_RU = {1097: "Религиозный сионизм — строка бюллетеня (голоса фракции Смотрича)"}


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


# Журнал правок хранится как написан (§15), но читатель видит не ключи схемы,
# а их названия (ревью 18.10, R8-F11, R10-F07). Перевод — только при показе.
READER_TERMS = {
    "coverage.why": "пояснение к охвату", "quote_ru": "русский перевод цитаты",
    "quote_he": "ивритская цитата", "duplicate_of": "пометка дубля",
    "not_budgetary": "«не денежное обязательство»",
    "subset_of_line": "«часть строки бюджета»",
    "spread_over_lines": "«размазано по нескольким строкам»",
    "exact_takana": "«одна бюджетная статья»", "not_found": "«не найдено»",
    "required_in_base": "«требуется в базе»", "human_undecided": "«носитель не выбран»",
    # title_levelN — поле выгрузки, а не порядковая глубина узла (R13-F02)
    "title_level6": "название родительского узла",
    "title_level4": "название узла уровнем выше",
    "granularity": "категория сопоставления", "counter_search": "поиск опровержения",
    "readings": "прочтения", "conclusion": "вывод", "rejection_reason": "причина отказа",
}


def reader_terms(text: str) -> str:
    """Перевод ключа — только в прозе. Буквальные сегменты целиком не
    трогаются: `код`, «цитата», "цитата", имена файлов (R13-F03, R15-F02).
    Внутренние ID записей (shas-p32-1653) показываются как «запись строки N»
    (R15-F01): читателю они ничего не говорят."""
    # Имя файла — любое латинское расширение 2–5 знаков (R18-F01: список
    # py|md|… портил .pdf/.sql/.png). Ключ схемы с точкой (coverage.why)
    # выглядит так же, поэтому токен-ключ отдаётся прозе.
    lit = re.compile(r"`[^`]*`|«[^»]*»|\"[^\"]*\"|"
                     r"[^\s(]+\.[A-Za-z0-9]{2,5}\b")
    out, pos = [], 0
    for m in lit.finditer(text):
        if m.group(0) in READER_TERMS:
            continue
        out.append(_terms_prose(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_terms_prose(text[pos:]))
    return "".join(out)


def _terms_prose(text: str) -> str:
    # Только полный токен: часть составного имени (prefix-noam-p2-79-x) —
    # не ID записи (R18-F01).
    text = re.sub(r"(?<![\w.-])(?:shas|rz|yt|otzma|noam|uright)-p\d+-(\d+)(?![\w-])",
                  r"запись строки \1", text)
    for k in sorted(READER_TERMS, key=len, reverse=True):
        text = re.sub(r"(?<![\w./`«-])" + re.escape(k) + r"(?![\w`»-])",
                      READER_TERMS[k], text)
    return text


def budget_summary(cards: list) -> str:
    commitments = [c for card in cards for c in card.get("commitments", [])
                   if not c.get("duplicate_of") and c.get("granularity") != "not_budgetary"]
    found = sum(c.get("granularity") in ("exact_takana", "subset_of_line", "spread_over_lines")
                for c in commitments)
    return CELL["reviewed"][1].format(n=found, m=len(commitments))


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
        # Ложный денежный кандидат (not_budgetary) — тоже запись, не обещание
        # денег (ревью 18.10, F-06): знаменатель — денежные обязательства.
        dups = [c for c in card.get("commitments") or [] if c.get("duplicate_of")]
        nonmoney = [c for c in card.get("commitments") or []
                    if not c.get("duplicate_of") and c.get("granularity") == "not_budgetary"]
        uniq = n - len(dups) - len(nonmoney)
        parts = []
        if dups:
            parts.append(f"{len(dups)} {ru_plural(len(dups), 'запись', 'записи', 'записей')} — "
                         "продолжение другого пункта (помечено в самой записи)")
        if nonmoney:
            parts.append(f"{len(nonmoney)} {ru_plural(len(nonmoney), 'запись', 'записи', 'записей')} — "
                         "без собственной суммы (разобрано, но денег не обещает)")
        dup_note = ("" if not parts else
                    f" Самостоятельных денежных обязательств {uniq}: " + "; ".join(parts) + ".")
        out.append(f'<section data-budget="{esc(card["period_id"])}">'
                   f'<p>Период: {esc(card["period_id"])}. Разобрано '
                   f'{n} {ru_plural(n, "запись", "записи", "записей")} из '
                   f'{esc(total)}; {tail}.{esc(dup_note)}</p>')
        out.append('<p>Снимки источников: ' + esc(
            "; ".join(f"{k} — {v}" for k, v in sorted(card["snapshots"].items()))) + '</p>')
        for c in card.get("commitments") or []:
            amt = ("не указана" if c.get("amount_ils") is None
                   else money(c["amount_ils"]))
            out.append(f'<article id="{esc(c["id"])}"><p>Сумма в соглашении: '
                       f'{amt}</p>'
                       + render_commitment(c, idx, titles, []) + '</article>')
        out.append('<p>Журнал исправлений:</p><ul>' + ''.join(
            f'<li>{esc(r["date"])} · версия {esc(r["version"])}: '
            f'{esc(reader_terms(str(r["what"])))} — {esc(reader_terms(str(r["why"])))}</li>'
            for r in card.get("revisions") or []) + '</ul></section>')
    return "".join(out)


def reviewed_from_files() -> set:
    """Фракции с непустой карточкой разбора — по файлам *-gov37.yaml, мимо
    load_cards (независимый путь для сверки, R22-F01)."""
    from validate_cards import load_yaml_ish
    out = set()
    for p in (ROOT / "cards").glob("*-gov37.yaml"):
        c = load_yaml_ish(p)
        if c.get("commitments"):
            out.add(int(str(c["period_id"]).split("-")[0]))
    return out


def _money_td(doc: str, fid: int) -> str:
    """Ровно одна строка обзора этой фракции и ровно одна её клетка «деньги»
    (R22-F02, W04b: регулярка через </tr> брала клетку соседней строки)."""
    trs = [tr for tr in re.findall(r"<tr>(.*?)</tr>", doc, flags=re.S)
           if f'href="f-{fid}.html"' in tr]
    if len(trs) != 1:
        raise Refuse(f"строк обзора у {fid}: {len(trs)}, а не одна")
    eq = re.findall(r"<td class=c-eq[^>]*>(.*?)</td>", trs[0], flags=re.S)
    if len(eq) != 1:
        raise Refuse(f"клеток «деньги» в строке {fid}: {len(eq)}, а не одна")
    return eq[0]


def _cell_word(html: str, where: str) -> str:
    words = [w for _, w, _ in CELL.values() if f"{w}<span class=lb>" in html
             or f">{w}</b>" in html]
    words += re.findall(r"в бюджете нашлась строка под [0-9]+ из [0-9]+ обещаний(?=<span class=lb>|</b>)", html)
    if len(words) != 1:
        raise Refuse(f"{where}: значений клетки {words}, а не одно")
    return words[0]


def _money_summaries(page: str) -> list:
    """Заголовки денежной клетки — только внутри <summary> (R22-F02, W03)."""
    return [x for x in re.findall(r"<summary>(.*?)</summary>", page, flags=re.S)
            if x.lstrip().startswith("Деньги — ")]


def check_overview_money(doc: str, reviewed: set | dict, lines: set | None = None) -> None:
    """R19-F02/R22-F02: у каждой строки бюллетеня ровно одна клетка «деньги»,
    и денежное покрытие стоит ровно у разобранных."""
    lines = set(lines) if lines is not None else set(reviewed)
    if not set(reviewed) <= lines:
        raise Refuse(f"разобранные вне строк бюллетеня: {sorted(set(reviewed) - lines)}")
    for fid in lines:
        if (fid in reviewed) != (_cell_word(_money_td(doc, fid), f"обзор {fid}")
                                 .startswith("в бюджете нашлась строка под ")):
            raise Refuse(f"клетка «деньги» строки {fid} не согласована с разбором")
        if isinstance(reviewed, dict) and fid in reviewed:
            if _cell_word(_money_td(doc, fid), f"обзор {fid}") != reviewed[fid]:
                raise Refuse(f"денежное покрытие строки {fid} не совпало с карточками")


def check_money_same(doc: str, page: str, fid: int, unresolved: bool = False) -> None:
    """R19-F01: обзор и страница фракции отвечают одним значением. Строка
    без установленной связи (1097) денежной клетки на странице не имеет, а в
    обзоре — «мы сюда не дошли» (R22: проверяется, а не пропускается)."""
    a = _cell_word(_money_td(doc, fid), f"обзор {fid}")
    heads = _money_summaries(page)
    if unresolved:
        if heads or a != "мы сюда не дошли":
            raise Refuse(f"f-{fid}: строка без связи получила денежный вывод")
        return
    if len(heads) != 1:
        raise Refuse(f"f-{fid}: денежных заголовков {len(heads)}, а не один")
    if _cell_word(heads[0], f"f-{fid}") != a:
        raise Refuse(f"f-{fid}: клетка «деньги» в обзоре ({a}) и на странице расходятся")


def check_budget_page(page: str, cards: list, idx: dict, titles: list) -> None:
    """Отсутствие любого готового разбора — отказ, даже если остальная страница цела."""
    # Разбор есть — проза «не построено» / сырой счёт ожиданий карты
    # извлечения ему противоречит (R8-F04/F05): отказ, а не две версии.
    if cards:
        for stale in ("не построено", "ожидают решения о сопоставлении"):
            if stale in page:
                raise Refuse(f"страница с разбором обязательств говорит «{stale}»")
        # именно в заголовке денежной клетки (R19-F02, M11), не где угодно
        if [_cell_word(h, "страница") for h in _money_summaries(page)] != [budget_summary(cards)]:
            raise Refuse("денежное покрытие в заголовке не совпало с карточками")
    for card in cards:
        for date in card["snapshots"].values():
            if esc(date) not in page:
                raise Refuse("дата снимка бюджетного разбора потеряна")
        for c in card.get("commitments") or []:
            amt = ("не указана" if c.get("amount_ils") is None
                   else money(c["amount_ils"]))
            # у СВОЕГО обязательства: равная сумма соседа не маскирует потерю
            # (R13-F06)
            tag = f'<article id="{esc(c["id"])}">'
            seg = page[page.find(tag):page.find("</article>", page.find(tag))] \
                if tag in page else ""
            if f"Сумма в соглашении: {amt}" not in seg:
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


def faction_summary(row: dict, card: dict, money_text: str, laws: list[dict]) -> str:
    """Четыре строки из уже рассчитанных данных, без наследования фракций."""
    from slice_party_theme import load_periods
    fid = row["anchor_id"]
    ax = card.get("axis_institutions") or {}
    direction = "направление не установлено"
    if row["a"]["status"] == "observed" and ax.get("arrow") in ("up", "down", "both") and alpha_ok(ax):
        direction = (f'{CELL[ax["arrow"]][0]} из {ax["acts"]} законов темы, по которым '
                     f'фракция голосовала, {ax["down"]} — в сторону ослабления, '
                     f'{ax["up"]} — в сторону укрепления')
    positions = '; '.join(
        f'<a href="grounds.html#a{law["bill"]}">{esc(law["name"])}</a>: '
        f'<b>{esc(law["positions"][str(fid)])}</b> ({esc(law["date"])})' for law in laws)
    if not money_text:
        money_text = ("коалиционного соглашения не подписывала" if row["b"]["status"] == "not_exposed"
                      else "денежных обещаний не найдено" if row["b"].get("commitments") == 0
                      else "сопоставление денежных обещаний с бюджетом не построено")
    periods = load_periods(fid)
    dates = '; '.join(p["start"] + ' — ' + (p["finish"] if p["finish"] != "null" else "окончание не указано")
                      for p in periods)
    government = "да: " + dates if periods else "нет"
    return (f'<section class="faction-summary" aria-label="Коротко о фракции">'
            f'<p><b>Суд, парламент, свободы:</b> {esc(direction)}.</p>'
            f'<p><b>Четыре закона владельца — последняя стадия:</b> {positions}.</p>'
            f'<p><b>Деньги:</b> {esc(money_text)}.</p>'
            f'<p><b>В правительстве в 25-м Кнессете:</b> {esc(government)}.</p></section>')


def state_page(row: dict, brief: str = "") -> str:
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
{brief}
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
            row["b"]["commitments"] = maps[row["anchor_id"]]["commitments"]
    cards = load_cards()
    budgets = load_cards("party_period")
    idx, titles = budget_index() if budgets else ({}, [])
    reviewed = {k for k, v in budgets.items() if v}
    # R22-F01 (W01): набор разборов сверяется с файлами карточек независимым
    # путём — пропущенная загрузка иначе согласованно опустошает все стражи.
    if reviewed != reviewed_from_files():
        raise Refuse(f"разборы загружены не все: {sorted(reviewed)} против "
                     f"{sorted(reviewed_from_files())} по файлам")
    # Покрытие вместо точности (владелец 19.10): строка без собственных
    # голосований получает данные фракции с той же цепочкой преемственности
    # (1097 «הציונות הדתית» — цепочка 961→1073→1077… та же, что у 1105).
    for r in m["lines"]:
        src = ALIAS.get(r["anchor_id"])
        if src and src in cards:
            srow = next(x for x in m["lines"] if x["anchor_id"] == src)
            r["a"], r["b"] = dict(srow["a"]), dict(srow["b"])
            # своё имя строки бюллетеня, а не «(Смотрич)» второй раз
            cards[r["anchor_id"]] = dict(cards[src], party_ru=ALIAS_RU.get(r["anchor_id"], cards[src].get("party_ru")),
                                          party_he=r["line"])
            if budgets.get(src):
                budgets[r["anchor_id"]] = budgets[src]
    summaries = {fid: budget_summary(bc) for fid, bc in budgets.items() if bc}
    doc, total, filled = build(m, cards, summaries)
    check_overview_money(doc, summaries,
                         {r["anchor_id"] for r in m["lines"]})
    bad = jargon(doc)
    if bad:
        print(f"ОТКАЗ: внутренний язык в обзоре: {bad}")
        return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    laws = owner_law_positions([str(r["anchor_id"]) for r in m["lines"]])
    pages = 0
    for r in m["lines"]:
        c = cards.get(r["anchor_id"])
        brief = faction_summary(r, c or {}, summaries.get(r["anchor_id"], ""), laws)
        if r["a"]["status"] == "lineage_unresolved":
            page = state_page(r, brief)
            check_money_same(doc, page, r["anchor_id"], unresolved=True)
        elif not c:
            raise Refuse(f"нет карточки наблюдаемой строки {r['anchor_id']}")
        else:
            bc = budgets.get(r["anchor_id"], [])
            budget = budget_block(bc, idx, titles) if bc else ""
            page = faction_page(c, r, votes_for(ALIAS.get(r["anchor_id"], r["anchor_id"])),
                                budget, budget_summary(bc), brief)
            check_budget_page(page, bc, idx, titles)
            check_money_same(doc, page, r["anchor_id"])
        bad = jargon(page)
        if bad:
            print(f"ОТКАЗ: внутренний язык на f-{r['anchor_id']}.html: {bad}")
            return 1
        (OUT.parent / f"f-{r['anchor_id']}.html").write_text(page, encoding="utf-8")
        pages += 1
    print(f"обзор + {pages} страниц фракций -> {OUT.parent}")
    rev = doc.count('tx-rev">')   # клетки, не легенда (R22-F05)
    print(f"ЗАМЕР: клеток {total}, заполнено {filled}, разобрано без вывода {rev}, "
          f"пусто {total - filled - rev}")
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


_SIGNS = {}


def _gloss(desc: str) -> str:
    """Русский смысл опции голосования из справочника смыслов «за»."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_landmark_table import gloss
    if not _SIGNS:
        from direction_confidence import sign_table
        _SIGNS.update(sign_table())
    return gloss(desc, _SIGNS)


def faction_page(card: dict, row: dict, votes: list, budget: str = "", summary: str = "", brief: str = "") -> str:
    """Страница фракции. Клетка оси — details, как в макете; счёт
    голосований уходит ВНУТРЬ раскрытия, а не вываливается на страницу."""
    ru, he = with_leader(card.get("faction_id") or 0, card.get("party_ru") or ""), card.get("party_he")
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
        s2, c2 = (f'Деньги — <b class=tx-rev>{esc(summary)}</b>',
                  "самостоятельные денежные обязательства из коалиционного соглашения")
    elif row["b"]["status"] == "observed" and row["b"].get("commitments") == 0:
        # R19-F01: та же клетка, что в обзоре; сырой нулевой счёт карты не
        # печатается — он ничего не говорит читателю.
        s2, c2 = ('Деньги — <b class=tx-none>искали, не нашли</b>',
                  "в коалиционном соглашении денежных обещаний не найдено")
        budget = ('<p>В тексте коалиционного соглашения фракции не найдено ни '
                  'одного денежного обещания, поэтому сверять с бюджетом нечего. '
                  'Полнота распознавания текста соглашения отдельно не '
                  'перепроверялась.</p>')
    elif row["b"]["status"] == "not_exposed":
        # R21: холодное чтение не поняло, что искали. Предмет назван.
        s2, c2 = ('Деньги — <b class=tx-none>искали, не нашли</b>',
                  "коалиционного соглашения у этой фракции нет: она его не "
                  "подписывала, и сверять денежные обещания с бюджетом не с чем")
        budget = ('<p>В 25-м Кнессете фракция в правительство не входила и '
                  'коалиционного соглашения не подписывала. Это не результат '
                  'проверки, не выявившей проблем, и не обвинение.</p>')
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
                f'{esc(OUTCOME_RU.get(cs.get("outcome"), cs.get("outcome")))}</p><ul class=dim>{where}</ul>'
                f'<p class=dim>{esc(cs.get("note", ""))}</p>'
                f'<p><b>Уверенность:</b> {esc(CERT.get(card.get("confidence")))} — '
                f'{esc(card.get("confidence_reason"))}</p>'
                f'<p><b>Чем это опровергается.</b> '
                f'{esc(card.get("what_would_falsify"))}</p></div>')
    acts = "".join(
        f'<tr><td data-l="дата">{esc(x["date"])}</td>'
        f'<td data-l="акт">{esc(x["name_ru"])}'
        f'<span class="he" lang=he dir=rtl><bdi>{esc(x["name_he"])}</bdi></span></td>'
        # R27-F09: русский смысл опции рядом с оригиналом; нет перевода —
        # сборка отказывает (gloss), а не показывает голый иврит.
        f'<td data-l="«за» означало">{esc(_gloss(x["for_option_desc"]))}'
        f'<span class=he lang=he dir=rtl>'
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
{brief}
{''.join(cells)}
{''.join(body)}
<div class=foot><p>Первая грубая итерация, 19.10.2026. Форма принята
01.08.2026. Снимок голосований: {esc(str((card.get("snapshots") or {}).get("votes_25", "не указан"))[:10])}.</p></div>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
