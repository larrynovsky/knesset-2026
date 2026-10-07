#!/usr/bin/env python3
"""c-*.html — страница решения: что из голосований фракции вообще считается.

Обзор даёт клетку, страница фракции — перепись всех её голосований. Между
ними дыра: читатель видит «1761 голосование» и «клетка пуста» и не может
понять, как одно превратилось в другое. Эта страница показывает именно
превращение — сколько голосований отсеялось и ПО КАКОМУ правилу.

ЧЕГО ЗДЕСЬ НАРОЧНО НЕТ. Второй переписи голосований. Полный список живёт
на странице фракции, и копировать его сюда значило бы завести таблице
второй дом. Здесь — только разбор по правилам отсева, с примерами.

Главное число, которое страница обязана донести: «за» в большинстве
голосований не означает продвижения акта (§10). Пока это знание лежало
только в docs/reference, читатель не мог узнать, что две трети переписи
к направлению отношения не имеют.

    python3 scripts/render_card_page.py --selftest
    python3 scripts/render_card_page.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOTES = ROOT / "data" / "votes_25.json"
OUT_DIR = ROOT / "site"

# Корзины отсева. Порядок — порядок применения правил в compose(), и он
# тут не случаен: единогласие палаты смотрится ДО смысла «за», поэтому
# голосование, выброшенное единогласием, в корзину опции не попадает.
BUCKETS = {
    "unanimous": ("палата голосовала почти единогласно",
                  "меньшинство меньше 2,5% голосов: такой акт не различает "
                  "фракции, и объявленное правило его отбрасывает"),
    "none": ("«за» касалось оговорки, а не самого акта",
             "§10: мы не предполагаем, что означает «за», а читаем это из "
             "описания опции. Здесь «за» означало принять оговорку или "
             "вернуть акт в комиссию — к направлению это отношения не имеет"),
    "split": ("фракция раскололась",
              "индекс Райса ниже объявленного порога: одной позиции у "
              "фракции в этом голосовании нет, и это третье состояние — "
              "не «против» и не «воздержалась»"),
    "nopos": ("фракция не заняла позиции",
              "воздержавшиеся и отсутствующие в знаменатель не входят: это "
              "отсутствие позиции, а не позиция"),
    "carries": ("«за» продвигало сам акт",
                "такое голосование идёт в счёт направления: позиция фракции "
                "переносится на знак акта как есть. ПРОДВИГАЛО — не значит "
                "«принимало»: на какой стадии шло голосование, видно в "
                "описании опции рядом, и передача в комиссию — это тоже "
                "продвижение, но ещё не закон"),
    "inverts": ("«за» означало отклонить акт", "такое голосование в "
                "направление идёт с перевёрнутым знаком"),
}
ORDER = ["carries", "inverts", "none", "unanimous", "split", "nopos"]


def classify(rows: list, fid: int, table: dict, rule: dict) -> dict:
    """Разбор голосований одной фракции по корзинам отсева.

    Вся арифметика отсева переиспользуется из direction_confidence: второго
    дома у правил отсева быть не должно, иначе страница и расчёт разойдутся,
    и заметить это будет некому.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import faction_position, lopsided, sign_of
    out = {k: {"votes": 0, "acts": set(), "examples": []} for k in BUCKETS}
    for r in rows:
        bf = r.get("by_faction") or {}
        cell = next((v for k, v in bf.items()
                     if k.split("|", 1)[0] == str(fid)), None)
        if cell is None:
            continue
        f_all = sum(int(c.get("for", 0)) for c in bf.values())
        a_all = sum(int(c.get("against", 0)) for c in bf.values())
        if lopsided(f_all, a_all, rule["drop_below"]):
            key = "unanimous"
        else:
            vs = sign_of(r.get("for_option_desc"), table)
            if vs == "none":
                key = "none"
            elif int(cell.get("for", 0)) + int(cell.get("against", 0)) == 0:
                key = "nopos"
            elif faction_position(cell, rule["split_below"]) is None:
                key = "split"
            else:
                key = vs
        b = out[key]
        b["votes"] += 1
        if r.get("bill_id") is not None:
            b["acts"].add(r["bill_id"])
        if len(b["examples"]) < 3:
            b["examples"].append(r)
    return out


