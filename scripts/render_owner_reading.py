#!/usr/bin/env python3
"""Страница чтения актов владельцем: без имён фракций, без направления.

Правило — criteria/declared_before_owner_reading_2026-10-10.yaml, объявлено
до показа. Здесь только исполнение: отбор пяти актов (3 самых голосуемых +
2 случайных с объявленным seed), цитаты норм, отобранные механически из
сохранённых ответов моделей (quote_found == exact, без знака и без имени
модели), и пересказ автора из docs/reference/owner_reading_summaries_*.yaml.

Что страница НЕ содержит по устройству: ни одной позиции фракции, ни одного
исхода голосования, ни одной даты голосования. Имя фракции или слово из
словаря направления в пересказе — отказ сборки, не предупреждение.

CLI:
  python3 scripts/render_owner_reading.py            # отбор + страница
  python3 scripts/render_owner_reading.py --selftest
"""
from __future__ import annotations

import collections
import hashlib
import json
import random
import sys
from html import escape as E
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOTES = ROOT / "data" / "votes_25.json"
ARROW = ROOT / "data" / "direction_arrow_2026-10-07.json"
TEXTS = ROOT / "data" / "bill_texts"
NAMES_GLOB = "vote_names_ru_*.json"
FACTIONS = ROOT / "criteria" / "faction_names_ru.yaml"
SUMMARIES = ROOT / "docs" / "reference" / "owner_reading_summaries_2026-10-10.yaml"
DECL = ROOT / "criteria" / "declared_before_owner_reading_2026-10-10.yaml"
SEL = ROOT / "data" / "selection_owner_reading_2026-10-10.json"
OUT = ROOT / "report" / "owner_reading_2026-10-10.html"

SEED_PREFIX = "owner-reading-2026-10-10|"
EXPECTED_A = [2207472, 2201200, 2201202]
N_A, N_B = 3, 2
# Словарь направления и блоков — запрещён в ПЕРЕСКАЗЕ (не в цитатах закона:
# «правительство» в тексте закона — норма, в пересказе — подсказка).
FORBIDDEN_STEMS = ["ослабля", "усилива", "сдерж", "коалиц", "оппозиц",
                   "правительств", "большинств"]


def refuse(msg: str) -> None:
    raise SystemExit(f"ОТКАЗ: {msg}")


def yaml_flat(path: Path, key: str) -> dict[str, str]:
    """`key:` → словарь из строк `  a: b` без pyyaml (на Mac его нет)."""
    out, on = {}, False
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not on:
            on = ln.startswith(f"{key}:")
            continue
        if ln and not ln.startswith(" "):
            break
        s = ln.strip()
        if not s or s.startswith("#") or ": " not in s:
            continue
        k, v = s.split(": ", 1)
        out[k.strip()] = v.strip().strip('"')
    return out


def faction_tokens() -> set[str]:
    """Все формы имён фракций: иврит, русская полная и русская до скобки."""
    toks = set()
    for he, ru in yaml_flat(FACTIONS, "names").items():
        toks.add(he)
        toks.add(ru)
        base = ru.split(" (")[0].split(" –")[0].split(" —")[0].strip()
        if len(base) >= 4:
            toks.add(base)
    return toks


def snapshot(votes: dict) -> str:
    return str(votes.get("at", ""))[:19]


def seed_for(votes: dict) -> str:
    return hashlib.sha256((SEED_PREFIX + snapshot(votes)).encode()).hexdigest()


def population(rows: list, table: dict) -> set[int]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import sign_of
    return {r["bill_id"] for r in rows if r.get("bill_id") is not None
            and sign_of(r.get("for_option_desc"), table) != "none"}


def select(rows: list, table: dict, seed: str) -> dict:
    pop = population(rows, table)
    cnt = collections.Counter(r["bill_id"] for r in rows
                              if r.get("bill_id") in pop)
    part_a = [b for b, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:N_A]]
    rng = random.Random(seed)
    rest = sorted(pop - set(part_a))
    part_b = rng.sample(rest, N_B)
    order = part_a + part_b
    rng.shuffle(order)
    return {"population": len(pop), "part_a": part_a, "part_b": part_b,
            "order": order, "seed": seed}


