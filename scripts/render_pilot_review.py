#!/usr/bin/env python3
"""Страница для человеческого просмотра прогона v1.1. Вход в решение Р2.

Показывает ровно то, что нужно для решения, и ничего больше. Согласованные
строки НЕ выводятся поимённо: их десятки, и просмотр подряд создал бы ощущение
проверки без её содержания.

Порядок разделов — по убыванию плотности информации, а не по логике данных:
  1. цитаты, которых нет в тексте (это подделка свидетельства, если подтвердится);
  2. расхождения по общему знаку (случай труден);
  3. оракул: промахи и отказы;
  4. расхождения по разбиению на нормы (менее срочно, но показывает,
     насколько согласовано само понятие «норма»).

Иврит идёт с dir=rtl и unicode-bidi: isolate — иначе цитата ломает вёрстку
соседнего русского текста.
"""
from __future__ import annotations

import collections
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "direction_pilot.json"
OUT = ROOT / "report" / "pilot_review.html"
SIGN = {-1: "−1 ослабляет", 0: "0 не меняет", 1: "+1 усиливает", None: "нет знака"}
FOUND = {"exact": "найдена дословно", "prefix": "найден только префикс",
         "name_only": "ВЗЯТА ИЗ НАЗВАНИЯ", "unlocated": "НЕ НАЙДЕНА В ТЕКСТЕ"}
CORE = 611          # плотное ядро после починки границ слова 29.07


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def quote_badge(found: str) -> str:
    cls = "ok" if found == "exact" else "warn" if found == "prefix" else "bad"
    return f'<span class="badge {cls}">{e(FOUND.get(found, found))}</span>'


def norms_block(norms: list) -> str:
    if not norms:
        return '<div class=meta>норм не выделено</div>'
    out = ['<div class=lbl>нормы</div>']
    for n in norms:
        star = " ★ сильнейшая" if n.get("strongest") else ""
        c = n.get("contrast")
        out.append(
            f'<div class=norm><b>{e(n.get("checklist_item"))}</b> '
            f'<span class="s s{n.get("sign")}">{SIGN.get(n.get("sign"))}</span>{star}'
            f' {quote_badge(n.get("quote_found"))}'
            f' <span class=meta>контраст {"—" if c is None else c}</span>'
            f'<div class=he dir=rtl>{e(n.get("quote_he"))}</div>'
            f'<div class=ru>{e(n.get("quote_ru"))}</div>'
            f'<div class=ru><i>{e(n.get("what_changes"))}</i></div></div>')
    return "".join(out)


def verdict_block(v: dict, who: str) -> str:
    if v.get("status") != "ok":
        return f'<div class=v><b>{who}</b><div class=bad>{e(v.get("status"))}</div></div>'
    ov = v["overall"]
    basis = ""
    if ov.get("basis_required"):
        note = str(ov.get("basis_note") or "").strip()
        basis = (f'<div class=lbl>пометка об основании (K2d)</div>'
                 f'<div class="ru{"" if note else " bad"}">'
                 f'{e(note) if note else "ОБЯЗАТЕЛЬНА, НО ПУСТА"}</div>')
    return f"""<div class=v><b>{who}</b> → <span class="s s{ov.get('sign')}">{SIGN.get(ov.get('sign'))}</span>
      {quote_badge(ov.get('quote_found'))}
      <div class=meta>уверенность {e(ov.get('confidence'))}</div>
      <div class=he dir=rtl>{e(ov.get('quote_he'))}</div>
      <div class=ru>{e(ov.get('quote_ru'))}</div>
      <div class=lbl>почему такая уверенность</div><div class=ru>{e(ov.get('confidence_reason'))}</div>
      <div class=lbl>довод ПРОТИВ собственного знака</div><div class=ru>{e(ov.get('argument_against'))}</div>
      {basis}{norms_block(v.get('norms', []))}</div>"""


def card(r: dict, head: str) -> str:
    return f"""<div class=card><div class=name dir=rtl>{e(r['name'])}</div>
<div class=meta>BillID {r['bill']} · символов {r['chars']} · единиц структуры {r.get('units')}
{' · ТЕКСТ ОБРЕЗАН' if r.get('truncated') else ''}{head}</div>
<div class=cols>{verdict_block(r['verdicts'].get('anthropic', {}), 'Anthropic')}
{verdict_block(r['verdicts'].get('openai', {}), 'OpenAI')}</div></div>"""


