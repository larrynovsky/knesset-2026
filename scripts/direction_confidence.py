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

import json
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
    if m["overlap"] >= 0.60 and m["reading"] == 1.0:
        base = "high", "вендоры увидели одни нормы и прочли их одинаково"
    elif m["overlap"] >= 0.30 and m["reading"] >= 0.75:
        base = "medium", ("вендоры в основном согласны: перекрытие "
                          f"{m['overlap']:.2f}, чтение {m['reading']:.2f}")
    elif m["overlap"] < 0.30:
        return "low", "вендоры извлекли разные множества норм", m
    else:
        return "low", "вендоры разошлись в чтении общих норм", m

    # Поправка применяется ТОЛЬКО к high|medium — так она и объявлена
    # (applies_to в criteria). Первая редакция кода ставила проверку раньше
    # порогов и переклеймила три уже слабых акта: причина «разошлись в знаке»
    # вытеснила «извлекли разные множества норм». Вытеснила худшим образом —
    # менее действенной причиной: сойтись в направлении, не увидев одних
    # норм, вендоры не могли в принципе, и чинить надо извлечение.
    # Расхождение кода с собственным объявлением поймал прогон, а не я.
    if (overall is not None and len(set(overall)) > 1
            and all(s is not None for s in overall)):
        return "low", ("вендоры разошлись в общем знаке акта: "
                       + " против ".join(str(s) for s in overall)), m
    return base[0], base[1], m


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
    # Уже слабый акт поправка НЕ переклеймляет: причина «разные множества»
    # действеннее и первичнее. Без этого случая код разошёлся бы с полем
    # applies_to объявления, а поймал бы это только прогон — как 13.08.
    weak_clash, weak_why, _ = verdict([_n("אאא", 1), _n("בבב", -1), _n("גגג", 0)],
                                      [_n("דדד", 1)], overall=(-1, 1))
    assert (weak_clash, weak_why) == (v_recall, r_recall), \
        "поправка объявлена для high|medium и не имеет права вытеснять " \
        "причину у акта, который слаб по извлечению: сойтись в направлении, " \
        "не увидев одних норм, вендоры не могли в принципе"

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


    # ── СТРЕЛКА: по одной провокации на каждую часть объявленного правила ──
    R = {"drop_below": 0.025, "min_acts": 20,
         "acceptable": 0.800, "tentative": 0.667}
    # очистка: порог строгий, 2.4% выбрасывается, 2.6% остаётся
    assert lopsided(976, 24, R["drop_below"]) is True
    assert lopsided(974, 26, R["drop_below"]) is False
    assert lopsided(0, 0, R["drop_below"]) is True, \
        "акт без голосов обязан выпадать, а не делиться на ноль"
    # альфа: полное согласие, полное несогласие, одна категория у всех
    assert alpha([(1, 1), (-1, -1), (1, 1), (-1, -1)]) == 1.0
    assert alpha([(1, -1), (-1, 1), (1, -1), (-1, 1)]) < 0.0
    assert alpha([(1, 1), (1, 1)]) == 1.0, \
        "все судили одинаково — это согласие, а не деление на ноль"
    assert alpha([]) == 0.0, "пусто — не согласие"
    # Уилсон: ничего не известно ≠ ровно половина
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(10, 20)
    assert lo < 0.5 < hi, "десять из двадцати обязаны накрывать половину"
    lo, hi = wilson(19, 20)
    assert lo > 0.5, "девятнадцать из двадцати половину накрывать не должны"
    # стрелка: минимум актов, оба направления, однозначные случаи
    assert arrow(10, 19, R["min_acts"]) == "miss", \
        "меньше объявленного минимума — «не дошли», а не «ничего не делала»"
    assert arrow(10, 20, R["min_acts"]) == "both"
    assert arrow(19, 20, R["min_acts"]) == "down"
    assert arrow(1, 20, R["min_acts"]) == "up"
    # уровень: охват ниже половины опускает до низшего при любом согласии
    assert level(0.95, 0.80, R) == "high"
    assert level(0.95, 0.49, R) == "very_low", \
        "согласие вендоров не имеет права купить уверенность при пустом охвате"
    assert level(0.70, 0.90, R) == "moderate"
    assert level(0.10, 0.90, R) == "low"
    # формулировка: шаблон выбирает уровень, и слова канона не теряются
    assert "ослабляла" in say("high", "down", "X", 20, 30, "")
    assert "вероятно" in say("moderate", "up", "X", 20, 30, "")
    assert say("very_low", "miss", "X", 0, 30, "актов меньше двадцати") \
        == "сказать нечего: актов меньше двадцати"
    for lvl in GRADE:
        assert lvl in SAY, f"уровень {lvl} без шаблона"
    # правило читается из объявленного файла, а не из констант кода
    live = arrow_rule()
    assert live == R, f"код и объявление разошлись: {live} против {R}"


    # ── СМЫСЛ «ЗА»: отказ громче умолчания ────────────────────────────────
    T = {"להעביר": {"sign": "carries"}, "לדחות": {"sign": "inverts"},
         "לקבל את ההסתייגות": {"sign": "none"}}
    assert sign_of("להעביר", T) == "carries"
    assert sign_of(" лдоcss ".replace("лдоcss", "לדחות"), T) == "inverts", \
        "описание обязано сопоставляться без краевых пробелов"
    try:
        sign_of("чего-то такого в таблице нет", T)
        raise AssertionError("неизвестное описание опции проглочено умолчанием")
    except SystemExit as e:
        assert "§10" in str(e), "отказ не называет правило, по которому отказал"
    # произведение трёх множителей: знак акта × смысл «за» × позиция
    assert faction_move(1, "carries", "for") == 1
    assert faction_move(1, "carries", "against") == -1
    assert faction_move(1, "inverts", "for") == -1
    assert faction_move(-1, "inverts", "against") == -1
    assert faction_move(1, "none", "for") is None, \
        "опция без знака обязана давать None, а не единицу"
    assert faction_move(1, "carries", "abstain") is None
    assert faction_move(0, "carries", "for") is None, \
        "акт без направления не двигает ось ни в какую сторону"

    # ── ПОЗИЦИЯ ФРАКЦИИ И СБОРКА ──────────────────────────────────────────
    assert faction_position({"for": 8, "against": 0}, 0.5) == "for"
    assert faction_position({"for": 0, "against": 5}, 0.5) == "against"
    assert faction_position({"for": 5, "against": 3}, 0.5) is None, \
        "раскол 5:3 — индекс Райса 0.25, одной позиции у фракции нет"
    assert faction_position({"for": 7, "against": 1}, 0.5) == "for", \
        "7:1 — индекс 0.75, это позиция"
    assert faction_position({"abstain": 9, "absent": 2}, 0.5) is None, \
        "воздержались и отсутствовали — это не позиция, а её отсутствие"
    assert rice(4, 4) == 0.0 and rice(8, 0) == 1.0

    TBL = {"ЗА": {"sign": "carries"}, "ОГ": {"sign": "none"}}
    RB = {"drop_below": 0.025, "min_acts": 2, "acceptable": 0.8,
          "tentative": 0.667, "split_below": 0.5}

    def v(vid, bid, desc, fac):
        return {"vote_id": vid, "bill_id": bid, "for_option_desc": desc,
                "by_faction": fac}

    # один акт, два голосования в одну сторону — ОДИН ход, а не два
    rows = [v(1, 100, "ЗА", {"A": {"for": 9, "against": 0},
                             "B": {"for": 0, "against": 9}}),
            v(2, 100, "ЗА", {"A": {"for": 9, "against": 0},
                             "B": {"for": 0, "against": 9}}),
            v(3, 200, "ЗА", {"A": {"for": 9, "against": 0},
                             "B": {"for": 0, "against": 9}})]
    out, theme, st = compose(rows, {100: 1, 200: 1}, TBL, RB)
    assert out["A"]["acts"] == 2, \
        f"акты сложились по голосованиям, а не по актам: {out['A']}"
    assert out["A"]["up"] == 2 and out["A"]["down"] == 0
    assert out["B"]["down"] == 2, "фракция против усиливающего акта двигает вниз"
    assert theme == {100, 200}

    # противоречие ВНУТРИ акта выпадает, а не становится «и туда и обратно»
    # В палате обязаны быть обе стороны, иначе акт выпадет по единогласию
    # ДО проверки противоречия — и провокация проверила бы не то.
    rows2 = [v(1, 100, "ЗА", {"A": {"for": 9, "against": 0},
                              "Z": {"for": 0, "against": 9}}),
             v(2, 100, "ЗА", {"A": {"for": 0, "against": 9},
                              "Z": {"for": 9, "against": 0}})]
    out2, _, _ = compose(rows2, {100: 1}, TBL, RB)
    assert out2["A"]["acts"] == 0 and out2["A"]["mixed_acts"] == 1, \
        "неразрешённость внутри акта выдана за позицию фракции"

    # опция без знака не даёт хода
    out3, _, _ = compose([v(1, 100, "ОГ", {"A": {"for": 9, "against": 0},
                                           "Z": {"for": 0, "against": 9}})],
                         {100: 1}, TBL, RB)
    assert not out3, "голосование по оговорке дало ход — §10 обойдён"

    # единогласный акт выбрасывается ДО того, как посмотрели направление
    out4, _, st4 = compose([v(1, 100, "ЗА", {"A": {"for": 119, "against": 1}})],
                           {100: 1}, TBL, RB)
    assert not out4 and st4.get("выброшено по единогласию") == 1

    # клетка: охват ниже половины опускает уровень при любом согласии
    c = cell({"down": 20, "up": 0, "acts": 20, "mixed_acts": 0}, 25, 0.95, "X", RB)
    assert c["arrow"] == "down" and c["level"] == "high", c
    c2 = cell({"down": 20, "up": 0, "acts": 20, "mixed_acts": 0}, 1000, 0.95, "X", RB)
    assert c2["level"] == "very_low", "охват 2% не имеет права быть high"
    c3 = cell({"down": 1, "up": 0, "acts": 1, "mixed_acts": 0}, 4, 0.95, "X", RB)
    assert c3["arrow"] == "miss" and "меньше 2" in c3["text"], c3
    c4 = cell({"down": 10, "up": 10, "acts": 20, "mixed_acts": 0}, 25, 0.95, "X", RB)
    assert c4["arrow"] == "both", c4
    # МАЛОЕ n ДАЁТ «И ТУДА И ОБРАТНО», И ЭТО ПРАВИЛЬНЫЙ ОТВЕТ, А НЕ ДЕФЕКТ:
    # три акта в одну сторону не отличимы от случайности — интервал Уилсона
    # на 3 из 3 накрывает половину (нижняя граница 0.44). Утверждать «фракция
    # ослабляла» на трёх актах значит выдать шум за поведение. Поэтому в
    # объявленном правиле стоит минимум 20 актов, а здесь RB["min_acts"] = 2
    # нарочно занижен, чтобы провокации не упирались в него.
    c5 = cell({"down": 3, "up": 0, "acts": 3, "mixed_acts": 0}, 4, 0.95, "X", RB)
    assert c5["arrow"] == "both", \
        "три акта в одну сторону выданы за направление — это шум, не поведение"

    # ── ОТКАЗ ПО СОГЛАСИЮ (falsification.согласие_ниже_порога) ────────────
    # Правило объявило не «оговорку при низком согласии», а «стрелка не
    # публикуется вовсе». До 07.10 код публиковал знак с формулировкой «мы в
    # этом не уверены» — это другое обещание, и читателю оно даёт стрелку там,
    # где правило её запретило. Расхождение нашёл Кодекс в состязательном
    # ревью, проверено здесь своим входом.
    E20 = {"down": 20, "up": 0, "acts": 20, "mixed_acts": 0}
    c6 = cell(E20, 20, 0.10, "X", RB)
    assert c6["arrow"] == "miss", "альфа 0.10 опубликовала стрелку"
    assert c6["level"] == "very_low" and "согласие" in c6["text"], c6
    c7 = cell(E20, 20, RB["tentative"] - 0.001, "X", RB)
    assert c7["arrow"] == "miss", "порог согласия нестрогий — чуть ниже прошло"
    c8 = cell(E20, 20, RB["tentative"], "X", RB)
    assert c8["arrow"] == "down", \
        "ровно на объявленном пороге стрелка обязана публиковаться"

    # §6: у низшего уровня причина НАЗВАНА. «сказать нечего: » без причины —
    # это отсутствие причины, выданное за причину.
    c9 = cell(E20, 1000, 0.95, "X", RB)
    assert c9["level"] == "very_low" and "охват" in c9["text"], c9
    assert not c9["text"].rstrip().endswith(":"), \
        f"причина пуста там, где правило требует её назвать: {c9['text']!r}"

    # ── ОГОВОРКА ТЕМЫ ПРИ СТРЕЛКЕ (not_transferred.тема) ─────────────────
    for lvl in ("high", "moderate", "low"):
        assert THEME_CAVEAT in say(lvl, "down", "X", 20, 30, ""), \
            f"уровень {lvl} утверждает направление без оговорки темы"
    assert THEME_CAVEAT in ARROW_CRIT.read_text(encoding="utf-8"), \
        "копия оговорки в коде разошлась с объявлением — дом правила один"

    # ── §10 ПРОВЕРЯЕТСЯ ДО ОТСЕВОВ ───────────────────────────────────────
    # Неизвестная опция обязана останавливать стрелку всегда. Раньше её
    # проверку обходили две ветки: единогласие и акт без направления.
    for rows_x, why_x in (
            ([v(1, 100, "чего-то такого в таблице нет",
                {"A": {"for": 119, "against": 1}})], "единогласие"),
            ([v(1, 100, "чего-то такого в таблице нет",
                {"A": {"for": 60, "against": 0}, "Z": {"for": 0, "against": 60}})],
             "акт без направления")):
        try:
            compose(rows_x, {}, TBL, RB)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"неизвестная опция проскочила через {why_x}")
    print(f"самопроверка direction_confidence пройдена: {n_asserts(selftest)} утверждений")
    return 0