def quotes_for(arrow_rows: list, bill: int) -> list[tuple[str, str]]:
    """Механический отбор: exact у любой модели, дедуп по иврит-цитате,
    порядок — по позиции в тексте акта. Знак и модель не передаются."""
    row = next((r for r in arrow_rows if r.get("bill") == bill), None)
    if row is None:
        return []
    seen, out = set(), []
    for vendor in sorted((row.get("verdicts") or {}).keys()):
        for n in (row["verdicts"][vendor] or {}).get("norms") or []:
            if n.get("quote_found") != "exact":
                continue
            he = (n.get("quote_he") or "").strip()
            ru = (n.get("quote_ru") or "").strip()
            if not he or not ru or he in seen:
                continue
            seen.add(he)
            out.append((he, ru))
    text = ""
    tp = TEXTS / f"{bill}.txt"
    if tp.exists():
        text = tp.read_text(encoding="utf-8", errors="replace")
    out.sort(key=lambda q: (text.find(q[0]) if text.find(q[0]) >= 0 else 10**9))
    return out


def year_stage(rows: list, bill: int, table: dict) -> tuple[str, str]:
    """Год и стадия последнего голосования, где «за» двигает акт. Без даты."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import sign_of
    vs = sorted((r for r in rows if r.get("bill_id") == bill
                 and sign_of(r.get("for_option_desc"), table) != "none"),
                key=lambda r: r["date"])
    if not vs:
        return "?", "?"
    last = vs[-1]
    g = (table.get((last.get("for_option_desc") or "").strip()) or {}).get("gloss_ru", "")
    return last["date"][:4], g.split(":")[0]


def check_summary(bill: int, text: str, tokens: set[str]) -> None:
    low = text.lower()
    for stem in FORBIDDEN_STEMS:
        if stem in low:
            refuse(f"акт {bill}: в пересказе словарь направления «{stem}» — "
                   "пересказ подсказывает ответ")
    for t in tokens:
        if t and t in text:
            refuse(f"акт {bill}: в пересказе имя фракции «{t}» — слепота нарушена")
    if len(text.split(". ")) > 4:
        refuse(f"акт {bill}: пересказ длиннее трёх предложений")


CSS = """
:root{--bg:#fbfaf7;--fg:#1a1a18;--mut:#6b6b64;--line:#dcd8cf;--card:#fff}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14140f;
--fg:#ece9e1;--mut:#9a978e;--line:#33322b;--card:#1c1c16}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:17px/1.6 -apple-system,Segoe UI,Roboto,sans-serif}
.w{max-width:760px;margin:0 auto;padding:28px 16px 80px}
h1{font-size:1.5rem;margin:0 0 6px}h2{font-size:1.15rem;margin:0 0 8px}
.mut{color:var(--mut)}.frame{border:1px solid var(--line);border-radius:8px;
padding:12px 14px;margin:0 0 26px;background:var(--card)}
.act{border:1px solid var(--line);border-radius:10px;padding:16px;
margin:0 0 22px;background:var(--card)}
.he{direction:rtl;text-align:right;font-size:1.05rem}
.q{border-left:3px solid var(--line);padding:6px 12px;margin:10px 0}
.q .he{font-size:.98rem}.q .ru{font-size:.95rem}
label{display:block;margin:6px 0}textarea{width:100%;min-height:60px;
font:inherit;background:var(--bg);color:var(--fg);border:1px solid var(--line);
border-radius:6px;padding:8px}
button{font:inherit;padding:8px 14px;border-radius:6px;border:1px solid var(--line);
background:var(--card);color:var(--fg);cursor:pointer}
pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:12px;font-size:.9rem}
"""

JS = """
function collect(){var out=['# пометки владельца — скопируй целиком и пришли',
'read_at: '+new Date().toISOString().slice(0,10),'marks:'];
document.querySelectorAll('.act').forEach(function(a){var b=a.dataset.bill;
var m=a.querySelector('input[type=radio]:checked');var w=a.querySelector('textarea').value.trim();
out.push('  '+b+':');out.push('    mark: '+(m?m.value:'НЕ ОТМЕЧЕНО'));
if(w){out.push('    why: >-');out.push('      '+w.replace(/\\n/g,' '));}});
document.getElementById('out').textContent=out.join('\\n');}
"""


def act_html(i: int, bill: int, names: dict, summ: str,
             quotes: list, year: str, stage: str) -> str:
    nm = names.get(str(bill)) or {}
    qs = "".join(
        f'<div class="q"><div class="he">{E(he)}</div>'
        f'<div class="ru">{E(ru)}</div></div>' for he, ru in quotes) or (
        '<p class="mut">Цитат, найденных в тексте акта дословно, нет — '
        'пересказ стоит один; текст акта: data/bill_texts/%d.txt</p>' % bill)
    opts = "".join(
        f'<label><input type="radio" name="m{bill}" value="{v}"> {t}</label>'
        for v, t in (("недопустимо", "недопустимо"), ("допустимо", "допустимо"),
                     ("не_могу_судить", "не могу судить")))
    return f"""<div class="act" data-bill="{bill}">
