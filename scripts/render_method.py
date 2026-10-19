#!/usr/bin/env python3
"""site/method.html — методология, собранная из объявлений и замеров, не руками.

Каждое число на странице приходит из источника в репозитории или из того же
кода, который делал замер: пороги — arrow_rule(); α — direction_confidence.
alpha() по тому же файлу прогона; покрытие — data/coverage_matrix.json; смысл
«за» — sign_table() по выгрузке; правило чтения владельцем — criteria/
declared_before_owner_reading_*.yaml; деньги — coverage_matrix.commitment_maps().
Страница, собранная руками, пережила бы любое изменение этих источников и
тихо устарела (тот же довод, что у render_axes). Базовая ставка канала денег
стоит здесь как свойство КАНАЛА (§7), в карточки партий она не входит.

Вызывается из check_report_canon.build_site; OUT переопределяется оттуда.
"""
from __future__ import annotations

from build_report import plural_ru
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOTES = ROOT / "data" / "votes_25.json"
ARROW = ROOT / "data" / "direction_arrow_2026-10-07.json"
COVERAGE = ROOT / "data" / "coverage_matrix.json"
OWNER_DECL = ROOT / "criteria" / "declared_before_owner_reading_2026-10-10.yaml"
OUT = ROOT / "site" / "method.html"


def refuse(msg: str) -> None:
    raise SystemExit(f"ОТКАЗ: {msg}")


def flat(path: Path, key: str) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_owner_reading import yaml_flat
    return yaml_flat(path, key)


