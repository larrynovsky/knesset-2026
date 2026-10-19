# -*- coding: utf-8 -*-
"""Проверки вёрстки отчёта — с объявленной выборкой и подложенным нарушением.

ЗАЧЕМ ЭТОТ КАРКАС. 2026-08-01 четыре проверки этого файла отчитались зелёным,
не осмотрев ничего: одна искала клетки по образцу с кавычками, а в разметке
кавычек не было — нашла ноль клеток и напечатала «все клетки правильные».
Она напечатала бы это же про пустую страницу.

Работающая проверка и мёртвая проверка выглядят одинаково: обе зелёные.
Отличить их по выводу нельзя в принципе — отсутствие жалобы не выглядит никак.
Поэтому здесь два механизма, и оба обязательны:

  1. ВЫБОРКА. Каждая проверка возвращает N — сколько объектов осмотрела.
     N == 0 — красный, а не зелёный. Ноль легален только с объявленной
     причиной (`expect_zero=`). Это §23, применённый к проверкам вместо
     выгрузок: ожидание объявляется заранее, тихий недобор — отказ.

  2. МУТАНТ. Каждая проверка носит при себе заготовленное нарушение.
     `--selftest` подкладывает его и требует красного. Не покраснела —
     проверка мертва, и это видно сразу, а не через месяц.

СУДЬБА ФАЙЛА ОБЪЯВЛЕНА ЗАРАНЕЕ: тринадцать проверок отсюда — это будущий
`build_report.py --selftest` (бриф C, этап 2). При переносе каждая обязана
приехать вместе со своим мутантом; иначе переезд обнулит защиту.

    python3 scripts/check_report_canon.py <каталог>
    python3 scripts/check_report_canon.py <каталог> --selftest
"""
import re, sys, pathlib, html as _h
import hashlib, shutil, subprocess, tempfile, json
from datetime import date

# ─────────────────────────────────────────────────────────────── канон отчёта
# Решение владельца 19.10: в денежной клетке разрешено покрытие N из M.
CLOSED = ["укрепляла", "ослабляла", "и туда и обратно",
          "искали, не нашли", "пока не разбирали", "денежных обещаний пока не разбирали", "в бюджете нашлась строка под {n} из {m} обещаний"]
ARROW = {"укрепляла": "↑", "ослабляла": "↓", "и туда и обратно": "↕"}
FORBIDDEN = [r"прогон", r"чек-?лист", r"кворум", r"размеч|размет", r"перепис",
             r"классификатор", r"валидатор", r"единиц[аеы]\s+наблюдения",
             r"отложенн\w*\s+период", r"норм\w*\s+со\s+знаком", r"карточк"]
BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
DOCS_FREE = ("method.html", "axes.html")   # страницы методики: лексика разрешена

# Обход легален, но обязан быть громким, произнесённым и СЧИТАЕМЫМ (§24).
EXEMPTIONS = [
    dict(id="E1-проза", date="2026-08-01", by="владелец",
         what="канон значений обязателен в клетках; в прозе формулировка свободна"),
    dict(id="кегль-7", date="2026-08-01", by="владелец",
         what="семь ступеней шкалы кеглей вместо шести (добавлена 1.08rem)"),
]

# ───────────────────────────────────────────────────────────── разбор входа
def strip_comments(s):
    """CSS-комментарий — тоже комментарий. Прошлая редакция ловила
    `overflow-x:hidden` внутри комментария, объясняющего его отсутствие."""
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    return re.sub(r"/\*.*?\*/", " ", s, flags=re.S)

def text_of(s):
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    return _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", strip_comments(s))))

def cells_of(doc):
    """Клетки: значение обзора и заголовок раскрытия. Разбор, а не регулярка:
    клетка вложенная, и нежадный `.*?` обрывался на первом `</span>`,
    возвращая одну стрелку вместо значения."""
    out = []
    for m in re.finditer(r'<span class="?v[^">]*"?[^>]*>', doc):
        rest = doc[m.end():]
        # Порядок предпочтений, а не min(): подпись `lb` идёт ПОСЛЕ вложенной
        # стрелки, и min() обрывал клетку на её `</span>`, возвращая «↓» без
        # значения. Счётчик при этом честно показывал 56 — то есть считал
        # синтаксис, а не предмет.
        cut = rest.find("<span class=lb")
        if cut < 0: cut = rest.find('<span class="lb')
        if cut < 0: cut = rest.find("</span>")
        if cut < 0: cut = len(rest)
        t = _h.unescape(re.sub(r"<[^>]+>", "", rest[:cut])).replace("\u2009", " ").strip()
        a = ""
        if t and t[0] in "↑↓↕":
            a, t = t[0], t[1:].strip()
        out.append((a, t))
    for m in re.finditer(r"<summary[^>]*>(.*?)</summary>", doc, flags=re.S):
        t = re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", " ", m.group(1))))
        for v in CLOSED + ["в обе стороны"]:
            if v in t:
                out.append(("", v))
    return out

def styles(s):  return s[:s.find("</style>")] if "</style>" in s else ""
def party(src): return {n: v for n, v in src.items() if n not in DOCS_FREE}

# ──────────────────────────────────────────────────────────── каркас: реестр
CHECKS = []

def edit(src, fname, old, new, n=1):
    # Отсутствующий якорь — громкий отказ с адресом (R20-F01), а не тихое
    # «ничего не изменил» без объяснения, где искали.
    if old not in src[fname]:
        raise LookupError(f"{fname}: якорь {old[:50]!r} не найден")
    d = dict(src); d[fname] = d[fname].replace(old, new, n); return d

# Первая клетка обзора, какая есть: живой сайт без стрелок и принятый макет
# со стрелками испытываются одним и тем же воздействием (R20-F01).
CELL_RX = re.compile(r'(<span class="v[^"]*">)((?:<span class=a>[^<]*</span>&#8201;)?)([^<]+)')

def cell_edit(src, mk):
    s = src["index.html"]
    m = CELL_RX.search(s)
    if not m:
        raise LookupError("index.html: ни одной клетки со значением")
    d = dict(src)
    d["index.html"] = s[:m.start()] + m.group(1) + mk(m.group(3)) + s[m.end():]
    return d

def party_page(src):
    for n in sorted(party(src)):
        if n.startswith("f-") and "<h1>" in src[n]:
            return n
    raise LookupError("нет страницы партии с <h1>")

def anyfile(src): return sorted(src)[0]

def filewith(src, needle):
    """Файл, в котором мутируемое место реально существует. Без этого мутант
    может «подложить» нарушение в файл, где подкладывать некуда, — и проверка
    останется зелёной не потому, что мертва, а потому, что её не трогали."""
    for n in sorted(src):
        if needle in src[n]: return n
    raise LookupError(f"ни в одном файле нет {needle!r} — мутант невозможен")

def check(name, mutants, expect_zero=None):
    """mutants — [(подпись, функция src -> испорченный src)]."""
    def deco(fn):
        CHECKS.append(dict(name=name, fn=fn, mutants=list(mutants), expect_zero=expect_zero))
        return fn
    return deco

# ───────────────────────────────────────────────────────────────── проверки
@check("согласование числительных (v36)",
       [("возвращено 4 законов", lambda s: edit(s, anyfile(s), "</body>",
          "<p>4 законов в сторону плюса</p></body>")),
        ("возвращено из 131 законов", lambda s: edit(s, anyfile(s), "</body>",
          "<p>из 131 законов</p></body>"))])
def c_plural_ru(src):
    # §20–24: независимый HTML-оракул; не вызывает проверяемый plural_ru.
    bad = []
    for name, html in src.items():
        text = text_of(html)
        for m in re.finditer(r"\b(\d*1)\s+(законов|актов|голосований|обещаний)\b|"
                             r"\b(\d*[234])\s+(законов|актов)\b", text):
            n = int(m[1] or m[3])
            if 11 <= n % 100 <= 14:
                continue
            # В родительном: из 4 законов, но из 21 закона.
            if m[3] and re.search(r"\b(?:из|у|до|от|после|около)\s+$", text[:m.start()], re.I):
                continue
            bad.append(f"{name}: {m[0]}")
    return len(src), bad, f"{len(src)} страниц"


