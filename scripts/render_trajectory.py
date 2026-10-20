#!/usr/bin/env python3
"""Траектория списков 20→25 на сайте (решения владельца 20.10, criteria/trajectory_2026-10-20.json).

Два обзора: по темам (шкала горизонтальная) и по партиям (вертикальная, «вверх» наверху),
и блок на странице каждого списка. Данные — data/trajectory.json (scripts/trajectory.py),
своей арифметики нет: доля «вверх» = up/(up+down) точки, где прибор поставил направление.
Без JavaScript; краски — только переменные палитры; кегли — шкала сайта.
"""
from __future__ import annotations
import html, json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
esc = html.escape
DATA = ROOT / "data" / "trajectory.json"
TH = [("rule_of_law", "Суд и права", "укреплял", "ослаблял"), ("religion_state", "Религия", "больше религии", "меньше религии"),
      ("economy", "Экономика", "легче бизнесу", "строже к бизнесу"), ("security", "Безопасность", "шире силовикам", "уже силовикам")]
ROLE = {"gov": "в коалиции", "opp": "в оппозиции", "trans": "переход: правительство ещё не присягнуло"}
CSS = """
.tj svg{width:100%;height:auto;display:block;max-width:40rem}.tj svg.vc{max-width:34rem}.tj .sc{overflow-x:auto}
.tj .g{fill:var(--ink)}.tj .o{fill:var(--bg);stroke:var(--ink)}.tj .t{fill:var(--panel);stroke:var(--dim);stroke-dasharray:3 2}.tj .m{fill:var(--rule);stroke:var(--ink)}
.tj .lg{fill:var(--bg)}.tj .lo,.tj .lt,.tj .lm{fill:var(--ink)}.tj .ax{stroke:var(--rule)}.tj .mid{stroke:var(--dim);stroke-dasharray:2 3}
.tj .ar{stroke:var(--dim);stroke-width:1.4;fill:none}.tj .ah{fill:var(--dim)}.tj text{fill:var(--ink)}.tj .nm{paint-order:stroke;stroke:var(--bg);stroke-width:3px}.tj .w{fill:var(--dim)}
.tj .how{border:1px solid var(--rule);background:var(--panel);padding:.6rem .8rem;font-size:.9rem}
.tj ul.v{list-style:none;padding:0;margin:.3rem 0}.tj ul.v li{margin:.15rem 0}.tj .n{color:var(--dim);font-size:.78rem}
.tj table{width:100%;border-collapse:collapse;font-size:.78rem}.tj table.why{table-layout:fixed}.tj table.why th:first-child{width:2.6rem}.tj th,.tj td{padding:.25rem .3rem;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
"""
VERD = {"steady": "одна линия — «{d}» — и в коалиции, и в оппозиции",
        "mixed_dir": "разнонаправленно: в основном «{d}» и в коалиции, и в оппозиции, но были сроки «и так, и так»",
        "holds_gov": "в коалиции одна линия — «{d}»; в оппозиции — и так, и так",
        "holds_opp": "в оппозиции одна линия — «{d}»; в коалиции — и так, и так",
        "one_role_gov": "одна линия — «{d}», но только в коалиции: позицию от обязательства не отличить",
        "one_role_opp": "одна линия — «{d}», но только в оппозиции: позицию от обязательства не отличить",
        "by_role": "меняется вместе с ролью",
        "shifts": "меняется, и не только вместе с ролью",
        "mixed": "ясной линии нет — чаще голосовал и так, и так",
        "few": "мало данных"}


def load():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    ballot = json.loads((ROOT / "criteria" / "ballot_2026.json").read_text(encoding="utf-8"))["lists"]
    return d, ballot


def share(p, th):
    x = p["themes"].get(th) or {}
    if x.get("arrow") not in ("up", "down", "both"):
        return None
    return x["up"] / (x["up"] + x["down"])