def facts() -> dict:
    """Все числа страницы — одним словарём, чтобы оракул мог их пересчитать."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import (alpha, arrow_rule, load_directions,
                                      sign_of, sign_table)
    from coverage_matrix import commitment_maps
    f: dict = {}
    for p in (VOTES, ARROW, COVERAGE, OWNER_DECL):
        if not p.exists():
            refuse(f"нет {p.relative_to(ROOT)} — страницу методологии без него "
                   "собирать нельзя: она бы врала о состоянии")
    votes = json.loads(VOTES.read_text(encoding="utf-8"))
    rows = votes["rows"]
    table = sign_table()
    f["snapshot"] = str(votes.get("at", ""))[:10]
    f["window"] = [str(w)[:10] for w in votes.get("window", ["", ""])]
    f["votes_rows"] = len(rows)
    f["votes_unique"] = len({r["vote_id"] for r in rows})
    c = collections.Counter(sign_of(r.get("for_option_desc"), table) for r in rows)
    f["carries"], f["none"], f["inverts"] = c["carries"], c["none"], c["inverts"]
    f["reservations"] = sum(1 for r in rows
                            if (r.get("for_option_desc") or "").strip() == "לקבל את ההסתייגות")
    f["acts"] = len({r["bill_id"] for r in rows if r.get("bill_id") is not None})

    rule = arrow_rule()
    f["alpha_threshold"] = rule["tentative"]
    f["alpha_good"] = rule["acceptable"]
    f["min_acts"] = rule["min_acts"]
    arrow = json.loads(ARROW.read_text(encoding="utf-8"))
    _, units, _ = load_directions(ARROW)
    f["alpha"] = round(alpha(units), 4)
    f["pairs"] = len(units)
    f["agree"] = sum(1 for u in units if u[0] == u[1])
    f["codebook"] = arrow.get("codebook_version")
    f["models"] = arrow.get("models") or {}
    f["attempted"] = arrow.get("attempted")
    f["arrow_published"] = f["alpha"] >= f["alpha_threshold"]
    from build_line_cards import COVERAGE_FIRST
    f["coverage_first"] = COVERAGE_FIRST

    cov = json.loads(COVERAGE.read_text(encoding="utf-8"))
    f["lines"] = cov["counts"]["lines"]
    f["a_obs"], f["b_obs"], f["c_obs"] = (cov["counts"]["a_observed"],
                                          cov["counts"]["b_observed"],
                                          cov["counts"]["c_observed"])
    money = commitment_maps()
    f["money"] = {fid: v for fid, v in money.items()}
    # R8-F04: счёт «деньги — у N» берётся из тех же живых объектов, что
    # обзор, а не из снимка coverage_matrix.json (там b_observed=1 с августа).
    # Не «1 → 7» вслепую: у 1098 карта извлечения есть, обязательств ноль.
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_overview import load_cards
    f["b_obs"] = len(money)
    rev = {k for k, v in load_cards("party_period").items() if v}
    f["b_rev"] = len(rev & set(money))
    f["b_zero"] = sum(1 for k, v in money.items() if k not in rev and not v["commitments"])
    f["b_open"] = f["b_obs"] - f["b_rev"] - f["b_zero"]

    sel = flat(OWNER_DECL, "selection")
    f["owner_size"] = int(sel.get("size", 0) or 0)
    f["owner_scale"] = flat(OWNER_DECL, "marks").get("scale", "")
    # v40: reuse the production signs and counters; do not maintain a second tally.
    from build_line_cards import axis_directions, _arrow_split
    from direction_confidence import compose
    from theme_arrows import load_signs, theme_arrows
    from map_commitments import agreement_entries
    ballot = json.loads((ROOT / "criteria/ballot_2026.json").read_text())
    yashar = next(x for x in ballot["lists"] if x["he"] == "ישר!")
    f["personal"] = bool(yashar.get("personal"))
    f["ballot_note"] = ballot["note"]
    original, _, _ = load_directions(ARROW)
    second = {}
    for name in ("axis_audit_v32", "axis_reread_v39A", "axis_reread_v39B"):
        part = json.loads((ROOT / "reviews" / (name + ".json")).read_text())
        if second.keys() & part.keys():
            refuse("второе чтение содержит повторяющиеся акты")
        second.update(part)
    declared = json.loads((ROOT / "criteria/axis_second_reading_2026-10-19.json").read_text())["signs"]
    if {k: v["sign"] for k, v in second.items()} != declared:
        refuse("второе чтение в отчётах и применённое правило расходятся")
    if not set(map(str, original)) <= second.keys():
        refuse("второе чтение не покрывает все числовые оценки большинства")
    effective, _ = axis_directions(ARROW)
    f["reread_total"], f["numeric_total"] = len(second), len(original)
    f["opposite"] = sum(v in (-1, 1) and second[str(k)]["sign"] == -v
                        for k, v in original.items())
    f["withdrawn"] = sum(v in (-1, 1) and effective[k] == 0 for k, v in original.items())
    f["declined"] = sum(second[str(k)]["sign"] is None for k in original)
    f["signed_total"] = sum(v in (-1, 1) for v in original.values())
    tb = json.loads((ROOT / "criteria/claude_tiebreak_signs_2026-10-19.json").read_text())["signs"]
    # Historical signs survive in the comparison table, before withdrawal.
    history = re.findall(r"^\| (\d+) \| ([+-][01]) \| (?:[+-][01]|null) \|",
                         (ROOT / "reviews/tiebreak_crosscheck_v29.md").read_text(), re.M)
    if len(history) != len(tb) or {k for k, _ in history} != set(tb):
        refuse("таблица слепой сверки решающего голоса неполна")
    f["disputed"] = len(tb)
    f["tiebreak_withdrawn"] = sum(int(v) != 0 and tb[k] == 0 for k, v in history)
    robustness = json.loads((ROOT / "data/arrow_robustness.json").read_text())
    from arrow_robustness import label
    f["stable_min"] = next(i for i in range(101) if label(i / 100) == "устойчива")
    f["shaky_min"] = next(i for i in range(101) if label(i / 100) == "шаткая")
    f["runs"] = robustness["runs"]
    f["p"] = robustness["probabilities"][0]
    f["axis_examples"] = robustness["topics"]["rule_of_law"]["factions"]
    # A stale simulation must not silently describe newer production arrows.
    per, _, _ = compose(rows, effective, table, dict(rule, split_below=float(_arrow_split())))
    for fid in ("1096", "1098"):
        current = next(v for k, v in per.items() if k.split("|")[0] == fid)
        if any(current[k] != f["axis_examples"][fid][k] for k in ("up", "down")):
            refuse("пример устойчивости устарел: пересоберите arrow_robustness.json")
    f["religion_total"] = len(load_signs("religion_state"))
    f["religion_signed"] = sum(v != 0 for v in load_signs("religion_state").values())
    f["economy_example"] = theme_arrows("economy", votes)[1096]
    f["ca37"] = len(agreement_entries((ROOT / "criteria/budget_mapping.yaml").read_text()))
    ca36 = json.loads((ROOT / "criteria/agreements_ca36.json").read_text())
    ocr = json.loads((ROOT / "data/agreements_ocr_report_ca36.json").read_text())
    if {Path(a["file"]).stem for a in ca36["agreements"]} != set(ocr["files"]):
        refuse("состав CA36 и отчёт распознавания расходятся")
    f["ca36"], f["budget_years"] = len(ocr["files"]), ca36["budget_years"]
    return f


def build(f: dict) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_overview import SHORT_FRAME, css_from_mockup, esc
    models = ", ".join(f"{k}: {esc(str(v))}" for k, v in sorted(f["models"].items()))
    verdict = ("публикуется" if f["arrow_published"]
               else "публикуется как первая грубая итерация: порог, объявленный "
               "до прогона, не достигнут и временно снят решением владельца "
               "19.10 «покрытие вместо точности»" if f.get("coverage_first")
               else "НЕ публикуется — порог, объявленный до прогона, не достигнут")
    yashar = ("по личным голосам участников, указанным в таблице состава" if f["personal"]
              else "по фракции Ганца, в которой Айзенкот и Тропер голосовали до ухода")
    likud, gantz = (f["axis_examples"][k] for k in ("1096", "1098"))
    econ = f["economy_example"]
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Как это сделано — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<nav class=crumbs><a href="index.html">Все списки</a> · Как это сделано</nav>
{SHORT_FRAME}
<h1>Как это сделано</h1>
<p class=lead>Состояние на вечер 19.10.2026. Мы смотрим, как голосовали партии,
какие денежные обещания подписывали и что удалось найти в бюджете.
Стрелка помогает увидеть направление голосований; она не советует, за кого голосовать.
Например, совпадение обещания со строкой бюджета ещё не означает, что деньги дошли до получателя.</p>

<h2>Списки бюллетеня и фракции</h2>
<p>В бюллетене — сегодняшние союзы, а в сохранённых голосованиях — фракции
25-го Кнессета. Поэтому рядом со списком показываем прошлое тех фракций, которые
с ним связаны (§1–2). Это способ посмотреть на прошлое, а не прогноз поведения нового союза.</p>
<p>Например, у Беннета в этом Кнессете голосов нет. В «Беяхад» видны голоса
Еш Атида Лапида; приписывать их Беннету нельзя. «Яшар!» читается {yashar}.
Новый список и старая фракция — не одно и то же.</p>
<p>Состав списков сверяли 19.10 по
IDI (en.idi.org.il/israeli-elections-and-parties/elections/2026/),
лидеров — по Википедии (en.wikipedia.org/wiki/2026_Israeli_legislative_election).
Это датированная сверка, а не гарантия неизменности состава к выборам.</p>

<h2>Как ставился знак закона</h2>
<p>{len(f['models'])} {plural_ru(len(f['models']), "модель", "модели", "моделей")} независимо читали закон по общему правилу.
Плюс означает усиление сдержек власти или защиты прав, минус — ослабление,
ноль — отсутствие направленного изменения по этой оси. Например, обязательное
согласие парламентской комиссии ограничивает министра; обязанность только отчитаться
такого ограничения не создаёт. Если оценки совпадали у большинства моделей, брали эту оценку.</p>
<p>Для {f['disputed']} спорных законов большинства не было: решающий голос дал Claude.
Затем Codex прочитал полные доступные тексты, не видя этого голоса до фиксации своего ответа.
После сверки сняты {f['tiebreak_withdrawn']} знаков. Например, если один читатель видел
усиление прав, а другой — смешанный эффект, закон переставал двигать стрелку.</p>
<p>Следом перечитали весь корпус с решением большинства: {f['reread_total']} акта,
из них {f['numeric_total']} с числовой оценкой (включая нули).
Прямых противоречий «плюс вместо минуса» или наоборот — {f['opposite']};
снято {f['withdrawn']} ненулевых знаков, включая расхождения с нулём.
Отказ второго читателя сам по себе знак не снимает: например, в тексте продления
может не быть содержания продлеваемой нормы. Перечитывали полные локальные тексты,
но их полноту относительно оригиналов отдельно не доказали.</p>
<p class=dim>След проверки: axis_audit_v32, axis_reread_v39A/B и tiebreak_crosscheck_v29
в материалах проекта. Согласие читателей не делает их эталоном истины.</p>

<h2>Устойчивость стрелки</h2>
<p>Проверяем, сохранится ли стрелка при ошибках в знаках законов. В каждом из
{f['runs']} повторений случайно выбираем долю p={f['p']:.2f} законов с ненулевым
знаком и меняем плюс на минус или наоборот. Один закон меняется сразу для всех
его чтений и всех фракций; нули не меняются.</p>
<p>«Устойчива» — прежняя стрелка остаётся хотя бы в {f['stable_min']}% повторений;
«шаткая» — от {f['shaky_min']}% до {f['stable_min']}% (не включая верхнюю границу);
«ненадёжна» — меньше {f['shaky_min']}%.
Это устойчивость к выбранной ошибке, а не вероятность правоты партии или нашей оценки.</p>
<p>Почему p={f['p']:.2f}: прямые противоположности составили
{100*f['opposite']/f['signed_total']:.1f}% от {f['signed_total']} ненулевых оценок большинства.
Если считать риском также неподтверждённые оценки, отказы второго чтения
({f['declined']} из {f['numeric_total']}, {100*f['declined']/f['numeric_total']:.1f}%)
дают ориентир порядка {round(100*f['declined']/f['numeric_total'], -1):.0f}%. Это условная верхняя граница для такого сценария,
не доказанный предел ошибок: отказы не равны ошибкам, а общие ошибки читателей могут остаться незамеченными.
Выбранная доля — рабочее допущение между этими ориентирами, не измеренная частота.</p>
<p>Например, у Ликуда {likud['up']}:{likud['down']} законов в сторону усиления
и ослабления сдержек: большой перевес, стрелка сохраняется в {100*likud['rates']['0.10']:.1f}% повторений.
У фракции Ганца — {gantz['up']}:{gantz['down']}, сохранение {100*gantz['rates']['0.10']:.1f}%:
результат ближе к границе двух третей, поэтому небольшая перестановка знаков
может превратить направленную стрелку в «и туда и обратно».
Связанные ошибки — например, неверное прочтение всей группы похожих законов — эта проверка не моделирует.</p>

<h2>Темы</h2>
<p>Экономика: почти единогласные законы говорят об общем решении парламента,
а не об отличии партии. Например, у Ликуда таких законов {econ['consensus']},
а различающих — {econ['up'] + econ['down']}; поэтому пишем «голосовали со всеми».
Это не означает, что у партии нет экономической позиции.</p>
<p>Государство и религия: в текущем наборе {f['religion_total']} законов,
из них {f['religion_signed']} с ненулевым знаком. После исключения почти единогласных
голосований и повторных чтений у отдельной фракции остаётся ещё меньше.
Например, смена оценки одного закона в маленьком наборе может заметно сдвинуть
стрелку. Поэтому смотрим на её устойчивость, а не только на направление.</p>
<p>Безопасность: временное правило даёт плюс расширению полномочий армии и
силовых органов или ужесточению мер против террора, минус — сужению полномочий
или усилению гражданского контроля. Плюс здесь не означает «хорошо».
Например, продление чрезвычайного полномочия — плюс относительно его прекращения;
льгота военнослужащему без нового полномочия — ноль.
Спорная граница — гражданские санкции за уклонение: денежное взыскание призывным
органом отнесено к силовым мерам, а лишение налоговой льготы — к косвенным стимулам.
Владелец ещё не утвердил это правило как постоянное.</p>

<h2>Деньги</h2>
<p>Для правительства 37 взяты {f['ca37']} соглашений и приложений (CA37).
Для правительства 36 найдены в Wayback Machine {f['ca36']} PDF (CA36),
включая основные принципы правительства. Текст распознан со сканов — OCR;
например, неверно распознанная цифра может исказить сумму, поэтому найденная
машиной строка ещё требует проверки. Для CA36 используем бюджет
{'–'.join(map(str, f['budget_years']))}.</p>
<p>Сначала ищем денежное обещание, затем вручную решаем, какая бюджетная строка
ему соответствует. Такие разборы есть у РААМ и других партнёров.
Например, строка на развитие населённых пунктов может покрывать лишь часть обещания:
совпадение темы не доказывает совпадение суммы и получателя. План и факт сравниваем
в одном году с первоначальным бюджетом (§11). Наличие строки не доказывает выплату.</p>
<p>Ликуд и Еш Атид показаны также как «вторая сторона»: они подписывали соглашения
с партнёрами. Например, обещание РААМ остаётся обещанием партнёру, даже когда видно
в обзоре Еш Атида; его нельзя второй раз прибавить как независимое обещание.
Число исходных записей и число самостоятельных обещаний после удаления повторов различаются.</p>
<p>В учёте извлечённых обещаний деньги — у <b>{f['b_obs']}</b> (обещания соглашения сверены с бюджетом
по одному у <b>{f['b_rev']}</b>; денежных обещаний не найдено у {f['b_zero']};
без ручного разбора — {f['b_open']}). Это покрытие источников, не оценка партий (§7).</p>

<h2>Чего нет</h2>
<p>Новых голосований получить не удалось: доступ к источнику Кнессета закрывался
геоблоком. Поэтому используем сохранённый снимок от {esc(f['snapshot'])},
с окном {esc(f['window'][0])} — {esc(f['window'][1])} (правая граница не включена).
Например, голосование после этой границы не может изменить показанную стрелку,
пока не появится в данных. Зеркало Open Knesset не закрывает пробел:
его голосования обрываются 13.07.2021, хотя дата обновления файла может быть свежей (§9).</p>
<p>Мы не ставим общий балл и не ранжируем партии (§13).
Отсутствие данных — не оправдание и не обвинение: например, отсутствие голосов
Беннета не означает ни согласия, ни несогласия с законами этого Кнессета.</p>

<details><summary>Подробности для проверки расчёта</summary>
<p>В снимке {f['votes_rows']} записей и {f['votes_unique']} голосований.
«За» двигает акт в {f['carries']} записях, не определяет его судьбу в {f['none']},
останавливает в {f['inverts']}. Например, «за отклонение» нельзя считать поддержкой закона (§10).</p>
<p>Модели: {models}. Исходная проверка согласия: {f['attempted']} актов,
{f['pairs']} пар, {f['agree']} совпадений; альфа Криппендорфа {f['alpha']}
при первоначальном пороге {f['alpha_threshold']}. Это мера согласия оценщиков.
Стрелка <b>{verdict}</b>. Этот старый порог не следует путать с нынешней проверкой устойчивости:
даже устойчивый результат может опираться на общую ошибку моделей.</p>
</details>
</body></html>"""


