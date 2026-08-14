#!/usr/bin/env python3
"""Обзор бюллетеня в ПРИНЯТОЙ форме (design/mockup_v5), заполненный тем, что есть.

Урок 13.08 (docs/explanation/why_design_was_invisible_2026-08-13.md): целевая
форма была принята 01.08 и две недели оставалась невидимой. Здесь она впервые
становится источником: CSS и разметка НЕ копируются в код, а читаются из
макета при сборке. Разошёлся макет — разошёлся вывод, и это видно.

ЧЕСТНЫЙ ПЕРВЫЙ ВЫПУСК. Клетка обзора несёт НАПРАВЛЕНИЕ: укрепляла, ослабляла,
и туда и обратно, искали-не-нашли, не дошли. Направления у нас почти нет:
классификация встала на 15 сильных актах из 55, и только 2 из них имеют
голосования наблюдаемых фракций. Поэтому почти все клетки честно получают
«мы сюда не дошли» — состояние, для которого макет и завёл фактуру.

Число заполненных клеток из 64 — это и есть замер. Базовая линия сегодня,
прирост меряется тем же числом.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCK = ROOT / "design" / "mockup_v5" / "index.html"
MATRIX = ROOT / "data" / "coverage_matrix.json"
OUT = ROOT / "site" / "index.html"

# Закрытый список пяти значений клетки — канон D2 из приёмки 01.08.
CELL = {"up": ("↑", "укрепляла", ""), "down": ("↓", "ослабляла", ""),
        "both": ("↕", "и туда и обратно", ""),
        "none": ("", "искали, не нашли", "tx-none"),
        "miss": ("", "мы сюда не дошли", "tx-miss")}


def css_from_mockup() -> str:
    """CSS берётся из макета, а не копируется в код: один дом у формы."""
    m = re.search(r"<style>(.*?)</style>", MOCK.read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit("ОТКАЗ: в макете не найден <style> — форма не читается")
    return m.group(1)


def esc(s) -> str:
    import html
    return html.escape("" if s is None else str(s))


def cell(kind: str, label: str) -> str:
    a, word, tx = CELL[kind]
    cls = "v nd " + tx if tx else "v"
    arrow = f'<span class=a>{a}</span>&#8201;' if a else ""
    return (f'<span class="{cls}">{arrow}{esc(word)}'
            f'<span class=lb> · {esc(label)}</span></span>')


FRAME = """<div class=note id=frame data-frame=full>
<p class=dim style="margin-top:0"><b>Темы выбрал автор.</b> Не данные подсказали,
о чём говорить, — человек решил. Тема здесь одна: что фракция делала с судом,
парламентом и свободами.</p>
<p class=dim><b>Оценок здесь нет.</b> Ни баллов, ни звёзд, ни «лучшая-худшая».
Партии стоят в порядке черновика преемственности. Мы рассказываем, что
произошло; вывод — ваш.</p>
<p class=dim><b>Это первый выпуск на живых данных.</b> Почти все клетки ниже
пусты, и пустота эта — про нас, а не про партии: направление голосований мы
считать пока не умеем. Что известно про каждую фракцию, лежит в карточках.</p>
<p class=dim style="margin-bottom:0"><b>Автор — частное лицо,</b> проект никто
не финансирует и ни с кем не согласовывал. Ошибки тут авторские.</p>
</div>"""


def rows(m: dict) -> tuple[str, int, int]:
    """Строки обзора. Возвращает разметку, число клеток и число заполненных."""
    out, total, filled = [], 0, 0
    for r in m["lines"]:
        a, b = r["a"]["status"], r["b"]["status"]
        who = (f'<td class=who><a href="f-{r["anchor_id"]}.html">{esc(r["line"][:44])}</a>')
        if b == "not_exposed":
            who += ('<span class=norec>ни разу не была в правительстве</span>')
        who += "</td>"
        # Колонка «суд, парламент, свободы»: направление. Его нет ни у одной
        # строки — классификация встала. Единственное честное значение — miss.
        # Исключение: строка без связи с фракцией не «не дошли», а неизвестно
        # чья, и это другое состояние.
        k1 = "miss" if a == "observed" else "miss"
        c1 = cell(k1, "голосования по теме правового государства")
        total += 1
        if k1 not in ("miss", "none"):
            filled += 1
        # Колонка «деньги»: здесь состояние ЕСТЬ и оно различено §7.
        k2 = {"observed": "none", "not_exposed": "none",
              "source_missing": "miss", "lineage_unresolved": "miss"}[b]
        lab = ("коалиционного соглашения не подписывала"
               if b == "not_exposed" else "обязательства против бюджета")
        c2 = cell(k2, lab)
        total += 1
        if k2 not in ("miss", "none"):
            filled += 1
        out.append(f"<tr>{who}\n<td class=c-inst "
                   f'data-l="суд, парламент, свободы">{c1}</td>\n'
                   f'<td class=c-eq data-l="деньги">{c2}</td>\n</tr>')
    return "\n".join(out), total, filled


def build(m: dict) -> tuple[str, int, int]:
    body, total, filled = rows(m)
    miss = total - filled
    doc = f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Что фракции делали — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<h1>Что фракции делали на самом деле</h1>
<p class=lead>27 октября в бюллетене будет около двенадцати списков. Этот
документ нужен для одного: вычеркнуть два-три из них и уметь объяснить себе
почему — не «они мне не нравятся», а «вот закон, вот дата, вот как они
проголосовали».</p>
<p>Мы смотрим на поступки, а не на заявления. Слова перед выборами стоят ноль;
голос в Кнессете записан поимённо и никуда не денется.</p>
{FRAME}
<h2>Сначала о том, чего мы не знаем</h2>
<p>Клеток в таблице ниже — <b class=big>{total}</b>. Заполнены {filled};
в остальных {miss} мы либо не дошли, либо смотрели и вернулись пустыми.</p>
<p>Это разные вещи, и подписаны они по-разному.
<b class=tx-miss>«Не дошли»</b> значит, что мы туда не смотрели вовсе.
<b class=tx-none>«Искали, не нашли»</b> — что смотрели и вернулись пустыми.
И ни то, ни другое не значит «к этой партии вопросов нет». Пустая клетка
рассказывает про нас, а не про партию.</p>
<h2>Шестнадцать строк бюллетеня</h2>
<p>Стрелка показывает, в какую сторону фракция двигала то, что написано в
заголовке колонки, — а не «хорошо это или плохо». <b>↑</b> укрепляла,
<b>↓</b> ослабляла, <b>↕</b> ходила и туда и обратно.</p>
<table class=ov><thead><tr>
<th scope=col class=who>фракция</th>
<th scope=col class=c-inst>суд, парламент, свободы</th>
<th scope=col class=c-eq>деньги</th></tr></thead><tbody>
{body}
</tbody></table>
<div class=foot><p>Первый выпуск на живых данных, 13.08.2026.
Форма принята 01.08.2026 (design/mockup_v5). Снимок голосований:
{esc(m.get("source", {}).get("votes_at", "не объявлен"))}.</p></div>
</body></html>"""
    return doc, total, filled