# ── СМЫСЛ «ЗА» (§10): закрытая таблица, а не догадка ──────────────────────
SIGN_DIR = Path(__file__).resolve().parent.parent / "docs" / "reference"
SIGN_KINDS = ("carries", "inverts", "none")


def sign_table(path: Path | None = None) -> dict:
    """Таблица смысла «за»: описание опции → одно из трёх значений.

    Файл ГЕНЕРИРУЕТСЯ из выгрузки (`--emit-sign-table`) и коммитится как
    reference раньше первого запуска стрелки. Руками в нём заполняется только
    поле `sign`: что означает «за», машина не выводит — §10 запрещает
    предполагать, и ровно поэтому поле пустое, пока человек его не закроет.
    """
    if path is None:
        f = sorted(SIGN_DIR.glob("for_option_sign_*.json"))
        if not f:
            raise SystemExit(
                "ОТКАЗ: нет docs/reference/for_option_sign_*.json. Стрелка без "
                "таблицы смысла «за» приписала бы фракции обратное на каждом "
                "девятом голосовании (§10).")
        path = f[-1]
    d = json.loads(path.read_text(encoding="utf-8"))
    bad = [k for k, v in d["options"].items() if v.get("sign") not in SIGN_KINDS]
    if bad:
        raise SystemExit(
            f"ОТКАЗ: {len(bad)} описаний опции без вердикта в {path.name}. "
            f"Первое: {bad[0][:60]}. Пустое поле — не «carries по умолчанию».")
    return d["options"]