def bucket_html(key: str, b: dict, names: dict, esc) -> str:
    title, why = BUCKETS[key]
    ex = "".join(
        f'<tr><td data-l="дата">{esc(r["date"][:10])}</td>'
        f'<td data-l="акт">{esc((names.get(str(r["bill_id"])) or {}).get("ru", ""))}'
        f'<span class="he" lang=he dir=rtl><bdi>{esc(r["bill_name"])}</bdi>'
        f'</span></td><td data-l="«за» означало">'
        f'<span class=he lang=he dir=rtl><bdi>'
        f'{esc(r.get("for_option_desc") or "")}</bdi></span></td></tr>'
        for r in b["examples"])
    tbl = (f'<table class=acts><thead><tr><th scope=col>дата</th>'
           f'<th scope=col>акт</th><th scope=col>«за» означало</th></tr>'
           f'</thead><tbody>{ex}</tbody></table>' if ex else
           '<p class=dim>ни одного такого голосования у этой фракции.</p>')
    return (f'<h3>{esc(title)} — {b["votes"]}</h3>'
            f'<p class=dim>{esc(why)}.</p>'
            f'<p>Голосований {b["votes"]}, по разным актам — '
            f'{len(b["acts"])}. {"Примеры:" if ex else ""}</p>{tbl}')