def selftest() -> int:
    m = {"lines": [
        {"anchor_id": 1, "line": "правившая",
         "a": {"status": "observed"}, "b": {"status": "source_missing"}},
        {"anchor_id": 2, "line": "неправившая",
         "a": {"status": "observed"}, "b": {"status": "not_exposed"}},
        {"anchor_id": 3, "line": "без связи",
         "a": {"status": "lineage_unresolved"}, "b": {"status": "source_missing"}}],
        "source": {"votes_at": "2026-07-31"}}
    doc, total, filled = build(m)
    assert total == 6, f"клеток {total}, а строк три по две колонки"
    assert "<script" not in doc, "§13: в выводе появился JavaScript"
    assert 'content="noindex, nofollow"' in doc, "§16: нет noindex"
    assert doc.index("data-frame=full") < doc.index("<table"), \
        "§17: рамка обязана стоять раньше первой таблицы"
    assert "ни разу не была в правительстве" in doc, \
        "§7: неправившая строка обязана нести пометку, иначе её пустота " \
        "неотличима от нашей недоработки"
    assert doc.count("tx-miss") >= 2 and doc.count("tx-none") >= 2, \
        "две фактуры обязаны различаться: «не дошли» и «искали, не нашли» — " \
        "разные состояния, и слить их значит выдать нашу дыру за факт"
    # Ловим ЗАПРОС, а не упоминание. Первая редакция запрещала подстроку
    # «http» — и краснела на xmlns='http://www.w3.org/2000/svg' внутри data:
    # URL фоновой текстуры, то есть на пространстве имён, которое никуда не
    # ходит. Мина, названная в приёмке 01.08, другая: @import шрифтов Google
    # из дизайн-системы _ds. Её и стережём.
    assert "@import" not in doc, \
        "@import в выводе: приёмка 01.08 назвала это миной — шрифты Google " \
        "тянут внешний запрос, а файл обязан открываться с диска"
    assert not re.search(r"url\(\s*['\"]?https?://", doc), \
        "внешний ресурс по url(): файл обязан открываться с диска"
    assert not re.search(r"(src|href)\s*=\s*['\"]?https?://", doc), \
        "внешняя ссылка в src/href: файл обязан открываться с диска"
    # §13 — ярлыки ищутся ВНЕ рамки. Первая редакция сканировала документ
    # целиком и покраснела на собственной рамке: там написано «ни баллов, ни
    # звёзд, ни лучшая-худшая», то есть проверка поймала своё же отрицание.
    # Ровно это уже случалось 27.07 с §9, когда grep на имя запрещённого
    # эндпоинта заблокировал коммит, вводивший сам запрет.
    # Стиль тоже вырезается: §13 про то, что ЧИТАЕТ читатель. В комментарии
    # палитры принятого макета стоит «худшая соседняя пара ΔE 20.2» — про
    # контраст красок, а не про партии. Сканируя CSS, проверка объявила бы
    # нарушением сам принятый дизайн; это второй случай за один прогон, когда
    # грубая проверка запрещает то, что защищает.
    body_only = re.sub(r"<style>.*?</style>", "", doc, flags=re.S)
    body_only = re.sub(r"<div class=note id=frame.*?</div>", "", body_only, flags=re.S)
    for bad in ("лучшая", "худшая", "рейтинг", "балл", "звёзд"):
        assert bad not in body_only.lower(), \
            f"§13: оценочный ярлык «{bad}» вне рамки — рамка его отрицает, " \
            "остальной документ не имеет права его употреблять"
    assert "лучшая-худшая" in doc, \
        "отрицание ярлыков исчезло из рамки: без него сканирование вне рамки " \
        "проходило бы и на документе, где §13 просто не объявлен читателю"

    # --- страница фракции: те же нормы, что у обзора, плюс крошки и §12.
    fcard = {"party_ru": "Тест", "party_he": "\u05e4", "conclusion": "вывод",
             "confidence": "low", "confidence_reason": "базовая линия",
             "what_would_falsify": "если доля изменится",
             "readings": [{"type": "weakening", "text": "раз"},
                          {"type": "reframing", "text": "два"}],
             "counter_search": {"searched_where": ["выгрузка"], "outcome": "nothing",
                                "note": "искали устройство, не поведение"},
             "votes": {"theme_caveat_ru": "по вопросам правового государства",
                       "census": {"votes": 2, "acts": 2, "from": "2022-12-13",
                                  "to": "2026-07-14",
                                  "acts_without_participation": 1}}}
    frow = {"b": {"status": "not_exposed", "note": "соглашения не подписывала"}}
    fv = [{"date": "2022-12-13", "name_ru": "Законопроект",
           "name_he": "\u05d4\u05e6\u05e2\u05ea", "for_option_desc": "\u05dc\u05d4\u05e2\u05d1\u05d9\u05e8",
           "pos": "против 5"}]
    fp = faction_page(fcard, frow, fv)
    assert "<script" not in fp, "§13: скрипт на странице фракции"
    assert 'content="noindex, nofollow"' in fp, "§16: нет noindex на странице фракции"
    assert fp.index("data-frame=short") < fp.index("<h1"), \
        "§17: короткая рамка обязана стоять ДО заголовка — читатель, пришедший " \
        "по прямой ссылке, встречает её раньше всего остального"
    assert "<bdi>" in fp and "dir=rtl" in fp, "§12: иврит без bdi/rtl переставляется"
    assert "\u05dc\u05d4\u05e2\u05d1\u05d9\u05e8" in fp, "§10: смысл «за» не дошёл до страницы"
    assert "искали, не нашли" in fp, "§7: не экспонирована — не «не дошли»"
    assert fp.count("по вопросам правового государства") >= 1, \
        "оговорка о теме не дошла до страницы фракции"
    print("самопроверка render_overview: 20 утверждений")
    return 0


