# -*- coding: utf-8 -*-
# Приёмка вёрстки отчёта по брифу C и разделу D пакета handoff.
#
# СУДЬБА ЭТОГО ФАЙЛА ОБЪЯВЛЕНА ЗАРАНЕЕ: тринадцать из пятнадцати проверок —
# это будущий `build_report.py --selftest` (бриф C, этап 2). При исполнении
# этапа 2 они переезжают в генератор, а этот файл удаляется. Снаружи остаются
# только две: прокрутка (нужен браузер) и лексика (нужен словарь — это
# check_lexicon.py брифа). Модуль одноразовый по замыслу, и это сказано здесь,
# а не выяснится через месяц.
# Каждая проверка — отдельная, с именем файла. Ни одна не «на глаз».
import re, sys, pathlib, html as _h

# По умолчанию — канонический макет в репозитории, а не каталог распаковки в
# /tmp: путь во временный каталог делал проверку невоспроизводимой из чистого
# клона (§14). Макет живёт в design/, а НЕ в report/: report/ — рабочий стол
# трёх разведочных рендереров и целиком в .gitignore, design/ — рукописный
# источник, который обязан быть в версиях.
D = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                 else pathlib.Path(__file__).resolve().parent.parent / "design/mockup_v5")
FILES = sorted(D.glob("*.html"))
PARTY_PAGES = [f for f in FILES if f.name not in ("method.html", "axes.html")]

# D2 — закрытый список пяти значений
CLOSED = ["укрепляла", "ослабляла", "и туда и обратно", "искали, не нашли", "мы сюда не дошли"]
ARROW = {"укрепляла": "↑", "ослабляла": "↓", "и туда и обратно": "↕"}
# D6 — запрещённая лексика на страницах партий
FORBIDDEN = [r"прогон", r"чек-?лист", r"кворум", r"размеч|размет", r"перепис",
             r"классификатор", r"валидатор", r"единиц[аеы]\s+наблюдения",
             r"отложенн\w*\s+период", r"норм\w*\s+со\s+знаком", r"карточк"]
BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")

# ─────────────────────────────────────────────────────────────────────────
# РАЗРЕШЁННЫЕ ОТСТУПЛЕНИЯ. Обход легален, но обязан быть громким,
# произнесённым и СЧИТАЕМЫМ (§24). Поэтому они живут здесь, в коде проверки,
# а не в голове у того, кто её запускал. Каждое несёт причину и дату.
# Ненайденное отступление при найденном обходе = отказ.
EXEMPTIONS = [
    dict(id="E1-проза", date="2026-08-01", by="владелец",
         what="Закрытый список пяти значений обязателен в КЛЕТКАХ (обзор и "
              "заголовок раскрытия) — там он и есть механизм §13. В связной "
              "прозе допускается свободная формулировка: «в обе стороны — 3» "
              "в сводке по экономике.",
         why="Сводка описательной оси — предложение, а не значение клетки. "
             "Требовать канонической строки в прозе значит требовать "
             "канцелярита ровно там, откуда его убирали."),
    dict(id="кегль-7", date="2026-08-01", by="владелец",
         what="Семь ступеней шкалы кеглей вместо шести: добавлена 1.08rem "
              "для .lead.",
         why="Лид-абзац первого экрана. Цель «шесть» назначена как дисциплина "
             "против разнобоя, а не как физический предел."),
]

def strip_comments(s):
    """CSS-комментарий — тоже комментарий. Прошлая редакция этой проверки
    ловила слово overflow-x:hidden ВНУТРИ комментария, который объясняет,
    почему его здесь нет, и краснела на восьми файлах подряд."""
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    return re.sub(r"/\*.*?\*/", " ", s, flags=re.S)

def text_of(s):
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    s = strip_comments(s)
    return _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)))

res = []
def ok(n, m=""):  res.append(("ЗЕЛЁНЫЙ", n, m))
def bad(n, m=""): res.append(("КРАСНЫЙ", n, m))
def warn(n, m=""): res.append(("ВОПРОС", n, m))

src = {f.name: f.read_text(encoding="utf-8") for f in FILES}

# 1 — ноль JS
j = [n for n, s in src.items() if "<script" in s or re.search(r"\son\w+\s*=", s)]
ok("1 · ноль JavaScript", f"{len(FILES)} страниц") if not j else bad("1 · ноль JavaScript", str(j))

