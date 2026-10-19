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
from build_report import plural_ru
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
    "signed_from": "С чьей стороны смотрим",
}
# В STRUCTURAL попадают ТОЛЬКО поля, которые страница действительно
# использует иначе, чем прозой. Белый список — место, где объявленное
# решение исчезает по моей собственной руке: `signed_from` («с чьей стороны
# смотрим») лежал здесь и не выводился нигде, то есть отказ на незнакомом
# поле охранял страницу от чужих ошибок и не охранял от моей. Нашёл Кодекс
# в состязательном ревью 07.10. Самопроверка теперь требует, чтобы ЗНАЧЕНИЕ
# каждого объявленного строкового поля стояло на странице.
STRUCTURAL = {"id", "rank", "role", "signed", "title_ru",
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
        if counts["acts"] is None or counts["votes"] is None:
            return ("выгрузки нет",
                    "это ось, по которой мы считаем, но самой выгрузки "
                    "голосований на месте нет — числа сказать не из чего. "
                    "Это про нас, а не про ноль действий")
        return ("считаем", f"отобрано {counts['acts']} парламентских действий "
                           f"и {counts['votes']} {plural_ru(counts['votes'], 'поимённое голосование', 'поимённых голосования', 'поимённых голосований')}; "
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
    # None, а НЕ ноль: отсутствие выгрузки — техническое состояние, и
    # выданное числом оно превращается в замер «ни одного действия» (§7).
    out = {"measured_axis": None, "acts": None, "votes": None}
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
        # УНИКАЛЬНЫЕ голосования, а не строки выгрузки: vote_id 46121
        # лежит в ней четыре раза, и «1809 голосований» было неправдой —
        # строк 1809, голосований 1806. Нашёл Кодекс, проверено своим
        # счётом.
        out["votes"] = len({r.get("vote_id") for r in (v.get("rows") or [])
                            if r.get("vote_id") is not None})
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
             f'</h3>',
             f'<p class=val>{esc(ROLE_RU.get(axis.get("role"), axis.get("role")))}</p>',
             '<div class=body>']
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
<h1>Что мы меряем</h1>
<p class=lead>В обзоре четыре темы: суд, парламент и свободы; государство и религия; экономика; безопасность.</p>
<p>Направления по всем четырём темам уже рассчитываются. Действующие правила и ограничения
описаны в <a href="method.html">методе</a>; результаты — в <a href="index.html">обзоре</a>.
Темы выбрал автор. Решение о вычёркивании списка принимает читатель; автоматического порога нет.</p>
<details><summary>Первоначальное объявление тем — 31.07.2026 (история)</summary>
<p>Ниже сохранены исходные решения и рабочие пометки автора. Они объясняют,
с чего началась работа, и не описывают состояние расчётов на 19.10.2026.
Например, первоначальный отказ от знака по безопасности позднее сменился временным правилом;
оно описано в методе. K1, K8 и K9 — обозначения пунктов исходного правила;
английские сокращения ниже — названия внешних исследовательских шкал, не оценки партий.</p>
<div class=axes>
{body}
</div>
<div class=note>
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
исходного объявления рамки. Это история выбора тем;
текущие правила и результаты находятся по ссылкам выше. Автор — частное лицо, проект никто не
финансирует и ни с кем не согласовывал.</p></div>
</details>
<footer>{SHORT_FRAME}</footer>
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
    # ── ОТСУТСТВИЕ ВЫГРУЗКИ — НЕ НОЛЬ ДЕЙСТВИЙ (§7) ─────────────────────
    none_c = {"measured_axis": "rule_of_law", "acts": None, "votes": None}
    lab, txt = axis_state(T["themes"][0], none_c)
    assert lab == "выгрузки нет" and "0" not in txt, (lab, txt)
    # Проверяется не только ветка, но и ПРОВОДКА: первая версия этой
    # проверки трогала axis_state на рукотворном входе и оставалась зелёной,
    # когда counts_from_repo возвращал ноль вместо None. Оракул, который
    # смотрит на функцию и не смотрит на вызов, охраняет не то место.
    global SELECTION, VOTES
    keep = (SELECTION, VOTES)
    try:
        SELECTION = Path("/tmp/нет-такого-отбора.json")
        VOTES = Path("/tmp/нет-такой-выгрузки.json")
        c0 = counts_from_repo()
        assert c0["acts"] is None and c0["votes"] is None, \
            f"отсутствие файлов выдано числом: {c0}"
    finally:
        SELECTION, VOTES = keep

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
    assert page.index("<footer>") < page.index("data-frame=short") < page.index("</footer>"), \
        "v62: рамка вне подвала"
    for a in live["themes"]:
        assert a["title_ru"] in page, f"ось {a['id']} потерялась на странице"
    # ── ЗНАЧЕНИЕ КАЖДОГО ОБЪЯВЛЕННОГО ПОЛЯ СТОИТ НА СТРАНИЦЕ ────────────
    # Отказ на НЕЗНАКОМОМ поле охранял от чужих ошибок; эта проверка
    # охраняет от моей — от поля, которое я сам внёс в белый список и
    # нигде не вывел. Так потерялся полюс оси «экономика» (signed_from).
    # Поля, которые выводятся НЕ дословно, а через словарь: проверяется и
    # то, что значение словарю известно (иначе теряется молча), и то, что
    # перевод стоит на странице. Пустой список исключений здесь был бы
    # ложью: три поля правда переводятся для читателя.
    TRANSLATED = {"role": ROLE_RU, "channel_a_votes": STRENGTH,
                  "channel_b_budget": STRENGTH}
    flat = " ".join(page.split())
    for a in live["themes"]:
        for k, val in a.items():
            if not isinstance(val, str) or k == "id":
                continue
            if k in TRANSLATED:
                assert val in TRANSLATED[k], \
                    f"{a['id']}.{k}={val!r} словарю неизвестно — потеряется молча"
                want = TRANSLATED[k][val]
            else:
                want = val
            head = " ".join(str(want).split())[:40]
            assert head in flat, \
                f"объявленное {a['id']}.{k} не выведено на страницу: {head!r}"
    assert "Направления по всем четырём темам уже рассчитываются" in page
    assert '<details><summary>Первоначальное объявление тем' in page
    assert 'Вычёркиваем по' not in page
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