@check("деньги бюллетеня = обзор = фракция (v53)",
       [("подменено N", lambda s: edit(s, "index.html", '>вторая сторона: 46/71</span>', '>вторая сторона: 45/71</span>')),
        ("подменён title", lambda s: dict(s, **{"index.html": re.sub(
            r'(<td data-l="Деньги"><span title=")[^"]+', r'\1подмена', s["index.html"], count=1)})),
        ("удалена денежная клетка", lambda s: dict(s, **{"index.html": re.sub(
            r'<td data-l="Деньги">.*?</td>', '', s["index.html"], count=1)}))])
def c_ballot_money(src):
    from render_overview import load_ballot, _money_td, check_money_same
    doc = src["index.html"]
    rows = re.findall(r'<tr data-ballot-list="([^"]+)">(.*?)</tr>', doc, re.S)
    expected = load_ballot()["lists"]
    bad = []
    if len(rows) != len(expected):
        bad.append("число строк бюллетеня")
    for (name, row), entry in zip(rows, expected):
        groups = {}
        for fid in entry.get("factions", []):
            full = text_of(_money_td(doc, fid)).strip()
            check_money_same(doc, src[f"f-{fid}.html"], fid)
            # Независимое чтение чисел из обзорной клетки, не вызов форматтера.
            pair = re.search(r"под (\d+) из (\d+)", full)
            leader = re.search(r"после разбора: (\d+);.*под (\d+)", full)
            value = (f"{leader[2]}/{leader[1]}" if leader else
                     f"{pair[1]}/{pair[2]}" if pair else
                     "—" if "не подписывала" in full else "?")
            if value not in ("—", "?") and "подписала как вторая сторона" in full:
                value = "вторая сторона: " + value
            groups.setdefault(value, []).append(full)
        cells = re.findall(r'<td data-l="Деньги">(.*?)</td>', row)
        wanted = ' / '.join(f'<span title="{_h.escape(" / ".join(dict.fromkeys(full)), quote=True)}">{value}</span>'
                            for value, full in groups.items()) or '?'
        if cells != [wanted]:
            bad.append(f"{_h.unescape(name)}: деньги или title расходятся с обзором")
    if '<th scope=col>Безопасность</th><th scope=col>Деньги</th>' not in doc:
        bad.append("порядок денежных колонок")
    legend = "Деньги: N/M — для скольких денежных обещаний из коалиционного соглашения в бюджете нашлась статья; это не значит, что деньги выделены полностью"
    if legend not in doc:
        bad.append("нет денежной легенды")
    return len(rows), bad, f"{len(rows)} строк; значения и полные title"


@check("компактные клетки бюллетеня (v42)",
       [("убран значок ненадёжной стрелки", lambda s: dict(s, **{"index.html": re.sub(
           r'(title="ненадёжна: [0-9.]+%">[↑↓↕]<small class="robustness">)\?\?(</small>)', r'\1\2', s["index.html"], count=1)})),
        ("возвращено длинное единогласие", lambda s: edit(s, "index.html", "со всеми (9/3)",
          "голосовали со всеми (почти единогласно: 9 законов)")),
        ("снят title устойчивости", lambda s: dict(s, **{"index.html": re.sub(
          r' title="устойчива: [0-9.]+%"', '', s["index.html"], count=1)})),
        ("снята оговорка личной стрелки", lambda s: edit(s, "index.html",
          ' title="Устойчивость личной стрелки не оценивалась"', ""))])
def c_compact_ballot(src):
    entries = re.findall(r'<td class="ballot-axis"([^>]*)>(.*?)</td>', src["index.html"], re.S)
    cells = [cell for _, cell in entries]
    bad = []
    for attrs, cell in entries:
        if "data-personal=1" in attrs:
            expected = re.findall(r'<span title="Устойчивость личной стрелки не оценивалась">[↑↓↕]</span>', cell)
            if len(expected) != len(re.findall(r'[↑↓↕]', cell)):
                bad.append("личная стрелка без оговорки об устойчивости")
            continue
        notes = re.findall(r'<span title="(устойчива|шаткая|ненадёжна): ([0-9.]+)%">[↑↓↕]<small class="robustness">(.*?)</small></span>', cell)
        if len(notes) != len(re.findall(r'[↑↓↕]', cell)):
            bad.append("стрелка без title со словом и процентом")
        for word, percent, mark in notes:
            expected = {"устойчива": "", "шаткая": "?", "ненадёжна": "??"}[word]
            if mark != expected:
                bad.append(f"{word}: неверный значок {mark!r}")
        if 'голосовали со всеми' in cell or 'почти единогласно' in cell:
            bad.append("длинная клетка единогласия")
    if 'со всеми (9/3)' not in cells:
        bad.append("Ликуд: не сохранены оба числа 9/3")
    return len(cells), bad, f"{len(cells)} клеток; значки и title"


def list_page_mutant(src, pattern, replacement, filename="l-1.html"):
    changed, n = re.subn(pattern, replacement, src[filename], count=1)
    if n != 1:
        raise LookupError(f"{filename}: якорь {pattern!r} не найден")
    return dict(src, **{filename: changed})


@check("страница списка = строка таблицы (v52)",
       [("подмена стрелки l-1", lambda s: list_page_mutant(s,
           r'(<p data-theme="institutions"><b>[^<]+</b> )[↑↓↕]', r'\1↑')),
        ("подмена позиции закона в таблице", lambda s: list_page_mutant(s,
           r'(<span class="ballot-laws"><span title="[^"]*">)<b>за</b>',
           r'\1против', "index.html")),
        ("убраны буквы l-3", lambda s: list_page_mutant(s,
           r'<span class="ballot-letters"[^>]*>[^<]+</span>', '', "l-3.html")),
        ("подмена денег l-1", lambda s: edit(s, "l-1.html", '<b>Деньги:</b>', '<b>Деньги:</b> подмена')),
        ("потеря страницы l-14", lambda s: {k: v for k, v in s.items() if k != "l-14.html"}),
        ("потеря разделителя направлений", lambda s: edit(s, "index.html",
           '</small></span> / <span', '</small></span> <span')),
        ("потеря устойчивости l-14", lambda s: list_page_mutant(s,
           r'(<small class="robustness"[^>]*>) \(шаткая\)', r'\1 (устойчива)', "l-14.html"))])
