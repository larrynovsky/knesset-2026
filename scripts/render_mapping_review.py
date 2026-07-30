#!/usr/bin/env python3
"""Страница обзора сопоставлений — то, на чём решение принимает человек (D-2).

Зачем существует. Единственный оракул на осмысленность сопоставления —
человек, читающий ивритскую цитату рядом с названием бюджетной строки (§12).
Машина проверить это не может принципиально. Форма чтения выбрана страницей,
а не JSON'ом, по простой причине: тяжёлое чтение тихо превращается в
непрочитанное, а непрочитанный результат означает, что теста нет.

Что страница НЕ делает: не считает балл, не сортирует по «качеству», не
предлагает «лучшего кандидата». §13 запрещает это в публикации, а привычка
складывается здесь. Кандидаты идут в порядке числа совпавших терминов —
это факт поиска, а не оценка соответствия.

Одноразовость: `disposable`. Когда появится build_report.py, страница умирает
вместе с этапом. Оракул у неё один и он живой — владелец на Ф5.

    python3 scripts/render_mapping_review.py
    -> report/mapping_review_shas.html
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "commitment_map_shas.json"
OUT = ROOT / "report" / "mapping_review_shas.html"

CAT_RU = {
    "commitment": "обязательство",
    "status_quo": "описание существующего",
    "unit_rate": "ставка на единицу",
    "continuation": "продолжение пункта",
}
REJ_RU = {
    "no_term_match": "ни один термин из цитаты не дал строк",
    "term_too_generic": "термины слишком общие, сузить словами из цитаты не удалось",
    "not_budgetary": "не денежное обязательство государства",
    "ocr_unreadable": "цитата повреждена распознаванием",
    "not_a_line": "адресовано учреждению, а не строке",
    "human_undecided": "человек посмотрел и не смог решить",
}


def money(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}".replace(",", " ")


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def year_cells(years: dict, transfers: list) -> str:
    tr_by_year: dict[str, float] = {}
    for t in transfers:
        y = str(t["year"])
        tr_by_year[y] = tr_by_year.get(y, 0.0) + (t.get("net_expense_diff") or 0.0)
    out = []
    for y in ("2023", "2024", "2025"):
        d = years.get(y)
        if d is None:
            out.append(f"<tr><td>{y}</td><td colspan=4 class=none>строки нет</td></tr>")
            continue
        base = "в базе" if not d.get("non_repeating") else "разовая"
        out.append(
            f"<tr><td>{y}</td>"
            f"<td>{money(d['net_allocated'])}</td>"
            f"<td>{money(d['net_revised'])}</td>"
            f"<td>{money(d['net_executed'])}</td>"
            f"<td>{money(tr_by_year.get(y)) if y in tr_by_year else '—'}</td>"
            f"<td class=dim>{base}</td></tr>")
    return "".join(out)


def render(d: dict) -> str:
    c = d["counts"]
    parts = [f"""<!doctype html><html lang=ru><meta charset=utf-8>