def sign_of(for_desc: str, table: dict) -> str:
    """Значение для одного голосования. Неизвестное описание — ОТКАЗ.

    Умолчание здесь было бы худшим из возможных: оно тихо перенесло бы знак
    акта на голосование, смысл которого никто не читал. Неверно объявленная
    таблица всё равно сработает; отсутствующая запись не сработает никогда
    (§23 в приложении к смыслу).
    """
    v = table.get((for_desc or "").strip())
    if v is None:
        raise SystemExit(
            f"ОТКАЗ (§10): описание опции вне таблицы — {for_desc!r}. "
            "Добавь вердикт в docs/reference/for_option_sign_*.json и "
            "закоммить его раньше прогона.")
    return v["sign"]


def faction_move(act_sign: int, vote_sign: str, position: str) -> int | None:
    """Куда фракция двинула ось этим голосованием: +1 · −1 · None.

    Три множителя, и ни один нельзя опустить: знак самого акта, смысл «за» в
    этом голосовании и позиция фракции. `None` — голос не несёт знака: либо
    опция такого типа (`none`), либо фракция не голосовала «за»/«против».
    """
    if vote_sign == "none" or act_sign == 0:
        return None
    k = {"for": 1, "against": -1}.get(position)
    if k is None:
        return None
    return act_sign * k * (-1 if vote_sign == "inverts" else 1)


