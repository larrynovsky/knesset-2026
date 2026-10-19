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

import collections
import json
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
    money_rows = "".join(
        f"<tr><td>{fid}</td><td>{v['candidates']}</td><td>{v['commitments']}</td>"
        f"<td>{v['unresolved']}</td></tr>" for fid, v in sorted(f["money"].items()))
    return f"""<!doctype html>
<html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Как мы считаем — 25-й Кнессет</title>
<style>{css_from_mockup()}</style></head><body>
<nav class=crumbs><a href="index.html">Все фракции</a> · Как мы считаем</nav>
{SHORT_FRAME}
<h1>Как мы считаем</h1>
<p class=lead>Эта страница — для тех, кто хочет проверить. Формулировки
сухие, потому что спорить можно только с точным. Каждое число здесь
получено тем же кодом, что и замер, из файлов репозитория; руками сюда
ничего не вписано.</p>

<h2>Откуда данные и до какого дня</h2>
<p>Поимённые голосования 25-го Кнессета, источник
<code>knesset.gov.il/OdataV4/ParliamentInfo</code> (§9). Снимок
{esc(f['snapshot'])}, окно выгрузки {esc(f['window'][0])} — <b>{esc(f['window'][1])}</b>.
О том, что Кнессет делал после {esc(f['window'][1])}, документ не говорит
ничего. В снимке {f['votes_rows']} записей, {f['votes_unique']} разных
голосований, {f['acts']} актов темы «правовое государство».</p>

<h2>Три источника поступков и кого они видят</h2>
<p>Фракций в сборке: {f['lines']}. Голосования наблюдаемы у
<b>{f['a_obs']}</b>, деньги — у <b>{f['b_obs']}</b> (обещания соглашения сверены с бюджетом
по одному у <b>{f['b_rev']}</b>, сводного вывода нет; денежных обещаний в
соглашении не найдено у <b>{f['b_zero']}</b>; обещания извлечены, но не
разобраны у <b>{f['b_open']}</b>), должности — у
<b>{f['c_obs']}</b>. Молчание документа о деньгах или должностях партии —
свойство измерения, а не партии (§7): его нельзя читать ни как «чистая»,
ни как обвинение.</p>

<h2>Что такое «за»</h2>
<p>В Кнессете голосуют не «за закон», а за конкретное предложение, и у
каждого голосования записано, что означает «за» именно в нём (§10).
Из {f['votes_rows']} записей снимка «за» двигает сам акт в
<b>{f['carries']}</b>; в <b>{f['none']}</b> «за» акта не касается —
{f['reservations']} из них оговорки, поправки, которые обычно вносит
противник закона; в <b>{f['inverts']}</b> «за» акт останавливает.
Две трети голосований к судьбе закона отношения не имеют или имеют
обратное — поэтому «голосовала за N раз» в документе не встречается.</p>

<h2>Направление акта: что измерили и почему стрелки нет</h2>
<p>Модели ({models} — так записано в метаданных прогона; какие две
оценки образуют пары, эта страница пока не разбирает) независимо читали акты по кодбуку {esc(str(f['codebook']))}
и ставили метку «ослабляет / не касается / усиливает» сдержки. Прогон:
{f['attempted']} актов, {f['pairs']} пар с числовой меткой у обеих,
совпадений {f['agree']}. Альфа Криппендорфа <b>{f['alpha']}</b> при пороге
<b>{f['alpha_threshold']}</b>, объявленном до прогона (уверенная стрелка —
от {f['alpha_good']}, минимум актов на стрелку — {f['min_acts']}).
Стрелка <b>{verdict}</b>. Число есть, в таблицу оно не выносится
нарочно: колонка с числом превращает документ в рейтинг (§13).</p>

<h2>Чьё суждение о направлении</h2>
<p>Свод запрещает документу вердикт «ослабляла» — держится факт: акт,
дата, номер голосования, что означало «за». Суждение о том, допустим ли
акт, принадлежит владельцу. Оно снимается по правилу, записанному до
показа (<code>{esc(OWNER_DECL.name)}</code>): {f['owner_size']} актов,
отобранных механически, читаются без колонок «кто как голосовал»; шкала
пометки — {esc(f['owner_scale'])}; если все пометки одинаковы, результат
недействителен. Пересказы актов пишет автор документа, иврит рядом —
чтобы их можно было оспорить. Порога «сколько актов достаточно» в
документе нет.</p>

<h2>Деньги: что считается сопоставлением</h2>
<p>Обязательство из коалиционного соглашения сопоставляется с бюджетной
строкой человеком, по правилу <code>criteria/budget_mapping.yaml</code>.
Кандидат ≠ обязательство ≠ принятое сопоставление; отказ — не решение.
Это свойство канала, а не партии (§7); в карточку партии базовая ставка
не входит.</p>
<div class="table-scroll" tabindex="0" role="region" aria-label="Сопоставление обязательств"><table><thead><tr><th scope=col>фракция</th><th scope=col>кандидатов</th>
<th scope=col>обязательств</th><th scope=col>ждут решения</th></tr></thead>
<tbody>{money_rows}</tbody></table></div>

<h2>Чего документ не делает</h2>
<p>Не ставит балл и не ранжирует (§13). Не переносит статистику одних
партий на другие (§7). Не утверждает направления там, где измеритель не
прошёл свой порог. Не говорит о сентябре–октябре 2026. Исправления
публикуются журналом, а не тихой заменой (§15).</p>
</body></html>"""


def selftest() -> int:
    f = facts()
    page = build(f)
    assert 'content="noindex, nofollow"' in page, "§16: нет noindex"
    assert page.index("data-frame=short") < page.index("<h1"), "§17: рамка после заголовка"
    # Каждое число словаря обязано быть на странице — страница не вправе
    # выборочно молчать о замере.
    for k in ("alpha", "alpha_threshold", "pairs", "agree", "attempted",
              "carries", "none", "inverts", "a_obs", "b_obs", "b_rev", "b_zero", "b_open", "c_obs", "lines"):
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
    for _p in (ROOT / "cards").glob("*-gov37.yaml"):
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
    assert "какие две\nоценки образуют пары, эта страница пока не разбирает" in p3, \
        "оговорка о неизвестности пар пропала или изменила смысл"
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
