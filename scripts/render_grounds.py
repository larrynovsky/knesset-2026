#!/usr/bin/env python3
"""site/grounds.html — основания: акты, помеченные владельцем, и кто их провёл.

Правило — criteria/declared_before_owner_reading_2026-10-10.yaml, раздел
grounds: для каждого акта с пометкой «недопустимо» — кто голосовал ЗА на
последней стадии, где «за» двигает акт, кто ПРОТИВ, у кого позиции нет (с
числом поимённых в зале, чтобы 64 против 120 было видно), плюс все
предыдущие стадии той же таблицей. Порога «сколько актов достаточно» нет;
числа на строку бюллетеня нет (§13) — только названия актов.

Документ не говорит «вычеркнуть». Он говорит «проголосовали за акт, который
владелец прочитал и пометил». Пометки — criteria/owner_marks_*.yaml,
поставлены без колонок фракций (f436ad2 после объявления 1ff8ae1).
"""
from __future__ import annotations

import json
import sys
from html import escape as E
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOTES = ROOT / "data" / "votes_25.json"
MARKS = ROOT / "criteria" / "owner_marks_2026-10-10.yaml"
DECL = ROOT / "criteria" / "declared_before_owner_reading_2026-10-10.yaml"
SEL = ROOT / "data" / "selection_owner_reading_2026-10-10.json"
OUT = ROOT / "site" / "grounds.html"
POS = {"for": "за", "against": "против", "split": "раскол",
       "abstain": "воздержались", "none": "нет позиции"}


def refuse(msg: str) -> None:
    raise SystemExit(f"ОТКАЗ: {msg}")


def read_marks(path: Path) -> dict[int, dict]:
    """marks: → {bill: {mark, why}} без pyyaml. Пометка вне шкалы — отказ."""
    out, cur, on = {}, None, False
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("marks:"):
            on = True
            continue
        if not on or not ln.strip() or ln.lstrip().startswith("#"):
            continue
        ind = len(ln) - len(ln.lstrip())
        s = ln.strip()
        if ind == 2 and s.endswith(":"):
            cur = int(s[:-1])
            out[cur] = {}
        elif ind == 4 and cur is not None and ": " in s:
            k, v = s.split(": ", 1)
            out[cur][k] = v.strip()
    for b, m in out.items():
        if m.get("mark") not in ("недопустимо", "допустимо", "не_могу_судить"):
            refuse(f"акт {b}: пометка {m.get('mark')!r} вне объявленной шкалы")
    return out


def controls(marks: dict) -> None:
    """Контроли из объявления — здесь, чтобы страница не собралась вопреки им."""
    vals = [m["mark"] for m in marks.values()]
    if len(set(vals)) == 1:
        refuse("все пометки одинаковы — по объявлению результат недействителен, "
               "прибор измерил расположенность, а не акты")
    if vals.count("не_могу_судить") >= 3:
        refuse("«не могу судить» на трёх и более — непригодны пересказы; "
               "набор не расширять без нового объявления")


def act_votes(rows: list, bill: int, table: dict) -> list:
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import sign_of
    vs = [r for r in rows if r.get("bill_id") == bill
          and sign_of(r.get("for_option_desc"), table) != "none"]
    return sorted(vs, key=lambda r: r["date"])


def cells_by_fid(r: dict) -> dict:
    return {str(k).split("|", 1)[0]: v for k, v in (r.get("by_faction") or {}).items()}


def stance_of(cell, split: float) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_landmark_table import stance
    return stance(cell, split)


def vote_table(r: dict, table: dict, ru: dict, fids: list, split: float) -> dict:
    cb = cells_by_fid(r)
    groups = {k: [] for k in POS}
    for f in fids:
        groups[stance_of(cb.get(f), split)].append(f)
    g = (table.get((r.get("for_option_desc") or "").strip()) or {}).get("gloss_ru", "")
    return {"date": r["date"][:10], "vote_id": r["vote_id"], "gloss": g,
            "named": r.get("named_total"), "groups": groups}