def selftest() -> int:
    f = facts()
    page = build(f)
    assert 'content="noindex, nofollow"' in page, "§16: нет noindex"
    assert page.index("data-frame=short") < page.index("<h1"), "§17: рамка после заголовка"
    # Каждое число словаря обязано быть на странице — страница не вправе
    # выборочно молчать о замере.
    for k in ("alpha", "alpha_threshold", "pairs", "agree", "attempted",
              "carries", "none", "inverts", "b_obs", "b_rev", "b_zero", "b_open",
              "reread_total", "numeric_total", "opposite", "withdrawn"):
        assert str(f[k]) in page, f"на странице нет {k}={f[k]}"
    assert f["window"][1] in page, "граница среза не напечатана"
    # R8-F04: однозначные числа найдутся на странице где угодно — ищем фразу.
    assert (f"деньги — у <b>{f['b_obs']}</b> (обещания соглашения сверены с бюджетом\n"
            f"по одному у <b>{f['b_rev']}</b>") in page, "счёт канала денег не напечатан"
    assert f["b_open"] >= 0 and f["b_rev"] + f["b_zero"] + f["b_open"] == f["b_obs"], \
        "разбиение канала денег не сходится"
    from coverage_matrix import commitment_maps as _cm
    assert f["b_obs"] == len(_cm()), "счёт денег взят не из живых карт извлечения"
    # R19-F02 (M07): разобранные — независимым путём, по файлам карточек
    # разбора и числу их записей, а не через load_cards.
    from validate_cards import load_yaml_ish as _ly
    _rev = set()
    for _p in (ROOT / "cards").glob("*-gov*.yaml"):
        _c = _ly(_p)
        if _c.get("commitments"):
            _rev.add(int(str(_c["period_id"]).split("-")[0]))
    _money = _cm()
    assert f["b_rev"] == len(_rev & set(_money)), (f["b_rev"], sorted(_rev))
    assert f["b_zero"] == sum(1 for k, v in _money.items()
                              if k not in _rev and not v["commitments"]), f["b_zero"]
    # R8-F12: число моделей не зашито словом «Две» при другом составе
    import copy as _copy
    g3 = _copy.deepcopy(f)
    g3["models"] = {"a": "m1", "b": "m2", "c": "m3"}
    p3 = build(g3)
    assert "Две модели" not in p3 and "две модели" not in p3, "«две модели» при трёх в метаданных"
    assert all(m in p3 for m in ("m1", "m2", "m3")), "выведены не все модели"
    assert f["carries"] + f["none"] + f["inverts"] == f["votes_rows"], \
        "классы «за» не складываются в число записей"
    print(f"  OK: все замеры на странице; α={f['alpha']} при пороге "
          f"{f['alpha_threshold']}, окно до {f['window'][1]}")
    # Провокация: другой порог обязан менять вердикт на странице.
    g = dict(f, alpha_threshold=0.1, arrow_published=f["alpha"] >= 0.1)
    assert "публикуется" in build(g) and "НЕ публикуется" not in build(g), \
        "вердикт не следует за порогом — число на странице декоративно"
    h = dict(f, alpha_threshold=0.99, arrow_published=False, coverage_first=False)
    assert "НЕ публикуется" in build(h)
    print("  OK: вердикт о стрелке вычисляется из порога, не вписан")
    # Провокация: без объявления чтения владельцем — отказ, не пустой раздел.
    global OWNER_DECL
    real = OWNER_DECL
    OWNER_DECL = ROOT / "criteria" / "нет_такого.yaml"
    try:
        facts()
        print("  ПРОВАЛ: страница собралась без объявления")
        return 1
    except SystemExit:
        print("  OK: без объявления чтения владельцем страница не собирается")
    finally:
        OWNER_DECL = real
    # Mutation oracles: a changed source must change visible prose or refuse.
    g = dict(f, opposite=71, withdrawn=72, disputed=73, tiebreak_withdrawn=74,
             numeric_total=975, reread_total=976, ca36=81, ca37=82, personal=True)
    changed = build(g)
    for phrase in ("наоборот — 71", "снято 72 ненулевых", "Для 73 спорных",
                   "сняты 74 знаков", "976 акта", "975 с числовой",
                   "Wayback Machine 81 PDF", "взяты 82 соглашений",
                   "по личным голосам участников"):
        assert phrase in changed, f"число или способ чтения зашиты: {phrase}"
    assert "по фракции Ганца, в которой" not in changed
    from unittest.mock import patch
    real_read = Path.read_text
    broken = ROOT / "reviews/axis_reread_v39A.json"
    # Removing one reviewed act must not quietly lower the reported total.
    damaged = json.loads(real_read(broken))
    damaged.pop(next(iter(damaged)))
    with patch.object(Path, "read_text", lambda path, *a, **kw:
                      json.dumps(damaged) if path == broken else real_read(path, *a, **kw)):
        try:
            facts()
        except SystemExit:
            pass
        else:
            raise AssertionError("пропажа акта второго чтения не обнаружена")
    print("  OK: числа и personal меняют прозу; неполное второе чтение — отказ")
    assert "§13" in page and "§7" in page
    print("самопроверка render_method пройдена")
    return 0


def main() -> int:
    page = build(facts())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"методология -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