def load_cards() -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_cards import load_yaml_ish
    out = {}
    for f in sorted((ROOT / "cards").glob("*.yaml")):
        c = load_yaml_ish(f)
        if c.get("unit") == "faction_knesset":
            out[int(c["faction_id"])] = c
    return out


def votes_for(fid: int) -> list:
    """Голосования фракции с переводом названия. Отказ, а не пустота."""
    src = ROOT / "data" / "votes_25.json"
    tr = json.loads((ROOT / "docs" / "reference"
                     / "vote_names_ru_2026-08-13.json").read_text(encoding="utf-8"))["names"]
    POS = {"for": "за", "against": "против", "abstain": "воздержались",
           "present": "присутствовали, не голосовали"}
    out = []
    for r in json.loads(src.read_text(encoding="utf-8"))["rows"]:
        cell = next((v for k, v in (r.get("by_faction") or {}).items()
                     if k.split("|", 1)[0] == str(fid)), None)
        if cell is None:
            continue
        t = tr.get(str(r["bill_id"]))
        if not t or not r["bill_name"].startswith(t["he_head"]):
            raise SystemExit(f"ОТКАЗ §12: перевод акта {r['bill_id']} отсутствует "
                             "или устарел — страница нечитаема для владельца")
        out.append({"date": r["date"][:10], "name_ru": t["ru"],
                    "name_he": r["bill_name"],
                    "for_option_desc": r.get("for_option_desc") or "",
                    "pos": ", ".join(f"{POS.get(k, k)} {n}" for k, n in cell.items())})
    out.sort(key=lambda x: x["date"])
    return out


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not MATRIX.exists():
        print(f"нет {MATRIX} — сначала scripts/coverage_matrix.py"); return 2
    m = json.loads(MATRIX.read_text(encoding="utf-8"))
    doc, total, filled = build(m)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    cards, pages = load_cards(), 0
    for r in m["lines"]:
        c = cards.get(r["anchor_id"])
        if not c:
            continue
        page = faction_page(c, r, votes_for(r["anchor_id"]))
        (OUT.parent / f"f-{r['anchor_id']}.html").write_text(page, encoding="utf-8")
        pages += 1
    print(f"обзор + {pages} страниц фракций -> {OUT.parent}")
    print(f"ЗАМЕР: клеток {total}, заполнено {filled}, пусто {total - filled}")
    return 0




