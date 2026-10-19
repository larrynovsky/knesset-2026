#!/usr/bin/env python3
"""Генератор отчёта — единственный выход проекта. §11–§17.

Что этот модуль делает и, важнее, чего НЕ делает.

НЕ считает ничего. Числа берутся из выгрузки по ссылкам карточки и
подставляются как есть. Ни одной функции агрегирования здесь нет — не
«не вызывается», а не существует (§13). Вывод — статический HTML без
единой строки JavaScript и без единой таблицы: сортировать нечего и
нечем, потому что сортируемая колонка «качества» и есть тот рейтинг,
против которого написан проект.

НЕ дублирует контракт карточки. `validate_cards.check_card` вызывается
отсюда целиком. Причина не в лени: `data/` заигнорен и на MacBook его нет,
поэтому pre-commit прогоняет валидатор БЕЗ выгрузки и проверки ссылок на
числа там не выполняются никогда. Генератор работает на Studio, где данные
есть, — и это единственное место, где полный контракт реально исполняется.
Механизм, срабатывающий лишь там, где он бессилен, защищает вызов (§24).

ЧТО ОХРАНЯЕТ ОСОБО — расхождение прозы и чисел (§11 на рендере).
Вывод в карточке написан человеком по срезу данных на дату `snapshots`.
Числа подставляются при сборке. obudget перерезает таблицы задним числом,
и между написанием и сборкой значение может измениться: фраза «база
выросла» останется, число под ней перестанет это показывать. Документ
начнёт противоречить сам себе, и заметит это читатель, а не мы.
Механизм: `data_fingerprint` — свёртка множества ЯЧЕЕК, которые читает
карточка. Пишется осознанно (`--stamp`), проверяется при каждой сборке,
расхождение — отказ со списком текущих значений.

Почему свёртка, а не сверка времени выгрузки: сверка времени краснела бы на
каждой штатной перевыгрузке, ничего не изменившей. Сторож, кричащий на
норму, обучает себя игнорировать — это ровно тот дефект, который уже был
допущен в детекторе потери манифеста 30.07.

Почему это не нарушает §14 («карточка не кэширует числа»): свёртка
необратима. Её нельзя отрендерить и нельзя из неё восстановить сумму.
Она умеет ровно одно — краснеть.

    python3 scripts/build_report.py            # собрать site/
    python3 scripts/build_report.py --stamp    # пересчитать отпечатки карточек
    python3 scripts/build_report.py --selftest # 13 провокаций, работает без data/

Вывод: 0 — собрано · 1 — отказ · 2 — внутренняя ошибка (блок).
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_cards as vc  # noqa: E402  — контракт карточки, не копия

ROOT = vc.ROOT
CARDS = vc.CARDS
SITE = ROOT / "site"
CHANGES = ROOT / "data" / "budget_changes.json"

# Файлы, которые порождает генератор. Всё, что окажется в site/ кроме них, —
# отказ: каталог отдаётся наружу целиком, и посторонний файл там публикуется
# вместе с отчётом (ровно поэтому отчёт не пишется в report/, где лежат
# внутренние разведочные страницы).
OUTPUTS = ("index.html", "robots.txt")

# Символы, переставляющие ОТОБРАЖАЕМЫЙ текст, не меняя байтов: встраивание,
# override и изоляция направления. html.escape их не трогает, посимвольное
# сравнение с источником проходит, а на экране цитата читается иначе.
# Цитаты приходят из OCR ивритских сканов — это граница доверия, и здесь
# отказ, а не тихая чистка: тихая чистка тоже меняет цитату.
BIDI = frozenset(range(0x202A, 0x202F)) | frozenset(range(0x2066, 0x206A))

READING_RU = {"weakening": "ослабляющее", "strengthening": "усиливающее",
              "reframing": "переформулирующее"}
CONF_RU = {"high": "высокая", "medium": "средняя", "low": "низкая", "none": "нет"}
OUTCOME_RU = {
    "found": "контрсвидетельство найдено и включено",
    "nothing": "честный поиск ничего не дал",
    "contradictory": "свидетельства противоречивы, доминирующего вывода нет",
}
CHAN_RU = {"allocated": "база", "revised": "после пересмотра",
           "executed": "исполнено", "transfers": "переносы"}
GRAN_RU = {
    # Прежняя метка «код статьи назван в самом обязательстве» утверждала то,
    # чего exact_takana не означает (criteria: совпадение с одной 10-значной
    # строкой); верна была 1 записи из 7 (ревью 18.10, R6-F07).
    "exact_takana": "сопоставлено с одной бюджетной статьёй",
    "subset_of_line": "часть строки бюджета",
    "spread_over_lines": "размазано по нескольким строкам",
    "not_found": "в бюджете на публикуемой глубине не найдено",
    "not_budgetary": "не денежное обязательство",
}


class Refuse(Exception):
    """Отказ сборки. Публиковать нечего — это состояние, а не предупреждение."""


# ------------------------------------------------------------------ разметка

def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Форма для целого счётчика; падеж задаёт вызывающий (из: закона/законов/законов)."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def esc(s) -> str:
    s = str(s if s is not None else "")
    bad = sorted({hex(ord(c)) for c in s if ord(c) in BIDI})
    if bad:
        raise Refuse(f"управляющие символы направления {bad} в тексте — "
                     f"отображение разойдётся с источником: {s[:60]!r}")
    return html.escape(s)


def as_text(w) -> str:
    """Элемент `searched_where` — либо строка, либо `источник: …`. Прежняя
    редакция звала esc() прямо на словаре и печатала в отчёт python-repr:
    `{'источник': 'raw_budget, поиск…'}`. Читатель видел служебную скобку
    там, где обещана область поиска."""
    if isinstance(w, dict):
        return "; ".join(f"{k}: {v}" for k, v in w.items())
    return str(w)


def money(v) -> str:
    if v is None:
        return "нет значения"
    return f"{v:,.0f}".replace(",", " ") + " ₪"


# ---------------------------------------------------------------- ячейки
def cells(card: dict, idx: dict, titles: list[str]) -> list[tuple[str, object]]:
    """Множество чтений карточки: что именно она берёт из выгрузки.

    Единица согласованности выбрана здесь, и выбор не нейтрален. Весь срез —
    слишком крупно: карточка про религию краснела бы из-за правки в обороне.
    Одна ячейка — слишком мелко: метаданных больше, чем данных. Множество
    ячеек одной карточки — то, от чего зависит именно её проза.
    """
    idx, titles = vc.budget_scope(card, idx, titles)
    out: list[tuple[str, object]] = []
    for c in card.get("commitments") or []:
        concl = c.get("conclusion") or ""
        # Ссылки на числа живут и вне conclusion: прочтения, область поиска,
        # note, опровержение рендерятся с подстановкой (ревью 18.10, R6-F08),
        # значит и их ячейки — часть прочитанного карточкой (§11).
        cs = c.get("counter_search") or {}
        extra = " ".join([*(r.get("text") or "" for r in c.get("readings") or []),
                          *(as_text(w) for w in cs.get("searched_where") or []),
                          cs.get("note") or "", c.get("what_would_falsify") or "",
                          c.get("confidence_reason") or ""])
        for code, year, chan in vc.REF_NUM.findall(extra):
            out.append((f"num|{code}|{year}|{chan}", cell_value(code, int(year),
                                                                chan, idx)))
        for code, year, chan in vc.REF_NUM.findall(concl):
            out.append((f"num|{code}|{year}|{chan}", cell_value(code, int(year),
                                                                chan, idx)))
        for term in vc.REF_ABSENT.findall(concl):
            out.append((f"absent|{term}", sum(1 for t in titles if term in t)))
        for code in vc.REF_NOCODE.findall(concl):
            out.append((f"nocode|{code}", sum(1 for k in idx if k[0] == code)))
    # КАНАЛ А. Без этого блока отпечаток карточки голосований — хеш пустой
    # строки: поле в карточке есть, зелёное, и не сторожит ничего. Такой
    # механизм хуже отсутствующего, потому что выглядит как защита. Поймано
    # 13.08 первым же --stamp: обе новые карточки получили e3b0c442… —
    # sha256 пустоты.
    #
    # Единица та же по смыслу: то, от чего зависит проза ИМЕННО этой
    # карточки. Проза говорит «205 голосований по 138 актам», значит в
    # отпечаток идут числа переписи и фракция, к которой они относятся.
    v = card.get("votes")
    if v:
        out.append(("votes|faction", v.get("faction_id")))
        out.append(("votes|theme", v.get("theme")))
        for k, val in sorted((v.get("census") or {}).items()):
            out.append((f"votes|census|{k}", val))
    return sorted(out)


def cell_value(code: str, year: int, chan: str, idx: dict):
    if chan == "transfers":
        raise Refuse(
            f"канал transfers не реализован ({code}:{year}). Переносы записаны "
            "на кодах длиной 8, обязательства — на 10, и сопоставление между "
            "ними не решено. Перенос не доказывает адресность. Пока решения "
            "нет, ссылка на перенос — отказ, а не пустое место")
    row = idx.get((code, year))
    if row is None:
        raise Refuse(f"ссылка на строку {code} за {year}, которой нет в выгрузке")
    return row.get({"allocated": "net_allocated", "revised": "net_revised",
                    "executed": "net_executed"}[chan])


def fingerprint(card: dict, idx: dict, titles: list[str]) -> str:
    body = "\n".join(f"{k}={v!r}" for k, v in cells(card, idx, titles))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def stamp(path: Path, fp: str) -> None:
    """Записать отпечаток в карточку. Одна строка правится регуляркой:
    писать YAML-сериализатор ради одного поля — заводить второй разбор."""
    txt = path.read_text(encoding="utf-8")
    line = f"data_fingerprint: {fp}"
    if re.search(r"^data_fingerprint:.*$", txt, flags=re.M):
        txt = re.sub(r"^data_fingerprint:.*$", line, txt, flags=re.M)
    elif re.search(r"^card_version:.*$", txt, flags=re.M):
        txt = re.sub(r"^(card_version:.*)$", r"\1\n" + line, txt, flags=re.M)
    else:
        raise Refuse(f"{path.name}: некуда положить отпечаток — нет card_version")
    path.write_text(txt, encoding="utf-8")


# ----------------------------------------------------------------- подстановка
def substitute(text: str, idx: dict, titles: list[str], nulls: list[str]) -> str:
    """Экранируем ДО подстановки: html.escape не трогает фигурные скобки,
    поэтому ссылки переживают экранирование, а вставляемая нами разметка
    не проходит через него повторно."""
    out = esc(text)

    def num(m: re.Match) -> str:
        code, year, chan = m.group(1), int(m.group(2)), m.group(3)
        v = cell_value(code, year, chan, idx)
        if v is None:
            nulls.append(f"{code}:{year}:{chan}")
        return (f'<span class=n>{money(v)}</span>'
                f'<span class=src>[{code} · {year} · {CHAN_RU[chan]}]</span>')

    def absent(m: re.Match) -> str:
        # Текст уже экранирован: «"» стало «&quot;». Искать надо исходный
        # термин, иначе термин с кавычкой «не находится» никогда, и пометка
        # «отсутствие проверено» лжёт (ревью 18.10, R8-F02).
        term = html.unescape(m.group(1))
        hits = [t for t in titles if term in t]
        if hits:
            raise Refuse(f"заявлено отсутствие {term!r}, но оно есть в "
                         f"{len(hits)} названиях статей — утверждение неверно")
        # Подстановка — именная группа, а не предложение. Первая редакция
        # вставляла «не встречается ни разу», и рядом с фразой карточки
        # получалось «Слова «מקוואות» не встречается ни разу нет ни в одном
        # из 17 791 названия». Грамматику держит проза карточки; разметка
        # добавляет только пометку о проверке, как у ссылки на число.
        return (f'<span class=absent>«{esc(term)}»</span>'
                f'<span class=src>[отсутствие проверено]</span>')

    def nocode(m: re.Match) -> str:
        code = m.group(1)
        if any(k[0] == code for k in idx):
            raise Refuse(f"заявлено отсутствие кода {code}, но он есть в выгрузке")
        return (f'<span class=absent>{code}</span>'
                f'<span class=src>[отсутствие проверено]</span>')

    out = vc.REF_NUM.sub(num, out)
    out = vc.REF_ABSENT.sub(absent, out)
    out = vc.REF_NOCODE.sub(nocode, out)
    return out


# --------------------------------------------------------------------- рендер
FRAME = """<section id=frame>
<h1>Что партии обещали в коалиционных соглашениях и что стало деньгами</h1>
<p class=lead>Личный документ к выборам 27 октября 2026 года. Он собран,
чтобы его автор мог объяснить себе свой бюллетень, показав пальцем на
страницу соглашения и на строку бюджета.</p>
<ul class=frame>
<li><b>Темы выбраны автором, а не выведены из данных.</b> Другой человек
выбрал бы другие обязательства и получил бы другую картину.</li>
<li><b>Здесь нет оценок, баллов и рейтинга.</b> Ни числа «качества партии»,
ни сортировки по нему. Документ сообщает, что произошло с деньгами;
вывод делает читатель.</li>
<li><b>Единица наблюдения — партия в период участия в правительстве</b>,
не депутат. В системе с закрытыми списками и антидефекционным законом
активность депутата измеряет должность, а не убеждения.</li>
<li><b>Автор — частное лицо, проект не финансируется никем</b> и ни с кем
не согласован. Ошибки в нём — авторские.</li>
<li><b>Всё проверяемо.</b> Каждое число — ссылка на строку бюджета с кодом
и годом; каждая цитата приведена на иврите рядом с переводом.</li>
</ul>
</section>"""

CSS = """:root{color-scheme:light dark}
body{max-width:46rem;margin:0 auto;padding:2rem 1.2rem 6rem;
font:16px/1.65 Georgia,'Times New Roman',serif;
background:#fbfaf7;color:#1c1a17}
@media(prefers-color-scheme:dark){body{background:#16150f;color:#e8e4da}}
h1{font-size:1.7rem;line-height:1.25;margin:0 0 1rem}
h2{font-size:1.25rem;margin:2.6rem 0 .4rem;border-top:1px solid #c9c2b2;
padding-top:1.2rem}
h3{font-size:1.05rem;margin:2rem 0 .3rem}
.lead{font-size:1.06rem}
ul.frame{padding-left:1.1rem}ul.frame li{margin:.35rem 0}
#frame{border-left:3px solid #8a7f66;padding-left:1rem}
.he{direction:rtl;text-align:right;font-size:1.08rem;margin:.3rem 0}
.meta,.src{font-size:.8rem;color:#6d6455}
.src{margin-left:.25em}
.n{font-variant-numeric:tabular-nums;font-weight:bold}
.absent{border-bottom:1px dotted #6d6455}
.q{background:#f1ece0;padding:.6rem .8rem;margin:.5rem 0}
@media(prefers-color-scheme:dark){.q{background:#232016}}
.r{margin:.45rem 0 .45rem 0}
.r b{font-variant:small-caps}
.cov{border:1px solid #c9c2b2;padding:.8rem 1rem;margin:1.5rem 0}
.foot{margin-top:4rem;font-size:.85rem;color:#6d6455}"""


def render_commitment(c: dict, idx, titles, nulls) -> str:
    from render_overview import reader_terms
    p = [f"<h3>{esc(c.get('quote_ru'))}</h3>"]
    p.append(f'<div class=q><div class=he lang=he dir=rtl>'
             f'<bdi>{esc(c.get("quote_he"))}</bdi></div>'
             f'<div class=he lang=he dir=rtl><bdi>{esc(c.get("heading_he"))}</bdi></div>'
             f'<div class=meta>{esc(c.get("heading_ru"))} · '
             f'страница {esc(c.get("page"))}, строка {esc(c.get("line"))}</div></div>')
    p.append(f"<p>{substitute(reader_terms(c.get('conclusion') or ''), idx, titles, nulls)}</p>")
    # «Год плана и факта» снят: один plan_year не описывает пары лет, которые
    # сравнивает вывод (Ноам 78 — 2023/2024, РС 477 — 2025, Оцма 422 — вне
    # снимка); годы стоят при каждом числе (ревью 18.10, R8-F06).
    p.append(f'<p class=meta>Сопоставление: '
             f'{esc(GRAN_RU.get(c.get("granularity"), c.get("granularity")))}'
             + (f' · раздел бюджета {esc(c["branch"])}' if c.get("branch") else "") + "</p>")
    for r in c.get("readings") or []:
        p.append(f'<p class=r><b>{esc(READING_RU.get(r.get("type")))} '
                 f'прочтение.</b> '
                 f'{substitute(reader_terms(r.get("text") or ""), idx, titles, nulls)}</p>')
    cs = c.get("counter_search") or {}
    where = "".join(f"<li>{substitute(reader_terms(as_text(w)), idx, titles, nulls)}</li>"
                    for w in cs.get("searched_where") or [])
    p.append(f'<p class=r><b>Поиск опровержения.</b> '
             f'{esc(OUTCOME_RU.get(cs.get("outcome"), cs.get("outcome")))}.</p>'
             f'<ul class=meta>{where}</ul>')
    if cs.get("note"):
        p.append(f'<p class=meta>{substitute(reader_terms(cs["note"]), idx, titles, nulls)}</p>')
    p.append(f'<p class=r><b>Уверенность:</b> '
             f'{esc(CONF_RU.get(c.get("confidence")))} — '
             f'{substitute(reader_terms(c.get("confidence_reason") or ""), idx, titles, nulls)}</p>')
    p.append(f'<p class=r><b>Чем это опровергается.</b> '
             f'{substitute(reader_terms(c.get("what_would_falsify") or ""), idx, titles, nulls)}</p>')
    return "\n".join(p)


VOTES_SRC = ROOT / "data" / "votes_25.json"
NAMES_RU = ROOT / "docs" / "reference" / "vote_names_ru_2026-08-13.json"


def votes_of(faction_id: int) -> list[dict]:
    """Голосования фракции — из ВЫГРУЗКИ, не из карточки (§14).

    Перевод названия берётся из справочника и сверяется якорем he_head: если
    название в выгрузке изменилось, перевод устарел, и это ОТКАЗ сборки, а не
    тихо разошедшаяся пара. Тот же механизм, что отпечаток чисел под прозой,
    только для строк: там расходятся данные и суждение о них, здесь —
    оригинал и его перевод.
    """
    if not VOTES_SRC.exists() or not NAMES_RU.exists():
        raise SystemExit(f"ОТКАЗ: нет {VOTES_SRC} или {NAMES_RU}. Сборка "
                         "страницы голосований без выгрузки невозможна; "
                         "гнать её на MacBook нечем (§21).")
    tr = json.loads(NAMES_RU.read_text(encoding="utf-8"))["names"]
    out = []
    for r in json.loads(VOTES_SRC.read_text(encoding="utf-8"))["rows"]:
        cell = next((v for k, v in (r.get("by_faction") or {}).items()
                     if k.split("|", 1)[0] == str(faction_id)), None)
        if cell is None:
            continue
        t = tr.get(str(r["bill_id"]))
        if not t:
            raise SystemExit(f"ОТКАЗ §12: у акта {r['bill_id']} нет перевода "
                             "названия — страница нечитаема для владельца")
        if not r["bill_name"].startswith(t["he_head"]):
            raise SystemExit(f"ОТКАЗ §12: перевод акта {r['bill_id']} устарел, "
                             "название в выгрузке изменилось после перевода")
        out.append({"date": r["date"][:10], "bill_id": r["bill_id"],
                    "name_he": r["bill_name"], "name_ru": t["ru"],
                    "for_option_desc": r.get("for_option_desc") or "",
                    "position": cell})
    out.sort(key=lambda x: (x["date"], x["bill_id"]))
    return out


POS_RU = {"for": "за", "against": "против", "abstain": "воздержались",
          "present": "присутствовали, не голосовали"}


def render_votes(card: dict) -> str:
    """Перепись голосований. Отбора нет: показаны ВСЕ, и потому правила
    отбора не требуется (§3, Snyder)."""
    v = card["votes"]
    cav = v.get("theme_caveat_ru") or ""
    cen = v.get("census") or {}
    rows = votes_of(v["faction_id"])
    p = [f'<div class=cov><b>Перепись голосований — {esc(cav)}.</b> '
         f'{esc(cen.get("votes"))} {plural_ru(cen["votes"], "голосование", "голосования", "голосований")} по {esc(cen.get("acts"))} {plural_ru(cen["acts"], "акту", "актам", "актам")} '
         f'из {esc(cen.get("acts_in_theme_total"))} {plural_ru(cen["acts_in_theme_total"], "акта", "актов", "актов")} темы, '
         f'{esc(cen.get("from"))} — {esc(cen.get("to"))}. '
         f'Актов темы без участия фракции: {esc(cen.get("acts_without_participation"))}. '
         f'Отбор внутри темы не производился: показаны все.</div>']
    if len(rows) != cen.get("votes"):
        raise SystemExit(f"ОТКАЗ §11: карточка объявляет {cen.get('votes')} "
                         f"голосований, выгрузка даёт {len(rows)} — проза и "
                         "данные разошлись")
    for r in rows:
        pos = ", ".join(f"{POS_RU.get(k, k)} {n}" for k, n in r["position"].items())
        p.append(
            f'<div class=vote><p class=vru>{esc(r["date"])} · {esc(r["name_ru"])}</p>'
            f'<p class=he lang=he dir=rtl><bdi>{esc(r["name_he"])}</bdi></p>'
            f'<p class=meta>«За» означало: <span class=he lang=he dir=rtl>'
            f'<bdi>{esc(r["for_option_desc"])}</bdi></span></p>'
            f'<p class=meta>Фракция: {esc(pos)}</p></div>')
    return "\n".join(p)


def render_votes_card(card: dict) -> str:
    """Карточка канала А. Оговорка о теме печатается ДВАЖДЫ и намеренно:
    в шапке переписи и внутри самого вывода. Утверждения путешествуют
    отдельно от документов — скриншотом, абзацем, пересказом, — и оговорка,
    оставшаяся только в шапке, до этих мест не доезжает."""
    p = [f'<h2 id=c-f{esc(card.get("faction_id"))}>{esc(card.get("party_ru"))} '
         f'<span class=he lang=he dir=rtl><bdi>{esc(card.get("party_he"))}'
         f'</bdi></span></h2>']
    snaps = card.get("snapshots") or {}
    p.append(f'<p class=meta>{esc(card.get("knesset"))}-й Кнессет, фракция '
             f'{esc(card.get("faction_id"))} · срез источников: '
             + esc(", ".join(f"{k} — {v}" for k, v in sorted(snaps.items())))
             + '</p>')
    hold = card.get("holdout_checked") or {}
    if not hold.get("period"):
        p.append('<p class=meta>Проверка на отложенном периоде: '
                 f'{esc(hold.get("outcome") or "не проводилась")}</p>')
    p.append(f'<p class=r><b>Что документ утверждает.</b> '
             f'{esc(card.get("conclusion"))}</p>')
    for r in card.get("readings") or []:
        p.append(f'<p class=r><b>{esc(READING_RU.get(r.get("type"), r.get("type")))}.'
                 f'</b> {esc(r.get("text"))}</p>')
    cs = card.get("counter_search") or {}
    where = "".join(f'<li>{esc(as_text(w))}</li>'
                    for w in cs.get("searched_where") or [])
    p.append(f'<p class=r><b>Искал опровержение:</b> {esc(cs.get("outcome"))}</p>'
             f'<ul class=meta>{where}</ul>')
    if cs.get("note"):
        p.append(f'<p class=meta>{esc(cs["note"])}</p>')
    p.append(f'<p class=r><b>Уверенность:</b> '
             f'{esc(CONF_RU.get(card.get("confidence")))} — '
             f'{esc(card.get("confidence_reason"))}</p>')
    p.append(f'<p class=r><b>Чем это опровергается.</b> '
             f'{esc(card.get("what_would_falsify"))}</p>')
    p.append(render_votes(card))
    revs = "".join(f'<li>версия {esc(r.get("version"))}, {esc(r.get("date"))} — '
                   f'{esc(r.get("what"))}</li>' for r in card.get("revisions") or [])
    p.append(f'<p class=meta><b>Журнал правок.</b></p><ul class=meta>{revs}</ul>')
    return "\n".join(p)


def render_card(card: dict, idx, titles, nulls) -> str:
    idx, titles = vc.budget_scope(card, idx, titles)
    if card.get("votes"):
        return render_votes_card(card)
    p = [f'<h2 id=c-{esc(card.get("period_id"))}>{esc(card.get("party_ru"))} '
         f'<span class=he lang=he dir=rtl><bdi>{esc(card.get("party_he"))}'
         f'</bdi></span></h2>']
    snaps = card.get("snapshots") or {}
    p.append('<p class=meta>Период: ' + esc(card.get("period_id"))
             + ' · срез источников: '
             + esc(", ".join(f"{k} — {v}" for k, v in sorted(snaps.items())))
             + '</p>')
    hold = card.get("holdout_checked") or {}
    if not hold.get("period"):
        p.append(f'<p class=meta>Проверка на отложенном периоде: '
                 f'{esc(hold.get("outcome") or "не проводилась")}</p>')
    cov = card.get("coverage") or {}
    if cov:
        p.append(f'<div class=cov><b>Разобрано '
                 f'{esc(cov.get("commitments_analysed"))} обязательств из '
                 f'{esc(cov.get("commitments_total"))}.</b> '
                 f'{esc(cov.get("why"))}<br><span class=meta>Не разобраны '
                 f'строки соглашения: '
                 f'{esc(", ".join(str(x) for x in cov.get("not_analysed_lines") or []))}'
                 f'</span></div>')
    for c in card.get("commitments") or []:
        p.append(render_commitment(c, idx, titles, nulls))
    revs = "".join(f'<li>версия {esc(r.get("version"))}, {esc(r.get("date"))} — '
                   f'{esc(r.get("what"))} ({esc(r.get("why"))})</li>'
                   for r in card.get("revisions") or [])
    p.append(f'<p class=meta><b>Журнал правок.</b></p><ul class=meta>{revs}</ul>')
    return "\n".join(p)


def build(cards: list[tuple[str, dict]], idx: dict, titles: list[str]) -> str:
    """Собрать документ. Ни одной таблицы и ни одной строки JavaScript:
    сортировать нечем — значит колонки «качества» не появится случайно."""
    nulls: list[str] = []
    body = "\n".join(render_card(c, idx, titles, nulls) for _, c in cards)
    snapshots = sorted({v for _, c in cards
                        for v in (c.get("snapshots") or {}).values()})
    срез = snapshots[-1] if snapshots else "не объявлен"
    doc = (
        "<!doctype html>\n<html lang=ru>\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        "<title>Обещания и деньги — личный документ к выборам 27.10.2026</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n"
        f"{FRAME}\n{body}\n"
        f'<p class=foot>Данные бюджета по срезу {esc(срез)}. Документ '
        f'воспроизводится из репозитория прогоном скриптов: числа не '
        f'вписаны руками, а подставлены из выгрузки по коду статьи и году. '
        f'Не индексируется и не распространяется.</p>\n'
        "</body>\n</html>\n")
    if nulls:
        print(f"ссылок, разрешившихся в пустое значение: {len(nulls)} — "
              f"{', '.join(nulls)}", file=sys.stderr)
    return doc


ROBOTS = """# Обход РАЗРЕШЁН намеренно, и это не оплошность.
#
# `Disallow: /` запрещает обход, а не индексацию. Краулер, которому запрещён
# обход, не откроет страницу и не прочитает <meta name="robots"
# content="noindex">, — а URL всё равно может попасть в выдачу по внешней
# ссылке. Запрет обхода и запрет индексации — взаимоисключающая пара, и из
# двух работает только вторая. Поэтому: обход разрешён, noindex стоит в
# каждом документе (CLAUDE.md §16).
User-agent: *
Allow: /
"""


def write_site(doc: str) -> None:
    if SITE.exists():
        if SITE.name != "site" or SITE.parent != ROOT:
            raise Refuse(f"отказываюсь чистить {SITE}")
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    (SITE / "index.html").write_text(doc, encoding="utf-8")
    (SITE / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    got = sorted(p.name for p in SITE.iterdir())
    if got != sorted(OUTPUTS):
        raise Refuse(f"в site/ оказалось {got}, ожидалось {sorted(OUTPUTS)} — "
                     "каталог отдаётся целиком, посторонний файл публикуется")


# ---------------------------------------------------------------- самопроверка
def selftest() -> int:
    """Работает БЕЗ выгрузки: данные подкладываются. Иначе проверка не
    вызывалась бы на той машине, где стоит pre-commit."""
    for n, expected in [(0, "many"), (1, "one"), (2, "few"), (4, "few"),
                        (5, "many"), (11, "many"), (12, "many"), (14, "many"),
                        (21, "one"), (24, "few"), (111, "many"), (131, "one")]:
        assert plural_ru(n, "one", "few", "many") == expected, n
    assert plural_ru(131, "закона", "законов", "законов") == "закона"
    assert plural_ru(5, "обещания", "обещаний", "обещаний") == "обещаний"
    idx = {("0022010213", 2023): {"net_allocated": 1000, "net_executed": 500},
           ("0022010212", 2023): {"net_allocated": None}}
    titles = ["הקמת מוסדות דת שוטף", "פיתוח בתי עלמין", 'תמיכה בבתי חב"ד']

    def card(**kw) -> dict:
        c = {"card_version": 1, "period_id": "1095-gov37", "card_type": "party",
             "party_ru": "Тест", "party_he": "מבחן", "periods_in_government": 1,
             "status": "observed", "snapshots": {"raw_budget": "2026-07-30"},
             "holdout_checked": {"period": None}, "revisions": [{"version": 1}],
             "commitments": [{
                 "id": "t1", "quote_he": "טקסט", "quote_ru": "текст",
                 "granularity": "exact_takana", "branch": "00220102",
                 "plan_year": 2023, "fact_year": 2023, "page": 9, "line": 1,
                 "counter_search": {"searched_where": ["raw_budget"],
                                    "outcome": "nothing"},
                 "readings": [{"type": "weakening", "text": "a"},
                              {"type": "strengthening", "text": "b"}],
                 "confidence": "low", "confidence_reason": "причина",
                 "what_would_falsify": "чем",
                 "conclusion": "база {0022010213:2023:allocated}",
             }]}
        for k, v in kw.items():
            if k in ("conclusion", "quote_he"):
                c["commitments"][0][k] = v
            else:
                c[k] = v
        return c

    def refuses(name: str, **kw) -> bool:
        try:
            build([(name, card(**kw))], idx, titles)
        except Refuse:
            return True
        return False

    fails = []
    ok = build([("t", card())], idx, titles)

    # 1-5: отказы, каждый на своём нарушении
    for name, kw in (
            ("битая ссылка", {"conclusion": "нет {9999999999:2023:allocated}"}),
            ("канал transfers", {"conclusion": "нет {0022010213:2023:transfers}"}),
            ("ложное отсутствие", {"conclusion": "нет {absent:מוסדות דת}"}),
            ("ложное отсутствие с кавычкой", {"conclusion": 'нет {absent:בתי חב"ד}'}),
            ("ложное отсутствие кода", {"conclusion": "нет {nocode:0022010213}"}),
            ("BiDi в цитате", {"quote_he": "טקסט‮הפוך"})):
        if not refuses(name, **kw):
            fails.append(name)

    # 6: разметка в цитате рендерится текстом и сохраняется посимвольно
    hostile = "<script>alert(1)</script> & \"кавычки\" 'и' <b>"
    h = build([("t", card(quote_he=hostile))], idx, titles)
    if "<script>alert" in h:
        fails.append("экранирование: разметка утекла в документ")
    if html.escape(hostile) not in h:
        fails.append("экранирование: цитата потеряла кусок")

    # 6b: область поиска, записанная как `источник: …`, доходит до читателя
    # текстом, а не служебной скобкой
    c6 = card()
    c6["commitments"][0]["counter_search"]["searched_where"] = [
        {"источник": "raw_budget, дата 2026-07-30"}]
    h6 = build([("t", c6)], idx, titles)
    if "полная выгрузка бюджета, дата 2026-07-30" not in h6 or "&#x27;источник&#x27;" in h6:
        fails.append("область поиска отрендерена как python-repr, "
                     "а не как текст")

    # 6c: ссылки {код:год:поле} в прочтениях и в области поиска подставляются,
    # а не уходят читателю сырым текстом (ревью 18.10, R6-F08); метка
    # exact_takana не утверждает, что код назван в соглашении (R6-F07)
    c6c = card()
    c6c["commitments"][0]["readings"][1]["text"] = "b {0022010213:2023:executed}"
    c6c["commitments"][0]["counter_search"]["searched_where"] = [
        "строка {0022010213:2023:allocated}"]
    c6c["commitments"][0]["counter_search"]["note"] = "n {0022010213:2023:allocated}"
    c6c["commitments"][0]["what_would_falsify"] = "w {0022010213:2023:executed}"
    c6c["commitments"][0]["confidence_reason"] = "r {0022010213:2023:executed}"
    h6c = build([("t", c6c)], idx, titles)
    assert not re.search(r"\{\d{10}:\d{4}:", h6c), \
        "ссылка в прочтении или в области поиска не подставлена"
    assert f"r <span class=n>{money(500)}</span>" in h6c, \
        "причина уверенности: ссылка подставлена не тем числом (R13-F04)"
    assert "код статьи назван" not in h6c, \
        "метка exact_takana утверждает, что код назван в соглашении"
    # Каждое из пяти полей — отдельно: ссылка только в нём, меняется ровно
    # её ячейка (R11-F01: удаление одного поля из extra проходило зелёным).
    idx2 = {k: dict(v) for k, v in idx.items()}
    idx2[("0022010213", 2023)]["net_executed"] = 501
    ref = "x {0022010213:2023:executed}"
    for field in ("readings", "searched_where", "note",
                  "what_would_falsify", "confidence_reason"):
        c6d = card(conclusion="нет {absent:מוסדות דת זמני}")
        cm = c6d["commitments"][0]
        if field == "readings":
            cm["readings"][1]["text"] = ref
        elif field in ("searched_where", "note"):
            cm["counter_search"][field] = [ref] if field == "searched_where" else ref
        else:
            cm[field] = ref
        assert fingerprint(c6d, idx, titles) != fingerprint(c6d, idx2, titles), \
            f"§11: отпечаток не краснеет на ячейке, прочитанной в поле {field}"
    # R8-F06: сводная метка года не возвращается
    assert "год плана и факта" not in h6c, "вернулась метка «год плана и факта»"

    # 7: §13 — сортировать нечем, потому что нечего и незачем
    if "<table" in ok or "<script" in ok:
        fails.append("§13: в документе таблица или скрипт — появилась "
                     "возможность отсортировать")
    # 8: §16
    if 'content="noindex, nofollow"' not in ok:
        fails.append("§16: нет noindex")
    # Ловим ДИРЕКТИВУ, а не упоминание. Первая редакция этой проверки
    # покраснела на собственном комментарии в robots.txt, где объясняется,
    # почему Disallow не используется. Тот же дефект уже случался в проекте
    # дважды: grep §9 поймал свой комментарий, а проверка обхода
    # guarded_fetch глушилась словом в docstring. Третий раз — значит
    # правило: проверка ищет исполняемую строку, не текст о ней.
    if any(ln.strip().lower().startswith("disallow:")
           for ln in ROBOTS.splitlines() if not ln.lstrip().startswith("#")):
        fails.append("§16: robots.txt запрещает обход и тем отменяет noindex")
    # 9: §17 — рамка до первой карточки
    if not 0 <= ok.index("id=frame") < ok.index("<h2 id=c-"):
        fails.append("§17: рамка не на первом экране")
    # 10: журнал правок §15
    if "Журнал правок" not in ok:
        fails.append("§15: нет журнала правок")
    # 11: детерминизм
    if build([("t", card())], idx, titles) != ok:
        fails.append("сборка недетерминирована")
    # 12: отпечаток краснеет на изменении прочитанной ячейки
    fp1 = fingerprint(card(), idx, titles)
    idx2 = {k: dict(v) for k, v in idx.items()}
    idx2[("0022010213", 2023)]["net_allocated"] = 1001
    if fingerprint(card(), idx2, titles) == fp1:
        fails.append("отпечаток не заметил изменения ячейки")
    # 13: отпечаток НЕ краснеет на изменении непрочитанной ячейки
    idx3 = {k: dict(v) for k, v in idx.items()}
    idx3[("0022010212", 2023)]["net_allocated"] = 777
    if fingerprint(card(), idx3, titles) != fp1:
        fails.append("отпечаток краснеет на ячейке, которую карточка не читает "
                     "— ложное разделение, сторож будет кричать на норму")

    if fails:
        print("САМОПРОВЕРКА ПРОВАЛЕНА:", file=sys.stderr)
        for f in fails:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1
    # --- карточка канала А. Данных на MacBook нет, поэтому выгрузка
    # подменяется: проверяется РЕНДЕР, а не чтение файла. Чтение файла
    # стережёт отказ в самом votes_of, и он краснеет на Studio.
    vcard = {
        "card_type": "party", "unit": "faction_knesset", "faction_id": 1103,
        "knesset": 25, "party_ru": "ХАДАШ-ТААЛ", "party_he": 'חד"ש-תע"ל',
        "snapshots": {"votes_25": "2026-07-31"},
        "holdout_checked": {"period": None, "outcome": "не проводилась"},
        "conclusion": "фракция голосовала по вопросам правового государства",
        "readings": [{"type": "weakening", "text": "мало"},
                     {"type": "reframing", "text": "иначе"}],
        "counter_search": {"searched_where": ["выгрузка целиком"],
                           "outcome": "nothing"},
        "confidence": "medium", "confidence_reason": "неполнота периода",
        "what_would_falsify": "если доля упадёт",
        "revisions": [{"version": 1, "date": "2026-08-13", "what": "первая"}],
        "votes": {"theme": "rule_of_law",
                  "theme_caveat_ru": "по вопросам правового государства",
                  "faction_id": 1103,
                  "census": {"votes": 1, "acts": 1, "acts_in_theme_total": 144,
                             "acts_without_participation": 39,
                             "from": "2022-12-13", "to": "2026-07-14"}},
    }
    row = [{"date": "2022-12-13", "bill_id": 1, "name_he": "הצעת חוק",
            "name_ru": "Законопроект", "for_option_desc": "להעביר לוועדה",
            "position": {"against": 5}}]
    orig = globals()["votes_of"]
    try:
        globals()["votes_of"] = lambda fid: list(row)
        vhtml = render_votes_card(vcard)
        assert vhtml.count("по вопросам правового государства") >= 2, \
            "оговорка о теме обязана стоять И в шапке переписи, И в самом " \
            "утверждении: из шапки она не доедет до процитированного абзаца"
        assert "<table" not  in vhtml and "<script" not  in vhtml, \
            "§13: в карточке канала А появилась таблица или скрипт — " \
            "значит появилось чем сортировать"
        assert "<bdi>"  in vhtml and 'dir=rtl'  in vhtml, \
            "ивритское название без bdi/rtl переставляется на экране"
        assert "להעביר לוועדה"  in vhtml, \
            "§10: смысл «за» обязан быть на странице, а не только в данных"
        assert "против 5"  in vhtml, "расклад фракции не отрендерен"
        # Отпечаток карточки голосований обязан быть НЕ хешем пустоты и
        # обязан краснеть на правке переписи. Без этих двух утверждений поле
        # data_fingerprint у неё зелёное и не сторожит ничего — ровно то,
        # что произошло при первом --stamp 13.08.
        EMPTY = ("sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca4"
                 "95991b7852b855")
        fp_v = fingerprint(vcard, {}, [])
        assert fp_v != EMPTY, \
            "отпечаток карточки голосований — хеш пустоты: поле есть, " \
            "защиты нет, и зелёное оно всегда"
        import copy as _copy
        moved = _copy.deepcopy(vcard)
        moved["votes"]["census"]["acts"] = 999
        assert fingerprint(moved, {}, []) != fp_v, \
            "отпечаток не краснеет на правке переписи, под которую написана проза"
        vcard["votes"]["census"]["votes"] = 999
        try:
            render_votes_card(vcard)
            raise AssertionError("§11: расхождение переписи с выгрузкой не "
                                 "остановило сборку — проза и данные разошлись")
        except SystemExit:
            pass
    finally:
        globals()["votes_of"] = orig

    print("самопроверка отчёта пройдена: 23 утверждений + 8 на карточку канала А. Напоминание: "
          "проверено, что документ СОБИРАЕТСЯ и не врёт механически; "
          "осмысленность выводов машиной не проверяется (§24)")
    return 0


# ---------------------------------------------------------------------- main
def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    if "--stamp" not in sys.argv:
        raise Refuse("старый генератор выведен из сборки сайта (§14); "
                     "используйте make report (render_overview). "
                     "site/ не изменён; post-receive должен вызывать make report")

    paths = sorted(CARDS.glob("*.yaml")) if CARDS.exists() else []
    if not paths:
        raise Refuse("карточек нет — публиковать нечего")

    # Отпечаток — факт о данных, а данные есть только на Studio. Записать его
    # обязан MacBook: он единственный писатель (§19). Поэтому две формы.
    # `--stamp sha256:...` пишет готовое значение и выгрузки не требует;
    # `--stamp` без значения считает по локальной выгрузке.
    # Запись на Studio запрещена явно: следующий push делает `git reset --hard`
    # и молча стёр бы её — ровно так уже терялся data/MANIFEST.json 30.07.
    if "--stamp" in sys.argv:
        i = sys.argv.index("--stamp")
        given = (sys.argv[i + 1] if len(sys.argv) > i + 1
                 and sys.argv[i + 1].startswith("sha256:") else None)
        if given:
            if len(paths) != 1:
                raise Refuse("карточек больше одной — назови файл явно, "
                             "иначе отпечаток ляжет не в ту")
            stamp(paths[0], given)
            print(f"{paths[0].name}: {given} записан")
            return 0

    idx, titles = vc.budget_index()
    if not idx:
        raise Refuse(
            f"нет {vc.TAKANOT.relative_to(ROOT)} — числа подставить неоткуда. "
            "Это отказ, а не режим: отчёт без выгрузки был бы отчётом с "
            "дырами на месте чисел. Выгрузка: python3 scripts/fetch_budget.py")

    # Полный контракт карточки — здесь, где выгрузка есть. На MacBook он
    # исполняется без неё и ссылки на числа не проверяет (§24).
    periods = vc.known_periods()
    cards = []
    for p in paths:
        card = vc.load_yaml_ish(p)
        vc.check_card(card, p.name, periods, idx, titles)
        cards.append((p.name, card))
    if vc.problems:
        for x in vc.problems:
            print(f"  ✗ {x}", file=sys.stderr)
        raise Refuse(f"контракт карточки нарушен ({len(vc.problems)})")

    if "--stamp" in sys.argv:
        studio = socket.gethostname().lower().startswith("studio")
        for p, (_, card) in zip(paths, cards):
            fp = fingerprint(card, idx, titles)
            if not studio:
                stamp(p, fp)
            print(f"{p.name}: {fp}")
        if studio:
            print("НЕ ЗАПИСАНО: пишет только MacBook (§19). Здесь запись "
                  "пережила бы ровно до следующего push — post-receive делает "
                  "git reset --hard. Скопируй значение и на MacBook прогони:\n"
                  "  python3 scripts/build_report.py --stamp <значение>")
            return 0
        print("отпечатки записаны. Это осознанное действие: оно означает, что "
              "выводы перечитаны против текущих чисел")
        return 0

    for p, (name, card) in zip(paths, cards):
        want = card.get("data_fingerprint")
        got = fingerprint(card, idx, titles)
        if not want:
            raise Refuse(
                f"{name}: нет data_fingerprint. Проза карточки написана по "
                "срезу данных, и ничто не связывает её с тем, что сейчас в "
                "выгрузке. Прогони --stamp, перечитав выводы")
        if want != got:
            print(f"{name}: текущие значения ячеек:", file=sys.stderr)
            for k, v in cells(card, idx, titles):
                print(f"    {k} = {v!r}", file=sys.stderr)
            raise Refuse(
                f"{name}: данные под выводами изменились с момента, когда "
                f"выводы писались.\n  было {want}\n  стало {got}\n"
                "Перечитай выводы против значений выше. Согласен — подними "
                "версию карточки, запиши правку в revisions (§15) и прогони "
                "--stamp. Это не техническая помеха: фраза, написанная по "
                "старому числу, рядом с новым числом — ложь документа о себе")

    doc = build(cards, idx, titles)
    write_site(doc)
    print(f"отчёт собран: {SITE.relative_to(ROOT)}/index.html, "
          f"{len(doc)} символов, карточек {len(cards)}")
    print(f"sha256: {hashlib.sha256(doc.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as exc:
        print(f"\nОТКАЗ СБОРКИ: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # блокируем, а не пропускаем
        print(f"ОШИБКА ГЕНЕРАТОРА (это блок, не warn): {exc}", file=sys.stderr)
        sys.exit(2)
