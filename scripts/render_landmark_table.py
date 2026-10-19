#!/usr/bin/env python3
"""Таблица для чтения владельцем: главные акты × как голосовал каждый список.

ЗАЧЕМ. Владельцу нужно выбрать, за кого голосовать. Стрелка по каналу А
заблокирована согласием вендоров, но стрелка — это инфраструктура для
НЕЗНАКОМЦА: она нужна, чтобы утверждение выдержало проверку человеком,
который нам не доверяет. Владелец сам себе оракул, и ему мешает другое:
он не читает на иврите и у него нет перед глазами таблицы. Таблица есть.

ОТБОР АКТОВ — механический: число поимённых голосований по акту. Не наша
оценка важности: так голосовал Кнессет. Четырнадцать актов держат около
двух третей всей выгрузки.

НАЗВАННОЕ СМЕЩЕНИЕ. Отбор по объёму процедуры коррелирует со спорностью,
а спорные акты максимально разделяют своих и чужих — это ровно то
смещение, против которого в своде стоит запрет Снайдера (LSQ 1992).
Поэтому страница живёт в report/ как рабочая, НЕ в site/, и несёт это
предупреждение в тексте. Как вывод прибора такой отбор непригоден.

ОТБОР ГОЛОСОВАНИЙ ВНУТРИ АКТА — по объявленной таблице смысла «за»
(§10): берутся только те, где «за» продвигает сам акт или его отклоняет.
Оговорки («принять оговорку») выброшены — их в этих актах 1035 из 1160, и
они говорят о тактике обструкции, а не о позиции по акту.

    python3 scripts/render_landmark_table.py --selftest
    python3 scripts/render_landmark_table.py [--top N]
"""
from __future__ import annotations
from build_report import plural_ru

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOTES = ROOT / "data" / "votes_25.json"
OUT = ROOT / "report" / "landmark_votes.html"
TOP = 14

POS = {"for": ("за", "p-for"), "against": ("против", "p-ag"),
       "abstain": ("воздерж.", "p-ab"), "split": ("раскол", "p-sp"),
       "none": ("—", "p-no")}


def stance(cell: dict | None, split_below: float) -> str:
    """Что сделал список в одном голосовании. Пять состояний, не три.

    Раскол — отдельное состояние, а не «против»: если фракция разошлась,
    приписать ей одну позицию значит соврать о ней ровно в том месте, где
    она интереснее всего.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import faction_position
    if cell is None:
        return "none"
    f, a = int(cell.get("for", 0)), int(cell.get("against", 0))
    if f + a == 0:
        return "abstain" if int(cell.get("abstain", 0)) else "none"
    return faction_position(cell, split_below) or "split"


def pick_acts(rows: list, top: int) -> list:
    """Акты по числу поимённых голосований. Признак механический."""
    c = collections.Counter(r["bill_id"] for r in rows
                            if r.get("bill_id") is not None)
    return [b for b, _ in c.most_common(top)]


def act_votes(rows: list, bill: int, table: dict) -> list:
    """Голосования акта, где «за» относится к САМОМУ акту (§10)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import sign_of
    out = [r for r in rows if r.get("bill_id") == bill
           and sign_of(r.get("for_option_desc"), table) != "none"]
    out.sort(key=lambda r: r["date"])
    return out


def gloss(desc: str, table: dict) -> str:
    """Русское пояснение опции — из объявленного справочника, не отсюда.

    §12 и смысл всей страницы: владелец не читает на иврите. Описание опции
    без перевода делает таблицу нечитаемой ровно в том месте, где решается,
    что означало «за». Отсутствие перевода роняет сборку — молча показать
    иврит было бы хуже отказа.
    """
    e = table.get((desc or "").strip())
    g = (e or {}).get("gloss_ru")
    if not g:
        raise SystemExit(
            f"ОТКАЗ §12: у опции {desc!r} нет русского пояснения в "
            "docs/reference/for_option_sign_*.json — таблица была бы "
            "нечитаема там, где решается смысл «за»")
    return g