def emit_sign_table(votes: Path) -> int:
    """Скелет таблицы из выгрузки: все различные пары описаний, sign пустой.

    Три значения `none` ставятся заранее — они объявлены в
    criteria/declared_before_arrow_2026-10-07.yaml ДО этой выгрузки, и
    проставить их здесь значит исполнить объявленное, а не решить задним
    числом. Всё остальное остаётся пустым.
    """
    import collections
    v = json.loads(votes.read_text(encoding="utf-8"))
    cnt: collections.Counter = collections.Counter()
    pairs: dict = {}
    for r in v["rows"]:
        f = (r.get("for_option_desc") or "").strip()
        cnt[f] += 1
        pairs[f] = (r.get("against_option_desc") or "").strip()
    known_none = {
        "לקבל את ההסתייגות": "принять оговорку: оговорка часто двигает закон "
                             "в сторону, противоположную законопроекту",
        "לקבל את ההחלטה בדבר": "принять решение по вопросу: не законопроект",
        "לקבל את המלצת ועדת הכנסת להעביר את הצעת החוק מוועדה לוועדה":
            "передача из комитета в комитет: процедура без содержания",
    }
    out = {}
    for f, n in cnt.most_common():
        out[f] = {"against": pairs[f], "votes": n,
                  "sign": "none" if f in known_none else "",
                  "gloss_ru": known_none.get(f, "")}
    root = SIGN_DIR.parent.parent
    vr = votes.resolve()
    src = str(vr.relative_to(root)) if root in vr.parents else str(vr)
    doc = {"source": src,
           "snapshot": v.get("at"), "votes_total": sum(cnt.values()),
           "options": out}
    print(json.dumps(doc, ensure_ascii=False, indent=1))
    filled = sum(1 for o in out.values() if o["sign"])
    print(f"\n# различных описаний «за»: {len(out)}; заранее объявленных "
          f"none: {filled}; ждут вердикта: {len(out) - filled}", file=sys.stderr)
    return 0