def verdict_text(line, th, up, dn):
    v = line["verdict"][th]
    dirs = {(p["themes"].get(th) or {}).get("arrow") for p in line["points"] if p["role"] in ("gov", "opp")} & {"up", "down"}
    d = up if dirs == {"up"} else dn if dirs == {"down"} else ""
    n = v["clear"]
    tail = "" if v["label"] == "few" and n == 0 else f' <span class=n>({n} {plural(n, "ясная точка", "ясные точки", "ясных точек")})</span>'
    return esc(VERD[v["label"]].format(d=d)) + tail


def marks(pts, lo=None, hi=None):
    """pts: [(label, x, y, role, title)] → совпадающие точки одной меткой «20·23»; lo/hi — границы рисунка."""
    groups = []
    for lab, x, y, rk, ttl in pts:
        for g in groups:
            if abs(g[1] - x) < 16 and abs(g[2] - y) < 16:
                g[0].append((lab, rk, ttl)); break
        else:
            groups.append([[(lab, rk, ttl)], x, y])
    out = []
    for items, x, y in groups:
        lab = "·".join(dict.fromkeys(i[0] for i in items))
        roles = {i[1] for i in items}
        rk = next(iter(roles)) if len(roles) == 1 else "m"
        cls = {"gov": "g", "opp": "o", "trans": "t"}.get(rk, "m")
        w = 18 if len(lab) <= 2 else 7 * len(lab) + 6
        if lo is not None:
            x = min(max(x, lo + w / 2), hi - w / 2)
        ttl = "; ".join(i[2] for i in items)
        out.append(f'<g><title>{esc(ttl)}</title><rect class={cls} x="{x-w/2:.1f}" y="{y-9:.1f}" width="{w}" height="18" rx="9"/>'
                   f'<text class=l{cls} x="{x:.1f}" y="{y+3.5:.1f}" font-size="9.5" text-anchor="middle">{esc(lab)}</text></g>')
    return "".join(out)


def seg(x1, y1, x2, y2, r=10):
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L < 2 * r + 4:
        return ""
    ux, uy = dx / L, dy / L
    ex, ey = x2 - ux * (r + 1), y2 - uy * (r + 1)
    # наконечник без marker-id: id на странице пришлось бы делать уникальными
    hx, hy = ex - ux * 6, ey - uy * 6
    px, py = -uy * 3.5, ux * 3.5
    return (f'<line class=ar x1="{x1+ux*r:.1f}" y1="{y1+uy*r:.1f}" x2="{hx:.1f}" y2="{hy:.1f}"/>'
            f'<path class=ah d="M{ex:.1f} {ey:.1f}L{hx+px:.1f} {hy+py:.1f}L{hx-px:.1f} {hy-py:.1f}z"/>')


def ttl(p, th, up, dn):
    x = p["themes"].get(th) or {}
    return f'{p["k"]}-й, {ROLE[p["role"]]} ({p["from"][8:10]}.{p["from"][5:7]}.{p["from"][:4]}–{p["to"][8:10]}.{p["to"][5:7]}.{p["to"][:4]}): {x.get("up")} — «{up}», {x.get("down")} — «{dn}»'


def plotted(line, th):
    return [p for p in line["points"] if share(p, th) is not None]