# 2 — ноль внешних запросов
ext = [n for n, s in src.items() if re.search(r'(src|href)="https?://', s)
       or re.search(r'url\(\s*["\']?https?://', s)]
ok("2 · ноль внешних запросов") if not ext else bad("2 · ноль внешних запросов", str(ext))

# 3 — noindex в КАЖДОМ документе (§16, D3)
miss = [n for n, s in src.items() if "noindex, nofollow" not in s]
ok("3 · §16 noindex в каждом документе", f"{len(FILES)}/{len(FILES)}") if not miss else bad("3 · §16 noindex", str(miss))

# 4 — §17 рамка в каждом документе, до первого содержательного блока (D5)
fr = []
for n, s in src.items():
    m = re.search(r'data-frame=["\']?(full|short)', s)
    if not m: fr.append(f"{n}: маркера data-frame нет"); continue
    body = s.find("<body")
    # §17 дословно: «раньше первой КАРТОЧКИ». Заголовок документа карточкой не является.
    first = min([p for p in [s.find("<table", body), s.find("<details", body)] if p > 0] or [10**9])
    if m.start() > first: fr.append(f"{n}: рамка ПОСЛЕ первой карточки")
    if n == "index.html" and m.group(1) != "full": fr.append("index.html: рамка не full")
ok("4 · §17 рамка в каждом документе", f"{len(FILES)}/{len(FILES)}, позиция верна") if not fr else bad("4 · §17 рамка", "; ".join(fr))

# 5 — D1/D2: клетки обзора только из закрытого списка, стрелка ↔ значение.
# Разбор НЕ регуляркой по одной паре тегов: клетка вложенная
# (<span class=v><span class=a>↓</span> ослабляла <span class=lb>…),
# и наивная нежадная регулярка обрывалась на первом же </span>, ловя одну
# стрелку. Проверка, которая смотрит мимо предмета, — хуже отсутствующей.
def cells_of(doc):
    """Вернуть [(стрелка, значение)] для каждой клетки обзора и каждого
    заголовка раскрытия."""
    out = []
    for m in re.finditer(r'<span class="?v[^">]*"?[^>]*>', doc):
        rest = doc[m.end():]
        cut = rest.find('<span class=lb')
        if cut < 0: cut = rest.find('<span class="lb')
        if cut < 0: cut = rest.find('</span>')
        frag = rest[:cut]
        t = _h.unescape(re.sub(r"<[^>]+>", "", frag)).replace("\u2009", " ").strip()
        a = ""
        if t and t[0] in "\u2191\u2193\u2195": a, t = t[0], t[1:].strip()
        out.append((a, t))
    for m in re.finditer(r'<summary[^>]*>(.*?)</summary>', doc, flags=re.S):
        t = _h.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
        t = re.sub(r"\s+", " ", t)
        for v in CLOSED:
            if v in t: out.append(("", v))
        if "в обе стороны" in t: out.append(("", "в обе стороны"))
    return out

bad_cells, arrow_bad = [], []
for a, t in cells_of(src["index.html"]):
    if not t: continue
    if t not in CLOSED: bad_cells.append(repr(t)[:40]); continue
    exp = ARROW.get(t, "")
    if a != exp: arrow_bad.append(f"{t!r} со стрелкой {a!r}, ожидалась {exp!r}")
if bad_cells: bad("5 \u00b7 D2 закрытый список из пяти значений", "вне списка: " + ", ".join(sorted(set(bad_cells))))
elif arrow_bad: bad("5 \u00b7 D2 стрелка \u2194 значение", "; ".join(sorted(set(arrow_bad))))
else: ok("5 \u00b7 D2 закрытый список + стрелка", f"{len(cells_of(src['index.html']))} клеток обзора канонические")

# 6 — цифры в клетках обзора (§13: колонка с числом запрещена)
digits = [c for c in re.findall(r'<td class=c-(?:inst|eq)[^>]*>(.*?)</td>', src["index.html"], flags=re.S)
          if re.search(r"\d", _h.unescape(re.sub(r"<[^>]+>", "", c)))]
ok("6 · §13 ни одной цифры в клетках обзора") if not digits else bad("6 · §13 цифра в клетке обзора", str(len(digits)))

# 7 — D6 лексика на страницах партий
lex = []
for f in PARTY_PAGES:
    t = text_of(src[f.name]).lower()
    for rule in FORBIDDEN:
        for m in re.finditer(rule, t):
            lex.append(f"{f.name}: «{t[max(0,m.start()-30):m.end()+30].strip()}»")