def build(rows: list, acts: list, table: dict, names: dict, fids: list,
          ru: dict, split_below: float) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_overview import css_from_mockup, esc
    total_votes = len(rows)
    blocks, shown = [], 0
    for bill in acts:
        vs = act_votes(rows, bill, table)
        allv = sum(1 for r in rows if r.get("bill_id") == bill)
        shown += len(vs)
        name = (names.get(str(bill)) or {}).get("ru", "—")
        he = vs[0]["bill_name"] if vs else ""
        head = (f'<tr><th scope=col>дата</th><th scope=col>«за» означало</th>'
                + "".join(f'<th scope=col class=v>{esc(ru.get(f, f))}</th>'
                          for f in fids) + "</tr>")
        body = ""
        for r in vs:
            bf = r.get("by_faction") or {}
            cells = ""
            for f in fids:
                cell = next((c for k, c in bf.items()
                             if k.split("|", 1)[0] == str(f)), None)
                word, cls = POS[stance(cell, split_below)]
                cells += f'<td class="v {cls}">{esc(word)}</td>'
            body += (f'<tr><td class=d>{esc(r["date"][:10])}</td>'
                     f'<td class=o>{esc(gloss(r.get("for_option_desc"), table))}'
                     f'<span class="he" lang=he dir=rtl><bdi>'
                     f'{esc(r.get("for_option_desc") or "")}</bdi></span></td>'
                     f'{cells}</tr>')
        blocks.append(
            f'<h2>{esc(name)}</h2>'
            f'<p class=he lang=he dir=rtl><bdi>{esc(he)}</bdi></p>'
            f'<p class=dim>Поимённых голосований по этому акту — {allv}. '
            f'Ниже {len(vs)}: те, где «за» относилось к самому акту. '
            f'Остальные {allv - len(vs)} — голосования по оговоркам.</p>'
            f'<div class=wrap><table class=lm><thead>{head}</thead>'
            f'<tbody>{body}</tbody></table></div>')
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Главные акты: кто как голосовал</title>
<style>{css_from_mockup()}
.wrap{{overflow-x:auto;margin:.6rem 0 1.6rem}}
table.lm{{border-collapse:collapse;font:.8rem/1.4 system-ui,sans-serif}}
table.lm th,table.lm td{{border:1px solid var(--rule);padding:.25rem .4rem;
 vertical-align:top}}
table.lm th.v,table.lm td.v{{text-align:center;white-space:nowrap}}
table.lm thead th{{position:sticky;top:0;background:var(--panel);
 font-weight:600;writing-mode:vertical-rl;text-orientation:mixed;
 max-height:9rem}}
table.lm thead th:first-child,table.lm thead th:nth-child(2)
 {{writing-mode:horizontal-tb}}