<div class="mut">акт {i} из 5 · {E(year)} · {E(stage)}</div>
<div class="he">{E(nm.get('he_head') or '')}</div>
<h2>{E(nm.get('ru') or str(bill))}</h2>
<p><b>Что изменилось в праве</b> <span class="mut">(пересказ автора документа)</span><br>{E(summ)}</p>
<p class="mut" style="margin-bottom:4px">Нормы, на которые пересказ опирается — иврит и перевод, найдены в тексте акта дословно:</p>
{qs}
<p><b>Твоя пометка</b></p>{opts}
<label>почему — одна-две фразы, необязательно<textarea></textarea></label>
</div>"""


def page(sel: dict, names: dict, summaries: dict, arrow_rows: list,
         rows: list, table: dict, tokens: set[str]) -> str:
    acts = []
    for i, b in enumerate(sel["order"], 1):
        s = summaries.get(str(b))
        if not s:
            refuse(f"акт {b}: нет пересказа в {SUMMARIES.name}")
        check_summary(b, s, tokens)
        y, st = year_stage(rows, b, table)
        acts.append(act_html(i, b, names, s, quotes_for(arrow_rows, b), y, st))
    body = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Пять актов</title>
<style>{CSS}</style></head><body><div class="w">
<h1>Пять актов — прочитать и пометить</h1>
<p class="mut">Правило отбора записано до того, как ты это увидел:
criteria/declared_before_owner_reading_2026-10-10.yaml. Три акта — самые
голосуемые в теме, два — случайные с объявленным seed. Порядок перемешан.</p>
<div class="frame"><b>Что здесь есть и чего нет.</b> Есть: название акта,
год, стадия, пересказ того, что изменилось, и дословные цитаты норм с
переводом. Нет: кто голосовал, как голосовал, чем кончилось. Пересказ
написан автором документа и может быть неверен — цитаты рядом для того,
чтобы читающий иврит мог это оспорить. Пометка «не могу судить» —
законный ответ, он говорит о пересказе, а не о тебе.</div>
{''.join(acts)}
<p><button onclick="collect()">Собрать ответы</button></p>
<pre id="out" class="mut">здесь появится текст для отправки</pre>
</div><script>{JS}</script></body></html>"""
    for t in tokens:
        if t and t in body:
            refuse(f"на странице имя фракции «{t}» — сборка отказана")
    return body


def load_all():
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import sign_table
    votes = json.loads(VOTES.read_text(encoding="utf-8"))
    arrow = json.loads(ARROW.read_text(encoding="utf-8"))["rows"]
    trs = sorted((ROOT / "docs" / "reference").glob(NAMES_GLOB))
    if not trs:
        refuse("§12: справочника переводов названий нет")
    names = json.loads(trs[-1].read_text(encoding="utf-8"))["names"]
    return votes, arrow, names, sign_table()


def main() -> int:
    votes, arrow, names, table = load_all()
    rows = votes["rows"]
    sel = select(rows, table, seed_for(votes))
    if sel["part_a"] != EXPECTED_A:
        refuse(f"часть a {sel['part_a']} ≠ объявленному {EXPECTED_A} — "
               "правило или данные изменились, объявление не правится молча")
    SEL.write_text(json.dumps(dict(sel, snapshot=snapshot(votes),
                                   declared_in=DECL.name), ensure_ascii=False,
                              indent=1), encoding="utf-8")
    print(f"отбор: популяция {sel['population']} · a={sel['part_a']} · "
          f"b={sel['part_b']} · порядок {sel['order']} → {SEL.name}")
    summaries = yaml_flat(SUMMARIES, "summaries") if SUMMARIES.exists() else {}
    if not summaries:
        print(f"пересказов нет ({SUMMARIES.name}) — страница не собрана; "
              "это следующий шаг автора, отбор уже зафиксирован")
        return 0
    html = page(sel, names, summaries, arrow, rows, table, faction_tokens())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"страница чтения -> {OUT} · актов {len(sel['order'])}")
    return 0


