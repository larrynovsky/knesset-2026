#!/usr/bin/env python3
"""Уверенность направления акта из двух чисел, а не из одного.

Правило объявлено ДО прогона: criteria/direction_confidence_2026-08-01.yaml.
Решение владельца 01.08.2026 (вариант В): согласие вендоров перестаёт быть
рубильником на весь канал и становится уровнем уверенности КАЖДОГО акта.

Почему двух. Разбор 01.08 (docs/explanation/direction_stall_2026-08-01.md)
нашёл два разных режима отказа, которые одно число смешивало:

    полнота извлечения — вендоры видят РАЗНЫЕ множества норм (6 против 0);
    чтение нормы       — на ОБЩИХ нормах дают противоположные знаки.

Одно число не говорит, что чинить, и не даёт читателю названной причины,
которой требует §6.

СОПОСТАВЛЕНИЕ ЦИТАТ — место, которое я уже сломал однажды. Первая редакция
разбора сравнивала СЫРЫЕ ивритские строки по 40-знаковому префиксу и выдала
ложный ноль конфликтов: у одного вендора цитата начинается с «(ב) », у
другого нет. Здесь нормализация `norm_he` (та же, что у цитат карточки) и
сравнение по ВХОЖДЕНИЮ, потому что вендоры режут цитату по разной длине.
Оба случая — и обманувший, и заведомо чужой — стоят в самопроверке.

    python3 scripts/direction_confidence.py --selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import n_asserts, norm_he   # noqa: E402

LEVELS = ("high", "medium", "low", "none")


def pair_norms(a: list[dict], o: list[dict]) -> list[tuple[dict, dict]]:
    """Пары «одна и та же норма у двух вендоров». Вхождение, не равенство.

    ЭТО СОПОСТАВЛЕНИЕ, А НЕ ПРОИЗВЕДЕНИЕ. Первая редакция брала все подходящие
    пары подряд, и одна норма пáрилась с несколькими: на живых данных 01.08
    это дало «перекрытие» 1.33, 1.50 и 2.00 — при том что Жаккар по построению
    не больше единицы. Самопроверка не поймала: все её случаи были один к
    одному. Каждая норма используется не более раза с обеих сторон.
    """
    used_o: set[int] = set()
    out = []
    for x in a:
        nx = norm_he(x.get("quote_he") or "")
        if not nx:
            continue
        for j, y in enumerate(o):
            if j in used_o:
                continue
            ny = norm_he(y.get("quote_he") or "")
            if ny and (nx in ny or ny in nx):
                used_o.add(j)
                out.append((x, y))
                break
    return out


def measure(a: list[dict], o: list[dict]) -> dict:
    """Два числа: перекрытие множеств норм и согласие на общих."""
    pairs = pair_norms(a, o)
    matched_a = {id(x) for x, _ in pairs}
    matched_o = {id(y) for _, y in pairs}
    union = len(a) + len(o) - len(pairs)
    overlap = len(pairs) / union if union else 0.0
    agree = sum(1 for x, y in pairs if x.get("sign") == y.get("sign"))
    reading = agree / len(pairs) if pairs else 0.0
    return {"n_a": len(a), "n_o": len(o), "shared": len(pairs),
            "overlap": overlap, "reading": reading,
            "unmatched_a": len(a) - len(matched_a),
            "unmatched_o": len(o) - len(matched_o)}


def verdict(a: list[dict], o: list[dict],
            overall: tuple | None = None) -> tuple[str, str, dict]:
    """(уверенность, названная причина, числа). Причина обязательна — §6.

    ПОПРАВКА 13.08 (criteria-revision в шапке правила). Редакция 01.08 сняла
    прежний критерий «согласие по общему знаку» и заменила его двумя числами
    по нормам. Замена была верной по мотиву и потеряла гарантию: вендоры
    могут сойтись на 75% общих норм и свернуть акт в ПРОТИВОПОЛОЖНЫЕ общие
    знаки. На живых данных таких актов два, оба числились medium — то есть
    «уверенно классифицированными» при взаимоисключающих выводах.

    Нашёл не механизм: второй агент, читая прибор. Здесь это и чинится —
    расхождение по общему знаку опускает уровень до low с НАЗВАННОЙ
    причиной, а не выбрасывает акт молча (§6, §7: молчание неотличимо от
    отсутствия предмета).

    `overall=None` означает «знаки не предъявлены» и НЕ означает «согласны»:
    в этом случае поправка не применяется и уровень считается как прежде.
    """
    m = measure(a, o)
    if not a and not o:
        return "none", "ни один вендор не выделил норм в этом акте", m
    if not a or not o:
        return "low", "один из вендоров не нашёл ни одной нормы", m
    clash = (overall is not None and len(set(overall)) > 1
             and all(s is not None for s in overall))
    if m["overlap"] >= 0.60 and m["reading"] == 1.0 and not clash:
        return "high", "вендоры увидели одни нормы и прочли их одинаково", m
    if m["overlap"] >= 0.30 and m["reading"] >= 0.75 and not clash:
        return "medium", "вендоры в основном согласны: перекрытие " \
                         f"{m['overlap']:.2f}, чтение {m['reading']:.2f}", m
    if clash:
        return "low", ("вендоры разошлись в общем знаке акта: "
                       + " против ".join(str(s) for s in overall)), m
    if m["overlap"] < 0.30:
        return "low", "вендоры извлекли разные множества норм", m
    return "low", "вендоры разошлись в чтении общих норм", m


def channel_escape(verdicts: list[str]) -> tuple[bool, str]:
    """Порог на канал целиком, объявленный ДО прогона: больше трети low/none."""
    if not verdicts:
        return True, "актов нет — направление не измерено ни разу"
    weak = sum(1 for v in verdicts if v in ("low", "none"))
    share = weak / len(verdicts)
    if share > 1 / 3:
        return True, (f"{weak} из {len(verdicts)} актов ({share:.0%}) несут "
                      "low или none — канал А не даёт направления")
    return False, f"слабых {weak} из {len(verdicts)} ({share:.0%}), порог 33% не пройден"


def report(src: Path, pair: tuple = ("anthropic", "openai")) -> int:
    """Применить правило к прогону. До 12.08 этого не было ВООБЩЕ.

    Числа «high 5 · medium 14 · low 33 · none 2» и вывод «канал А не даёт
    направления» были получены разовым кодом в сессии и нигде не жили. То
    есть вердикт, останавливающий целый канал, не воспроизводился из репо
    (§14) и не имел механизма (§20). Модуль при этом молча возвращал ноль,
    если его звали без --selftest, — вид работающего инструмента.

    Пара объявлена: правило уверенности касается (anthropic, openai). Третий
    вендор ждёт своего правила и здесь не считается — иначе замер поменяет
    прибор задним числом.
    """
    import collections
    import json
    d = json.loads(src.read_text(encoding="utf-8"))
    levels, reasons, skipped, no_overall = [], collections.Counter(), 0, 0
    for r in d["rows"]:
        vs = r.get("verdicts", {})
        if any(vs.get(v, {}).get("status") != "ok" for v in pair):
            skipped += 1
            continue
        # Отсутствие блока overall — это «знак не предъявлен», а не «знаки
        # совпали». Считаем такие строки отдельно и печатаем: иначе поправка
        # 13.08 молча не применится к части корпуса, и мы этого не увидим.
        signs = tuple(vs[v].get("overall", {}).get("sign") for v in pair)
        no_overall += any(s is None for s in signs)
        lvl, why, _ = verdict(*(vs[v].get("norms", []) for v in pair),
                              overall=signs)
        levels.append(lvl)
        reasons[(lvl, why.split(":")[0])] += 1
    dist = collections.Counter(levels)
    print(f"источник: {src}   пара: {pair[0]} · {pair[1]}")
    print(f"актов с ответом обоих: {len(levels)}, "
          f"вне замера {skipped} (кто-то из пары не ответил)")
    print("  " + " · ".join(f"{k} {dist.get(k, 0)}" for k in LEVELS))
    for (lvl, why), n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"   {n:>3}  {lvl:<7} {why}")
    if no_overall:
        print(f"   (у {no_overall} актов общий знак не предъявлен хотя бы "
              "одним вендором — поправка 13.08 к ним не применялась)")
    esc, msg = channel_escape(levels)
    print(("\n⚠ ПОРОГ ПРОЙДЕН: " if esc else "\nпорог не пройден: ") + msg)
    print("Порог объявлен ДО прогона: criteria/direction_confidence_2026-08-01.yaml")
    return 0


def _n(q, s=0):
    return {"quote_he": q, "sign": s}


def selftest() -> int:
    # Сопоставление, случай 1: разная длина и ведущий маркер пункта. Это тот
    # случай, на котором разбор 01.08 дал ложный ноль конфликтов, — но чинит
    # его ВХОЖДЕНИЕ, а не нормализация: на сырых строках он тоже проходит.
    a = [_n("פרסום מכרז לאיוש משרה בשירות המדינה יבוצע בדרך של מכרז פומבי", 0)]
    o = [_n("(ב) פרסום מכרז לאיוש משרה בשירות המדינה יבוצע בדרך של מכרז פומבי, תוך", 1)]
    assert len(pair_norms(a, o)) == 1, \
        "цитата с «(ב) » обязана сопоставиться с цитатой без неё"

    # Случай 2: РАЗНАЯ ПУНКТУАЦИЯ внутри. Вот ради чего нужна norm_he, и без
    # этого случая её присутствие ничем не оправдано. Дефис-минус против
    # ивритского макафа плюс кавычка в начале — вхождение на сырых строках
    # даёт False, на нормализованных True. Первая редакция самопроверки этого
    # случая не имела: снятие norm_he её НЕ роняло, то есть проверка
    # стерегла норму, которую не проверяла.
    a2 = [_n("האמור בסעיפים קטנים (א) ו-(ב) יחול", 0)]
    o2 = [_n('"האמור בסעיפים קטנים (א) ו־(ב) יחול, בשינויים המחויבים', 0)]
    assert len(pair_norms(a2, o2)) == 1, \
        "одна норма с разной пунктуацией обязана сопоставиться: без " \
        "нормализации вендоры с «ו-» и «ו־» выглядят как разные нормы"
    # Случай 3: ОДНА цитата одного вендора подходит к НЕСКОЛЬКИМ у другого.
    # Первая редакция брала все пары и выдавала перекрытие 1.33, 1.50, 2.00 на
    # живых данных — величину, которой у Жаккара не бывает. Проверка этого не
    # ловила: все её случаи были один к одному, то есть она стерегла формулу,
    # ни разу не проверив её область значений.
    many = [_n("אאאבבבגגג", 1)]
    to = [_n("אאא", 1), _n("בבב", 1), _n("גגג", 1)]
    assert len(pair_norms(many, to)) == 1, \
        "одна норма не имеет права дать три пары — это произведение, не сопоставление"
    assert measure(many, to)["overlap"] <= 1.0, \
        "перекрытие больше единицы невозможно по построению Жаккара"
    for A, O in ((many, to), (to, many), (a, o), (a2, o2)):
        assert 0.0 <= measure(A, O)["overlap"] <= 1.0, "перекрытие вне [0,1]"
        assert 0.0 <= measure(A, O)["reading"] <= 1.0, "чтение вне [0,1]"

    # И заведомо чужие не должны слипаться.
    assert not pair_norms(
        [_n("היועץ המשפטי לממשלה נושא באחריות למילוי תפקידו בפני הממשלה")],
        [_n("פרסום מכרז לאיוש משרה בשירות המדינה")]), \
        "разные нормы не имеют права стать одной парой"

    # Два режима отказа обязаны давать РАЗНЫЕ причины, а не общий «low».
    v_recall, r_recall, _ = verdict([_n("אאא", 1), _n("בבב", -1), _n("גגג", 0)],
                                    [_n("דדד", 1)])
    assert v_recall == "low" and "разные множества" in r_recall, (v_recall, r_recall)
    v_read, r_read, _ = verdict([_n("אאא", 1), _n("בבב", -1)],
                                [_n("אאא", -1), _n("בבב", 1)])
    assert v_read == "low" and "чтении" in r_read, (v_read, r_read)
    assert r_recall != r_read, \
        "полнота и чтение обязаны называться разными причинами: иначе §6 " \
        "получает уровень без причины, а мы не знаем, что чинить"

    # --- ПОПРАВКА 13.08: расхождение по ОБЩЕМУ знаку акта. Живой случай,
    # ради которого она написана: акт 2203822 — перекрытие 0.50, чтение 0.75,
    # то есть medium по редакции 01.08, при знаках −1 и +1. «Уверенно
    # классифицирован» при взаимоисключающих выводах.
    # Четыре общих нормы, три знака совпали: чтение 0.75, перекрытие 1.00 —
    # ровно нижняя граница medium. Первая редакция этого случая брала пять
    # норм и давала high: проверка стерегла бы не тот уровень.
    agree_norms = ([_n("אאא", 1), _n("בבב", -1), _n("גגג", 1), _n("דדד", 1)],
                   [_n("אאא", 1), _n("בבב", -1), _n("גגג", 1), _n("דדד", -1)])
    base, base_why, _ = verdict(*agree_norms)
    assert base == "medium", f"случай-основание перестал быть medium: {base}"
    lo, lo_why, _ = verdict(*agree_norms, overall=(-1, 1))
    assert lo == "low", "расхождение по общему знаку обязано опускать уровень"
    assert "общем знаке" in lo_why, \
        "причина обязана называть ИМЕННО расхождение знаков, а не общую " \
        "формулу: §6 требует названной причины, чтобы знать, что чинить"
    same, same_why, _ = verdict(*agree_norms, overall=(1, 1))
    assert (same, same_why) == (base, base_why), \
        "совпадающие знаки не имеют права менять вердикт"
    none_, none_why, _ = verdict(*agree_norms, overall=None)
    assert (none_, none_why) == (base, base_why), \
        "отсутствие знаков — не расхождение: overall=None означает «не " \
        "предъявлено», и молчаливое понижение спрятало бы нехватку данных " \
        "внутри содержательной причины"
    half, _, _ = verdict(*agree_norms, overall=(1, None))
    assert half == base, \
        "один предъявленный знак против непредъявленного — не расхождение"

    # Пустой вендор — не «согласие», а названный отказ.
    assert verdict([_n("אאא", 1)], [])[0] == "low"
    assert verdict([], [])[0] == "none"
    # Полное совпадение — high; расхождение в одной норме из двух — не high.
    assert verdict([_n("אאא", 1), _n("בבב", 1)],
                   [_n("אאא", 1), _n("בבב", 1)])[0] == "high"
    assert verdict([_n("אאא", 1), _n("בבב", 1)],
                   [_n("אאא", 1), _n("בבב", -1)])[0] != "high"

    # Порог на канал: объявлен до прогона и обязан срабатывать строго выше трети.
    assert channel_escape(["high"] * 7 + ["low"] * 3)[0] is False
    assert channel_escape(["high"] * 6 + ["low"] * 4)[0] is True
    assert channel_escape([])[0] is True, "нет актов — не «всё хорошо», а отказ"

    print(f"самопроверка direction_confidence пройдена: {n_asserts(selftest)} утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    # Молчаливый ноль без аргументов — то самое «выглядит рабочим». Теперь
    # звать без источника нельзя: инструмент говорит, чего от него хотят.
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print("нужен путь к прогону, например:\n"
              "  python3 scripts/direction_confidence.py data/direction_v2.json\n"
              "  python3 scripts/direction_confidence.py --selftest")
        return 2
    return report(Path(args[0]))


if __name__ == "__main__":
    raise SystemExit(main())
