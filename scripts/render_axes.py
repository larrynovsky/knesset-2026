#!/usr/bin/env python3
"""axes.html — страница осей: ЧТО этот документ вообще мерит.

Первый вопрос холодного читателя к обзору — не «какая партия хуже», а «что
вы померили и почему именно это». Обзор на него не отвечает: там одна
колонка с направлением и одна с деньгами, а четыре оси рамки читателю
нигде не показаны. Эта страница их показывает — и показывает, что три из
четырёх НЕ участвуют в вычёркивании, а одна из трёх не имеет признака
вовсе.

Дом правила — criteria/themes.yaml, и страница собирается из него. Второго
дома у рамки быть не должно: в этом проекте уже было, что одно знание в
двух домах разошлось, и заметить это было некому.

ПОЧЕМУ ЗДЕСЬ ОТКАЗ НА НЕИЗВЕСТНОМ ПОЛЕ. Если в themes.yaml появится новое
поле, а здесь его не окажется в карте — молчаливо исчезло бы объявленное
решение владельца, и страница выглядела бы полной. Поэтому незнакомое
поле роняет сборку: пусть лучше откажет, чем тихо недоскажет (§24).

    python3 scripts/render_axes.py --selftest
    python3 scripts/render_axes.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = ROOT / "criteria" / "themes.yaml"
KEYVOTES = ROOT / "criteria" / "keyvotes.yaml"
SELECTION = ROOT / "data" / "selection_arrow_2026-10-07.json"
VOTES = ROOT / "data" / "votes_25.json"
OUT = ROOT / "site" / "axes.html"

# Заголовки для читателя. Ключ — поле объявления, значение — то, как это
# называется на странице. Поля, несущие устройство, а не текст, собраны в
# STRUCTURAL: они используются иначе и в прозу не идут.
HEAD = {
    "role_note": "Что означает эта роль",
    "columns_note": "Две колонки, и они не складываются",
    "признак": "Признак: что считается плюсом и минусом",
    "убрано_31_07": "Что из признака убрано и почему",
    "защита_от_зеркала": "Проверка на зеркало",
    "axis_form": "Форма оси",
    "known_finding": "Что уже известно",
    "signed_note": "Почему знака нет",
    "note": "Замечание",
    "external_anchor": "Внешний якорь",
    "ches_mapping": "Откуда взята ось",
    "owner_words": "Слова владельца",
}
STRUCTURAL = {"id", "rank", "role", "signed", "signed_from", "title_ru",
              "columns", "channel_a_votes", "channel_b_budget"}

ROLE_RU = {"РЕШАЮЩАЯ": "по этой оси список вычёркивается",
           "описательная": "по этой оси список НЕ вычёркивается"}
STRENGTH = {"сильный": "многое видно", "средний": "видно отчасти",
            "слабый": "видно мало"}


def load_themes(path: Path = THEMES) -> dict:
    """Рамка владельца из объявленного файла. yaml уже в зависимостях."""
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def axis_state(axis: dict, counts: dict) -> tuple[str, str]:
    """Состояние оси: что по ней уже посчитано. Возвращает (ярлык, фраза).

    Это главное, чего нет в themes.yaml: объявление говорит, ЧТО мерить, а
    читателю нужно знать, померено ли. Для решающей оси числа настоящие; для
    остальных их нет, и фраза говорит именно это, а не «данные готовятся».
    """
    if axis["id"] == counts.get("measured_axis"):
        return ("считаем", f"отобрано {counts['acts']} парламентских действий "
                           f"и {counts['votes']} поимённых голосований; "
                           f"направление по ним считается сейчас")
    if axis.get("signed") is False:
        return ("знака нет",
                "знак по этой оси не ставится — так решено, см. ниже; "
                "актов по ней мы не отбирали")
    if "признак" not in axis:
        return ("заблокирована",
                "ось помечена «со знаком», но признак нигде не объявлен: "
                "пока не решено, что здесь плюс, актов по ней мы не "
                "отбирали и знака у них не будет")
    return ("не начата",
            "признак объявлен, актов по этой оси мы ещё не отбирали: "
            "ни одного числа по ней в документе нет")


def counts_from_repo() -> dict:
    """Числа решающей оси — из выгрузки, а не из текста.

    Пустые значения законны: до первой выгрузки страница обязана собираться
    и говорить, что чисел нет.
    """
    out = {"measured_axis": None, "acts": 0, "votes": 0}
    # keyvotes.yaml НЕ читается ни yaml, ни разборщиком проекта: там есть
    # многострочные значения без `>-` (проверено — падают оба). Нужна оттуда
    # одна строка, и чинить файл ради неё значило бы тронуть критерий
    # отбора действий посреди другой работы. Берём строку.
    import re
    m = re.search(r"^theme:\s*(\S+)", KEYVOTES.read_text(encoding="utf-8"),
                  re.M)
    if not m:
        raise SystemExit("ОТКАЗ: в criteria/keyvotes.yaml нет строки theme: — "
                         "неизвестно, какая ось считается")
    out["measured_axis"] = m.group(1)
    if SELECTION.exists():
        sel = json.loads(SELECTION.read_text(encoding="utf-8"))
        out["acts"] = len(sel.get("selected") or [])
    if VOTES.exists():
        v = json.loads(VOTES.read_text(encoding="utf-8"))
        out["votes"] = len(v.get("rows") or [])
    return out


def axis_html(axis: dict, counts: dict, esc) -> str:
    """Один раздел страницы. Незнакомое поле объявления роняет сборку."""
    unknown = sorted(set(axis) - set(HEAD) - STRUCTURAL)
    if unknown:
        raise SystemExit(
            f"ОТКАЗ: в объявлении оси {axis.get('id')} есть поля, которых нет "
            f"на странице: {', '.join(unknown)}. Молчаливо потерянное решение "
            f"владельца хуже отказа сборки — добавьте поле в HEAD или в "
            f"STRUCTURAL осознанно.")
    lab, state = axis_state(axis, counts)
    cls = {"rule_of_law": "inst", "economy": "econ",
           "religion_state": "rel", "security": "sec"}.get(axis["id"], "")
    warn = " warn" if lab != "считаем" else ""
    parts = [f'<div class="ax {cls}"><h3>{esc(axis["title_ru"])}'
             f'<span class="rank{warn}">{esc(lab)}</span></h3>',
             f'<p class=val>{esc(ROLE_RU.get(axis.get("role"), axis.get("role")))}</p>',
             f'<div class=body><p><b>Что по ней уже есть.</b> {esc(state)}</p>']
    ca, cb = axis.get("channel_a_votes"), axis.get("channel_b_budget")
    if ca or cb:
        parts.append(f'<p><b>Чем её видно.</b> По голосованиям — '
                     f'{esc(STRENGTH.get(ca, ca))}; по деньгам — '
                     f'{esc(STRENGTH.get(cb, cb))}. Это оценка автора до '
                     f'работы, а не замер.</p>')
    cols = axis.get("columns")
    if cols:
        parts.append('<p><b>Колонки.</b> ' + esc(", ".join(cols)) + '</p>')
    for k, head in HEAD.items():
        if k in axis:
            parts.append(f'<p><b>{esc(head)}.</b> '
                         f'{esc(str(axis[k]).strip())}</p>')
    parts.append("</div></div>")
    return "".join(parts)


def build(themes: dict, counts: dict) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_overview import SHORT_FRAME, css_from_mockup, esc
    axes = sorted(themes["themes"], key=lambda t: t["rank"])
    if not axes:
        raise SystemExit("ОТКАЗ: в объявлении нет ни одной оси")
    deciding = [a for a in axes if a.get("role") == "РЕШАЮЩАЯ"]
    body = "".join(axis_html(a, counts, esc) for a in axes)
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Что мы меряем — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<nav class=crumbs><a href="index.html">Все фракции</a> · Что мы меряем</nav>
{SHORT_FRAME}
<h1>Что мы меряем</h1>
<p class=lead>Тем {len(axes)}. Вычёркиваем по {len(deciding)}.</p>
<p>Обзор показывает одну колонку с направлением, и читатель вправе спросить:
а почему именно это? Темы выбрал автор — живой человек со своими взглядами,
и ни одна из них не выведена из данных. Здесь написано, какие темы он
выбрал, что по каждой считается делом, и что по каждой уже посчитано.</p>
<p>Разница между темами не в важности. По одной автор готов вычеркнуть
список из бюллетеня — и только по ней выверяются знаки вручную. По
остальным — нет, и это сказано заранее, а не выяснилось в конце.</p>
<p class=dim><b>Ниже — объявления автора дословно,</b> вместе с его рабочими
пометками вроде «K8» и «§13». Пересказать их гладко значило бы подменить
решение пересказом: решение принято в тех словах, в каких записано, и
читатель вправе видеть именно их. Что непонятно — то и есть мера того,
насколько этот документ пока сырой.</p>
<div class=axes>
{body}
</div>
<div class=note>
<p><b>Чего на этой странице нет.</b> У темы «государство и религия» в
рабочих материалах есть три черновика признака, и ни один не выбран.
Здесь их нет намеренно: они живут только в макете, а макет из
репозитория не воспроизводится. Пока признак не объявлен в
<code>criteria/themes.yaml</code>, его нет и для читателя.</p>
<p><b>Пятая тема.</b> Социальная политика отдельной темой не заводится:
она распадается на три уже имеющиеся. Правило пересмотра объявлено
заранее: если больше десятой части действий не ляжет ни в одну из четырёх
тем — тема нужна.</p>
<p><b>Темы, исключённые осознанно.</b> Отношения с арабским миром,
равенство полов, риторика об исламе. Причина не в важности, а в
проверяемости: по нашим данным они делами не меряются, а спрашивать
позицию по тому, что нечем проверить у партий, — производить видимость
работы.</p>
</div>
<div class=foot><p>Собрано из <code>criteria/themes.yaml</code> —
единственного дома этой рамки. Если страница и объявление разойдутся,
сборка откажет, а не промолчит. Автор — частное лицо, проект никто не
финансирует и ни с кем не согласовывал.</p></div>
</body></html>"""


