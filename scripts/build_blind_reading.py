#!/usr/bin/env python3
"""Набор актов на ЧТЕНИЕ ВСЛЕПУЮ владельцем — чтобы у оракула появился ответ,
полученный не от классификатора.

ЗАЧЕМ. 12.08 механизм отказал оракулу направления: шесть дошедших актов, все
с ожидаемым ответом −1, и постоянный классификатор «−1 всегда» брал 6 из 6
(criteria/oracle_composition_2026-08-12.yaml, ORACLE_FITNESS). Чтобы прибор
стал прибором, нужны акты с ответом +1 и 0, известным НЕ от вендоров.

ПОЧЕМУ НЕ ВЗЯТЬ ИХ ИЗ ПРОГОНА. Соблазн — «где оба вендора единогласно
сказали +1». Это замкнутый круг: оракул тогда проверяет вендоров на актах,
которые вендоры сами и выбрали, и точность на нём высока по построению.
Ровно этот механизм произвёл «6 из 6», которое я подал как доказательство.

ГРАНИЦА, КОТОРУЮ ДЕРЖИТ ЭТОТ МОДУЛЬ. Он не читает НИ ОДНОГО файла с
вердиктами. Отбор — по свойствам текста и переписи, ответ — от человека.
Запрет проверяется исполнением: самопроверка отвергает собственный исходник,
если в нём появится обращение к direction_*.json. Отбор мой, ответ не мой —
это единственное, что здесь имеет значение.

ПЕРЕВОДА В СТРАНИЦЕ НЕТ, И ЭТО НАМЕРЕННО. Перевод сделал бы я, то есть
модель того же семейства, которое проверяется. Он протёк бы в ответ читателя
незаметно для нас обоих. Иврит идёт как есть; чем переводить — дело
читателя, и это вне моего влияния.

ОТБОР ОБЪЯВЛЕН ЗДЕСЬ, ДО ОТВЕТОВ:
  1. только акты пилота, у которых ЕСТЬ текст и structure_units > 0 —
     то есть те, что реально ДОХОДЯТ до классификации. Урок 2198907:
     подложенный акт, отсеянный конвейером, вычитается из прибора целиком;
  2. не из уже подложенных;
  3. длина текста не больше MAX_READ знаков — читать должно быть можно;
  4. не больше двух актов на группу чек-листа, чтобы набор не оказался
     шестью актами про суд.

    python3 scripts/build_blind_reading.py            # собрать страницу
    python3 scripts/build_blind_reading.py --selftest
"""
from __future__ import annotations

import html
import inspect
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import checklist_text, structure_units  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SELECTION = ROOT / "data" / "pilot_selection.json"
SCAN = ROOT / "data" / "bills_scan.json"
TEXTDIR = ROOT / "data" / "bill_texts"
OUT = ROOT / "report" / "blind_reading.html"
BATCH = ROOT / "criteria" / "blind_reading_batch_2026-08-12.json"

MAX_READ = 6000        # знаков: дальше чтение перестаёт быть чтением
PER_GROUP = 2          # не больше двух актов на группу чек-листа
WANT = 8               # размер набора


def pick(selected: list, oracle_bills: set, names: dict, groups: dict,
         basic: dict | None = None) -> list:
    """Отбор по объявленным правилам. Вердиктов не видит по построению.

    Пустая группа — не дефект: Основные законы попадают в пилот по своему
    статусу, а не по попаданию в лексикон, и группы у них законно нет. Так и
    подписывается, потому что прочерк читается как недоделка.
    """
    basic = basic or {}
    taken, per = [], {}
    for b in selected:
        if b in oracle_bills:
            continue
        p = TEXTDIR / f"{b}.txt"
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        if len(text) > MAX_READ or structure_units(text) == 0:
            continue
        fallback = "основной закон" if str(basic.get(b)) == "True" else "без группы"
        g = sorted(groups.get(b, {}) or {fallback: None})[0]
        if per.get(g, 0) >= PER_GROUP:
            continue
        per[g] = per.get(g, 0) + 1
        taken.append({"bill": b, "name": names.get(b, ""), "group": g,
                      "chars": len(text)})
        if len(taken) >= WANT:
            break
    return taken


