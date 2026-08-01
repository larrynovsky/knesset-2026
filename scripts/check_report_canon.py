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

# ─────────────────────────────────────────────────────────────── канон отчёта
CLOSED = ["укрепляла", "ослабляла", "и туда и обратно",
          "искали, не нашли", "мы сюда не дошли"]
ARROW = {"укрепляла": "↑", "ослабляла": "↓", "и туда и обратно": "↕"}
FORBIDDEN = [r"прогон", r"чек-?лист", r"кворум", r"размеч|размет", r"перепис",
             r"классификатор", r"валидатор", r"единиц[аеы]\s+наблюдения",
             r"отложенн\w*\s+период", r"норм\w*\s+со\s+знаком", r"карточк"]
BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
DOCS_FREE = ("method.html", "axes.html")   # страницы методики: лексика разрешена

# Обход легален, но обязан быть громким, произнесённым и СЧИТАЕМЫМ (§24).
EXEMPTIONS = [
    dict(id="E1-проза", date="2026-08-01", by="владелец",
         what="канон пяти значений обязателен в клетках; в прозе формулировка свободна"),
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
    d = dict(src); d[fname] = d[fname].replace(old, new, n); return d

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

@check("значение клетки из закрытого списка, стрелка ↔ значение",
       [("значение вне списка", lambda s: edit(s, "index.html", "&#8201;ослабляла", "&#8201;скорее ослабляла")),
        ("стрелка не та", lambda s: edit(s, "index.html", "<span class=a>↓</span>&#8201;ослабляла", "<span class=a>↑</span>&#8201;ослабляла")),
        ("неканоническая формулировка", lambda s: edit(s, "index.html", "&#8201;и туда и обратно", "&#8201;в обе стороны"))])
def c_closed(src):
    # Считаем клетки, ДАВШИЕ значение. Пустой разбор объектом не является:
    # иначе счётчик прикрывает вакуумность вместо того, чтобы её выдавать.
    cells = [(a, t) for a, t in cells_of(src["index.html"]) if t]
    bad = []
    for a, t in cells:
        if t not in CLOSED: bad.append(f"вне списка: {t[:40]!r}")
        elif a != ARROW.get(t, ""): bad.append(f"{t!r} со стрелкой {a!r}")
    return len(cells), sorted(set(bad))[:4], f"{len(cells)} клеток со значением"

@check("ни одной цифры в клетке обзора",
       [("число в клетке", lambda s: edit(s, "index.html", "&#8201;ослабляла", "&#8201;ослабляла 7 из 10"))])
def c_digits(src):
    tds = re.findall(r"<td class=c-(?:inst|eq)[^>]*>(.*?)</td>", src["index.html"], flags=re.S)
    bad = [t[:30] for t in tds if re.search(r"\d", _h.unescape(re.sub(r"<[^>]+>", "", t)))]
    return len(tds), bad[:3], f"{len(tds)} клеток"

@check("лексика страниц партий",
       [("слово «валидатор» в прозе", lambda s: edit(s, "f-likud.html", "<h1>", "<p>Так решил валидатор.</p><h1>"))])
def c_lex(src):
    pp, bad = party(src), []
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
       [("таблица без thead", lambda s: edit(s, "index.html", "<thead>", "<tbody-x>")),
        ("th без scope", lambda s: dict(s, **{"index.html": s["index.html"].replace("scope=col", "")})),
        ("RTL без bdi", lambda s: dict(s, **{k: v.replace("<bdi>", "").replace("</bdi>", "") for k, v in s.items()}))])
def c_sem(src):
    bad = []
    for n, s in src.items():
        if "<table" in s:
            if "<thead" not in s: bad.append(f"{n}: таблица без thead")
            if "scope=" not in s: bad.append(f"{n}: th без scope")
        if "<details" in s and "<summary" not in s: bad.append(f"{n}: details без summary")
        if "dir=rtl" in s and "<bdi>" not in s: bad.append(f"{n}: RTL без bdi")
    return len(src), bad[:3], ""

@check("фактуры несут состояния пустоты",
       [("фактуры сняты", lambda s: dict(s, **{"index.html": s["index.html"].replace("tx-none", "x").replace("tx-miss", "x")}))])
def c_texture(src):
    hits = len(re.findall(r"tx-none|tx-miss", src["index.html"]))
    return hits, [] if hits else ["в обзоре только слова"], f"{hits} мест"

@check("видимый фокус клавиатуры",
       [("focus-visible убран", lambda s: dict(s, **{k: v.replace(":focus-visible", ":focus-xxxxx") for k, v in s.items()}))])
def c_focus(src):
    bad = [n for n, s in src.items() if ":focus-visible" not in s]
    return len(src), bad, ""

# ───────────────────────────────────────────────────────────────── прогон
def run(src):
    rows = []
    for c in CHECKS:
        n, problems, note = c["fn"](src)
        if problems:
            rows.append(("КРАСНЫЙ", c["name"], "; ".join(map(str, problems))[:170]))
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

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = pathlib.Path(args[0] if args else "site")
    files = sorted(d.glob("*.html"))
    if not files:
        print(f"ОТКАЗ: в {d} нет ни одного HTML — проверять нечего")
        sys.exit(2)
    src = {f.name: f.read_text(encoding="utf-8") for f in files}
    sys.exit(selftest(src) if "--selftest" in sys.argv else (1 if report(run(src)) else 0))