def page(card: dict, buckets: dict, names: dict) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_overview import (CELL, SHORT_FRAME, css_from_mockup, esc)
    fid = card["faction_id"]
    ru, he = card.get("party_ru"), card.get("party_he")
    cen = (card.get("votes") or {}).get("census") or {}
    ax = card.get("axis_institutions") or {}
    total = sum(b["votes"] for b in buckets.values())
    usable = buckets["carries"]["votes"] + buckets["inverts"]["votes"]
    if ax.get("arrow") in ("up", "down", "both"):
        head = (f'<b>{CELL[ax["arrow"]][0]} {CELL[ax["arrow"]][1]}.</b> '
                f'{esc(ax.get("text"))}')
    else:
        head = ('<b class=tx-miss>Мы сюда не дошли.</b> Направление по этой '
                'теме мы пока не посчитали, и пустота здесь про нас, а не '
                'про фракцию. Что известно — ниже.')
    share = f"{usable / total:.0%}" if total else "—"
    body = "".join(bucket_html(k, buckets[k], names, esc) for k in ORDER)
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{esc(ru)}: суд, парламент, свободы — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<nav class=crumbs><a href="index.html">Все фракции</a> ·
<a href="f-{fid}.html">{esc(ru)}</a> · суд, парламент и свободы</nav>
{SHORT_FRAME}
<h1>{esc(ru)} <span class=he lang=he dir=rtl><bdi>{esc(he)}</bdi></span>:
что из голосований вообще считается</h1>
<p class=lead>{head}</p>
<p>Голосований этой фракции по теме — <b class=big>{total}</b>. В счёт
направления из них могут пойти <b class=big>{usable}</b>, это {share}.
Остальные отсеяны правилами, и каждое правило названо ниже вместе с тем,
сколько голосований оно забрало.</p>
<div class=note>
<p><b>Самое важное на этой странице.</b> «За» в Кнессете не всегда значит
«принять». Иногда это «принять оговорку», иногда «вернуть в комиссию».
Мы не угадываем: описание опции читается и сверяется с таблицей значений.
Поэтому бóльшая часть этих голосований к направлению отношения не имеет — и это
свойство процедуры, а не наша недоработка.</p>
<p><b>Чего в этом разборе нет.</b> Полного списка голосований: он на
<a href="f-{fid}.html">странице фракции</a>. Здесь только разбор по
правилам — списку хватает одного места.</p>
</div>
<h2>Как из {total} голосований остаётся {usable}</h2>
{body}
<div class=foot><p>Учтено: {esc(cen.get("votes"))} голосований по
{esc(cen.get("acts"))} актам, {esc(cen.get("from"))} — {esc(cen.get("to"))}.
Актов темы без участия фракции: {esc(cen.get("acts_without_participation"))}.
Отпечаток данных: {esc(card.get("data_fingerprint"))}. Правила отсева —
criteria/declared_before_arrow_2026-10-07.yaml, арифметика —
scripts/direction_confidence.py.</p></div>
</body></html>"""


def names_ref() -> dict:
    trs = sorted((ROOT / "docs" / "reference").glob("vote_names_ru_*.json"))
    if not trs:
        raise SystemExit("ОТКАЗ §12: справочника переводов нет")
    return json.loads(trs[-1].read_text(encoding="utf-8"))["names"]


def selftest() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import arrow_rule
    from render_overview import esc
    R = dict(arrow_rule(), split_below=0.5)
    T = {"ЗА": {"sign": "carries"}, "ОТК": {"sign": "inverts"},
         "ОГВ": {"sign": "none"}}

    def v(vid, bid, opt, bf):
        return {"vote_id": vid, "bill_id": bid, "date": "2024-01-01",
                "bill_name": "חוק", "for_option_desc": opt, "by_faction": bf}

    A, Z = "7|A", "9|Z"
    rows = [
        # пойдёт в счёт: «за» продвигает акт, палата разделена, позиция есть
        v(1, 100, "ЗА", {A: {"for": 10}, Z: {"against": 10}}),
        # перевёрнутый знак
        v(2, 101, "ОТК", {A: {"for": 10}, Z: {"against": 10}}),
        # §10: «за» про оговорку
        v(3, 102, "ОГВ", {A: {"for": 10}, Z: {"against": 10}}),
        # единогласие палаты — смотрится ДО смысла «за»
        v(4, 103, "ЗА", {A: {"for": 119}, Z: {"against": 1}}),
        # раскол фракции
        v(5, 104, "ЗА", {A: {"for": 5, "against": 5}, Z: {"against": 10}}),
        # позиции нет: только воздержавшиеся. Палата при этом РАЗДЕЛЕНА —
        # иначе голосование съест правило 2,5% и корзина окажется пустой.
        v(6, 105, "ЗА", {A: {"abstain": 9}, Z: {"against": 10},
                         "8|B": {"for": 10}}),
    ]
    b = classify(rows, 7, T, R)
    got = {k: b[k]["votes"] for k in ORDER}
    assert got == {"carries": 1, "inverts": 1, "none": 1, "unanimous": 1,
                   "split": 1, "nopos": 1}, got
    # ── ПОРЯДОК ПРАВИЛ — ЧАСТЬ ОТВЕТА, А НЕ ДЕТАЛЬ ───────────────────────
    # Голосование, выброшенное единогласием палаты, НЕ должно попадать в
    # корзину опции: иначе страница скажет читателю, что акт отсеян §10,
    # тогда как отсеяло его объявленное правило 2,5%. Один и тот же вход
    # с опцией-оговоркой это различает.
    b2 = classify([v(7, 106, "ОГВ", {A: {"for": 119}, Z: {"against": 1}})],
                  7, T, R)
    assert b2["unanimous"]["votes"] == 1 and b2["none"]["votes"] == 0, \
        "порядок правил на странице разошёлся с порядком в расчёте"
    # фракции нет в голосовании — строка не считается ничьей
    assert sum(x["votes"] for x in classify(rows, 999, T, R).values()) == 0, \
        "голосования чужой фракции попали в разбор"
    # у каждой корзины есть название и причина, иначе читатель видит ярлык
    for k in ORDER:
        assert k in BUCKETS and len(BUCKETS[k]) == 2, k
    assert set(ORDER) == set(BUCKETS), "корзина без места в порядке вывода"

    card = {"faction_id": 7, "party_ru": "Тест", "party_he": "פ",
            "data_fingerprint": "abc", "votes": {"census": {
                "votes": 6, "acts": 6, "from": "2022-12-13",
                "to": "2026-07-28", "acts_without_participation": 0}}}
    p = page(card, b, {"100": {"ru": "Акт"}})
    assert "<script" not in p, "§13: скрипт на странице решения"
    assert 'content="noindex, nofollow"' in p, "§16: нет noindex"
    assert p.index("data-frame=short") < p.index("<h1"), \
        "§17: рамка обязана стоять ДО заголовка"
    assert "f-7.html" in p, "нет пути к переписи — читатель её не найдёт"
    assert "Мы сюда не дошли" in p, \
        "карточка без решения выдала утверждение о направлении"
    # ── ЖАРГОН ──────────────────────────────────────────────────────────
    from render_overview import jargon
    bad = jargon(p)
    assert bad is None, f"внутренний язык на странице решения: {bad}"
    print("самопроверка render_card_page: 12 утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import arrow_rule, sign_table
    from render_overview import jargon, load_cards
    from build_line_cards import _arrow_split
    rule = dict(arrow_rule(), split_below=float(_arrow_split()))
    rows = json.loads(VOTES.read_text(encoding="utf-8"))["rows"]
    table, names, cards = sign_table(), names_ref(), load_cards()
    OUT_DIR.mkdir(exist_ok=True)
    n = 0
    for fid, card in sorted(cards.items()):
        b = classify(rows, fid, table, rule)
        if not sum(x["votes"] for x in b.values()):
            continue
        doc = page(dict(card, faction_id=fid), b, names)
        bad = jargon(doc)
        if bad:
            print(f"ОТКАЗ: внутренний язык на c-{fid}-inst.html: {bad}")
            return 1
        (OUT_DIR / f"c-{fid}-inst.html").write_text(doc, encoding="utf-8")
        n += 1
    print(f"страниц решения -> {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