HE: dict = {}   # ивритские названия фракций — владелец 19.10: партии на двух языках


def two_lang(f, ru: dict) -> str:
    he = HE.get(f)
    from render_overview import with_leader
    return E(with_leader(f, ru.get(f, f))) + (f' <span class=he lang=he dir=rtl><bdi>{E(he)}</bdi></span>' if he else "")


def names_list(fids: list, ru: dict) -> str:
    if not fids:
        return "<span class=dim>—</span>"
    return ", ".join(f'<a href="f-{E(f)}.html">{two_lang(f, ru)}</a>' for f in fids)


def act_section(bill: int, mark: dict, votes: list, names: dict, ru: dict) -> str:
    nm = names.get(str(bill)) or {}
    rows = []
    for i, v in enumerate(votes):
        last = i == len(votes) - 1
        rows.append(f"""<div class="vote{' last' if last else ''}">
<div class=dim>{E(v['date'])} · голосование {v['vote_id']} · в зале поимённо {v['named']} ·
смысл «за»: {E(v['gloss'])}{' · <b>последняя стадия</b>' if last else ''}</div>
<dl>
<dt>за</dt><dd>{names_list(v['groups']['for'], ru)}</dd>
<dt>против</dt><dd>{names_list(v['groups']['against'], ru)}</dd>
{'<dt>раскол</dt><dd>' + names_list(v['groups']['split'], ru) + '</dd>' if v['groups']['split'] else ''}
<dt>нет позиции</dt><dd>{names_list(v['groups']['none'] + v['groups']['abstain'], ru)}</dd>
</dl></div>""")
    why = f'<p class=dim>пометка владельца: <b>недопустимо</b> — «{E(mark.get("why", ""))}»</p>' \
        if mark.get("why") else '<p class=dim>пометка владельца: <b>недопустимо</b></p>'
    return f"""<section class=act id="a{bill}">
<div class=he>{E(nm.get('he_head') or '')}</div>
<h2>{E(nm.get('ru') or str(bill))}</h2>
{why}
{''.join(rows)}
</section>"""


def per_line(marked: list, tables: dict, fids: list, ru: dict, names: dict) -> str:
    """Строка бюллетеня → названия актов по позиции на последней стадии.
    Названия, не числа: колонки с числом здесь нет по §13."""
    out = []
    for f in fids:
        za, pr, no = [], [], []
        for b in marked:
            last = tables[b][-1]
            g = last["groups"]
            t = names.get(str(b), {}).get("ru", str(b))
            # Позиция на предыдущих стадиях: демарш на третьем чтении (64 в
            # зале) не должен стирать «против» на втором двумя неделями раньше.
            earlier = [v for v in tables[b][:-1]
                       if f in v["groups"]["for"] or f in v["groups"]["against"]]
            prev = ""
            if earlier:
                kinds = {"за" if f in v["groups"]["for"] else "против" for v in earlier}
                prev = f"; на предыдущих стадиях — {'/'.join(sorted(kinds))}"
            if f in g["for"]:
                za.append(t + (prev if "против" in prev else ""))
            elif f in g["against"]:
                pr.append(t)
            elif f in g["split"]:
                pr.append(t + " (раскол)")
            else:
                no.append(f"{t} (в зале {last['named']}{prev})")
        li = lambda xs: "".join(f"<li>{E(x)}</li>" for x in xs) or "<li class=dim>—</li>"
        out.append(f"""<section class=line><h3><a href="f-{E(f)}.html">{two_lang(f, ru)}</a></h3>
<dl><dt>за акт на последней стадии</dt><dd><ul>{li(za)}</ul></dd>
<dt>против</dt><dd><ul>{li(pr)}</ul></dd>
<dt>нет позиции</dt><dd><ul>{li(no)}</ul></dd></dl></section>""")
    return "".join(out)