# ══════════════════════════════════════════════════════════════════════════
#  СТРЕЛКА КАНАЛА А. Правило: criteria/declared_before_arrow_2026-10-07.yaml,
#  закоммичено раньше этого кода и раньше первого платного запроса (§3).
#  Пять частей правила — пять функций ниже, одна к одной, чтобы расхождение
#  кода с объявлением было видно сверкой имён, а не чтением.
# ══════════════════════════════════════════════════════════════════════════
ARROW_CRIT = Path(__file__).resolve().parent.parent / "criteria" \
    / "declared_before_arrow_2026-10-07.yaml"


def arrow_rule(path: Path = ARROW_CRIT) -> dict:
    """Пороги из объявленного правила, а не из констант в коде.

    Мини-разборщик возвращает числа с точкой СТРОКАМИ: `scalar()` приводит
    только целые. Приведение здесь явное — сравнение строки с числом в
    Python 3 бросает TypeError, то есть ошиблись бы громко, но ошиблись бы.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validate_cards import load_yaml_ish
    d = load_yaml_ish(path)
    return {"drop_below": float(d["cleaning"]["drop_lopsided_below"]),
            "min_acts": int(d["cleaning"]["min_acts_for_arrow"]),
            "acceptable": float(d["agreement"]["thresholds"]["acceptable"]),
            "tentative": float(d["agreement"]["thresholds"]["tentative"])}


def lopsided(fors: int, against: int, drop_below: float) -> bool:
    """Акт, где меньшинство меньше порога, различающей силы не несёт.

    W-NOMINATE XVMIN=0.0250. Отбрасывание ПО ОБЪЯВЛЕННОМУ ЗАРАНЕЕ порогу
    единогласия законно; отбор актов по тому, как хорошо они делят фракции, —
    запрещён (Snyder, LSQ 1992): он раздувает поляризацию и проверкой
    результата не обнаруживается.
    """
    t = fors + against
    return t == 0 or min(fors, against) / t < drop_below


def alpha(units: list[tuple]) -> float:
    """Альфа Криппендорфа для номинальной шкалы, ровно два кодировщика.

    Матрица совпадений при m=2: согласная единица даёт o[x][x] += 2,
    несогласная — o[x][y] += 1 и o[y][x] += 1. Тогда наблюдаемое несогласие
    сводится к доле несогласных единиц, а ожидаемое берётся из предельных
    частот с поправкой на малую выборку: De = (N² − Σn_c²) / (N(N−1)).

    Границы: при одной категории у всех De == 0 — согласие полное, но
    ожидаемое несогласие тоже нулевое, и отношение не определено. Возвращаем
    1.0: все судили одинаково. Это решение, а не деление на ноль.
    """
    if not units:
        return 0.0
    n = len(units)
    dis = sum(1 for x, y in units if x != y)
    cnt: dict = {}
    for x, y in units:
        cnt[x] = cnt.get(x, 0) + 1
        cnt[y] = cnt.get(y, 0) + 1
    N = 2 * n
    if N < 2:
        return 1.0
    de = (N * N - sum(v * v for v in cnt.values())) / (N * (N - 1))
    if de == 0:
        return 1.0
    return 1.0 - (dis / n) / de


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% интервал Уилсона на доле. Объявленная замена бутстрапу.

    Manifesto Project (Benoit, Laver, Mikhaylov 2009) мерит неопределённость
    бутстрапом; Уилсон отвечает на тот же вопрос без симуляции. При n == 0
    интервал (0, 1): ничего не известно, и это не «ровно половина».
    """
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - m), min(1.0, c + m)