td.d{{white-space:nowrap}} td.o{{max-width:22rem}}
.p-for{{background:rgba(105,130,27,.22)}}
.p-ag{{background:rgba(178,74,34,.22)}}
.p-ab{{background:rgba(110,99,83,.14)}}
.p-sp{{background:rgba(122,107,196,.26);font-weight:600}}
.p-no{{color:var(--dim)}}
</style></head><body>
<h1>Главные акты 25-го Кнессета: кто как голосовал</h1>
<div class=note>
<p><b>Это рабочая таблица, а не вывод прибора.</b> Акты отобраны по одному
механическому признаку — сколько раз по акту голосовали поимённо. Не наша
оценка важности: так голосовал Кнессет. {TOP} {plural_ru(TOP, 'акт держит', 'акта держат', 'актов держат')} около двух
третей всей выгрузки ({shown} показанных голосований из {total_votes}).</p>
<p><b>Смещение названо.</b> Отбор по объёму процедуры связан со
спорностью, а спорные акты сильнее всего делят зал. Как основание для
вывода о партии такой отбор непригоден — именно против него в своде стоит
запрет на отбор по различающей силе. Здесь он допустим потому, что
страница ничего не утверждает: она показывает, кто что сделал.</p>
<p><b>«За» не всегда значит «принять».</b> Рядом с каждой датой стоит,
что именно означало «за» в этом голосовании — по-русски и в оригинале.
Голосования по оговоркам (их большинство) из таблицы убраны: они про
тактику обструкции, а не про позицию по акту.</p>
<p><b>Пять состояний, не три.</b> «Раскол» — отдельное: список разошёлся
внутри себя, и приписать ему одну позицию значило бы соврать ровно там,
где он интереснее всего. «—» значит, что в этом голосовании у списка не
было ни одного голоса.</p>
</div>
{''.join(blocks)}
<div class=foot><p>Собрано из data/votes_25.json; смысл «за» — из
docs/reference/for_option_sign_*.json; названия актов —
docs/reference/vote_names_ru_*.json; раскол — по индексу Райса с порогом из
criteria/declared_before_arrow_2026-10-07.yaml. Воспроизводится
scripts/render_landmark_table.py.</p></div>
</body></html>"""


def selftest() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    T = {"ЗА": {"sign": "carries", "gloss_ru": "принять акт"},
         "ОГВ": {"sign": "none", "gloss_ru": "принять оговорку"}}

    def v(vid, bid, opt, bf, date="2024-01-01"):
        return {"vote_id": vid, "bill_id": bid, "date": date,
                "bill_name": "חוק", "for_option_desc": opt, "by_faction": bf}

    # пять состояний различаются, и раскол не выдаётся за позицию
    assert stance({"for": 9}, 0.5) == "for"
    assert stance({"against": 9}, 0.5) == "against"
    assert stance({"for": 5, "against": 5}, 0.5) == "split", \
        "раскол выдан за позицию — это ложь ровно там, где интересно"
    assert stance({"abstain": 7}, 0.5) == "abstain"
    assert stance(None, 0.5) == "none"
    assert stance({}, 0.5) == "none"
    # отбор актов — по числу голосований, без нашей оценки
    rows = [v(i, 100, "ЗА", {"1|A": {"for": 1}}) for i in range(5)] + \
           [v(90, 200, "ЗА", {"1|A": {"for": 1}})]
    assert pick_acts(rows, 1) == [100], "акт выбран не по объёму процедуры"
    # §10: оговорки в таблицу не идут
    rows2 = [v(1, 100, "ЗА", {"1|A": {"for": 1}}),
             v(2, 100, "ОГВ", {"1|A": {"for": 1}})]
    got = act_votes(rows2, 100, T)
    assert len(got) == 1 and got[0]["vote_id"] == 1, \
        "голосование по оговорке попало в таблицу позиций по акту"
    # неизвестная опция обязана останавливать сборку (§10)
    try:
        act_votes([v(3, 100, "чего-то такого в таблице нет", {})], 100, T)
    except SystemExit:
        pass
    else:
        raise AssertionError("неизвестный смысл «за» прошёл молча")
    # страница: канон формы и честность подписи
    page = build(rows2, [100], T, {"100": {"ru": "Акт"}}, [1], {1: "Список"},
                 0.5)
    assert "<script" not in page, "§13: скрипт на рабочей странице"
    assert 'content="noindex, nofollow"' in page, "§16: нет noindex"
    assert "непригоден" in page, "смещение отбора не названо читателю"
    assert "оговорк" in page, "читателю не сказано, что убрано из таблицы"
    assert "показанных голосований" in page
    assert "принять акт" in page, "русское пояснение опции не доехало"
    # ── §12: ИВРИТ БЕЗ ПЕРЕВОДА РОНЯЕТ СБОРКУ ───────────────────────────
    try:
        # опция в таблице ЕСТЬ (иначе сработал бы §10), но без перевода
        build(rows2, [100], {"ЗА": {"sign": "carries"},
                             "ОГВ": {"sign": "none", "gloss_ru": "огв"}},
              {"100": {"ru": "Акт"}}, [1], {1: "С"}, 0.5)
    except SystemExit as e:
        assert "§12" in str(e), e
    else:
        raise AssertionError("опция без перевода прошла — таблица нечитаема")
    print("самопроверка render_landmark_table: 14 утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    top = TOP
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_line_cards import _arrow_split
    from direction_confidence import sign_table
    from render_overview import load_cards
    rows = json.loads(VOTES.read_text(encoding="utf-8"))["rows"]
    trs = sorted((ROOT / "docs" / "reference").glob("vote_names_ru_*.json"))
    if not trs:
        raise SystemExit("ОТКАЗ §12: справочника переводов названий нет")
    names = json.loads(trs[-1].read_text(encoding="utf-8"))["names"]
    cards = load_cards()
    ru = {k: (c.get("party_ru") or str(k)) for k, c in cards.items()}
    fids = sorted(ru)
    acts = pick_acts(rows, top)
    page = build(rows, acts, sign_table(), names, fids, ru,
                 float(_arrow_split()))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"таблица главных актов -> {OUT} · актов {len(acts)} · "
          f"списков {len(fids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