def selftest() -> int:
    votes, arrow, names, table = load_all()
    rows = votes["rows"]
    seed = seed_for(votes)
    s1, s2 = select(rows, table, seed), select(rows, table, seed)
    assert s1 == s2, "отбор недетерминирован при том же seed"
    assert s1["part_a"] == EXPECTED_A, f"часть a {s1['part_a']} ≠ {EXPECTED_A}"
    assert not set(s1["part_b"]) & set(s1["part_a"]), "часть b пересекается с a"
    assert sorted(s1["order"]) == sorted(s1["part_a"] + s1["part_b"])
    other = select(rows, table, seed + "x")
    assert other["part_b"] != s1["part_b"] or other["order"] != s1["order"], \
        "другой seed дал тот же отбор — seed не используется"
    print(f"  OK: отбор детерминирован, a={EXPECTED_A}, b={s1['part_b']}")

    toks = faction_tokens()
    assert "Ликуд" in toks and "ШАС" in toks, "имена фракций не прочитаны"
    for bad, why in (("Этот акт Ликуд провёл в 2023", "имя фракции"),
                     ("Норма ослабляет надзор суда", "словарь направления"),
                     ("Коалиция провела акт", "словарь блоков")):
        try:
            check_summary(1, bad, toks)
            print(f"  ПРОВАЛ: пересказ с {why} принят")
            return 1
        except SystemExit:
            pass
    check_summary(1, "Суд больше не рассматривает разумность решений. "
                     "Полномочие уходит. Третье предложение.", toks)
    print("  OK: имя фракции и словарь направления в пересказе — отказ")

    qs = quotes_for(arrow, EXPECTED_A[0])
    assert qs, "у самого голосуемого акта нет exact-цитат — проверь вход"
    fake = [{"bill": 1, "verdicts": {"x": {"norms": [
        {"quote_found": "unlocated", "quote_he": "א", "quote_ru": "а"},
        {"quote_found": "exact", "quote_he": "ב", "quote_ru": "б"},
        {"quote_found": "exact", "quote_he": "ב", "quote_ru": "б-дубль"}]}}}]
    got = quotes_for(fake, 1)
    assert got == [("ב", "б")], f"фильтр цитат: {got}"
    print("  OK: только exact, дубли по ивриту схлопнуты, знак не передаётся")

    # Страница целиком: подложить имя фракции в название акта → отказ.
    summ = {str(b): "Пересказ. Два предложения." for b in s1["order"]}
    nm = dict(names)
    nm[str(s1["order"][0])] = {"he_head": "x", "ru": "Закон о Ликуд"}
    try:
        page(s1, nm, summ, arrow, rows, table, toks)
        print("  ПРОВАЛ: имя фракции на странице не поймано")
        return 1
    except SystemExit:
        print("  OK: имя фракции где угодно на странице — отказ сборки")
    html = page(s1, names, summ, arrow, rows, table, toks)
    assert "noindex" in html and html.count('class="act"') == 5
    # Проверяем блоки актов, не легенду: легенда обязана сказать «кто
    # голосовал — не показано», и грубый греп по всей странице запретил бы
    # ровно то, что защищает (шестой такой случай в проекте, см. 08.10).
    import re
    acts_only = html[html.find('<div class="act"'):html.find("<p><button")].lower()
    # …и не цитаты закона: «изберут тайным голосованием» в норме о выборе
    # судей — текст акта, не след нашего голосования. Третий раз за день
    # грубый греп ловит не тот объект; сужаем до прозы страницы.
    prose = re.sub(r'<div class="q">.*?</div></div>', "", acts_only, flags=re.S)
    for word in ("за:", "против:", "голосов"):
        assert word not in prose, f"в прозе блока акта след голосования: {word}"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", acts_only), \
        "в блоке акта полная дата — выдаёт заседание"
    print("  OK: страница без позиций, исходов и дат голосований")
    print("selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