def build(marks: dict, votes: dict, names: dict, ru: dict, fids: list,
          table: dict, split: float) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_overview import SHORT_FRAME, css_from_mockup
    controls(marks)
    marked = [b for b, m in marks.items() if m["mark"] == "недопустимо"]
    ok = [b for b, m in marks.items() if m["mark"] == "допустимо"]
    unsure = [b for b, m in marks.items() if m["mark"] == "не_могу_судить"]
    rows = votes["rows"]
    tables = {}
    for b in marked:
        vs = act_votes(rows, b, table)
        if not vs:
            refuse(f"акт {b}: нет ни одного голосования, где «за» двигает акт")
        tables[b] = [vote_table(r, table, ru, fids, split) for r in vs]
    sections = "".join(act_section(b, marks[b], tables[b], names, ru) for b in marked)
    other = "".join(f"<li>{E(names.get(str(b), {}).get('ru', str(b)))} — "
                    f"{'допустимо' if b in ok else 'не могу судить'}</li>"
                    for b in ok + unsure)
    extra = ("<style>.act{border:1px solid var(--line,#ddd);border-radius:10px;"
             "padding:14px 16px;margin:0 0 22px}.vote{border-top:1px solid "
             "var(--line,#ddd);padding:10px 0}.vote.last{background:rgba(127,127,127,.06)}"
             "dl{margin:6px 0}dt{font-weight:600;margin-top:6px}dd{margin:0 0 4px 0}"
             ".line{border-top:1px solid var(--line,#ddd);padding:10px 0}"
             ".line ul{margin:0;padding-left:18px}.he{direction:rtl;text-align:right}"
             "</style>")
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Основания — 25-й Кнессет</title>
<style>{css_from_mockup()}</style>{extra}</head><body>
<nav class=crumbs><a href="index.html">Все фракции</a> · Основания</nav>
{SHORT_FRAME}
<h1>Основания</h1>
<p class=lead>Владелец прочитал {len(marks)} актов, не видя, кто как голосовал,
и пометил {len(marked)} как недопустимые. Ниже — кто за эти акты голосовал,
на каждой стадии, где «за» двигало акт. Документ не говорит «вычеркнуть»:
он говорит «проголосовали за акт, который ты прочитал и пометил». Сколько
таких актов нужно — решает читатель; порога здесь нет (§13).</p>
<p class=dim>Правило — <code>criteria/declared_before_owner_reading_2026-10-10.yaml</code>,
записано до чтения. Пометки — <code>criteria/owner_marks_2026-10-10.yaml</code>,
дословно. Остальные из пяти: <ul>{other}</ul></p>
<h2>Что здесь ломается, и это названо</h2>
<ul>
<li><b>Уход из зала неотличим от отсутствия.</b> «Нет позиции» значит, что
позиция фракции в этой записи не установлена. По записи нельзя отличить
неучастие от того, что фракции в этот момент не было; причины здесь не
определяются. Число в зале стоит у каждого голосования — оно показывает,
сколько депутатов записано поимённо, но не почему остальных нет.</li>
<li><b>На спорных актах голос показывает блок, а не партию.</b> Четыре помеченных
акта делят зал одинаково. Основание здесь — не «был в коалиции», а
«проголосовал за эту конкретную вещь»; разницу делает только чтение акта.</li>
<li><b>Стадия имеет значение.</b> «За» на передаче в комитет продвигает акт, но
не принимает его; у законопроекта, не прошедшего дальше предварительного
чтения, «последняя стадия» — это она.</li>
<li><b>Слепота на громких актах неполная</b>, и владелец, посмотрев эту страницу,
может сказать, что пометил бы иначе. Это записывается отдельно как
опровержение, не правкой пометок.</li>
</ul>
<h2>По актам</h2>
{sections}
<h2>По строкам бюллетеня</h2>
<p class=dim>Названия актов, не числа. Строки без фракции в 25-м Кнессете здесь
отсутствуют: о них документ не может сказать ничего.</p>
{per_line(marked, tables, fids, ru, names)}
</body></html>"""


def load_all():
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_line_cards import _arrow_split
    from direction_confidence import sign_table
    from render_overview import load_cards
    votes = json.loads(VOTES.read_text(encoding="utf-8"))
    trs = sorted((ROOT / "docs" / "reference").glob("vote_names_ru_*.json"))
    if not trs:
        refuse("§12: справочника переводов названий нет")
    names = json.loads(trs[-1].read_text(encoding="utf-8"))["names"]
    cards = load_cards()
    ru = {str(k): (c.get("party_ru") or str(k)) for k, c in cards.items()}
    HE.update({str(k): c.get("party_he") for k, c in cards.items() if c.get("party_he")})
    return votes, names, ru, sorted(ru), sign_table(), float(_arrow_split())


def main() -> int:
    for p in (MARKS, DECL):
        if not p.exists():
            refuse(f"нет {p.relative_to(ROOT)} — без пометок оснований нет")
    marks = read_marks(MARKS)
    if SEL.exists():
        sel = json.loads(SEL.read_text(encoding="utf-8"))
        if sorted(marks) != sorted(sel["order"]):
            refuse(f"пометки {sorted(marks)} ≠ отбору {sorted(sel['order'])}")
    votes, names, ru, fids, table, split = load_all()
    page = build(marks, votes, names, ru, fids, table, split)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    n = sum(1 for m in marks.values() if m["mark"] == "недопустимо")
    print(f"основания -> {OUT} · помечено недопустимыми {n} из {len(marks)}")
    return 0


def selftest() -> int:
    import re
    import tempfile
    marks = read_marks(MARKS)
    assert len(marks) == 5, f"пометок {len(marks)}, ждали 5"
    votes, names, ru, fids, table, split = load_all()
    page = build(marks, votes, names, ru, fids, table, split)
    assert 'content="noindex, nofollow"' in page
    assert page.index("data-frame=short") < page.index("<h1")
    marked = [b for b, m in marks.items() if m["mark"] == "недопустимо"]
    for b in marked:
        assert f'id="a{b}"' in page, f"помеченный акт {b} не на странице"
    for b, m in marks.items():
        if m["mark"] != "недопустимо":
            assert f'id="a{b}"' not in page, f"допустимый акт {b} попал в основания"
    print(f"  OK: {len(marked)} помеченных актов на странице, допустимые — нет")
    # §13: ни одной ячейки таблицы с голым числом по строкам бюллетеня.
    lines_part = page[page.find("По строкам бюллетеня"):]
    assert "<td>" not in lines_part and not re.search(r"<li>\d+</li>", lines_part), \
        "в разделе по строкам есть числовая ячейка — это рейтинг"
    print("  OK: по строкам — названия актов, не числа (§13)")
    # Уход из зала: третье чтение 2207472 — 64 в зале, оппозиции нет.
    if 2207472 in marked:
        assert "в зале поимённо 64" in page, "число в зале на демарше не напечатано"
        # R27-F03: причина «нет позиции» не приписывается
        assert "демарш" not in page and "прогул" not in page, "странице приписана причина отсутствия"
        print("  OK: число поимённых в зале печатается (64 на третьем чтении 2207472)")
    # Провокации на контроли объявления.
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                     encoding="utf-8") as tmp:
        tmp.write("marks:\n" + "".join(f"  {b}:\n    mark: недопустимо\n" for b in marks))
        p = Path(tmp.name)
    try:
        build(read_marks(p), votes, names, ru, fids, table, split)
        print("  ПРОВАЛ: все пометки одинаковы, а страница собралась")
        return 1
    except SystemExit as e:
        assert "одинаковы" in str(e)
        print("  OK: все пометки одинаковы → отказ (контроль объявления)")
    p.write_text("marks:\n  1:\n    mark: плохо\n", encoding="utf-8")
    try:
        read_marks(p)
        print("  ПРОВАЛ: пометка вне шкалы принята")
        return 1
    except SystemExit:
        print("  OK: пометка вне шкалы → отказ")
    p.unlink()
    print("самопроверка render_grounds пройдена")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