def c_list_table(src):
    # §20–24: читаем выход двух рендеров, не вызываем их расчётные функции.
    # Ожидание 14 объявлено владельцем; пустые/дублированные поля — отказ.
    clean = lambda s: re.sub(r"\s+", " ", text_of(s)).strip()
    bad, seen = [], 0
    rows = re.findall(r'<tr data-ballot-list="[^"]*">(.*?)</tr>', src.get("index.html", ""), re.S)
    pages = {f"l-{i}.html" for i in range(1, 15)}
    if len(rows) != 14:
        bad.append(f"бюллетень: строк {len(rows)}, ожидалось 14")
    if {n for n in src if re.fullmatch(r'l-\d+\.html', n)} != pages:
        bad.append("бюллетень: состав страниц не l-1…l-14")
    used = []
    for row in rows:
        links = re.findall(r'href="(l-\d+\.html)"', row)
        if len(links) != 1:
            bad.append("бюллетень: нет единственной ссылки списка"); continue
        filename = links[0]
        used.append(filename)
        page = src.get(filename, "")
        name = clean(re.search(r'<a href="l-\d+\.html">(.*?)</a>', row, re.S)[1])

        def same(field, left, right):
            if not left or not right or left != right:
                bad.append(f"{name} ({filename}): {field}: таблица={left!r}, страница={right!r}")

        same("буквы", re.findall(r'<span class="ballot-letters"[^>]*>([^<]+)</span>', row),
             re.findall(r'<h1><span class="ballot-letters"[^>]*>([^<]+)</span>', page))
        # Только источники голосов в заголовке строки; сравнение Ганца у Яшар
        # не является источником личной позиции.
        sources = re.search(r'по голосам: (.*?)</span>', row)
        fids = re.findall(r'href="f-(\d+).html"', sources[1]) if sources else []
        sections = re.findall(r'<h2><a href="f-(\d+).html">.*?</h2>(.*?)(?=<h2>|</body>)', page, re.S)
        if fids != [fid for fid, _ in sections]:
            bad.append(f"{name} ({filename}): состав фракций расходится")
        personal = 'data-personal=1' in row
        law_cell = re.search(r'<td data-l="4 закона владельца">(.*?)</td>', row, re.S)
        table_laws = re.findall(r'<span title="[^"]*">(.*?)</span>', law_cell[1], re.S) if law_cell else []
        page_laws = []
        for fid, section in sections:
            positions = re.findall(r'<li><a href="grounds.html#a\d+">.*?</a>: <b>(.*?)</b>', section)
            if len(positions) != 4:
                bad.append(f"{name} ({filename}): 4 закона фракции {fid}: найдено {len(positions)}")
            page_laws.append([clean(v).replace("нет позиции", "—") for v in positions])
        if personal:
            positions = re.findall(r'<p>[^<]+: (за|против|воздержались|не голосовали|нет позиции) \(\d{4}-', page)
            page_laws = [["—" if v in ("не голосовали", "нет позиции") else v for v in positions]]
        if fids or personal:
            expected = ["/".join(dict.fromkeys(v[i] for v in page_laws)) for i in range(4)] if page_laws and all(len(v) == 4 for v in page_laws) else []
            same("4 закона", [re.sub(r"\s*/\s*", "/", clean(v)) for v in table_laws], expected)
        else:
            same("4 закона без голосов", clean(law_cell[1]) if law_cell else "", "—" if 'голосов в этом Кнессете нет' in page else "")
        table_axes = re.findall(r'<td class="ballot-axis"[^>]*>(.*?)</td>', row, re.S)
        for i, topic in enumerate(("institutions", "religion_state", "economy", "security")):
            values = []
            for section in ([page] if personal else [v for _, v in sections]):
                match = re.search(r'<p data-(?:personal-)?theme="' + topic + r'"><b>[^<]+</b> (.*?)</p>', section, re.S)
                value = clean(match[1]) if match else ""
                arrow = re.match(r'[↑↓↕]', value)
                if arrow:
                    mark = "??" if "(ненадёжна)" in value else "?" if "(шаткая)" in value else ""
                    values.append(arrow[0] + mark)
                else:
                    token = re.match(r'(?:со всеми|мало законов) \(\d+\)', value)
                    values.append(token[0] if token else "—" if value.startswith("направление не установлено") else "")
            if fids or personal:
                if values and all(re.fullmatch(r'со всеми \(\d+\)', v) for v in values):
                    expected = "со всеми (" + "/".join(re.search(r'\d+', v)[0] for v in values) + ")"
                else:
                    # Одинаковое направление сворачивается с худшей устойчивостью:
                    # ↑? и ↑ → ↑?; разные направления сохраняют «/».
                    grouped = {}
                    for v in values:
                        key = v.rstrip("?")
                        grouped[key] = max(grouped.get(key, v), v, key=len)
                    expected = " / ".join(grouped.values()) if all(values) else ""
                actual = clean(table_axes[i]) if len(table_axes) == 4 else ""
                # HTML-теги между стрелкой и ? не создают смыслового пробела.
                actual = re.sub(r'([↑↓↕])\s+(\?+)', r'\1\2', actual)
                same(topic, actual, expected)
            else:
                same(topic, "нет голосов" if 'голосов в этом Кнессете нет' in row else "", "нет голосов" if 'голосов в этом Кнессете нет' in page else "")
        for fid, section in sections:
            money_rows = [r for r in re.findall(r'<tr>(.*?)</tr>', src["index.html"], re.S)
                          if f'href="f-{fid}.html"' in r and 'class=c-eq' in r]
            cells = re.findall(r'<td class=c-eq[^>]*>(.*?)</td>', money_rows[0], re.S) if len(money_rows) == 1 else []
            words = cells_of(cells[0]) if len(cells) == 1 else []
            value = words[0][1] if len(words) == 1 else ""
            if value == "искали, не нашли" and cells:
                value = ("коалиционного соглашения не подписывала" if "коалиционного соглашения не подписывала" in cells[0]
                         else "денежных обещаний не найдено")
            money = re.findall(r'<p><b>Деньги:</b> (.*?)\.</p>', section, re.S)
            same(f"деньги фракции {fid}", [value] if value else [], [clean(v) for v in money])
        if not fids and '<b>Деньги:</b>' in page:
            bad.append(f"{name} ({filename}): деньги без связанной фракции")
        seen += 1
    if set(used) != pages or len(set(used)) != len(used):
        bad.append("бюллетень: ссылки списков неполны или повторяются")
    return seen, bad, f"{seen}/14 списков: буквы, 4 закона, 4 темы, деньги"


@check("ноль JavaScript",
       [("вставлен <script>", lambda s: edit(s, anyfile(s), "</body>", "<script>1</script></body>")),
        ("inline-обработчик onclick", lambda s: edit(s, anyfile(s), "<body>", '<body onclick="1">'))])
def c_js(src):
    bad = [n for n, s in src.items() if "<script" in s or re.search(r"\son\w+\s*=\s*[\"']", s)]
    return len(src), bad, f"{len(src)} страниц"

@check("ноль внешних запросов",
       [("@import с чужого домена", lambda s: edit(s, anyfile(s), "<style>", "<style>@import url('https://fonts.googleapis.com/x');")),
        ("картинка по http", lambda s: edit(s, anyfile(s), "</body>", '<img src="https://example.com/a.png"></body>'))])
def c_ext(src):
    bad = [n for n, s in src.items()
           if re.search(r'(src|href)\s*=\s*["\']https?://', s)
           or re.search(r'url\(\s*["\']?https?://', s)]
    return len(src), bad, ""

@check("noindex в каждом документе",
       [("noindex снят на одной странице", lambda s: edit(s, anyfile(s), "noindex, nofollow", "index, follow"))])
def c_noindex(src):
    bad = [n for n, s in src.items() if "noindex, nofollow" not in s]
    return len(src), bad, f"{len(src)}/{len(src)}"

def _frame_after(src):
    d = dict(src); s = d["index.html"]
    i = s.find("<div class=note id=frame")
    if i < 0: return d
    j = s.find("</div>", s.find("авторские", i)) + 6
    fr = s[i:j]
    d["index.html"] = (s[:i] + s[j:]).replace("</tbody></table>", "</tbody></table>" + fr, 1)
    return d

@check("рамка на каждом документе, до первой карточки",
       [("маркер рамки удалён", lambda s: edit(s, anyfile(s), "data-frame", "data-xxxxx")),
        ("рамка сдвинута за таблицу", _frame_after)])
def c_frame(src):
    bad = []
    for n, s in src.items():
        m = re.search(r'data-frame=["\']?(full|short)', s)
        if not m:
            bad.append(f"{n}: маркера нет"); continue
        b = s.find("<body")
        first = min([p for p in (s.find("<table", b), s.find("<details", b)) if p > 0] or [1 << 30])
        if m.start() > first: bad.append(f"{n}: рамка после первой карточки")
        if n == "index.html" and m.group(1) != "full": bad.append("index.html: рамка не full")
    return len(src), bad, f"{len(src)}/{len(src)}, позиция верна"

# v28: exact wording requested by owner, no free-form numeric verdicts.
LEADING_MONEY_PATTERN = (r"подписала как вторая сторона [0-9]+ денежн(?:ое обещание|ых обещания|ых обещаний) партнёрам в соглашениях правительства "
                         r"(?:37; самостоятельных обещаний после разбора: [0-9]+; в бюджете нашлась строка под [0-9]+"
                         r"|36 \(2021 год\)(?:; подтверждённых сопоставлений с бюджетом 2021 года: 0; сопоставление требует проверки"
                         r"|; разобрано вручную: [^<—]+ — строка бюджета нашлась под [0-9]+ из [0-9]+; у остальных сопоставление требует проверки))")