def arrow(down: int, n: int, min_acts: int) -> str:
    """Значение клетки: up · down · both · miss. Пяти значений макета пять.

    `miss` — «мы сюда не дошли», и это НЕ «ничего не делала»: у фракции
    меньше объявленного минимума актов, и утверждать нечего.
    `both` ставится, когда интервал Уилсона накрывает половину: по этой оси
    фракция вела себя не в одну сторону. Это утверждение, а не отговорка.
    """
    if n < min_acts:
        return "miss"
    lo, hi = wilson(down, n)
    if lo <= 0.5 <= hi:
        return "both"
    return "down" if down / n > 0.5 else "up"


GRADE = ("high", "moderate", "low", "very_low")


def level(a: float, coverage: float, rule: dict) -> str:
    """Уровень определённости: ХУДШЕЕ из согласия и охвата (GRADE).

    Охват ниже половины принудительно опускает до низшего — это то место,
    где согласие вендоров не может купить уверенность. Инвариант
    external_anchor_is_not_validation дословно: согласие двух измерителей
    ОДНОГО И ТОГО ЖЕ не валидирует ни один из них, а общая систематическая
    ошибка обоих даёт согласие ВЫСОКОЕ.
    """
    by_a = ("high" if a >= rule["acceptable"]
            else "moderate" if a >= rule["tentative"] else "low")
    by_c = "high" if coverage >= 0.5 else "very_low"
    return max(by_a, by_c, key=GRADE.index)


# Оговорка темы. not_transferred.тема требует, чтобы она стояла ПРИ
# стрелке, а не в подвале: без неё клетка читается как «партия такая».
# Дом правила — YAML; здесь копия, и copy_matches_rule в самопроверке
# краснеет, если копия разойдётся с объявлением.
THEME_CAVEAT = "по вопросам правового государства"