<title>Сопоставление обязательств ШАС с бюджетом — обзор</title>
<style>
 body{{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1100px;
      margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{font-size:1.5rem;margin-bottom:.2rem}}
 .meta{{color:#555;font-size:.86rem;margin-bottom:1.6rem}}
 .item{{border-top:1px solid #ddd;padding:1.1rem 0}}
 .he{{direction:rtl;text-align:right;font-size:1.12rem;background:#f7f7f4;
      padding:.55rem .8rem;border-radius:4px;margin:.35rem 0}}
 .tag{{display:inline-block;font-size:.76rem;background:#eceff1;color:#37474f;
       padding:.1rem .45rem;border-radius:3px;margin-right:.35rem}}
 .rej{{background:#fff3e0;color:#8a5300}}
 table{{border-collapse:collapse;font-size:.85rem;margin:.35rem 0 .1rem}}
 td,th{{padding:.16rem .55rem;border-bottom:1px solid #eee;text-align:right}}
 th:first-child,td:first-child{{text-align:left}}
 .cand{{margin:.6rem 0 .6rem 1.2rem;padding-left:.8rem;border-left:3px solid #cfd8dc}}
 .ct{{direction:rtl;text-align:right;font-size:1rem}}
 .dim{{color:#777}} .none{{color:#999;font-style:italic}}
 .ask{{background:#fffde7;border:1px solid #f0e2a0;padding:.5rem .7rem;
       border-radius:4px;font-size:.86rem;margin-top:.5rem}}
 code{{background:#f1f1f1;padding:0 .25rem;border-radius:3px}}
</style>
<h1>Сопоставление обязательств ШАС с бюджетными строками</h1>
<div class=meta>
Период <code>{esc(d['period_id'])}</code>, годы {', '.join(str(y) for y in d['years'])}.
Правило <code>{esc(d['rule'])}</code>, sha256 <code>{esc(d['rule_sha256'][:16])}…</code>.
Снимок бюджета {esc(d['budget_snapshot'])}, таблица <code>{esc(d['source_table'])}</code>.
Собрано {esc(d['built_at'])}.<br>
Кандидатов в тексте: {c['candidates']} ·
обязательств: {c['by_category'].get('commitment', 0)} ·
требуют вашего решения: {c['manual_decisions']}.<br>
<b>Страница ничего не решает.</b> Числа показаны по всем четырём каналам,
вердикта «выполнено» нет и не будет (§13). Ваш вопрос к каждому кандидату —
не «совпало ли», а «значит ли это то, что заявлено».
</div>"""]

    for it in sorted(d["items"], key=lambda x: x["line"]):
        if it["category"] != "commitment":
            continue
        parts.append('<div class=item>')
        parts.append(f'<div><span class=tag>стр. ⟦{it["page"]}⟧</span>'
                     f'<span class=tag>строка {it["line"]}</span>'
                     f'<span class=tag>{esc(CAT_RU.get(it["category"]))}</span>')
        if it["amount_ils"]:
            parts.append(f'<span class=tag>{money(it["amount_ils"])} ₪</span>')
        if it["in_budget_base"] == "required_in_base":
            parts.append('<span class=tag>соглашение требует «в базе бюджета»</span>')
        parts.append('</div>')
        parts.append(f'<div class=he>{esc(it["quote_he"])}</div>')

        if it.get("explicit_code"):
            parts.append('<div class=ask>В тексте соглашения назван код статьи '
                         f'<code>{esc(it["explicit_code"])}</code> — сопоставление '
                         'сделал автор соглашения, не мы. Проверьте, что код '
                         'существует и что это та статья.</div>')
        if it["rejection_reason"]:
            parts.append(f'<div><span class="tag rej">отказ: '
                         f'{esc(REJ_RU.get(it["rejection_reason"], it["rejection_reason"]))}'
                         f'</span>')
            if it.get("matches_before_narrowing") is not None:
                parts.append(f'<span class=dim>строк до сужения: '
                             f'{it["matches_before_narrowing"]}</span>')
            parts.append('</div>')
        if it.get("terms"):
            parts.append('<div class=dim>термины из цитаты: '
                         + ", ".join(esc(t) for t in it["terms"]) + '</div>')

        for cand in it["candidates"]:
            parts.append('<div class=cand>')
            title = cand.get("title") or (cand["years"].get("2023") or {}).get("title") \
                or (cand["years"].get("2024") or {}).get("title") or ""
            parts.append(f'<div><code>{esc(cand["code"])}</code> '
                         f'<span class=dim>совпало терминов: '
                         f'{len(cand["matched"])}</span></div>')
            parts.append(f'<div class=ct>{esc(title)}</div>')
            parts.append('<table><tr><th>год</th><th>утверждено</th>'
                         '<th>пересмотрено</th><th>исполнено</th>'
                         '<th>переносы</th><th></th></tr>'
                         + year_cells(cand["years"], cand["transfers"]) + '</table>')
            n = len(cand["transfers"])
            if n:
                parts.append(f'<div class=dim>переносов в эту ветку: {n}. '
                             'Перенос записан на коде длиной 8 — он показывает '
                             'приход денег в ветку, но НЕ доказывает адресность '
                             'этого обязательства.</div>')
            parts.append('</div>')

        if it["candidates"] and not it.get("explicit_code"):
            parts.append('<div class=ask>Ваше решение: '
                         '<b>exact_takana</b> (обязательство совпадает со строкой) · '
                         '<b>subset_of_line</b> (часть строки — числовой факт тогда '
                         'запрещён, только верхняя граница) · '
                         '<b>spread_over_lines</b> (несколько строк) · '
                         '<b>not_found</b> · <b>human_undecided</b>.</div>')
        parts.append('</div>')

    skipped = [it for it in d["items"] if it["category"] != "commitment"]
    parts.append(f'<div class=item><h2 style="font-size:1.05rem">Не обязательства '
                 f'({len(skipped)})</h2><div class=dim>Записаны, а не отброшены: '
                 '«не обязательство» — это результат, а не отсутствие результата.'
                 '</div><table><tr><th>строка</th><th>категория</th>'
                 '<th>сработало правило</th></tr>')
    for it in sorted(skipped, key=lambda x: x["line"]):
        parts.append(f'<tr><td>{it["line"]}</td>'
                     f'<td>{esc(CAT_RU.get(it["category"]))}</td>'
                     f'<td>{esc(it["category_rule"])}</td></tr>')
    parts.append('</table></div></html>')
    return "\n".join(parts)


def main() -> int:
    if not SRC.exists():
        sys.exit(f"ОТКАЗ: нет {SRC.name} — сначала scripts/map_commitments.py")
    d = json.loads(SRC.read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(d), encoding="utf-8")
    n = d["counts"]["manual_decisions"]
    print(f"-> {OUT.relative_to(ROOT)} · решений к принятию: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