MONEY_PATTERN = (LEADING_MONEY_PATTERN + r"|в бюджете нашлась строка под [0-9]+ из [0-9]+ обещани(?:я|й)"
                 r"|в соглашении 2021 года найдено (?:[0-9]+ денежн(?:ое обещание|ых обещания|ых обещаний)|0 — правило извлечения ничего не нашло; это не значит, что обещаний нет); "
                 r"(?:бюджет этих лет не выгружен|сопоставление требует проверки)")

@check("значение клетки из закрытого списка, стрелка ↔ значение",
       [("денежное отсутствие со стрелкой", lambda s: cell_edit(s, lambda w: "<span class=a>↑</span>&#8201;денежных обещаний пока не разбирали")),
        ("значение вне списка", lambda s: cell_edit(s, lambda w: "скорее ослабляла")),
        ("ведущей стороне приписано авторство", lambda s: cell_edit(s, lambda w: "обещала 79 денежных обещаний партнёрам в соглашениях правительства 37; самостоятельных обещаний после разбора: 71; в бюджете нашлась строка под 46")),
        ("стрелка не та", lambda s: cell_edit(s, lambda w: "<span class=a>↑</span>&#8201;ослабляла")),
        ("неканоническая формулировка", lambda s: cell_edit(s, lambda w: "в обе стороны"))])
def c_closed(src):
    # Считаем клетки, ДАВШИЕ значение. Пустой разбор объектом не является:
    # иначе счётчик прикрывает вакуумность вместо того, чтобы её выдавать.
    cells = [(a, t) for a, t in cells_of(src["index.html"]) if t]
    bad = []
    for a, t in cells:
        if t not in CLOSED[:-1] and not re.fullmatch(MONEY_PATTERN, t): bad.append(f"вне списка: {t[:40]!r}")
        elif a != ARROW.get(t, ""): bad.append(f"{t!r} со стрелкой {a!r}")
    return len(cells), sorted(set(bad))[:4], f"{len(cells)} клеток со значением"

@check("цифры только в денежном покрытии",
       [("число в клетке", lambda s: cell_edit(s, lambda w: w + " 7 из 10"))])
def c_digits(src):
    tds = re.findall(r"<td class=c-(?:inst|eq)[^>]*>(.*?)</td>", src["index.html"], flags=re.S)
    bad = [t[:30] for t in tds if re.search(r"\d", re.sub(
        MONEY_PATTERN, "",
        _h.unescape(re.sub(r"<[^>]+>", "", t))))]
    return len(tds), bad[:3], f"{len(tds)} клеток"

@check("v45: четыре закона — участие и счёт депутатов",
       [("бойкот подменён голосом одного", lambda s: edit(s, "index.html", "— (1 против)", "против")),
        ("потерян счёт", lambda s: edit(s, "index.html", "не голосовали ≥22", "не голосовали неизвестно")),
        ("потерян счёт в списке", lambda s: edit(s, "l-2.html", "не голосовали ≥22", "не голосовали неизвестно"))])
def c_owner_votes(src):
    bad, inspected = [], 0
    count = r"за [0-9]+, против [0-9]+, воздержались [0-9]+; не голосовали ≥?[0-9]+"
    rows = re.findall(r'<tr data-owner-fid="([0-9]+)">(.*?)</tr>', src["index.html"])
    if len(rows) != 16:
        bad.append("нет 16 фракций четырёх законов")
    for fid, row in rows:
        cells = re.findall(r'<td title="([^"]*)">(.*?)</td>', row)
        inspected += len(cells)
        if len(cells) != 4 or any(not re.fullmatch(count, title) for title, _ in cells):
            bad.append(f"фракция {fid}: нет четырёх счетов")
        if fid in ("1102", "1096") and cells:
            expected = "— (1 против)" if fid == "1102" else "за"
            if cells[0][1] != expected:
                bad.append(f"фракция {fid}: неверная позиция 2201200")
    for name, page in src.items():
        if re.fullmatch(r"[lf]-[0-9]+\.html", name):
            items = re.findall(r'<li><a href="grounds.html#a[0-9]+">.*?</li>', page)
            inspected += len(items)
            if any(not re.search(r"\(" + count + r"\)", item) for item in items):
                bad.append(f"{name}: нет текстового счёта")
    for row in re.findall(r'<tr data-ballot-list=.*?</tr>', src["index.html"]):
        if 'href="f-1102.html"' in row:
            cell = re.search(r'<span class="ballot-laws">(.*?)</span></td>', row)
            if not cell or not re.search(r'<span title="[^"]*">— \(1 против\)</span>', cell[1]):
                bad.append("Беяхад: бойкот Еш Атид потерян")
    ballot = re.findall(r'<span class="ballot-laws">(.*?)</span></td>', src["index.html"])
    for cell in ballot:
        titles = re.findall(r'<span title="([^"]*)">', cell)
        if len(titles) != 4 or any(not re.search(count, title) for title in titles):
            bad.append("бюллетень: нет четырёх подсказок со счётом")
    if "— — нет позиции, фракция не голосовала или голосовала меньше трети (бойкот)" not in src["index.html"]:
        bad.append("нет легенды бойкота")
    return inspected, bad, f"{inspected} позиций с депутатским счётом"


@check("лексика страниц партий",
       [("пропал раздел методики", lambda s: edit(s, "method.html", "<h2>Устойчивость стрелки</h2>", "")),
        ("старое состояние в методике", lambda s: edit(s, "method.html", "<h1>", "<p>мы сюда не дошли</p><h1>")),
        ("фракции названы строками", lambda s: edit(s, "index.html", "<h1>", "<p>пять-шесть строк бюллетеня из шестнадцати</p><h1>")),
        ("старые подписи примеров", lambda s: edit(s, "index.html", "<h1>", "<p>Примеры в плюс:</p><h1>")),
        ("старое денежное состояние", lambda s: edit(s, "index.html", "<h1>", "<p>сопоставление денежных обещаний с бюджетом не построено</p><h1>")),
        ("слово «валидатор» в прозе", lambda s: edit(s, party_page(s), "<h1>", "<p>Так решил валидатор.</p><h1>"))])
def c_lex(src):
    pp, bad = party(src), []
    method = src.get("method.html", "")
    for heading in ("Списки бюллетеня и фракции", "Как ставился знак закона",
                    "Устойчивость стрелки", "Темы", "Деньги", "Чего нет"):
        if f"<h2>{heading}</h2>" not in method:
            bad.append(f"method.html: нет раздела «{heading}»")
    if "почему стрелки нет" in text_of(method).lower():
        bad.append("method.html: устаревшее утверждение об отсутствии стрелок")
    # v26: видимый текст всех страниц; CSS-комментарий остаётся допустимым.
    for n, page in src.items():
        visible = text_of(page).lower()
        for stale in ("мы сюда не дошли", "примеры в плюс", "примеры в минус",
                      "сопоставление денежных обещаний с бюджетом не построено",
                      "строк бюллетеня в сборке", "по строкам бюллетеня",
                      "строка бюллетеня (голоса", "пять-шесть строк бюллетеня"):
            if stale in visible:
                bad.append(f"{n}: устаревший текст «{stale}»")
    for n, s in pp.items():
        t = text_of(s).lower()
        for rule in FORBIDDEN:
            for m in re.finditer(rule, t):
                bad.append(f"{n}: «{t[max(0, m.start()-25):m.end()+25].strip()}»")
    return len(pp), bad[:3], f"{len(pp)} страниц чисты"

@check("управляющие символы направления письма",
       [("U+202E в цитате", lambda s: edit(s, filewith(s, "<bdi>"), "<bdi>", "<bdi>\u202e"))])
def c_bidi(src):
    bad = [n for n, s in src.items() if any(c in BIDI for c in s)]
    return len(src), bad, ""

@check("overflow-x:hidden отсутствует",
       [("маскировка на html", lambda s: edit(s, anyfile(s), "*{box-sizing:border-box}", "*{box-sizing:border-box}html{overflow-x:hidden}")),
        ("маскировка на контейнере", lambda s: edit(s, anyfile(s), "</style>", ".note{overflow:clip}</style>"))])
def c_overflow(src):
    bad = [n for n, s in src.items()
           if re.search(r"overflow(-x)?\s*:\s*(hidden|clip)", strip_comments(s))]
    return len(src), bad, ""