ok("7 · D6 лексика страниц партий", f"{len(PARTY_PAGES)} страниц чисты") if not lex else bad("7 · D6 лексика", f"{len(lex)} срабатываний")

# 8 — BIDI
b = [n for n, s in src.items() if any(ch in BIDI for ch in s)]
ok("8 · §12 управляющие символы направления") if not b else bad("8 · §12 BIDI", str(b))

# 9 — overflow-x:hidden запрещён (D7)
ov = [n for n, s in src.items() if re.search(r"overflow(-x)?\s*:\s*(hidden|clip)", strip_comments(s))]
ok("9 · D7 overflow-x:hidden отсутствует") if not ov else bad("9 · D7 overflow-x:hidden", str(ov))

# 10 — шкала кеглей: шесть ступеней
sizes = set()
for s in src.values():
    for m in re.finditer(r"font(?:-size)?\s*:[^;}]*?([0-9.]+)rem", s): sizes.add(m.group(1) + "rem")
    for m in re.finditer(r"--f\d:\s*([0-9.]+rem)", s): sizes.add(m.group(1))
(ok if len(sizes) <= 7 else bad)("10 · шкала кеглей", f"{len(sizes)} ступеней (разрешено 7, см. {EXEMPTIONS[1]['id']}): {' '.join(sorted(sizes))}")

# 11 — палитра: только объявленные краски
decl = set(re.findall(r"#[0-9A-Fa-f]{6}", src["index.html"][:src["index.html"].find("</style>")]))
used = set()
for s in src.values(): used |= set(re.findall(r"#[0-9A-Fa-f]{6}", s[:s.find("</style>")]))
extra = {c for c in used if c.upper() not in {d.upper() for d in decl}}
ok("11 · палитра", f"{len(used)} красок, все из объявленных") if not extra else bad("11 · палитра", f"вне палитры: {sorted(extra)}")

# 12 — E1: канон обязателен в КЛЕТКАХ (см. EXEMPTIONS: E1-проза), проза свободна.
old = []
for n, doc in src.items():
    for a, t in cells_of(doc):
        if t and t not in CLOSED: old.append(f"{n}: {t[:40]!r}")
ok("12 \u00b7 E1 канон в клетках", f"проза освобождена ({EXEMPTIONS[0]['id']})") if not old else bad("12 \u00b7 E1 неканоническое значение в клетке", "; ".join(sorted(set(old))))

# 13 — семантика таблиц и раскрытий
sem = []
for n, s in src.items():
    if "<table" in s:
        if "<thead" not in s: sem.append(f"{n}: таблица без thead")
        if 'scope=' not in s and 'scope="' not in s: sem.append(f"{n}: th без scope")
    if "<details" in s and "<summary" not in s: sem.append(f"{n}: details без summary")
    for m in re.finditer(r'lang=he|dir=rtl', s):
        pass
    if "dir=rtl" in s and "<bdi>" not in s: sem.append(f"{n}: RTL без bdi")
ok("13 · семантика: thead/scope, details/summary, bdi") if not sem else bad("13 · семантика", "; ".join(sem))

# 14 — фактуры зарезервированы под смысл (бриф §2, F2)
tex = {n: bool(re.search(r"tx-none|tx-miss", s)) for n, s in src.items()}
if tex.get("index.html"): ok("14 · F2 фактуры вернулись в обзор", "растр = «искали, не нашли», штриховка = «мы сюда не дошли»")
else: bad("14 · F2 фактуры", "в обзоре только слова")

# 15 — фокус клавиатуры
foc = [n for n, s in src.items() if ":focus-visible" not in s]
ok("15 · видимый фокус клавиатуры") if not foc else bad("15 · фокус", str(foc))

print("┌" + "─"*78)
for st, n, m in res:
    print(f"│ {st:8} {n}")
    if m: print(f"│          {m[:200]}")
for x in EXEMPTIONS:
    print(f"│ ОТСТУПЛЕНИЕ {x['id']:12} разрешено {x['by']} {x['date']}")
    print(f"│              {x['what'][:150]}")
print("└" + "─"*78)
print(f"зелёных {sum(1 for r in res if r[0]=='ЗЕЛЁНЫЙ')} · красных {sum(1 for r in res if r[0]=='КРАСНЫЙ')} · вопросов {sum(1 for r in res if r[0]=='ВОПРОС')}")
sys.exit(1 if any(r[0]=="КРАСНЫЙ" for r in res) else 0)
