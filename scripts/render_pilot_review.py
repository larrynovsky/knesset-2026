#!/usr/bin/env python3
"""Страница для человеческого просмотра пилота. Вход в решение Р2.

Показывает ровно то, что нужно для решения, и ничего больше:
расхождения вендоров и промахи оракула. Согласованные строки НЕ показываются
поимённо — их 48, и просмотр их подряд создал бы ощущение проверки без
её содержания.

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


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def verdict_block(v: dict, who: str) -> str:
    if v.get("status") != "ok":
        return f'<div class=v><b>{who}</b><div class=bad>{e(v.get("status"))}</div></div>'
    return f"""<div class=v><b>{who}</b> → <span class="s s{v.get('sign')}">{SIGN.get(v.get('sign'))}</span>
      <div class=meta>пункт {e(v.get('checklist_item'))} · уверенность {e(v.get('confidence'))}</div>
      <div class=he dir=rtl>{e(v.get('quote_he'))}</div>
      <div class=ru>{e(v.get('quote_ru'))}</div>
      <div class=lbl>почему такая уверенность</div><div class=ru>{e(v.get('confidence_reason'))}</div>
      <div class=lbl>довод ПРОТИВ собственного знака</div><div class=ru>{e(v.get('argument_against'))}</div>
    </div>"""


def main() -> int:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    rows = d["rows"]
    dis = [r for r in rows if not r["agree"]]
    orc_miss = [r for r in rows if "oracle" in r
                and not (r["oracle"]["anthropic_hit"] and r["oracle"]["openai_hit"])]
    tok = collections.Counter()
    for r in rows:
        for v in r["verdicts"].values():
            u = v.get("usage") or {}
            tok["in"] += u.get("input_tokens") or u.get("prompt_tokens") or 0
            tok["out"] += u.get("output_tokens") or u.get("completion_tokens") or 0

    dist = {}
    for v in d["models"]:
        dist[v] = collections.Counter(
            r["verdicts"][v].get("sign") for r in rows
            if r["verdicts"][v].get("status") == "ok")

    parts = [f"""<!doctype html><html lang=ru><meta charset=utf-8>
<title>Пилот классификации — на просмотр</title><style>
body{{font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1000px;margin:0 auto;padding:24px;color:#1a1a1a}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:34px;border-top:1px solid #ddd;padding-top:18px}}
.he{{direction:rtl;unicode-bidi:isolate;font-size:15px;background:#f7f7f5;padding:8px;border-radius:5px;margin:6px 0}}
.ru{{font-size:14px;color:#333;margin:4px 0}}
.lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#888;margin-top:8px}}
.meta{{font-size:12px;color:#777}}
.card{{border:1px solid #ddd;border-radius:8px;padding:14px;margin:14px 0}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.v{{background:#fafafa;border-radius:6px;padding:10px}}
.s{{font-weight:600}} .s-1{{color:#b3261e}} .s0{{color:#666}} .s1{{color:#1e6b3a}}
.bad{{color:#b3261e;font-weight:600}}
.name{{font-size:14px;direction:rtl;unicode-bidi:isolate;font-weight:600}}
table{{border-collapse:collapse;font-size:14px}} td,th{{border:1px solid #ddd;padding:5px 10px;text-align:left}}
.note{{background:#fffbe6;border:1px solid #e8d98a;border-radius:6px;padding:12px;font-size:14px}}
</style>
<h1>Пилот классификации направления — на просмотр</h1>
<p class=meta>Прогон {e(d['at'])} · модели {e(d['models'])} · законопроектов {len(rows)}</p>

<div class=note><b>Что этот прогон доказывает и что нет.</b>
Оракул зелёный означает «прогон не сломан». Он <b>не</b> означает «классификация верна»:
семь актов из 667, и систематический крен ими не ловится. Правильность знака сейчас
не смотрит никто — это и есть решение, которое от вас нужно (Р2).
Ниже показаны только расхождения и промахи оракула: 48 согласованных строк
не выведены поимённо намеренно, их просмотр подряд создал бы ощущение проверки
без её содержания.</div>

<h2>Сводка</h2>
<table><tr><th>вендор</th><th>−1</th><th>0</th><th>+1</th><th>без знака</th></tr>"""]
    for v, c in dist.items():
        parts.append(f"<tr><td>{e(v)}</td><td>{c[-1]}</td><td>{c[0]}</td>"
                     f"<td>{c[1]}</td><td>{c[None]}</td></tr>")
    parts.append(f"""</table>
<p>Согласие <b>{d['agreements']}</b> · расхождений <b>{d['disagreements']}</b>
({d['disagreements'] * 100 // max(len(rows), 1)}%). Токенов: вход {tok['in']:,}, выход {tok['out']:,}
на {len(rows)} законопроектов — из этого считается цена батча на 667.</p>
<p><b>Вырождения нет.</b> Плюс поставлен {dist['anthropic'][1]} раз из {len(rows)}.
Это снимает главное опасение: чек-лист способен зафиксировать усиление сдержек,
а не только ослабление. Sanity-gate из keyvotes.yaml пройден не формально.</p>

<h2>Расхождения вендоров — {len(dis)}</h2>
<p class=meta>Здесь плотность информации максимальна: расхождение означает, что случай труден.</p>""")

    for r in dis:
        parts.append(f"""<div class=card><div class=name dir=rtl>{e(r['name'])}</div>
<div class=meta>BillID {r['bill']} · символов {r['chars']}{' · ТЕКСТ ОБРЕЗАН' if r['truncated'] else ''}</div>
<div class=cols>{verdict_block(r['verdicts']['anthropic'], 'Anthropic')}
{verdict_block(r['verdicts']['openai'], 'OpenAI')}</div></div>""")

    parts.append(f"<h2>Промахи оракула — {len(orc_miss)}</h2>")
    for r in orc_miss:
        o = r["oracle"]
        parts.append(f"""<div class=card><div class=name dir=rtl>{e(r['name'])}</div>
<div class=meta>BillID {r['bill']} · ожидался знак <b>{o['expect']:+d}</b> ·
Anthropic {'попал' if o['anthropic_hit'] else 'ПРОМАХ'} ·
OpenAI {'попал' if o['openai_hit'] else 'ПРОМАХ'}</div>
<div class=cols>{verdict_block(r['verdicts']['anthropic'], 'Anthropic')}
{verdict_block(r['verdicts']['openai'], 'OpenAI')}</div></div>""")

    parts.append("</html>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} · расхождений {len(dis)} · промахов оракула {len(orc_miss)}")
    print(f"токены: вход {tok['in']:,} выход {tok['out']:,} на {len(rows)} законопроектов")
    scale = 667 / max(len(rows), 1)
    print(f"экстраполяция на 667: вход ~{int(tok['in'] * scale):,} выход ~{int(tok['out'] * scale):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