@check("шкала кеглей",
       [("восьмая ступень", lambda s: edit(s, anyfile(s), "</style>", ".x{font-size:2.11rem}</style>"))])
def c_sizes(src):
    sz = set()
    for s in src.values():
        sz |= {m.group(1) + "rem" for m in re.finditer(r"font(?:-size)?\s*:[^;}]*?([0-9.]+)rem", s)}
        sz |= {m.group(1) for m in re.finditer(r"--f\d:\s*([0-9.]+rem)", s)}
    bad = [] if len(sz) <= 7 else [f"{len(sz)} ступеней: {' '.join(sorted(sz))}"]
    return len(sz), bad, f"{len(sz)} ступеней (разрешено 7 — кегль-7)"

@check("палитра: только объявленные краски",
       [("краска вне палитры", lambda s: edit(s, anyfile(s), "</style>", ".x{color:#FF00AA}</style>"))])
def c_palette(src):
    decl = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}", styles(src["index.html"]))}
    used = set()
    for s in src.values():
        used |= {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}", styles(s))}
    return len(used), sorted(used - decl), f"{len(used)} красок"

@check("семантика: thead/scope, details/summary, bdi",
       [("фракции раскрыты по умолчанию", lambda s: edit(s, "index.html", '<details class="faction-details">', '<details open class="faction-details">')),
        ("таблицы вынесены из раскрытия", lambda s: edit(s, "index.html", '</summary>\n<h2 id="grounds">', '</summary></details>\n<h2 id="grounds">')),
        ("пример без списка", lambda s: edit(s, "index.html", "<h1>", "<p>в сторону ↑:</p><p>пример</p><h1>")),
        ("два примера в одном пункте", lambda s: edit(s, "index.html", "<h1>", "<p>в сторону укрепления:</p><ul><li><bdi>один</bdi>; <bdi>два</bdi></li></ul><h1>")),
        ("таблица без thead", lambda s: edit(s, "index.html", "<thead>", "<tbody-x>")),
        ("th без scope", lambda s: dict(s, **{"index.html": s["index.html"].replace("scope=col", "")})),
        ("RTL без bdi", lambda s: dict(s, **{k: v.replace("<bdi>", "").replace("</bdi>", "") for k, v in s.items()}))])
def c_sem(src):
    bad = []
    overview = src["index.html"]
    block = re.search(r'<details class="faction-details"><summary>Подробно по 16 фракциям нынешнего Кнессета \(для проверки\)</summary>(.*?)</details>', overview, re.S)
    if not block or re.findall(r'<table class=["\']?([\w-]+)', block[1]) != ["owner-laws", "ov", "acts"]:
        bad.append("три фракционные таблицы должны быть в закрытом details в прежнем порядке")
    elif '<table class="ballot">' not in overview[:block.start()] or '<table class="ballot">' in block[1]:
        bad.append("бюллетень должен предшествовать фракционному раскрытию")
    for n, s in src.items():
        for group in re.finditer(r"<p>в сторону (?:↑|↓|укрепления|ослабления):</p>(.*?)(?=<p|</section>)", s, re.S):
            block = group[1]
            if not re.fullmatch(r"<ul>(?:<li>.*?</li>)+</ul>", block, re.S):
                bad.append(f"{n}: примеры без ul/li")
            for item in re.findall(r"<li>(.*?)</li>", block, re.S):
                if item != "нет" and (item.count("<bdi>") != 1 or not item.startswith("<bdi>") or not item.endswith("</bdi>")):
                    bad.append(f"{n}: пример не отдельным пунктом")
        for table in re.findall(r"<table\b[^>]*>.*?</table>", s, flags=re.S):
            if "<thead" not in table: bad.append(f"{n}: таблица без thead")
            if any("scope=" not in th for th in re.findall(r"<th\b[^>]*>", table)):
                bad.append(f"{n}: th без scope")
        if "<details" in s and "<summary" not in s: bad.append(f"{n}: details без summary")
        if "dir=rtl" in s and "<bdi>" not in s: bad.append(f"{n}: RTL без bdi")
    return len(src), bad[:3], ""

@check("фактуры несут состояния пустоты",
       [("фактуры сняты", lambda s: dict(s, **{"index.html": s["index.html"].replace("tx-none", "x").replace("tx-miss", "x")})),
        # R20-F03: CSS цел, в разметке фактур нет — прежде давало зелёное
        ("фактуры сняты только в разметке", lambda s: dict(s, **{"index.html": styles(s["index.html"]) + s["index.html"][len(styles(s["index.html"])):].replace("tx-none", "x").replace("tx-miss", "x")}))])
def c_texture(src):
    # Считаются ПРИМЕНЕНИЯ в клетках, не объявления в CSS: каждая пустая
    # клетка обязана нести свою фактуру (R20-F03).
    s = src["index.html"]
    body = s[len(styles(s)):]
    need = {"искали, не нашли": "tx-none", "пока не разбирали": "tx-miss",
            "денежных обещаний пока не разбирали": "tx-miss"}
    seen, bad = 0, []
    for m in CELL_RX.finditer(body):
        word = m.group(3).strip()
        if word in need:
            seen += 1
            if need[word] not in m.group(1):
                bad.append(f"«{word}» без {need[word]}")
    if not seen:
        bad.append("в обзоре нет ни одной пустой клетки с фактурой")
    return seen, sorted(set(bad))[:3], f"{seen} пустых клеток"

@check("видимый фокус клавиатуры",
       [("focus-visible убран", lambda s: dict(s, **{k: v.replace(":focus-visible", ":focus-xxxxx") for k, v in s.items()}))])
def c_focus(src):
    bad = [n for n, s in src.items() if ":focus-visible" not in s]
    return len(src), bad, ""

@check("шпаргалка: 14 списков с буквами и четырьмя законами (v51)",
       [("пропала строка шпаргалки", lambda s: dict(s, **{"cheatsheet.html": re.sub(
           r'<tr data-ballot-list=.*?</tr>', '', s['cheatsheet.html'], count=1)})),
        ("пропали буквы шпаргалки", lambda s: dict(s, **{"cheatsheet.html": re.sub(
           r'(<span class="ballot-letters"[^>]*>).*?(</span>)', r'\1\2', s['cheatsheet.html'], count=1)})),
        ("шпаргалка без рамки", lambda s: edit(s, "cheatsheet.html", "data-frame", "data-xxxxx")),
        ("шпаргалка без noindex", lambda s: edit(s, "cheatsheet.html", "noindex", "index")),
        ("JS в шпаргалке", lambda s: edit(s, "cheatsheet.html", "</body>", "<script>1</script></body>"))])
def c_cheatsheet(src):
    import json
    page = src.get("cheatsheet.html", "")
    expected = json.loads((pathlib.Path(__file__).resolve().parent.parent / "criteria/ballot_2026.json").read_text())["lists"]
    rows = re.findall(r'<tr data-ballot-list="([^"]+)">(.*?)</tr>', page, re.S)
    bad = []
    if len(rows) != 14 or [_h.unescape(name) for name, _ in rows] != [row['he'] for row in expected]:
        bad.append("шпаргалка: потеряны или переставлены списки")
    for (_, row), item in zip(rows, expected):
        letters = re.search(r'<span class="ballot-letters"[^>]*>(.*?)</span>', row)
        if not letters or text_of(letters[1]) != item['letters']:
            bad.append(f"шпаргалка: буквы {item['ru']}")
        laws = re.search(r'<span class="ballot-laws">(.*?)</span></td>', row)
        if not laws or len(re.findall(r'<span(?:\s[^>]*)?>', laws[1])) != 4:
            bad.append(f"шпаргалка: не четыре закона {item['ru']}")
        if 'class="crossout"' not in row or item['leaders'] not in _h.unescape(row):
            bad.append(f"шпаргалка: нет квадрата или лидеров {item['ru']}")
    for guard in (c_frame, c_noindex, c_js):
        bad.extend(guard({'cheatsheet.html': page})[1])
    if 'href="cheatsheet.html"' not in src.get('index.html', '').split('data-frame=full')[0]:
        bad.append("шпаргалка: нет ссылки в шапке обзора")
    if '@media print' not in page or 'size:A4 portrait' not in page:
        bad.append("шпаргалка: нет стилей A4")
    return len(rows), bad, f"{len(rows)} строк"