# ───────────── горизонтальный ряд (обзор по темам)
def hchart(rows, up, dn):
    """Ширина под телефон (вылета нет): имя списка над своей дорожкой, шкала во всю ширину."""
    W, X0, X1, RH, top = 400, 16, 384, 62, 62
    g = []
    for p, t, anc in ((0, f"только «{dn}»", "start"), (.5, "поровну", "middle"), (1, f"только «{up}»", "end")):
        g.append(f'<text class=w x="{X0+(X1-X0)*p:.0f}" y="14" font-size="10.5" text-anchor="{anc}">{esc(t)}</text>')
    H = top + (len(rows) - 1) * RH + 22
    for p in (0, .5, 1):
        g.append(f'<line class="{"mid" if p == .5 else "ax"}" x1="{X0+(X1-X0)*p:.0f}" x2="{X0+(X1-X0)*p:.0f}" y1="20" y2="{H-4}"/>')
    for r, (label, href, line, th) in enumerate(rows):
        y = top + r * RH
        name = f'<text class=nm x="{X0}" y="{y-24}" font-size="11.5">{esc(label)}</text>'
        names = (f'<a href="{href}">{name}</a>' if href else name)
        g.append(f'<line class=ax x1="{X0}" x2="{X1}" y1="{y}" y2="{y}"/>')
        pts = plotted(line, th) if line else []
        st = min(5, 24 / max(1, len(pts) - 1))          # лесенка не выше подписи
        ys = [y + (j - (len(pts) - 1) / 2) * st for j in range(len(pts))]
        xs = [X0 + (X1 - X0) * share(p, th) for p in pts]
        chain = [j for j, p in enumerate(pts) if p["role"] != "trans"]   # переход — без стрелок, только точка
        for a, b in zip(chain, chain[1:]):
            g.append(seg(xs[a], ys[a], xs[b], ys[b]))
        g.append(marks([(p["k"], x, yy, p["role"], ttl(p, th, up, dn)) for p, x, yy in zip(pts, xs, ys)], 2, W - 2))
        g.append(names)                                  # имя поверх точек, с ореолом фона
        if not pts:
            g.append(f'<text class=w x="{X0+4}" y="{y+4}" font-size="10">законов с ясным направлением нет</text>')
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="траектории">{"".join(g)}</svg>'


