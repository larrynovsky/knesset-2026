"""Шпаргалка A4 «кого вычеркнуть 27.10» — переписана 19.10 после замечания владельца
«иллюзия ясности»: каждое значение подписано словами, легенда — до таблицы, с примером.

Данные — те же функции, что у таблицы бюллетеня (render_overview); своего расчёта нет.
Оракул: selftest() — 14 строк, буквы, 4 позиции словами, уклон словами, пример
во вступлении совпадает со строкой Ликуда.
"""
from __future__ import annotations
import re
from datetime import date

LAW_HEADS = ("Выбор судей<br><small>Осн. закон, попр. 4 · 2025</small>",
             "Отмена «неразумности»<br><small>Осн. закон, попр. 3 · 2023</small>",
             "Закон о судах<br><small>попр. 105 · 2025</small>",
             "Разделить юрсоветника<br><small>законопроект · 2024</small>")
LAW_KEYS = ("поправка № 4", "поправка № 3", "105", "юридического советника")
POS = {"за": "<b>за</b>", "против": "против", "воздержались": "воздерж.",
       "не голосовали": "не голос.", "нет позиции": "не голос.", "—": "не голос."}
# в печати короче: «не голос.» переносилось на две строки
LEAN = {"down": "ослаблял", "up": "укреплял", "both": "и так, и так"}
# Владелец 19.10: «↑ по религии — довод вычеркнуть список» (да). Поэтому «больше религии» жирным, как «за» по 4 законам.
REL = {"up": "<b>за больше религии</b>", "down": "за меньше религии", "both": "и так, и так"}


def _pos(label: str) -> str:
    return POS.get(label.split(" (")[0].strip(), label)


def _short(name: str) -> str:
    """«Государственный правый — Гидеон Саар» → «Саара (Государственный правый)»: читатель знает людей, не фракции."""
    base, _, lead = name.partition(" — ")
    base = base.split(" (")[0]
    surname = lead.split(",")[0].split()[-1] if lead else ""
    return f"{base} ({surname})" if surname and surname not in base else base