def selftest() -> int:
    """Оракул вёрстки. Красное здесь = страница молча теряет то, ради чего сделана."""
    v = {"status": "ok",
         "overall": {"sign": -1, "quote_he": "בסעיף 15", "quote_ru": "в статье 15",
                     "confidence": "high", "confidence_reason": "текст ясен",
                     "argument_against": "можно прочесть иначе",
                     "quote_found": "name_only", "basis_required": True, "basis_note": ""},
         "norms": [{"checklist_item": "A3", "sign": -1, "strongest": True,
                    "quote_he": "בסעיף 15", "quote_ru": "в статье 15",
                    "what_changes": "снимает ограничение",
                    "quote_found": "unlocated", "contrast": None}]}
    h = verdict_block(v, "Anthropic")
    assert "ВЗЯТА ИЗ НАЗВАНИЯ" in h, "цитата из названия не помечена — R1 стал невидимым"
    assert "НЕ НАЙДЕНА В ТЕКСТЕ" in h, "ненайденная цитата нормы не помечена"
    assert "ОБЯЗАТЕЛЬНА, НО ПУСТА" in h, "пустой basis_note при обязательном не виден (K2d)"
    assert "★ сильнейшая" in h, "сильнейшая норма не помечена (K2b)"
    assert "контраст —" in h, "контраст None отрисован как число"
    assert 'dir=rtl' in h, "иврит без dir=rtl ломает вёрстку соседнего текста"

    bad = verdict_block({"status": "unparsed"}, "OpenAI")
    assert "unparsed" in bad, "отказ разбора не показан"
    print("самопроверка вёрстки пройдена: 7 утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    d = json.loads(SRC.read_text(encoding="utf-8"))
    rows = d["rows"]
    scored = [r for r in rows if r.get("agree")]
    dis_sign = [r for r in scored if not r["agree"]["overall_sign"]]
    dis_norms = [r for r in scored if not r["agree"]["norm_count"]]
    dis_strong = [r for r in scored if not r["agree"]["strongest"]]

    # Цитаты, которых нет в тексте, — отдельный и первый раздел.
    suspect = []
    for r in rows:
        bad = []
        for who, v in r["verdicts"].items():
            if v.get("status") != "ok":
                continue
            if v["overall"].get("quote_found") in ("name_only", "unlocated"):
                bad.append(f"{who}: общая цитата {v['overall']['quote_found']}")
            for n in v.get("norms", []):
                if n.get("quote_found") in ("name_only", "unlocated"):
                    bad.append(f"{who}: норма {n.get('checklist_item')} — {n['quote_found']}")
        if bad:
            suspect.append((r, bad))

    orc_bad = [r for r in rows if "oracle" in r
               and (r["oracle"]["anthropic"] != "hit" or r["oracle"]["openai"] != "hit")]

    tok = collections.Counter()
    for r in rows:
        for v in r["verdicts"].values():
            u = v.get("usage") or {}
            tok["in"] += u.get("input_tokens") or u.get("prompt_tokens") or 0
            tok["out"] += u.get("output_tokens") or u.get("completion_tokens") or 0

    dist = {v: collections.Counter(
        r["verdicts"][v]["overall"].get("sign") for r in scored) for v in d["models"]}

    st = d.get("stats", {})
    q_exact = st.get("quote:exact", 0) + st.get("norm_quote:exact", 0)
    q_bad = sum(st.get(f"{p}:{k}", 0) for p in ("quote", "norm_quote")
                for k in ("unlocated", "name_only"))

    parts = [f"""<!doctype html><html lang=ru><meta charset=utf-8>
<title>Прогон v1.1 — на просмотр</title><style>
body{{font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1040px;margin:0 auto;padding:24px;color:#1a1a1a}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:34px;border-top:1px solid #ddd;padding-top:18px}}
.he{{direction:rtl;unicode-bidi:isolate;font-size:15px;background:#f7f7f5;padding:8px;border-radius:5px;margin:6px 0}}
.ru{{font-size:14px;color:#333;margin:4px 0}}
.lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#888;margin-top:10px}}
.meta{{font-size:12px;color:#777}}
.card{{border:1px solid #ddd;border-radius:8px;padding:14px;margin:14px 0}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.v{{background:#fafafa;border-radius:6px;padding:10px}}
.norm{{border-left:3px solid #ddd;padding:4px 0 4px 10px;margin:8px 0}}
.s{{font-weight:600}} .s-1{{color:#b3261e}} .s0{{color:#666}} .s1{{color:#1e6b3a}}
.bad{{color:#b3261e;font-weight:600}}
.badge{{font-size:11px;padding:2px 6px;border-radius:4px;background:#eee;color:#444}}
.badge.ok{{background:#e3f2e6;color:#1e6b3a}} .badge.warn{{background:#fff4d6;color:#8a6100}}
.badge.bad{{background:#fde7e5;color:#b3261e}}
.name{{font-size:14px;direction:rtl;unicode-bidi:isolate;font-weight:600}}
table{{border-collapse:collapse;font-size:14px}} td,th{{border:1px solid #ddd;padding:5px 10px;text-align:left}}
.note{{background:#fffbe6;border:1px solid #e8d98a;border-radius:6px;padding:12px;font-size:14px}}
</style>
<h1>Классификация направления, кодбук v1.1 — на просмотр</h1>
<p class=meta>Прогон {e(d['at'])} · модели {e(d['models'])} · строк {len(rows)}</p>

<div class=note><b>Что этот прогон доказывает и что нет.</b>
Зелёный оракул означает «прогон не сломан». Он <b>не</b> означает «классификация верна»:
актов мало, среди них нет ни одного с ожидаемым +1, и систематический крен ими не ловится.
Правильность знака сейчас не смотрит никто — это и есть решение, которое от вас нужно (Р2).
<br><br>
До 29 июля тексты принятых актов читались <b>задом наперёд</b>, включая все семь актов
оракула. Прежний результат «7 из 7» означал угадывание по названию, а не чтение нормы.
Этот прогон — первый по настоящему тексту.</div>

<h2>Сводка</h2>
<table><tr><th>вендор</th><th>−1</th><th>0</th><th>+1</th><th>без знака</th></tr>"""]
    for v, c in dist.items():
        parts.append(f"<tr><td>{e(v)}</td><td>{c[-1]}</td><td>{c[0]}</td>"
                     f"<td>{c[1]}</td><td>{c[None]}</td></tr>")

    exp = d.get("expected_disagreements")
    parts.append(f"""</table>
<p><b>Расхождения на трёх уровнях</b> — это разные величины, и сравнивать с прежним
одним числом можно только первую строку:</p>
<table><tr><th>уровень</th><th>расхождений</th><th>из</th></tr>
<tr><td>общий знак законопроекта</td><td><b>{len(dis_sign)}</b></td><td>{len(scored)}</td></tr>
<tr><td>число выделенных норм</td><td>{len(dis_norms)}</td><td>{len(scored)}</td></tr>
<tr><td>какая норма сильнейшая</td><td>{len(dis_strong)}</td><td>{len(scored)}</td></tr></table>
{f'<p>Объявлено ДО прогона: <b>{exp}</b>. Вышло <b>{len(dis_sign)}</b>.</p>' if exp is not None else ''}
<p><b>Локализация цитат</b> (проверки, которой не было в прежней версии):
найдено дословно {q_exact}, не найдено или взято из названия <b>{q_bad}</b>.
Токенов: вход {tok['in']:,}, выход {tok['out']:,} на {len(rows)} строк —
экстраполяция на ядро {CORE}: вход ~{int(tok['in'] * CORE / max(len(rows), 1)):,},
выход ~{int(tok['out'] * CORE / max(len(rows), 1)):,}.</p>

<h2>1. Цитаты, которых нет в тексте — {len(suspect)}</h2>
<p class=meta>Самое плотное место. Цитата, взятая из названия, означает, что знак
поставлен по заголовку. Ненайденная может быть артефактом нормализации — но может
и не быть, и различить это способен только человек.</p>""")

    for r, why in suspect:
        parts.append(card(r, " · " + "; ".join(e(w) for w in why)))
    if not suspect:
        parts.append("<p>Ни одной. Все цитаты найдены в исходном тексте.</p>")

    parts.append(f"""<h2>2. Расхождения по общему знаку — {len(dis_sign)}</h2>
<p class=meta>Расхождение означает, что случай труден, а не что кто-то ошибся.</p>""")
    for r in dis_sign:
        parts.append(card(r, ""))
    if not dis_sign:
        parts.append("<p>Ни одного. Это подозрительно само по себе — проверьте распределение знаков выше.</p>")

    parts.append(f"<h2>3. Оракул: промахи и отказы — {len(orc_bad)}</h2>")
    for r in orc_bad:
        o = r["oracle"]
        parts.append(card(r, f" · ожидался {o['expect']:+d} · "
                             f"Anthropic {o['anthropic']} · OpenAI {o['openai']}"))
    if not orc_bad:
        parts.append("<p>Все акты оракула угаданы обоими вендорами.</p>")

    parts.append(f"""<h2>4. Расхождения по разбиению на нормы — {len(dis_norms)}</h2>
<p class=meta>Менее срочно, но показывает, насколько согласовано само понятие «норма».
Если здесь расходятся почти все — K2 описывает единицу записи недостаточно точно.</p>""")
    for r in dis_norms[:15]:
        parts.append(card(r, ""))
    if len(dis_norms) > 15:
        parts.append(f"<p class=meta>Показаны первые 15 из {len(dis_norms)}. "
                     f"Остальные — в data/direction_pilot.json.</p>")

    parts.append("</html>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}")
    print(f"  цитат вне текста: {len(suspect)} строк · расхождений по знаку: {len(dis_sign)}")
    print(f"  расхождений по числу норм: {len(dis_norms)} · по сильнейшей: {len(dis_strong)}")
    print(f"  оракул с промахом или отказом: {len(orc_bad)}")
    print(f"  токены: вход {tok['in']:,} выход {tok['out']:,} на {len(rows)} строк")
    return 0


if __name__ == "__main__":
    sys.exit(main())