def page(batch: list, checklist: str) -> str:
    e = html.escape
    head = f"""<!doctype html><html lang=ru><meta charset=utf-8>
<title>Чтение вслепую — знак направления</title><style>
body{{font:16px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
margin:0 auto;padding:24px;color:#1a1a1a}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:34px;border-top:1px solid #ddd;padding-top:16px}}
.he{{direction:rtl;unicode-bidi:isolate;background:#f7f7f5;padding:12px;
border-radius:6px;white-space:pre-wrap;font-size:15px}}
.note{{background:#fffbe6;border:1px solid #f0e0a0;padding:12px;border-radius:6px}}
.ans{{border:1px dashed #aaa;padding:10px;border-radius:6px;margin-top:10px}}
pre{{white-space:pre-wrap;font:13px/1.5 ui-monospace,Menlo,monospace;background:#f7f7f5;padding:12px;border-radius:6px}}
</style>
<h1>Чтение вслепую: {len(batch)} актов</h1>
<div class=note><b>Что от вас нужно.</b> Для каждого акта — один знак по оси
«сдержки исполнительной власти»: <b>−1</b> ослабляет, <b>0</b> не меняет,
<b>+1</b> усиливает. Если по тексту сказать нельзя — так и напишите:
«не могу сказать» — это законный ответ, он не считается промахом и нужен
не меньше остальных.
<br><br>
<b>Чего здесь намеренно нет.</b> Ответов моделей. Моего мнения. Перевода —
перевод сделал бы я, то есть та же модель, которую этот замер и проверяет;
он протёк бы в ваш ответ незаметно для нас обоих. Чем читать иврит — ваше
дело, и это вне моего влияния. Если пользовались переводчиком или искали акт
в открытых источниках, отметьте это: для замера важно, чем именно вы
пользовались.
<br><br>
<b>Куда это пойдёт.</b> Акты, где вы поставите <b>+1</b> или <b>0</b>,
станут подлогом оракула направления — он сейчас негоден, потому что все шесть
дошедших до него актов ждут ответа −1.</div>

<h2>Чек-лист (тот же, что видит модель)</h2>
<pre>{e(checklist)}</pre>
"""
    parts = [head]
    for i, a in enumerate(batch, 1):
        text = (TEXTDIR / f"{a['bill']}.txt").read_text(encoding="utf-8")
        parts.append(
            f"<h2>{i}. акт {a['bill']} · группа {e(a['group'])} · "
            f"{a['chars']} знаков</h2>\n"
            f"<div class=he>{e(a['name'])}</div>\n"
            f"<div class=he>{e(text)}</div>\n"
            f"<div class=ans>знак: −1 / 0 / +1 / не могу сказать &nbsp;·&nbsp; "
            f"пункт чек-листа: ______ &nbsp;·&nbsp; чем пользовались: ______</div>")
    parts.append("</html>")
    return "\n".join(parts)


def selftest() -> int:
    # ГЛАВНОЕ УТВЕРЖДЕНИЕ МОДУЛЯ: он не может видеть вердиктов. Проверяется
    # исполнением, а не обещанием в докстринге. Если кто-нибудь (я) решит
    # «удобнее взять кандидатов из прогона» — красное здесь, а не тихий круг.
    src = Path(__file__).read_text(encoding="utf-8")
    body = src.split("def selftest")[0]
    for forbidden in ("direction_pilot", "direction_v", "verdicts", "oracle\"]["):
        assert forbidden not in body, (
            f"в отборе появилось обращение к «{forbidden}»: кандидаты начали "
            "приходить от классификатора, который этим набором и проверяется")

    # Отбор: длинные и бесструктурные не проходят, подложенные исключены,
    # больше двух на группу не берётся.
    assert PER_GROUP == 2 and WANT == 8, "числа отбора объявлены в докстринге"
    assert "перевод" in page([], "").lower(), \
        "страница обязана называть отсутствие перевода: молчаливое отсутствие "\
        "читатель примет за недоделку и переведёт сам, не сказав"
    assert "не могу сказать" in page([], ""), \
        "отказ обязан быть предложен явно — иначе читатель угадывает (K5)"
    print(f"самопроверка build_blind_reading пройдена: "
          f"{inspect.getsource(selftest).count('assert ')} утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    sel = json.loads(SELECTION.read_text(encoding="utf-8"))
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    names = {m["id"]: m["name"] for m in scan["matched"]}
    groups = {m["id"]: m.get("groups") for m in scan["matched"]}
    basic = {m["id"]: m.get("basic_law") for m in scan["matched"]}
    batch = pick(sel["selected"], {o["bill"] for o in sel["oracle"]},
                 names, groups, basic)
    BATCH.write_text(json.dumps(
        {"rule": "criteria/oracle_composition_2026-08-12.yaml",
         "picked_by": "build_blind_reading.py, без доступа к вердиктам",
         "max_read": MAX_READ, "per_group": PER_GROUP, "want": WANT,
         "batch": batch}, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page(batch, checklist_text()), encoding="utf-8")
    print(f"отобрано {len(batch)} актов, групп {len({a['group'] for a in batch})}")
    for a in batch:
        print(f"   {a['bill']}  {a['group']:<28} {a['chars']:>5} знаков  {a['name'][:40]}")
    print(f"\n{OUT}\n{BATCH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