SAY = {"high": "{party} {theme}: {move}",
       "moderate": "вероятно {move} {theme}; у нас {n} актов из {m}",
       "low": "свидетельства расходятся; что мы видим — {move} {theme}, "
              "и мы в этом не уверены",
       "very_low": "сказать нечего: {why}"}
MOVE = {"up": "укрепляла", "down": "ослабляла",
        "both": "и туда и обратно", "miss": "мы сюда не дошли"}


def say(lvl: str, mv: str, party: str, n: int, m: int, why: str) -> str:
    """Формулировка по шаблону уровня. Четыре шаблона, четыре уровня.

    Шаблон выбирается уровнем, а не автором: иначе формулировка поползёт к
    уверенной при любом замере, и поползёт незаметно.
    """
    return SAY[lvl].format(party=party, move=MOVE[mv], n=n, m=m, why=why,
                           theme=THEME_CAVEAT)


def rice(fors: int, against: int) -> float:
    """Индекс когезии Райса (1925) по одной фракции в одном голосовании."""
    t = fors + against
    return 0.0 if t == 0 else abs(fors - against) / t


def faction_position(counts: dict, split_below: float) -> str | None:
    """Позиция фракции: «for» · «against» · None (раскол или нет позиции).

    Воздержавшиеся и отсутствующие в знаменатель не входят — это отсутствие
    позиции, а не позиция. Раскол (индекс Райса ниже порога) даёт None, и это
    ТРЕТЬЕ состояние: не «против» и не «воздержалась», а «одной позиции у
    фракции в этом голосовании нет». Правило объявлено в
    criteria/declared_before_arrow_2026-10-07.yaml, часть faction_position.
    """
    f, a = int(counts.get("for", 0)), int(counts.get("against", 0))
    if f + a == 0:
        return None
    if rice(f, a) < split_below:
        return None
    return "for" if f > a else "against"


def compose(rows: list[dict], directions: dict, table: dict,
            rule: dict) -> tuple[dict, set, dict]:
    """От голосований к ходам фракций. Единица — АКТ, а не голосование.

    «Все акты равны» объявлено в правиле, и здесь это решает устройство:
    фракция голосует по одному акту несколько раз (чтения, оговорки), и если
    считать голосованиями, акт с девятью голосованиями перевесит восемь
    однократных. Поэтому голоса сначала сворачиваются в ход ПО АКТУ, и
    противоречивый акт (ходы в обе стороны) из стрелки выпадает: это не
    «и туда и обратно» у фракции, а неразрешённость внутри одного акта.
    """
    import collections
    per: dict = collections.defaultdict(
        lambda: collections.defaultdict(set))
    stat = collections.Counter()
    dropped, acts_theme = set(), set()
    for r in rows:
        bid = r.get("bill_id")
        if bid is not None:
            acts_theme.add(bid)
        bf = r.get("by_faction") or {}
        # §10 проверяется ДО любых отсевов: опция, которой нет в таблице,
        # обязана останавливать стрелку, а не проскакивать потому, что
        # строку всё равно выбросило единогласие или отсутствие знака акта.
        vs = sign_of(r.get("for_option_desc"), table)
        f_all = sum(int(c.get("for", 0)) for c in bf.values())
        a_all = sum(int(c.get("against", 0)) for c in bf.values())
        if lopsided(f_all, a_all, rule["drop_below"]):
            dropped.add(r.get("vote_id"))
            stat["выброшено по единогласию"] += 1
            continue
        act = directions.get(bid) if bid is not None else None
        if act is None:
            stat["акт без направления"] += 1
            continue
        for fac, c in bf.items():
            pos = faction_position(c, rule["split_below"])
            if pos is None:
                stat["раскол или нет позиции"] += 1
                continue
            mv = faction_move(int(act), vs, pos)
            if mv is None:
                stat["голос без знака"] += 1
                continue
            per[fac][bid].add(mv)
    out: dict = {}
    for fac, by_act in per.items():
        down = sum(1 for m in by_act.values() if m == {-1})
        up = sum(1 for m in by_act.values() if m == {1})
        mixed = sum(1 for m in by_act.values() if len(m) > 1)
        out[fac] = {"down": down, "up": up, "mixed_acts": mixed,
                    "acts": down + up}
        stat["акты в обе стороны внутри акта"] += mixed
    return out, acts_theme, dict(stat)