def build(m: dict, cards: dict) -> str:
    import render_overview as ro
    from build_report import esc, plural_ru
    from arrow_robustness import label as rob_label
    import json
    ballot = ro.load_ballot()
    names = ro.party_names(m, cards)
    observed = {r["anchor_id"] for r in m["lines"] if r["a"]["status"] == "observed"}
    fids_all = list(dict.fromkeys(ro._al(f) for row in ballot["lists"] for f in row.get("factions", [])))
    laws = ro.owner_law_positions(fids_all)
    for law, key in zip(laws, LAW_KEYS):
        if key not in law["name"]:
            raise ro.Refuse(f"шпаргалка: порядок законов сменился ({law['name']})")
    rob = json.loads((ro.ROOT / "data" / "arrow_robustness.json").read_text(encoding="utf-8"))
    rob_axis = rob["topics"]["rule_of_law"]["factions"]
    rob_rel = rob["topics"]["religion_state"]["factions"]
    from theme_arrows import theme_arrows
    rel_arrows = theme_arrows("religion_state")
    rows, likud = [], None
    for row in ballot["lists"]:
        fids = row.get("factions", [])
        personal = ro.personal_result() if row.get("personal") else None
        # чьи голоса — одной фразой
        if personal:
            note = "Новый список. Судим по личным голосам Айзенкота и Тропера в этом Кнессете."
        elif not fids:
            note = "Новый список: в этом Кнессете не заседал — голосов нет, лист о нём ничего не говорит."
        else:
            note = "Судим по голосам фракции " + " и ".join(_short(names[f]) for f in fids) + "."
            if any("Беннет" in a for a in row.get("absent", [])):
                note += " Беннет в этом Кнессете не заседал."
        # 4 закона
        if personal:
            cells = [_pos(law["labels"]["yashar"]) for law in personal["laws"]]
        elif fids:
            cells = []
            for law in laws:
                vals = [_pos(law["labels"][ro._al(f)]) for f in fids]
                if len(set(vals)) == 1:
                    cells.append(vals[0])
                else:   # разные фракции списка голосовали по-разному — назвать, кто как
                    cells.append("<br>".join(f"{v} <small>({_short(names[f]).split(' (')[0]})</small>" for v, f in zip(vals, fids)))
        else:
            cells = ["нет данных"] * 4
        # общий уклон по суду и правам
        if personal:
            ax = personal["axis"]
            leans = [(ax.get("arrow"), ax.get("down"), ax.get("up"), None, "")]
        else:
            leans = []
            for f in fids:
                ax = cards.get(f, {}).get("axis_institutions") or {}
                if f in observed and ro.alpha_ok(ax) and ax.get("arrow") in LEAN:
                    e = rob_axis.get(str(ro._al(f)))
                    rate = e["rates"]["0.10"] if e else None
                    leans.append((ax["arrow"], ax["down"], ax["up"], rate, _short(names[f]) if len(fids) > 1 else ""))
        parts, words = [], []
        for arrow, down, up, rate, who in leans:
            if arrow not in LEAN:
                continue
            unsure = rate is not None and rob_label(rate) != "устойчива"
            words.append((LEAN[arrow], unsure))
            parts.append((f"{who}: " if who else "") + f"{down} {plural_ru(down, 'раз', 'раза', 'раз')} за ослабление, {up} за укрепление")
        merged = {}
        for w, unsure in words:          # одинаковое направление — один раз, с худшей уверенностью
            merged[w] = merged.get(w, False) or unsure
        words = [w + (" (не уверены)" if u else "") + (" (уверенность не считали)" if personal else "") for w, u in merged.items()]
        lean = (" / ".join(words) + "<br><small>" + "; ".join(parts)
                + "</small>") if words else "нет данных"
        # религия: направление по голосам, полярность — владельца
        if personal:
            x = personal["themes"]["religion_state"]
            rels = [(x.get("arrow"), x.get("up", 0), x.get("down", 0), None, "")]
        else:
            rels = []
            for f in fids:
                a = rel_arrows.get(f) or rel_arrows.get(ro._al(f)) or {}
                e = rob_rel.get(str(ro._al(f)))
                rels.append((a.get("arrow"), a.get("up", 0), a.get("down", 0),
                             e["rates"]["0.10"] if e else None, _short(names[f]).split(" (")[0] if len(fids) > 1 else ""))
        rel_items = []
        for arrow, up, down, rate, who in rels:
            w = REL.get(arrow, "мало данных")
            unsure = arrow in REL and (personal or (rate is not None and rob_label(rate) != "устойчива"))
            rel_items.append((w + (" (не уверены)" if unsure else ""), who))
        # разные слова у фракций одного списка — назвать, чьё какое (shining 19.10: «какое из двух брать?»)
        if len({w for w, _ in rel_items}) > 1:
            rel = " / ".join(f"{w} <small>({who})</small>" if who else w for w, who in rel_items)
        else:
            rel = rel_items[0][0] if rel_items else "нет данных"
        rel = rel if fids or personal else "нет данных"   # счёт по религии — на сайте: лист обязан влезть в одну A4
        tr = (f'<tr data-ballot-list="{esc(row["he"])}">'
              f'<th scope=row><span class="ballot-letters" lang="he" dir="rtl">{esc(row["letters"])}</span>'
              f'<b>{esc(row["ru"])}</b> <span lang=he dir=rtl><bdi>{esc(row["he"])}</bdi></span>'
              f'<span class=norec>{esc(row["leaders"])}</span>'
              # владелец 19.10: «чьи голоса» — только где список явно не равен своей фракции
              + (f'<span class=norec><i>{esc(note)}</i></span>'
                 if personal or any("Беннет" in a for a in row.get("absent", [])) else '') + '</th>'
              '<td class=laws-cells><span class="ballot-laws">' + "".join(f"<span>{c}</span>" for c in cells)
              + f'</span></td><td class=lean>{lean}</td><td class=lean>{rel}</td>'
              '<td><span class="crossout" aria-label="вычеркнуть"></span></td></tr>')
        rows.append(tr)
        if row["ru"] == "Ликуд":
            likud = (cells, words, leans)
    if not likud:
        raise ro.Refuse("шпаргалка: нет строки Ликуда для примера")
    za = sum(1 for c in likud[0] if c.startswith("<b>за</b>"))
    _, down, up, _, _ = likud[2][0]
    example = (f'Пример: Ликуд голосовал «за» по {za} из 4 законов, а по суду и правам в целом '
               f'{likud[1][0]}: {down} {plural_ru(down, "раз", "раза", "раз")} голосовал за ослабление и {up} {plural_ru(up, "раз", "раза", "раз")} — за укрепление.')
    votes_line = ro.data_periods(ro.ROOT / "data")[0]
    heads = ('<th scope=col class=lawsh><span class="ballot-laws heads">'
             + "".join(f'<span>{h}</span>' for h in LAW_HEADS) + '</span></th>')
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Кого исключить из выбора 27.10 — шпаргалка</title>
<style>
*{{box-sizing:border-box}}
body{{max-width:190mm;margin:5mm auto;padding:0 3mm;font:10pt/1.25 Arial,sans-serif;color:black;background:white}}
h1{{font-size:16pt;margin:0 0 1.5mm}}
.how{{margin:0 0 2mm;font-size:9pt;line-height:1.2}}.how p{{margin:1mm 0}}
.frame,.data-period,footer{{font-size:7pt;color:#444;margin:1mm 0}}
a{{color:inherit}}a:focus-visible{{outline:2px solid currentColor;outline-offset:2px}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}}
th,td{{padding:.9mm 1mm;border-bottom:1px solid gray;vertical-align:middle;text-align:left}}
thead th{{font-size:8pt;vertical-align:bottom}}thead th small{{font-weight:normal;color:#444}}
thead th:first-child{{width:25%}}thead th.lawsh{{width:37%}}thead th.leanh{{width:18%}}thead th.relh{{width:13%}}thead th:last-child{{width:7%}}
.heads>span{{font-size:7.5pt;font-weight:bold;line-height:1.15}}
tbody th{{font-weight:normal}}
.ballot-letters{{float:left;min-width:12mm;margin-right:2mm;font-size:19pt;font-weight:bold;line-height:1.05}}
.norec{{display:block;font-size:7.5pt;line-height:1.15;color:#333}}
td.laws-cells{{padding:0}}.ballot-laws{{display:flex}}.ballot-laws>span{{flex:1 1 0;text-align:center;font-size:8.5pt;padding:0 .5mm}}
.lean{{font-size:9pt}}.lean small{{font-size:7pt;color:#333}}
.crossout{{display:block;width:6mm;height:6mm;border:1.5px solid black;margin:auto}}
tr{{break-inside:avoid}}
@page{{size:A4 portrait;margin:7mm}}
@media print{{body{{width:190mm;max-width:none;margin:0;padding:0;zoom:.70}}a{{text-decoration:none}}thead{{display:table-header-group}}}}
</style></head><body>
<h1>Кого исключить из выбора 27.10 — шпаргалка</h1>
<div class=how>
<p><b>Одна строка — один список в бюллетене.</b> Слева буквы — те же, что на бумажке на участке. Дальше — как депутаты этого списка голосовали в нынешнем Кнессете. Квадрат справа — отметить список, который ты для себя исключаешь.</p>
<p><b>Четыре средние колонки</b> — законы о судах, которые ты сам 10.10 пометил «недопустимо», ещё не зная, кто за них голосовал. <b>за</b> — проголосовали ЗА такой закон; «против» — против; «не голос.» — не голосовали: у оппозиции это обычно бойкот (не поддержали, но и не нажали «против»). Юрсоветник — пока законопроект: голосовали на ранней стадии.</p>
<p><b>Колонка «Суд и права в целом»</b> — около 130 законов о суде, контроле Кнессета над правительством и правах граждан (смысл каждого закона определили три модели ИИ и перепроверили по тексту). «ослаблял» — фракция чаще голосовала за ослабление; «укреплял» — наоборот; числа — сколько раз в какую сторону. «не уверены» (здесь и в колонке религии) — если смысл части законов прочитан с ошибкой, вывод может смениться; «уверенность не считали» — у Яшар!: это голоса двух человек, такую проверку к ним не применяли.</p>
<p><b>Колонка «Религия в государстве»</b> — законы о месте религии в государстве (та же проверка ИИ). <b>за больше религии</b> выделено жирным: ты 19.10 сказал, что для тебя это довод исключить список. «за меньше религии» — наоборот.</p>
<p>{example}</p>
<p><b>Жирным</b> выделено только то, что ты сам назвал доводом исключить: «за» по четырём законам и «за больше религии».</p>
<p>Где не работает: «Резервисты» в этом Кнессете не заседали — о них лист молчит; «Яшар!» — по личным голосам двоих. Это сводка голосований, а не совет, за кого голосовать.</p>
</div>
<table><thead><tr><th scope=col>Буквы · список · лидеры</th>{heads}<th scope=col class=leanh>Суд и права в целом</th><th scope=col class=relh>Религия в государстве</th><th scope=col>Ис&shy;клю&shy;чаю</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<footer>Собрано {date.today():%d.%m.%Y} · <a href="index.html">подробно — на сайте</a></footer>
</body></html>"""


def selftest(page: str) -> None:
    rows = re.findall(r'<tr data-ballot-list=.*?</tr>', page, re.S)
    assert len(rows) == 14, "шпаргалка: не 14 строк"
    for r in rows:
        assert re.search(r'class="ballot-letters"[^>]*>[^<]+<', r), "нет букв"
        cells = re.findall(r'<span>(.*?)</span>', re.search(r'class="ballot-laws">(.*?)</span></td>', r, re.S)[1])
        assert len(cells) == 4 and all(re.sub(r"<[^>]+>", "", c) for c in cells), "не 4 позиции словами"
        assert not re.search(r'[↑↓↕]', r), "стрелка без слова"
    assert "Пример: Ликуд голосовал «за»" in page, "нет примера"
    noted = [r for r in rows if "Судим по" in r]
    assert len(noted) == 2 and any("Беннет в этом Кнессете не заседал" in r for r in noted) \
        and any("Айзенкота и Тропера" in r for r in noted), "«чьи голоса»: только Беяхад и Яшар! (владелец 19.10)"
