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
import hashlib, shutil, subprocess, tempfile

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
LEADING_MONEY_PATTERN = (r"подписала как вторая сторона [0-9]+ денежных обещаний партнёрам в соглашениях правительства "
                         r"(?:37; самостоятельных обещаний после разбора: [0-9]+; в бюджете нашлась строка под [0-9]+"
                         r"|36 \(2021 год\)(?:; подтверждённых сопоставлений с бюджетом 2021 года: 0; сопоставление требует проверки"
                         r"|; разобрано вручную: [^<—]+ — строка бюджета нашлась под [0-9]+ из [0-9]+; у остальных сопоставление требует проверки))")
MONEY_PATTERN = (LEADING_MONEY_PATTERN + r"|в бюджете нашлась строка под [0-9]+ из [0-9]+ обещаний"
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

@check("лексика страниц партий",
       [("старое состояние в методике", lambda s: edit(s, "method.html", "<h1>", "<p>мы сюда не дошли</p><h1>")),
        ("фракции названы строками", lambda s: edit(s, "index.html", "<h1>", "<p>пять-шесть строк бюллетеня из шестнадцати</p><h1>")),
        ("старые подписи примеров", lambda s: edit(s, "index.html", "<h1>", "<p>Примеры в плюс:</p><h1>")),
        ("старое денежное состояние", lambda s: edit(s, "index.html", "<h1>", "<p>сопоставление денежных обещаний с бюджетом не построено</p><h1>")),
        ("слово «валидатор» в прозе", lambda s: edit(s, party_page(s), "<h1>", "<p>Так решил валидатор.</p><h1>"))])
def c_lex(src):
    pp, bad = party(src), []
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
       [("пример без списка", lambda s: edit(s, "index.html", "<h1>", "<p>в сторону ↑:</p><p>пример</p><h1>")),
        ("два примера в одном пункте", lambda s: edit(s, "index.html", "<h1>", "<p>в сторону укрепления:</p><ul><li><bdi>один</bdi>; <bdi>два</bdi></li></ul><h1>")),
        ("таблица без thead", lambda s: edit(s, "index.html", "<thead>", "<tbody-x>")),
        ("th без scope", lambda s: dict(s, **{"index.html": s["index.html"].replace("scope=col", "")})),
        ("RTL без bdi", lambda s: dict(s, **{k: v.replace("<bdi>", "").replace("</bdi>", "") for k, v in s.items()}))])
def c_sem(src):
    bad = []
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
        for name in ("coverage_matrix.json", "votes_25.json", "budget_takanot.json", "budget_takanot_2021_2022.json"):
            shutil.copyfile(root / "data" / name, snapshot / "data" / name)
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
        for name in ("coverage_matrix.json", "votes_25.json", "budget_takanot.json", "budget_takanot_2021_2022.json"):
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