# ───────────── вертикальные колонки (обзор по партиям, страница списка)
def wrap2(s):
    w = s.split()
    if len(w) == 1:
        return [s]
    k = max(1, len(w) // 2)
    return [" ".join(w[:k]), " ".join(w[k:])]


def vchart(line):
    CW, W, Y0, Y1 = 100, 400, 46, 236
    H = Y1 + 40
    g = []
    for c, (th, t, up, dn) in enumerate(TH):
        cx = c * CW + CW / 2
        g.append(f'<text x="{cx}" y="12" font-size="11" text-anchor="middle" font-weight="bold">{esc(t)}</text>')
        for j, s in enumerate(wrap2(up)):
            g.append(f'<text class=w x="{cx}" y="{25+j*10}" font-size="9" text-anchor="middle">{esc(s)}</text>')
        for j, s in enumerate(wrap2(dn)):
            g.append(f'<text class=w x="{cx}" y="{Y1+16+j*10}" font-size="9" text-anchor="middle">{esc(s)}</text>')
        g.append(f'<line class=ax x1="{cx}" x2="{cx}" y1="{Y0-6}" y2="{Y1+6}"/>')
        g.append(f'<line class=mid x1="{c*CW+8}" x2="{c*CW+CW-8}" y1="{(Y0+Y1)/2}" y2="{(Y0+Y1)/2}"/>')
        pts = plotted(line, th)
        n = len(pts)
        step = min(14, (CW - 24) / max(1, n - 1)) if n > 1 else 0
        xs = [cx + (j - (n - 1) / 2) * step for j in range(n)]
        ys = [Y1 - (Y1 - Y0) * share(p, th) for p in pts]
        chain = [j for j, p in enumerate(pts) if p["role"] != "trans"]
        for a, b in zip(chain, chain[1:]):
            g.append(seg(xs[a], ys[a], xs[b], ys[b]))
        g.append(marks([(p["k"], x, y, p["role"], ttl(p, th, up, dn)) for p, x, y in zip(pts, xs, ys)], c * CW + 2, c * CW + CW - 2))
        if not n:
            g.append(f'<text class=w x="{cx}" y="{(Y0+Y1)/2-6}" font-size="9" text-anchor="middle">нет</text>')
    g.append(f'<text class=w x="{W-2}" y="{(Y0+Y1)/2-4}" font-size="8" text-anchor="end">поровну</text>')
    return f'<svg class=vc viewBox="0 0 {W} {H}" role="img" aria-label="траектория по темам">{"".join(g)}</svg>'


def details_table(line):
    rows = []
    for p in line["points"]:
        cells = []
        for th, t, up, dn in TH:
            x = p["themes"].get(th) or {}
            if x.get("up") is None:
                cells.append("<td>—</td>")
                continue
            w = {"up": up, "down": dn, "both": "и так, и так"}.get(x.get("arrow"), "мало законов")
            cells.append(f"<td>{esc(w)} <span class=n>{x['up']}–{x['down']}</span></td>")
        rows.append(f'<tr><th scope=row>{p["k"]}-й<br><span class=n>{esc(ROLE[p["role"]])}, '
                    f'{p["from"][8:10]}.{p["from"][5:7]}.{p["from"][2:4]}–{p["to"][8:10]}.{p["to"][5:7]}.{p["to"][2:4]}</span></th>{"".join(cells)}</tr>')
    return ('<div class=sc><table><thead><tr><th scope=col>Кнессет, роль</th>' + "".join(f"<th scope=col>{t}</th>" for _, t, *_ in TH)
            + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
            '<p class=n>Числа — законов «вверх–вниз» по теме за этот кусок срока. «Мало законов» — меньше трёх, направления нет.</p>')


def how_h(d) -> str:
    """Пример в подсказке считается из данных, а не вписан руками."""
    p = next(p for p in d["lines"]["מחל"][0]["points"] if p["k"] == "25" and p["role"] == "gov")
    x = p["themes"]["rule_of_law"]
    return HOW_H.replace("{EX}", f'Например, Ликуд в 25-м в коалиции по суду: {x["up"]} {plural(x["up"], "закон", "закона", "законов")} «укреплял» из {x["up"] + x["down"]} — точка почти у левого края. ')


HOW_H = ('<div class=how><b>Как читать.</b> Дорожка — список (имя над ней), точка — кусок Кнессета, когда фракция была в одной роли. '
         'Чем правее точка, тем чаще фракция голосовала «вверх» по теме; у левого края — только «вниз», посередине — поровну. '
         '{EX}'
         'Залитая точка — в коалиции, пустая — в оппозиции, серая с пунктиром — переход: Кнессет уже присягнул, правительство ещё нет '
         '(такие точки в вывод не входят). Стрелка ведёт к следующему куску в коалиции или оппозиции; каждый следующий чуть ниже. Совпавшие — одной меткой «20·23». '
         'Наведи на точку — даты и числа.</div>')
EMPTY_LEGEND = ('<p class=n>Пустота бывает разной. «Фракции не было» — партия в этот Кнессет не прошла. '
                '«Поимённых голосований нет» — фракция была, но голосований с её участием в источнике нет. '
                '«По теме не голосовали» — голосования были, но ни одного закона этой темы. '
                '«Со всеми» — законы темы были, но почти все голосовали одинаково, и такие голосования прибор не считает: это сигнал «тут не спорили». '
                '«Мало законов» — меньше трёх. «Переход» — правительство ещё не присягнуло, в вывод не входит. '
                'Голосований без привязки к законопроекту (процедура, повестка) в расчёте нет — их тему узнать нельзя.</p>')

HOW_V = ('<div class=how><b>Как читать.</b> Колонка — тема. Чем выше точка, тем чаще фракция голосовала «вверх» по теме '
         '(укреплял суд, больше религии, легче бизнесу, шире силовикам); внизу — только «вниз», на пунктире — поровну. '
         'Точка — кусок Кнессета в одной роли, слева направо по времени. Залитая — в коалиции, пустая — в оппозиции, '
         'серая с пунктиром — переход (в вывод не входит). Числа и даты — в таблице «подробно».</div>')


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    return one if n10 == 1 and n100 != 11 else few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many


KN6 = ("20", "21", "22", "23", "24", "25")
ROLE_SHORT = {"gov": "коал.", "opp": "опп.", "trans": "переход"}


def piece_word(x: dict, up: str, dn: str) -> str:
    """Состояние одного куска срока по теме — словами сайта (theme_arrows): направление или причина пустоты."""
    a = x.get("arrow")
    if a in ("up", "down", "both"):
        return {"up": up, "down": dn, "both": "и так, и так"}[a]
    n = (x.get("up") or 0) + (x.get("down") or 0)
    c = x.get("consensus") or 0
    if x.get("up") is None or (n == 0 and c == 0):
        return "по теме не голосовали"
    if c >= 3:
        return f"со всеми ({c})"
    return f"мало законов ({n + c})"   # все законы темы в куске, включая единогласные (criteria 777b615)


def knesset_cell(line: dict, k: str, th: str, up: str, dn: str) -> str:
    if not line.get("links", {}).get(k):
        return "<span class=n>фракции не было</span>"
    pts = [p for p in line["points"] if p["k"] == k]
    if not pts:
        return "<span class=n>фракция была, поимённых голосований нет</span>"
    sig = lambda p: (p["themes"].get(th) or {}).get("arrow") in ("up", "down", "both")
    shown = [p for p in pts if p["role"] != "trans" or sig(p)] or pts[:1]   # пустой переход не повторяем (край v92: только переходы — первый)
    has = lambda p: (p["themes"].get(th) or {}).get("up") is not None
    if any(has(p) for p in shown):          # кусок без голосов по теме не дублирует соседний кусок с голосами
        shown = [p for p in shown if has(p)]
    parts = []
    for p in shown:
        w = piece_word(p["themes"].get(th) or {}, up, dn)
        cls = "" if (p["themes"].get(th) or {}).get("arrow") in ("up", "down", "both") else " class=n"
        lab = "" if len(shown) == 1 and p["role"] == "trans" and not sig(p) else f"{ROLE_SHORT[p['role']]}: "
        parts.append(f"<span{cls}>{lab}{esc(w)}</span>")
    return "<br>".join(parts)


def why_table(line: dict) -> str:
    """Тема × Кнессет: где сигнал, а где — какая именно пустота (владелец 20.10)."""
    rows = "".join(f"<tr><th scope=row>{k}-й</th>" + "".join(f"<td>{knesset_cell(line, k, th, up, dn)}</td>" for th, t, up, dn in TH) + "</tr>"
                   for k in KN6)
    short = {"rule_of_law": "Суд", "religion_state": "Религия", "economy": "Эконом.", "security": "Безоп."}
    return ('<table class=why><thead><tr><th scope=col>Кн.</th>' + "".join(f"<th scope=col>{short[th]}</th>" for th, *_ in TH)
            + f'</tr></thead><tbody>{rows}</tbody></table>')


def line_section(line, heading="h3"):
    vs = "".join(f"<li><b>{t}:</b> {verdict_text(line, th, up, dn)}</li>" for th, t, up, dn in TH)
    return (f'<{heading}>{esc(line["name"])}</{heading}>{vchart(line)}<ul class=v>{vs}</ul>'
            f'<details><summary>Где сигнал, а где пусто — и почему</summary>{why_table(line)}{EMPTY_LEGEND}</details>'
            f'<details><summary>Подробно: {len(line["points"])} {plural(len(line["points"]), "кусок", "куска", "кусков")} срока</summary>{details_table(line)}</details>')


def list_block(letters: str) -> str:
    """Блок «Как менялся список» на странице списка (l-N.html)."""
    if not DATA.exists():      # самопроверки рендера во временном корне
        return ""
    d, _ = load()
    lines = d["lines"].get(letters) or []
    if not lines:
        return ""
    body = "".join(line_section(l) for l in lines)
    more = "Линии предшественников — каждая отдельно: общий список входит в линию каждой партии-участницы, голоса у них одни." if len(lines) > 1 else ""
    return (f'<section class="tj list-traj"><h2>Как менялся список: Кнессеты 20→25</h2>{HOW_V}'
            f'<p class=n>{esc(more)} Все списки: <a href="trajectory.html">по темам</a> · <a href="trajectory_parties.html">по партиям</a>.</p>{body}</section>')


def page(title, body, css_base):
    return (f'<!doctype html><html lang=ru><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<meta name="robots" content="noindex, nofollow"><title>{esc(title)}</title>\n<style>{css_base}{CSS}</style></head><body>\n'
            f'<nav class=crumbs><a href="index.html#ballot">Все списки</a></nav>\n{body}</body></html>')


def pages(css_base: str, footer: str = "") -> dict:
    if not DATA.exists():      # снимок входов §14 без траектории — страниц нет, без заглушки
        return {}
    d, ballot = load()
    order = [(i + 1, b) for i, b in enumerate(ballot)]
    rule = ('<p class=n>Правило вывода объявлено до расчёта и утверждено владельцем 20.10.2026: роль — по дате каждого голосования; '
            'переход между присягой Кнессета и присягой правительства в вывод не входит; «ясная» точка — где одна сторона набрала две трети '
            'законов темы (не меньше трёх законов). Направления в 20–24-м прочитаны по названиям законов. 21-й и 22-й Кнессеты правительства '
            'не сформировали и законов почти не приняли — их точек обычно нет.</p>')
    sw = lambda cur: ('<p>Группировка: ' + ('<b>по темам</b>' if cur == "t" else '<a href="trajectory.html">по темам</a>') + ' · '
                      + ('<b>по партиям</b>' if cur == "p" else '<a href="trajectory_parties.html">по партиям</a>') + '</p>')
    blocks = []
    for th, t, up, dn in TH:
        rows = []
        for num, b in order:
            lines = d["lines"].get(b["letters"]) or []
            main = lines[0] if lines else None
            rows.append((b["ru"] if len(b["ru"]) <= 30 else b["ru"][:29] + "…", f"l-{num}.html", main, th))
        extra = [f'{esc(b["ru"])}: ещё {len(d["lines"][b["letters"]]) - 1}' for _, b in order if len(d["lines"].get(b["letters"]) or []) > 1]
        blocks.append(f'<h2>{t}</h2>{hchart(rows, up, dn)}<p class=n>В строке — главная линия списка. Есть и другие линии '
                      f'(на странице списка): {"; ".join(extra)}.</p>')
    by_theme = page("Куда двигался каждый список",
                    '<section class=tj><h1>Куда двигался каждый список: Кнессеты 20→25</h1>' + sw("t") + how_h(d) + "".join(blocks) + rule + '</section>' + footer, css_base)
    parts = []
    for num, b in order:
        lines = d["lines"].get(b["letters"]) or []
        head = (f'<h2><a href="l-{num}.html">{esc(b["ru"])}</a> <span lang=he dir=rtl><bdi>{esc(b["he"])}</bdi></span></h2>'
                f'<p class=n>{esc(b["leaders"])}</p>')
        if not lines:
            parts.append(head + f'<p>{esc("; ".join(b.get("absent") or [])) or "в Кнессетах 20–25 не заседал"}.</p>')
            continue
        parts.append(head + "".join(line_section(l, "h3") for l in lines))
    by_party = page("Как менялся каждый список",
                    '<section class=tj><h1>Как менялся каждый список: Кнессеты 20→25</h1>' + sw("p") + HOW_V + "".join(parts) + rule + '</section>' + footer, css_base)
    return {"trajectory.html": by_theme, "trajectory_parties.html": by_party}


def selftest() -> int:
    line = {"name": "x", "points": [{"k": "20", "role": "gov", "from": "2015-06-01", "to": "2019-01-01",
                                     "themes": {"rule_of_law": {"arrow": "down", "up": 4, "down": 53}}}],
            "verdict": {th: {"label": "few", "clear": 1} for th, *_ in TH}}
    assert abs(share(line["points"][0], "rule_of_law") - 4 / 57) < 1e-9
    assert share(line["points"][0], "economy") is None
    assert "(1 ясная точка)" in verdict_text(line, "rule_of_law", "укреплял", "ослаблял")
    assert "<script" not in vchart(line) and "marker" not in vchart(line)
    assert [plural(k, "кусок", "куска", "кусков") for k in (1, 2, 5, 11, 21, 22)] == ["кусок", "куска", "кусков", "кусков", "кусок", "куска"]
    print("самопроверка render_trajectory пройдена: 5 утверждений")
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