# ───────────────────────────────────────────────────────────────── прогон
@check("период данных на каждой странице из исходных снимков (v54)",
       [("удалена строка голосований", lambda s: dict(s, **{"index.html": re.sub(
           r'<p class="data-period" data-source="votes_25.json">.*?</p>', '', s["index.html"])})),
        ("дата голосований из бюджета", lambda s: dict(s, **{"cheatsheet.html": re.sub(
           r'(data-source="votes_25.json">.*?снимок )[^)]+',
           lambda m: m[1] + date.fromisoformat(json.loads((ROOT / "data/budget_takanot.json").read_text())["fetched_at"][:10]).strftime('%d.%m.%Y'),
           s["cheatsheet.html"])})),
        ("удалена строка бюджета", lambda s: dict(s, **{"l-1.html": re.sub(
           r'<p class="data-period" data-source="budget_takanot">.*?</p>', '', s["l-1.html"])})),
        ("бюджет со снимком голосований", lambda s: dict(s, **{"index.html": re.sub(
           r'(data-source="budget_takanot">.*?снимок )[^)]+',
           lambda m: m[1] + date.fromisoformat(json.loads((ROOT / "data/votes_25.json").read_text())["at"][:10]).strftime('%d.%m.%Y'),
           s["index.html"])}))])
def c_data_periods(src):
    # Независимо от форматтера: сверяем видимый текст с сырыми JSON.
    votes = json.loads((ROOT / "data/votes_25.json").read_text())
    dates = [date.fromisoformat(v[:10]).strftime('%d.%m.%Y')
             for v in [*votes["window"], votes["at"]]]
    expected_votes = (f'Голосования {votes["knesset"]}-го Кнессета с {dates[0]} по {dates[1]} '
                      f'(снимок {dates[2]}); после этого сайт Кнессета закрыт для заходов '
                      'не из Израиля, новых голосований нет')
    budgets = []
    for name in ("budget_takanot_2021_2022.json", "budget_takanot.json"):
        snapshot = json.loads((ROOT / "data" / name).read_text())
        taken = date.fromisoformat(snapshot["fetched_at"][:10]).strftime('%d.%m.%Y')
        budgets.append(', '.join(str(y) for y in sorted(set(snapshot["years"])))
                       + f' (снимок {taken})')
    expected_budget = 'Бюджет: ' + '; '.join(budgets) + '.'
    bad = []
    for name, page in src.items():
        page = strip_comments(page)
        required = [("votes_25.json", expected_votes)]
        if name in ("index.html", "method.html") or name.startswith(("l-", "f-")) or '₪' in page:
            required.append(("budget_takanot", expected_budget))
        for source, expected in required:
            matches = list(re.finditer(r'<p class="data-period" data-source="'
                                       + re.escape(source) + r'">([^<]*)</p>', page))
            if len(matches) != 1 or _h.unescape(matches[0][1]) != expected:
                bad.append(f'{name}: отсутствует или неверен период {source}')
        # Обе строки должны идти непосредственно после заголовка, вне details.
        if not re.search(r'</h1>\s*<p class="data-period" data-source="votes_25.json">', page):
            bad.append(f'{name}: период голосований не под заголовком')
        if len(required) == 2 and not re.search(
                r'data-source="votes_25.json">[^<]*</p>\s*'
                r'<p class="data-period" data-source="budget_takanot">', page):
            bad.append(f'{name}: период бюджета не в шапке')
    return len(src), bad, ''


def run(src):
    rows = []
    for c in CHECKS:
        n, problems, note = c["fn"](src)
        if problems:
            rows.append(("КРАСНЫЙ", c["name"], "; ".join(map(str, problems))))
        elif n == 0 and not c["expect_zero"]:
            rows.append(("КРАСНЫЙ", c["name"],
                         "ОСМОТРЕНО 0 ОБЪЕКТОВ — проверка ничего не проверила"))
        else:
            rows.append(("ЗЕЛЁНЫЙ", c["name"], note or f"осмотрено {n}"))
    return rows

def report(rows, exemptions=True):
    print("┌" + "─" * 78)
    for st, n, m in rows:
        print(f"│ {st:8} {n}")
        if m: print(f"│          {m}")
    if exemptions:
        for x in EXEMPTIONS:
            print(f"│ ОТСТУПЛЕНИЕ {x['id']:10} разрешено {x['by']} {x['date']} — {x['what'][:70]}")
    print("└" + "─" * 78)
    red = sum(1 for x in rows if x[0] == "КРАСНЫЙ")
    print(f"зелёных {len(rows)-red} · красных {red}")
    return red

def selftest(src):
    """Поднести бумажку к каждому датчику. Проверка, не покрасневшая на
    собственном мутанте, мертва — и это единственный способ это узнать."""
    # Каждый адрес проверяется отдельно: потеря строки на f-/l-/служебной
    # странице не должна маскироваться исправной строкой в обзоре.
    period_mutants = 0
    for name, page in src.items():
        for match in re.finditer(r'<p class="data-period"[^>]*>[^<]*</p>', page):
            mutated = dict(src, **{name: page[:match.start()] + page[match.end():]})
            assert c_data_periods(mutated)[1], f"пропущена потеря периода: {name}"
            period_mutants += 1
    print(f"v54: удаление каждой строки периода — {period_mutants} мутантов красные")
    # Смена метаданных входа меняет вывод: даты не зашиты в форматтере.
    from render_overview import data_periods
    with tempfile.TemporaryDirectory() as tmp:
        data = pathlib.Path(tmp)
        for name in ("votes_25.json", "budget_takanot.json", "budget_takanot_2021_2022.json"):
            if name == "votes_25.json":
                snapshot = dict(knesset=25, window=["2020-01-02", "2021-03-04"], at="2022-05-06")
            else:
                snapshot = dict(years=[2018, 2020], fetched_at="2022-07-08")
            (data / name).write_text(json.dumps(snapshot))
        vote_line, budget_line = data_periods(data)
        assert 'с 02.01.2020 по 04.03.2021 (снимок 06.05.2022)' in vote_line
        assert budget_line.count('2018, 2020 (снимок 08.07.2022)') == 2
        changed = re.sub(r'<p class="data-period" data-source="votes_25.json">.*?</p>',
                         lambda m: vote_line, src["index.html"])
        assert c_data_periods(dict(src, **{"index.html": changed}))[1]
    for good in ("11 законов", "12 актов", "13 актов", "14 законов", "111 актов",
                 "из 4 законов", "из 131 закона", "из 5 обещаний", "из 21 обещания"):
        assert not c_plural_ru({"test.html": good})[1], good
    for bad in ("1 законов", "21 актов", "101 голосований", "131 обещаний",
                "4 законов", "22 актов", "из 131 законов", "<b>21</b> актов"):
        assert c_plural_ru({"test.html": bad})[1], bad
    # v47: закрытое раскрытие не должно скрывать клетки от канона.
    overview = src["index.html"]
    folded = overview.split('<details class="faction-details">', 1)[1].split('</details>', 1)[0]
    assert CELL_RX.search(folded) and 'class=c-eq' in folded
    unwrapped = dict(src, **{"index.html": overview.replace('<details class="faction-details">' + folded + '</details>', folded)})
    for guard in (c_closed, c_digits, c_texture):
        assert guard(src) == guard(unwrapped), guard.__name__
    print("── чистый вход: обязан быть зелёным")
    rows = run(src)
    if any(x[0] == "КРАСНЫЙ" for x in rows):
        report(rows, exemptions=False)
        print("САМОПРОВЕРКА ПРОВАЛЕНА: чистый вход красный")
        return 1
    print(f"   {len(rows)} проверок зелёные\n")
    print("── подложенные нарушения: каждое обязано покраснеть")
    dead, total = [], 0
    for c in CHECKS:
        if not c["mutants"]:
            dead.append(f"{c['name']}: НЕТ НИ ОДНОГО МУТАНТА")
            continue
        for label, mut in c["mutants"]:
            total += 1
            try:
                spoiled = mut(src)
            except LookupError as e:
                dead.append(f"{c['name']} ← {label}: МУТАНТ НЕВОЗМОЖЕН ({e})")
                print(f"   ПУСТЫШКА {c['name']} ← {label}")
                continue
            # Мутант, ничего не изменивший, делает проверку «испытанной» даром:
            # зелёный получится не потому, что она жива, а потому, что её не трогали.
            if spoiled == src:
                dead.append(f"{c['name']} ← {label}: МУТАНТ НИЧЕГО НЕ ИЗМЕНИЛ")
                print(f"   ПУСТЫШКА {c['name']} ← {label}")
                continue
            n, problems, _ = c["fn"](spoiled)
            red = bool(problems) or (n == 0 and not c["expect_zero"])
            print(f"   {'КРАСНЫЙ' if red else 'ЗЕЛЁНЫЙ'}  {c['name']} ← {label}")
            if not red:
                dead.append(f"{c['name']} ← {label}: НЕ ПОКРАСНЕЛА")
    print()
    if dead:
        for d in dead: print("ПРОВАЛ:", d)
        print(f"САМОПРОВЕРКА ПРОВАЛЕНА: не пойманы {len(dead)} из {total}")
        return 1
    print(f"САМОПРОВЕРКА ПРОЙДЕНА: {len(CHECKS)} проверок, {total} подложенных нарушений, все пойманы")
    return 0