def selftest() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_overview import esc

    T = {"themes": [
        {"id": "rule_of_law", "rank": 1, "role": "РЕШАЮЩАЯ", "signed": True,
         "title_ru": "Решающая", "признак": "п", "channel_a_votes": "сильный",
         "channel_b_budget": "слабый"},
        {"id": "security", "rank": 4, "role": "описательная", "signed": False,
         "title_ru": "Без знака", "signed_note": "так решено"},
        {"id": "religion_state", "rank": 3, "role": "описательная",
         "signed": True, "title_ru": "Заблокирована"},
        {"id": "economy", "rank": 2, "role": "описательная", "signed": True,
         "title_ru": "Начата", "признак": "п"}]}
    C = {"measured_axis": "rule_of_law", "acts": 277, "votes": 1809}

    # состояние оси выводится из объявления, а не приписывается рукой
    assert axis_state(T["themes"][0], C)[0] == "считаем"
    assert axis_state(T["themes"][1], C)[0] == "знака нет"
    assert axis_state(T["themes"][2], C)[0] == "заблокирована", \
        "ось со знаком и без признака выдана за начатую"
    assert axis_state(T["themes"][3], C)[0] == "не начата"
    assert "277" in axis_state(T["themes"][0], C)[1]

    # ── ОТКАЗ НА НЕИЗВЕСТНОМ ПОЛЕ ───────────────────────────────────────
    # Если решение владельца появится в объявлении, а на странице его не
    # будет, страница выглядит полной и врёт умолчанием. Поэтому отказ.
    try:
        axis_html(dict(T["themes"][0], новое_поле="решение владельца"), C, esc)
    except SystemExit as e:
        assert "новое_поле" in str(e), e
    else:
        raise AssertionError("незнакомое поле объявления молча исчезло")

    # все поля живого объявления покрыты — страница собирается без отказа
    live = load_themes()
    page = build(live, counts_from_repo())
    assert "<script" not in page, "§13: скрипт на странице осей"
    assert 'content="noindex, nofollow"' in page, "§16: нет noindex"
    assert page.index("data-frame=short") < page.index("<h1"), \
        "§17: рамка обязана стоять ДО заголовка"
    for a in live["themes"]:
        assert a["title_ru"] in page, f"ось {a['id']} потерялась на странице"
    # заявление «вычёркиваем по одной» обязано быть замером объявления
    n_dec = sum(1 for a in live["themes"] if a.get("role") == "РЕШАЮЩАЯ")
    assert f"Вычёркиваем по {n_dec}." in page, \
        "число решающих осей на странице не совпало с объявлением"
    # а эта страница — из тех, где внутренняя лексика методики разрешена
    from check_report_canon import DOCS_FREE
    assert "axes.html" in DOCS_FREE, \
        "страница методики потеряла разрешение на лексику — проверьте канон"
    print("самопроверка render_axes: 12 утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    page = build(load_themes(), counts_from_repo())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"страница осей -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