def cell(entry: dict, theme_total: int, a: float, party: str,
         rule: dict) -> dict:
    """Значение клетки, уровень и готовая формулировка для одной фракции."""
    n = entry["acts"]
    cov = n / theme_total if theme_total else 0.0
    # falsification.согласие_ниже_порога: альфа ниже tentative — стрелка НЕ
    # публикуется вовсе. Отказ стоит ДО вычисления стрелки: поставленный
    # после, он превращается в оговорку при уже опубликованном знаке, а
    # объявлено было не «с оговоркой», а «не публикуется».
    if a < rule["tentative"]:
        mv, lvl = "miss", "very_low"
        why = (f"согласие вендоров {a:.3f} ниже объявленного "
               f"{rule['tentative']}: мерить нечем")
    else:
        mv = arrow(entry["down"], n, rule["min_acts"])
        if mv == "miss":
            lvl, why = "very_low", (f"актов меньше {rule['min_acts']}: "
                                    f"{n} из {theme_total}")
        else:
            lvl = level(a, cov, rule)
            # §6: у низшего уровня обязана быть НАЗВАННАЯ причина. Пустая
            # строка давала читателю «сказать нечего: » — отсутствие причины
            # там, где правило требует её назвать.
            why = (f"охват {n} из {theme_total}: меньше половины актов темы"
                   if lvl == "very_low" else "")
    return {"arrow": mv, "level": lvl, "acts": n, "theme_total": theme_total,
            "coverage": round(cov, 3), "down": entry["down"], "up": entry["up"],
            "text": say(lvl, mv, party, n, theme_total, why)}


def load_directions(path: Path, pair: tuple = ("anthropic", "openai")
                    ) -> tuple[dict, list, dict]:
    """Направления актов и материал для альфы — из результата прогона.

    `quorum.value` — согласованный знак акта, `quorum.kind` — на чём он стоит.
    `no_quorum` в направления НЕ идёт: вендоры не сошлись о знаке самого акта,
    и переносить такой знак на фракцию значит выдать несогласие за данность.

    Для альфы берутся ПАРНЫЕ знаки обоих вендоров по каждому акту — то есть
    согласие меряется на том же материале, из которого построены стрелки, а
    не на отдельной удобной выборке.
    """
    import collections
    d = json.loads(path.read_text(encoding="utf-8"))
    directions, units = {}, []
    stat: collections.Counter = collections.Counter()
    for r in d["rows"]:
        q = r.get("quorum") or {}
        kind = q.get("kind")
        stat[f"кворум: {kind}"] += 1
        sg = [(r.get("verdicts") or {}).get(v, {}).get("overall", {}).get("sign")
              for v in pair]
        if all(x is not None for x in sg):
            units.append((sg[0], sg[1]))
        else:
            stat["нет знака у одного из пары"] += 1
        if kind == "no_quorum" or q.get("value") is None:
            continue
        directions[r["bill"]] = int(q["value"])
    stat["актов с направлением"] = len(directions)
    stat["пар для альфы"] = len(units)
    return directions, units, dict(stat)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    # Молчаливый ноль без аргументов — то самое «выглядит рабочим». Теперь
    # звать без источника нельзя: инструмент говорит, чего от него хотят.
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--emit-sign-table" in sys.argv:
        if not args:
            print("нужен путь к выгрузке голосований, например:\n"
                  "  python3 scripts/direction_confidence.py --emit-sign-table "
                  "data/votes_25.json > docs/reference/for_option_sign_<дата>.json")
            return 2
        return emit_sign_table(Path(args[0]))
    if not args:
        print("нужен путь к прогону, например:\n"
              "  python3 scripts/direction_confidence.py data/direction_v2.json\n"
              "  python3 scripts/direction_confidence.py --emit-sign-table data/votes_25.json\n"
              "  python3 scripts/direction_confidence.py --selftest")
        return 2
    return report(Path(args[0]))


if __name__ == "__main__":
    raise SystemExit(main())