# §14, §24: состав принятого макета проверяется независимо от генератора.
ROOT = pathlib.Path(__file__).resolve().parent.parent


# В макете восемь страниц, но четыре из них — ПРИМЕРЫ на живых именах:
# `f-likud.html`, `f-yahadut.html`, `f-hayamin.html`, `f-generic.html` и
# `c-likud-inst-in.html`. Сборка выпускает `f-<id фракции>.html` и
# `c-<...>.html` по данным, и файла с именем `f-likud.html` не будет никогда.
# Первая редакция этой проверки требовала СОВПАДЕНИЯ ИМЁН и потому была
# красной вечно — то есть хуже отсутствующей: вечно красную проверку
# перестают читать, и это ровно тот механизм, из-за которого 01.08
# предупреждение о неработающей сверке бюджетных чисел проскроллили
# тринадцать раз. Поэтому одиночные страницы сверяются по имени, а
# страницы-по-сущности — по виду, с требованием хотя бы одной.
KINDS = {"l-": "страница списка", "f-": "страница фракции", "c-": "страница карточки"}


def check_outputs(site, mock):
    expected = {p.relative_to(mock).as_posix() for p in mock.rglob("*.html")}
    actual = {p.relative_to(site).as_posix() for p in site.rglob("*.html")}
    if not expected:
        raise ValueError("ОТКАЗ §14: макет пуст — сверять состав не с чем")
    singles = {n for n in expected if not any(n.startswith(k) for k in KINDS)}
    missing = sorted(singles - actual)
    for pref, label in KINDS.items():
        if any(n.startswith(pref) for n in expected) \
                and not any(n.startswith(pref) for n in actual):
            missing.append(f"{label} (ни одной {pref}*.html)")
    if missing:
        raise ValueError("ОТКАЗ §14: страницы принятого макета отсутствуют "
                         "в сборке: " + ", ".join(missing))
    # Дополнительные страницы фракций разрешены: набор зависит от данных.
    unexpected = {name for name in actual - expected
                  if not any(name.startswith(k) for k in KINDS)}
    if unexpected:
        raise ValueError("ОТКАЗ §14: посторонние HTML в сборке: "
                         + ", ".join(sorted(unexpected)))
    for p in site.rglob("*"):
        if p.is_symlink() or (p.is_file() and p.suffix != ".html"
                              and p.relative_to(site).as_posix() != "robots.txt"):
            raise ValueError(f"ОТКАЗ §14: посторонний файл в сборке: {p.name}")
    robots = site / "robots.txt"
    if not robots.is_file() or re.search(r"^\s*Disallow\s*:", robots.read_text(), re.M | re.I):
        raise ValueError("ОТКАЗ §16: robots.txt отсутствует или запрещает обход")