# ────────────────────────────────────── страницы фракций (форма f-*.html)
SHORT_FRAME = ('<p class=frame data-frame=short>Темы выбрал автор · оценок и '
               'баллов нет · данные — поимённые голосования Кнессета · автор — '
               'частное лицо, без финансирования. '
               '<a href="index.html#frame">Полная рамка</a></p>')
CERT = {"high": "⊕⊕⊕⊕ высокая", "medium": "⊕⊕⊕◯ средняя",
        "low": "⊕⊕◯◯ низкая", "none": "◯◯◯◯ нет"}
READ_RU = {"weakening": "ослабляющее прочтение",
           "strengthening": "усиливающее прочтение",
           "reframing": "переформатирующее прочтение"}


def det(summary: str, cert: str, inner: str, open_: bool = False) -> str:
    o = " open" if open_ else ""
    return (f'<details class=cell{o}><summary>{summary}'
            f'<span class=cert>{esc(cert)}</span></summary>'
            f'<div class=inner>{inner}</div></details>')


def faction_page(card: dict, row: dict, votes: list) -> str:
    """Страница фракции. Клетка оси — details, как в макете; перепись
    голосований уходит ВНУТРЬ раскрытия, а не вываливается на страницу."""
    ru, he = card.get("party_ru"), card.get("party_he")
    v = card.get("votes") or {}
    cen = v.get("census") or {}
    cav = v.get("theme_caveat_ru", "")
    inner1 = (f'<p><b>почему пусто</b> направление голосований мы считать пока '
              f'не умеем: классификация встала на объявленном пороге. Пустота '
              f'здесь про нас, а не про фракцию.</p>'
              f'<p><b>на чём стояла бы</b> перепись {esc(cen.get("votes"))} '
              f'голосований по {esc(cen.get("acts"))} актам, {esc(cav)}, '
              f'{esc(cen.get("from"))} — {esc(cen.get("to"))}. Актов темы без '
              f'участия фракции: {esc(cen.get("acts_without_participation"))}.</p>')
    cells = [det("Суд, парламент, свободы — "
                 '<b class=tx-miss>мы сюда не дошли</b>',
                 "насколько мы в этом уверены: значения нет", inner1, True)]
    if row["b"]["status"] == "not_exposed":
        s2, c2 = ('Деньги — <b class=tx-none>искали, не нашли</b>',
                  "не экспонирована: канал покрывает только подписавших соглашение")
    else:
        s2, c2 = ('Деньги — <b class=tx-miss>мы сюда не дошли</b>',
                  "сопоставление обязательств не построено")
    cells.append(det(s2, c2, f'<p>{esc(row["b"]["note"])}</p>'))
    body = [f'<p class=lead>{esc(card.get("conclusion"))}</p>']
    for r in card.get("readings") or []:
        body.append(f'<p><b>{esc(READ_RU.get(r.get("type"), ""))}.</b> '
                    f'{esc(r.get("text"))}</p>')
    cs = card.get("counter_search") or {}
    where = "".join(f"<li>{esc(w.get('источник') if isinstance(w, dict) else w)}</li>"
                    for w in cs.get("searched_where") or [])
    body.append(f'<div class=note><p><b>Искали, чем это опровергнуть:</b> '
                f'{esc(cs.get("outcome"))}</p><ul class=dim>{where}</ul>'
                f'<p class=dim>{esc(cs.get("note", ""))}</p>'
                f'<p><b>Уверенность:</b> {esc(CERT.get(card.get("confidence")))} — '
                f'{esc(card.get("confidence_reason"))}</p>'
                f'<p><b>Чем это опровергается.</b> '
                f'{esc(card.get("what_would_falsify"))}</p></div>')
    acts = "".join(
        f'<tr><td data-l="дата">{esc(x["date"])}</td>'
        f'<td data-l="акт">{esc(x["name_ru"])}'
        f'<span class="he" lang=he dir=rtl><bdi>{esc(x["name_he"])}</bdi></span></td>'
        f'<td data-l="«за» означало"><span class=he lang=he dir=rtl>'
        f'<bdi>{esc(x["for_option_desc"])}</bdi></span></td>'
        f'<td data-l="фракция">{esc(x["pos"])}</td></tr>' for x in votes)
    body.append(det(f"Все {len(votes)} голосований этой фракции — {esc(cav)}",
                    "перепись целиком, отбора внутри темы не делалось",
                    '<table class=acts><thead><tr><th scope=col>дата</th>'
                    '<th scope=col>акт</th><th scope=col>«за» означало</th>'
                    f'<th scope=col>фракция</th></tr></thead><tbody>{acts}'
                    '</tbody></table>'))
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{esc(ru)} — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<nav class=crumbs><a href="index.html">Все фракции</a> · {esc(ru)}</nav>
{SHORT_FRAME}
<h1>{esc(ru)} <span class=he lang=he dir=rtl><bdi>{esc(he)}</bdi></span></h1>
{''.join(cells)}
{''.join(body)}
<div class=foot><p>Первый выпуск на живых данных, 13.08.2026. Форма принята
01.08.2026. Снимок голосований: 2026-07-31.</p></div>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