def build_site(root, destination):
    # Пустой каталог исключает маскировку недобора остатками прежней сборки.
    destination.mkdir()
    command = ("import sys; import render_overview as r; "
               "from pathlib import Path; r.OUT=Path(sys.argv[1])/'index.html'; "
               "sys.exit(r.main())")
    subprocess.run([sys.executable, "-c", command, str(destination)],
                   cwd=root / "scripts", check=True)
    # Страница тем собирается ЗДЕСЬ же, а не руками: собранная руками, она
    # пережила бы любое изменение criteria/themes.yaml и тихо устарела — а
    # проверка состава всё равно считала бы её на месте.
    axes = ("import sys; import render_axes as a; "
            "from pathlib import Path; a.OUT=Path(sys.argv[1])/'axes.html'; "
            "sys.exit(a.main())")
    subprocess.run([sys.executable, "-c", axes, str(destination)],
                   cwd=root / "scripts", check=True)
    # Методология — из объявлений и того же кода, что делал замеры;
    # руками собранная устарела бы тихо (см. render_method).
    method = ("import sys; import render_method as m; "
              "from pathlib import Path; m.OUT=Path(sys.argv[1])/'method.html'; "
              "sys.exit(m.main())")
    subprocess.run([sys.executable, "-c", method, str(destination)],
                   cwd=root / "scripts", check=True)
    # Основания — страница принятой формы с 2026-10-10 (design/mockup_v5/
    # grounds.html). Без пометок владельца рендер отказывает, и сборки нет:
    # сайт без оснований не публикуется, а не публикуется с пустой страницей.
    grounds = ("import sys; import render_grounds as g; "
               "from pathlib import Path; g.OUT=Path(sys.argv[1])/'grounds.html'; "
               "sys.exit(g.main())")
    subprocess.run([sys.executable, "-c", grounds, str(destination)],
                   cwd=root / "scripts", check=True)
    cards = ("import sys; import render_card_page as c; "
             "from pathlib import Path; c.OUT_DIR=Path(sys.argv[1]); "
             "sys.exit(c.main())")
    subprocess.run([sys.executable, "-c", cards, str(destination)],
                   cwd=root / "scripts", check=True)
    time_page = ("import sys; import render_time_page as t; "
                 "from pathlib import Path; t.OUT=Path(sys.argv[1])/'time.html'; "
                 "sys.argv=sys.argv[:1]; sys.exit(t.main())")
    subprocess.run([sys.executable, "-c", time_page, str(destination)],
                   cwd=root / "scripts", check=True)
    # Общая шапка всех публикуемых страниц, включая новые страницы сборки.
    from render_overview import data_periods
    votes_period, budget_period = data_periods(root / "data")
    for path in destination.rglob("*.html"):
        page = path.read_text(encoding="utf-8")
        periods = votes_period
        if path.name in ("index.html", "method.html") or path.name.startswith(("l-", "f-")) or '₪' in page:
            periods += '\n' + budget_period
        if '</h1>' not in page:
            raise ValueError(f"ОТКАЗ: нет заголовка для периода данных: {path.name}")
        path.write_text(page.replace('</h1>', '</h1>\n' + periods, 1), encoding="utf-8")
    (destination / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    from render_overview import check_index_links, Refuse
    try:
        check_index_links(destination)
    except Refuse as exc:
        raise ValueError(str(exc)) from exc
    check_outputs(destination, root / "design/mockup_v5")
    src = {p.relative_to(destination).as_posix(): p.read_text(encoding="utf-8")
           for p in destination.rglob("*.html")}
    if report(run(src)):
        raise ValueError("ОТКАЗ: сборка нарушает канон")


def hashes(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def compare_builds(first, second):
    if hashes(first) != hashes(second):
        raise ValueError("ОТКАЗ §14: состав или sha256 файлов двух сборок различается")


def reproduce(root):
    with tempfile.TemporaryDirectory(prefix="knesset-reproduce-") as tmp:
        snapshot = pathlib.Path(tmp) / "snapshot"
        # Только входы текущего render_overview; копия не является согласованным
        # срезом источников (§11) или архивом прежней публикации.
        for name in ("scripts", "cards", "criteria", "design/mockup_v5", "docs/reference"):
            shutil.copytree(root / name, snapshot / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        (snapshot / "data").mkdir()
        for name in ("coverage_matrix.json", "votes_25.json", "KNS_PersonToPosition_54.json", "budget_takanot.json", "budget_takanot_2021_2022.json", "direction_arrow_2026-10-07.json", "arrow_robustness.json"):
            shutil.copyfile(root / "data" / name, snapshot / "data" / name)
        shutil.copytree(root / "data/named_votes_cache", snapshot / "data/named_votes_cache")
        shutil.copytree(root / "data/agreements_ocr", snapshot / "data/agreements_ocr")
        shutil.copyfile(root / "data/agreements_ocr_report_ca36.json",
                        snapshot / "data/agreements_ocr_report_ca36.json")
        for path in (root / "data").glob("commitment_map_*.json"):
            shutil.copyfile(path, snapshot / "data" / path.name)
        first, second = pathlib.Path(tmp) / "first", pathlib.Path(tmp) / "second"
        build_site(snapshot, first)
        build_site(snapshot, second)
        compare_builds(first, second)
        print(f"§14: две сборки render_overview совпали: {len(hashes(first))} файлов; "
              "проверена детерминированность на локальной копии входов")


def selftest_reproduce():
    with tempfile.TemporaryDirectory(prefix="knesset-repro-test-") as tmp:
        root = pathlib.Path(tmp)
        mock, site = root / "mock", root / "site"
        mock.mkdir(); site.mkdir()
        for name in ("index.html", "f-example.html", "time.html"):
            (mock / name).write_text("example")
            (site / name).write_text("example")
        (site / "robots.txt").write_text("User-agent: *\nAllow: /\n")
        check_outputs(site, mock)
        other = root / "other"
        shutil.copytree(site, other)
        compare_builds(site, other)
        (site / "time.html").unlink()
        try:
            check_outputs(site, mock)
        except ValueError as e:
            assert "time.html" in str(e)
            print(f"КРАСНЫЙ (страница времени потеряна): {e}")
        else:
            raise AssertionError("пропущена потеря time.html")
        (site / "time.html").write_text("example")
        # Каждый подлог меняет настоящий файл и вызывает рабочий оракул.
        for label, path, content, oracle in (
            ("добавленная страница макета", mock / "new.html", "new",
             lambda: check_outputs(site, mock)),
            ("изменённая страница фракции", other / "f-example.html", "changed",
             lambda: compare_builds(site, other)),
            ("лишний файл во второй сборке", other / "extra.txt", "extra",
             lambda: compare_builds(site, other)),
            ("посторонний файл для публикации", site / "private.json", "{}",
             lambda: check_outputs(site, mock)),
            ("посторонняя HTML-страница", site / "private.html", "private",
             lambda: check_outputs(site, mock)),
        ):
            before = path.read_bytes() if path.exists() else None
            path.write_text(content)
            try:
                try:
                    oracle()
                except ValueError as e:
                    print(f"КРАСНЫЙ ({label}): {e}")
                else:
                    raise AssertionError(f"мёртвый оракул: {label}")
            finally:
                if before is None: path.unlink()
                else: path.write_bytes(before)
        # Интеграция того же пути сборки: управляемый renderer выдаёт макет.
        # Это контроль обёртки, не доказательство работы реального renderer.
        fixture = root / "fixture"
        for name in ("scripts", "cards", "criteria", "docs/reference", "data"):
            (fixture / name).mkdir(parents=True)
        shutil.copytree(ROOT / "design/mockup_v5", fixture / "design/mockup_v5")
        for name in ("coverage_matrix.json", "votes_25.json", "KNS_PersonToPosition_54.json", "budget_takanot.json", "budget_takanot_2021_2022.json", "direction_arrow_2026-10-07.json", "arrow_robustness.json"):
            (fixture / "data" / name).write_text("{}")
        # Общий build_site вызывает все генераторы; здесь проверяется обёртка.
        for module in ("render_axes", "render_card_page"):
            (fixture / f"scripts/{module}.py").write_text("def main(): return 0\n")
        (fixture / "scripts/render_time_page.py").write_text(
            "from pathlib import Path\nimport shutil\n"
            "def main():\n"
            "    shutil.copyfile(Path(__file__).resolve().parents[1]/"
            "'design/mockup_v5/f-generic.html', OUT)\n"
            "    return 0\n")
        renderer = fixture / "scripts/render_overview.py"
        renderer.write_text(
            "from pathlib import Path\nimport shutil\n"
            "def main():\n"
            "    mock = Path(__file__).resolve().parents[1]/'design/mockup_v5'\n"
            "    for p in mock.glob('*.html'): shutil.copyfile(p, OUT.parent/p.name)\n"
            "    return 0\n")
        reproduce(fixture)
        # Теперь источник формы расширился, а генератор новую страницу теряет.
        renderer.write_text(renderer.read_text().replace(
            "mock.glob('*.html')", "[p for p in mock.glob('*.html') if p.name != 'new.html']"))
        (fixture / "design/mockup_v5/new.html").write_text("new")
        try:
            reproduce(fixture)
        except ValueError as e:
            assert "new.html" in str(e), str(e)
            print(f"КРАСНЫЙ (две сборки, страница потеряна генератором): {e}")
        else:
            raise AssertionError("reproduce пропустил потерянную страницу")
        (fixture / "design/mockup_v5/new.html").unlink()
        renderer.write_text(renderer.read_text().replace(
            "    return 0", "    import time\n"
            "    p = OUT.parent/'f-likud.html'\n"
            "    p.write_text(p.read_text() + '<!--' + str(time.time_ns()) + '-->')\n"
            "    return 0"))
        try:
            reproduce(fixture)
        except ValueError as e:
            assert "sha256" in str(e), str(e)
            print(f"КРАСНЫЙ (недетерминированный renderer): {e}")
        else:
            raise AssertionError("reproduce пропустил недетерминированную страницу фракции")
    print("САМОПРОВЕРКА §14 ПРОЙДЕНА")
    return 0

if __name__ == "__main__":
    try:
        if "--selftest-reproduce" in sys.argv:
            sys.exit(selftest_reproduce())
        if "--reproduce" in sys.argv:
            reproduce(ROOT)
            sys.exit(0)
        if "--build" in sys.argv:
            with tempfile.TemporaryDirectory(prefix=".site-build-", dir=ROOT) as tmp:
                output = pathlib.Path(tmp) / "site"
                build_site(ROOT, output)
                # Решение владельца 19.10 (вопрос 2, А): подложенные нарушения на
                # СВЕЖЕЙ сборке, до замены site/ — красное оставляет прежний сайт.
                fresh = {f.name: f.read_text(encoding="utf-8") for f in sorted(output.glob("*.html"))}
                if selftest(fresh):
                    raise ValueError("самопроверка канона на свежей сборке красная — site/ НЕ заменён")
                target = ROOT / "site"
                if target.is_symlink():
                    raise ValueError("ОТКАЗ: site/ — символическая ссылка")
                previous = pathlib.Path(tmp) / "previous"
                if target.exists(): target.rename(previous)
                try:
                    output.rename(target)
                except OSError:
                    if previous.exists(): previous.rename(target)
                    raise
            sys.exit(0)
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        print(f"ОТКАЗ сборки: {e}", file=sys.stderr)
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = pathlib.Path(args[0] if args else "site")
    files = sorted(d.glob("*.html"))
    if not files:
        print(f"ОТКАЗ: в {d} нет ни одного HTML — проверять нечего")
        sys.exit(2)
    try:
        if d.resolve() != (ROOT / "design/mockup_v5").resolve():
            check_outputs(d, ROOT / "design/mockup_v5")
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    src = {f.name: f.read_text(encoding="utf-8") for f in files}
    sys.exit(selftest(src) if "--selftest" in sys.argv else (1 if report(run(src)) else 0))
