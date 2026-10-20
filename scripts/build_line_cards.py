#!/usr/bin/env python3
"""Базовая линия: карточка на КАЖДУЮ строку бюллетеня, на нынешнем качестве.

Решение владельца 13.08: делаем проект целиком с некоторой точностью, это
объявляется базовой линией, дальше — гипотеза, правка, замер прироста. Две
вылизанные строки дают анекдот; шестнадцать дают распределение, а прирост
виден только на распределении.

ЧТО ЗДЕСЬ МАШИННОЕ И ЧТО НЕТ. Машинное: перепись голосований, статусы
каналов, доказанный ноль периодов, оговорка о теме. Человеческого суждения
о конкретных голосованиях здесь НЕТ ни в одной карточке, и они помечены
`baseline: true` — чтобы структурная полнота не выдавала себя за разбор.
Две карточки, написанные руками 13.08 (ШАС и ХАДАШ-ТААЛ), не трогаются.

Гонится на Studio (данные там), пишет в stdout; файлы создаёт MacBook (§19):
    ssh studio 'cd ~/knesset && python3 scripts/build_line_cards.py --emit' \
      | python3 scripts/build_line_cards.py --apply
"""
from __future__ import annotations
from build_report import plural_ru
import json, re, sys, collections
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import n_asserts   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CAV = "по законопроектам, которые голосовались в пленуме"  # 20.10: полная выгрузка — не только отбор по теме суда
THEME = "rule_of_law"


def slug(name: str, fid: int) -> str:
    import re
    lat = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{lat or 'line'}-{fid}-k25-votes"


RU = {1096: "Ликуд", 1102: "Еш Атид", 1095: "ШАС", 1097: "Религиозный сионизм",
      1098: "Государственный лагерь", 1101: "Яадут ха-Тора",
      1105: "Религиозный сионизм (Смотрич)", 1110: "Кахоль-лаван — Гос. лагерь",
      1106: "Оцма Йегудит (Бен-Гвир)", 1103: "ХАДАШ-ТААЛ", 1104: "Наш дом Израиль",
      1108: "Государственный правый", 1099: "РААМ", 1100: "Авода",
      1107: "Ноам (Маоз)", 1109: "депутат Идан Роль"}


def census(rows: list, fid: int) -> dict:
    mine = [r for r in rows
            if any(k.split("|", 1)[0] == str(fid) for k in (r.get("by_faction") or {}))]
    if not mine:
        return {}
    acts = {r["bill_id"] for r in mine}
    all_acts = {r["bill_id"] for r in rows}
    ds = sorted(r["date"][:10] for r in mine)
    return {"votes": len(mine), "acts": len(acts),
            "acts_in_theme_total": len(all_acts),
            "acts_without_participation": len(all_acts) - len(acts),
            "from": ds[0], "to": ds[-1]}


def axis_block(ax: dict | None) -> str:
    """Блок решения по оси, или пустая строка, если решения нет.

    Карточка держит РЕШЕНИЕ и числа, из которых оно выведено, — так же, как
    она уже держит перепись голосований, и так же под отпечатком §11.
    Отсутствие блока — законное состояние: клетка остаётся «мы сюда не
    дошли», и это про нас, а не про фракцию.
    """
    if not ax:
        return ""
    if "alpha" not in ax:
        raise SystemExit(
            "ОТКАЗ: решение по оси без согласия, при котором оно получено. "
            "Правило объявляет отказ публикации при альфе ниже порога, а "
            "проверить его на готовой карточке можно только если число "
            "лежит РЯДОМ со стрелкой. Отсутствие числа — не разрешение.")
    return f"""
axis_institutions:
  arrow: {ax['arrow']}
  level: {ax['level']}
  acts: {ax['acts']}
  theme_total: {ax['theme_total']}
  coverage: {ax['coverage']}
  down: {ax['down']}
  up: {ax['up']}
  alpha: {ax['alpha']}
  text: >-
    {ax['text']}
"""


def card_yaml(fid: int, he: str, cen: dict, in_gov: bool, b_status: str,
              snap: str, ax: dict | None = None, reviewed: bool = False,
              zero: bool = False, gov_in_window: bool | None = None) -> str:
    ru = RU.get(fid, he)
    miss = cen["acts_without_participation"]
    share = miss / cen["acts_in_theme_total"]
    # Прочтения выводятся ИЗ ЧИСЕЛ ЭТОЙ СТРОКИ, а не переписываются из
    # соседней. Одинаковых карточек здесь нет: у каждой свой пропуск, свой
    # объём и своё положение по каналу денег.
    weak = (f"актов темы без участия — {miss} из {cen['acts_in_theme_total']}, "
            f"{share:.0%}. Причину выгрузка не показывает: отсутствие в зале, "
            "снятие с повестки и объединённое голосование выглядят одинаково")
    strong = (f"позиция зафиксирована {cen['votes']} раз за период "
              f"{cen['from']} — {cen['to']}; в Кнессете 92% голосований "
              "электронные и пишут каждого депутата, так что «не голосовать» "
              "не является способом скрыть позицию")
    if gov_in_window is None:
        gov_in_window = in_gov
    if in_gov:
        # R27-F02: «входила в правительство в наблюдаемый период» — только при
        # пересечении дат участия с окном голосований этой строки, а не по
        # одному факту участия когда-либо (1109, 1110).
        frame = ("фракция входила в правительство в наблюдаемый период, и её "
                 "голосование по правительственным законопроектам может "
                 "отражать коалиционную дисциплину, а не предпочтение по "
                 "предмету; голосованиями это не разделяется"
                 if gov_in_window else
                 "в окне этих голосований фракция в правительство не входила; "
                 "по этим голосам нельзя отделить предпочтение по предмету от "
                 "согласованного голосования с другими фракциями")
        # R8-F04: у партии с карточкой разбора обязательств прежняя проза
        # «не построено» противоречила бюджетному блоку той же страницы.
        bnote = ("партия правила; обязательства соглашения сверены с бюджетом "
                 "по одному, сводного вывода нет — записи — в блоке «Деньги» выше на этой странице"
                 if reviewed else
                 # R19-F01: пустая карта извлечения — смотрели и вернулись
                 # пустыми, а не «не дошли»
                 "партия правила; в коалиционном соглашении денежных обещаний "
                 "не найдено, сверять с бюджетом нечего"
                 if zero else
                 # v33: ведущая сторона соглашений — сводка подписанных партнёрам обещаний
                 "партия правила как ведущая сторона коалиционных соглашений; "
                 "сводка подписанных партнёрам обещаний — в блоке «Деньги» выше на этой странице"
                 if fid in (1096, 1102) else
                 "партия правила, сопоставление обязательств не построено")
    else:
        # R23: денег нет по устройству канала, должностей — из-за нашей
        # невыгрузки; одной причиной их не называть.
        frame = ("канал денег у этой строки пуст по устройству измерения: "
                 "коалиционного соглашения она не подписывала. Это свойство "
                 "измерителя, а не партии, и читать "
                 "пустоту как «к этой вопросов нет» — ошибка того же рода, "
                 "что читать её как обвинение")
        bnote = ("в 25-м Кнессете партия в правительство не входила — по "
                 "списку составов правительства")
    return f"""# Базовая линия. Сгенерирована scripts/build_line_cards.py 13.08.2026.
# Человеческого разбора конкретных голосований в этой карточке НЕТ.
# Правки руками ведут к расхождению с генератором — правь генератор.
card_version: 1
baseline: true
card_type: party
unit: faction_knesset
faction_id: {fid}
knesset: 25
party_he: {he}
party_ru: {ru}
status: observed

snapshots:
  votes_25: {snap}
{axis_block(ax)}
votes:
  theme: {THEME}
  theme_caveat_ru: {CAV}
  source: data/votes_25.json
  faction_id: {fid}
  census:
    votes: {cen['votes']}
    acts: {cen['acts']}
    acts_in_theme_total: {cen['acts_in_theme_total']}
    acts_without_participation: {miss}
    from: {cen['from']}
    to: {cen['to']}

holdout_checked:
  period: null
  date: null
  outcome: >-
    не проверялось: мы ни разу не перепроверили вывод на более раннем
    отрезке времени, в который до этого не смотрели

conclusion: >-
  Фракция участвовала в {cen['votes']} {plural_ru(cen['votes'], 'голосовании', 'голосованиях', 'голосованиях')} {CAV},
  охватив {cen['acts']} {plural_ru(cen['acts'], 'акт', 'акта', 'актов')} из {cen['acts_in_theme_total']}.
  Что означало «за» в каждом случае, читается из поля смысла опции, а не
  предполагается. Направление — в блоке «Суд, парламент, свободы» выше.
  Деньги: {bnote}. Должности: данных пока нет — это наша недоработка, к
  партии она отношения не имеет.

readings:
  - type: weakening
    text: >-
      {weak}
  - type: strengthening
    text: >-
      {strong}
  - type: reframing
    text: >-
      {frame}

counter_search:
  searched_where:
    - источник: >-
        поимённые голосования Кнессета по этим вопросам — у каждого
        проверено, участвовала ли фракция; снимок {snap[:10]}
    - источник: >-
        список составов правительства 25-го Кнессета — {bnote}
  outcome: nothing
  note: >-
    это первый, грубый выпуск: мы искали изъяны в том, КАК устроена эта
    страница, а не в поведении партии. Отдельные голосования не разбирались

confidence: low
confidence_reason: >-
  первый, грубый выпуск: взяты вопросы одной темы, вывод не перепроверен на
  более раннем отрезке времени, отдельные голосования не разбирались

what_would_falsify: >-
  если добавить вопросы второй темы и доля участия изменится больше чем на
  четверть — сказанное о фракции окажется свойством выбранных вопросов, а не
  её поведения

revisions:
  - version: 1
    date: 2026-08-13
    what: >-
      базовая линия, сгенерирована по решению владельца «сделать проект
      целиком с некоторой точностью и мерить прирост от неё»
"""


def _core(text: str) -> str:
    """Содержание карточки без версии, отпечатка и журнала."""
    text = text.split("\nrevisions:\n", 1)[0]
    return re.sub(r"^(card_version|data_fingerprint):.*\n", "", text, flags=re.M)


def carry_history(body: str, old: str | None, snap: str, name: str = "?") -> str:
    """§15 (R19-F03): перегенерация не стирает версию и журнал.

    Содержание не изменилось — файл остаётся байт в байт прежним.
    Изменилось — следующая версия, прежние записи журнала целиком и одна
    новая с причиной: числа пересчитаны по такому-то снимку."""
    if old is None:
        return body
    m = re.search(r"^card_version: (\d+)$", old, flags=re.M)
    if not m or "\nrevisions:\n" not in old:
        # R22-F04: без версии или журнала — отказ с адресом, а не тихий
        # возврат неполной карточки и не AttributeError
        raise SystemExit(f"ОТКАЗ: у cards/{name} нет card_version или "
                         "revisions — перегенерация не знает, какую версию продолжать")
    if _core(body) == _core(old):
        return old
    v = int(m.group(1)) + 1
    hist = old.split("\nrevisions:\n", 1)[1].rstrip("\n")
    head = re.sub(r"^card_version: \d+$", f"card_version: {v}",
                  body.split("\nrevisions:\n", 1)[0], count=1, flags=re.M)
    return (f"{head}\nrevisions:\n{hist}\n  - version: {v}\n"
            f"    date: {date.today().isoformat()}\n    what: >-\n"
            f"      перегенерация базовой линии по снимку голосований {snap}; "
            f"содержание изменилось, прежние записи журнала сохранены\n")


COVERAGE_FIRST = True   # решение владельца 19.10: покрытие вместо точности


USE_FULL = True   # trajectory.old_signs_any выключает, чтобы получить ПРЕЖНИЕ знаки без полной разметки


def axis_directions(directions_path: Path) -> tuple[dict, list]:
    """Единый набор знаков оси, включая решающий голос Claude."""
    from direction_confidence import load_directions
    dirs, units, _ = load_directions(directions_path)
    if COVERAGE_FIRST:
        # 28 законов без большинства трёх моделей — решающий голос Claude
        tb = ROOT / "criteria" / "claude_tiebreak_signs_2026-10-19.json"
        if tb.exists():
            for bill, sg in json.loads(tb.read_text(encoding="utf-8"))["signs"].items():
                dirs.setdefault(int(bill), int(sg))
        # Владелец 20.10 (вопрос 6): весь сайт на полной выгрузке — законы, которых нет в прежнем
        # конвейере, получают знак полной разметки по названиям (criteria/declared_before_site_full_2026-10-20.yaml).
        full = ROOT / "criteria" / "full_signs_K25.json"
        if USE_FULL and full.exists():
            added = {}
            for bill, sg in json.loads(full.read_text(encoding="utf-8"))["signs"]["rule_of_law"].items():
                if int(bill) not in dirs:
                    added[int(bill)] = int(sg)
            # Перепись 20.10 (criteria/census_second_reading_2026-10-20.json, правило c6114fe): снятые знаки
            # полной разметки → 0. Касается только законов, добавленных из полной разметки, не решающей оси.
            from theme_arrows import reread_filter
            dirs.update(reread_filter("rule_of_law", added))
    # Фаза точности 19.10: второе независимое прочтение по полному тексту
    # (Codex v32/v39). Где оно прямо расходится со знаком большинства — знак снят
    # (отказ второго чтения — null — не считается доводом против):
    # спорный акт не голосует в стрелке. Нет файла — нет эффекта.
    second = ROOT / "criteria" / "axis_second_reading_2026-10-19.json"
    if second.exists():
        for bill, sg in json.loads(second.read_text(encoding="utf-8"))["signs"].items():
            b = int(bill)
            if b in dirs and sg is not None and int(sg) != dirs[b]:
                dirs[b] = 0
    return dirs, units


def arrows(votes: dict, directions_path: Path | None) -> dict:
    """Решения по оси для всех фракций, или пусто, если прогона нет.

    Вся арифметика живёт в scripts/direction_confidence.py — здесь только
    сборка карточек. Второго дома у правила стрелки быть не должно: в этом
    проекте уже было, что одно знание в двух домах разошлось и заметить это
    было некому.
    """
    if directions_path is None or not directions_path.exists():
        return {}
    sys.path.insert(0, str(ROOT / "scripts"))
    from direction_confidence import (arrow_rule, cell, compose,
                                      alpha, sign_table)
    rule = arrow_rule()
    rule["split_below"] = float(_arrow_split())
    dirs, units = axis_directions(directions_path)
    a = alpha(units)
    # Решение владельца 19.10: покрытие вместо точности, первая итерация.
    # Порог согласия моделей (tentative) не блокирует стрелку; измеренное
    # согласие сохраняется отдельно (alpha_measured) для следующего шага.
    a_eff = max(a, rule["tentative"]) if COVERAGE_FIRST else a
    per, theme, _ = compose(votes["rows"], dirs, sign_table(), rule)
    out = {}
    for fac, entry in per.items():
        key = str(fac).split("|")[0]
        fid = int(key) if key.isdigit() else key
        c = dict(cell(entry, len(theme), a_eff, RU.get(fid, str(fid)), rule),
                 alpha=round(a_eff, 4), alpha_measured=round(a, 4))
        if COVERAGE_FIRST:
            # Без порогов охвата и числа актов: стрелка по большинству голосов
            # фракции × знак закона (две трети — направление, иначе «↕»).
            n = (c.get("up") or 0) + (c.get("down") or 0)
            if n:
                from theme_arrows import arrow_of
                c["arrow"] = arrow_of(c["up"], c["down"], min_acts=1)
                c["text"] = ("по голосам фракции и знаку закона по большинству "
                             "трёх моделей")
        out[fid] = dict(c, up_bills=entry["up_bills"], down_bills=entry["down_bills"])
    return out


def _arrow_split() -> str:
    """Порог раскола фракции — из объявленного правила, не из кода."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_cards import load_yaml_ish
    f = sorted((ROOT / "criteria").glob("declared_before_arrow_*.yaml"))[-1]
    return load_yaml_ish(f)["faction_position"]["split_below"]


def emit(directions: Path | None = None) -> int:
    """На Studio: посчитать и выдать карточки в stdout одним JSON."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_cards import load_yaml_ish
    votes = json.loads((ROOT / "data" / "votes_25.json").read_text(encoding="utf-8"))
    lin = json.loads((ROOT / "criteria" / "ballot_lineage_draft.json")
                     .read_text(encoding="utf-8"))
    per = load_yaml_ish(ROOT / "criteria" / "periods.yaml")
    gov = {p["faction_id"] for p in per["periods"]}
    windows = {}
    for p in per["periods"]:
        windows.setdefault(p["faction_id"], []).append(
            (str(p["start"]), str(p.get("finish") or "9999-12-31")))
    # Рукописные карточки не перегенерируются, базовые — перегенерируются.
    # Прежнее правило «есть файл с этим id — пропустить» годилось для первой
    # генерации и запрещало ВТОРУЮ: после перевыгрузки числа в базовых
    # карточках устарели бы, а скрипт отказался бы их обновить. Признак —
    # пометка baseline в самой карточке, а не имя файла.
    hand = set()
    for f in (ROOT / "cards").glob("*.yaml"):
        c = load_yaml_ish(f)
        if c.get("unit") == "faction_knesset" and not c.get("baseline"):
            hand.add(int(c["faction_id"]))
    snap = votes["at"][:19]   # §11: снимок берётся из данных, не из константы
    ax_all = arrows(votes, directions)
    from render_overview import load_cards
    reviewed = {k for k, v in load_cards("party_period").items() if v}
    from coverage_matrix import commitment_maps
    zero = {k for k, v in commitment_maps().items() if not v["commitments"]}
    out, skipped = {}, []
    for ch in lin["chains"]:
        fid, he = ch["anchor_id"], ch["anchor"]
        cen = census(votes["rows"], fid)
        if not cen:
            skipped.append((fid, he, "голосований под этим id нет — "
                                     "связь строки с фракцией не установлена"))
            continue
        if fid in hand:
            skipped.append((fid, he, "карточка написана руками — не трогаем"))
            continue
        name = slug(RU.get(fid, "line"), fid) + ".yaml"
        overlap = any(s <= cen["to"] and f >= cen["from"] for s, f in windows.get(fid, []))
        body = card_yaml(fid, he, cen, fid in gov, "", snap,
                         ax_all.get(fid), fid in reviewed, fid in zero, overlap)
        # Проводка (R19-F02, M09): разобранная правившая партия обязана
        # получить прозу о сверке — иначе отказ здесь, а не на сайте.
        if fid in gov and fid in reviewed and "сверены с бюджетом" not in body:
            raise SystemExit(f"ОТКАЗ: {fid} разобрана, а проза канала денег — «не построено»")
        p = ROOT / "cards" / name
        out[name] = carry_history(body, p.read_text(encoding="utf-8")
                                  if p.exists() else None, snap, name)
    print(json.dumps({"cards": out, "skipped": skipped}, ensure_ascii=False))
    return 0


def apply_() -> int:
    """На MacBook: записать файлы. Пишет только MacBook (§19)."""
    d = json.loads(sys.stdin.read())
    for name, body in d["cards"].items():
        (ROOT / "cards" / name).write_text(body, encoding="utf-8")
        print("записана", name, file=sys.stderr)
    for fid, he, why in d["skipped"]:
        print(f"пропущена {fid} {he[:34]}: {why}", file=sys.stderr)
    print(f"итого записано {len(d['cards'])}, пропущено {len(d['skipped'])}",
          file=sys.stderr)
    return 0


SNAP = "2026-10-07T12:00:00"


def selftest() -> int:
    cen = {"votes": 10, "acts": 8, "acts_in_theme_total": 20,
           "acts_without_participation": 12, "from": "2022-12-13",
           "to": "2026-07-14"}
    a = card_yaml(1, "פ", cen, True, "", SNAP)
    b = card_yaml(2, "ק", cen, False, "", SNAP)
    assert "коалиционную дисциплину" in a and "коалиционную дисциплину" not in b, \
        "правившая и неправившая обязаны получить РАЗНОЕ переформатирование: " \
        "иначе шестнадцать карточек — это одна, размноженная шестнадцать раз"
    assert "по устройству измерения" in b, "пустота не названа свойством измерителя"
    assert "baseline: true" in a, "карточка базовой линии не помечена как базовая"
    r = card_yaml(1, "פ", cen, True, "", SNAP, reviewed=True)
    assert "не построено" in a and "не построено" not in r and "сверены с бюджетом" in r, \
        "R8-F04: разобранная партия получила прозу «не построено»"
    # R19-F03: v2 с двумя записями журнала переживает перегенерацию
    v2 = (r.replace("card_version: 1\n", "card_version: 2\n")
          + "  - version: 2\n    date: 2026-10-18\n    what: >-\n      ручная правка\n")
    v2 = v2.replace("card_version: 2\n", "card_version: 2\ndata_fingerprint: sha256:ab\n", 1)
    assert carry_history(r, v2, SNAP) == v2, "неизменная перегенерация тронула файл"
    cen3 = dict(cen, votes=11)
    r3 = carry_history(card_yaml(1, "פ", cen3, True, "", SNAP, reviewed=True), v2, SNAP)
    assert "card_version: 3\n" in r3 and "card_version: 1\n" not in r3, "версия вернулась назад"
    assert "      ручная правка\n" in r3 and "  - version: 1\n" in r3 and \
        "  - version: 3\n" in r3 and SNAP in r3.split("  - version: 3", 1)[1], \
        "журнал правок потерян при перегенерации"
    assert carry_history(r, None, SNAP) == r, "новая карточка изменена"
    try:
        carry_history(r, r.replace("card_version: 1\n", ""), SNAP, "line-x.yaml")
    except SystemExit as e:
        assert "cards/line-x.yaml" in str(e), "R24-F01: отказ без адреса карточки"
    else:
        raise AssertionError("R22-F04: карточка без card_version прошла перегенерацию")
    assert "должностей у этой строки пусты" not in b and "портфелей" not in b, \
        "R23: пустота денег и должностей снова названа одной причиной"
    z = card_yaml(1, "פ", cen, True, "", SNAP, zero=True)
    w = card_yaml(1, "פ", cen, True, "", SNAP, gov_in_window=False)
    assert "коалиционную дисциплину" not in w and "не входила" in w and \
        "партия правила" in w, "R27-F02: участие вне окна голосований названо дисциплиной"
    assert "денежных обещаний не найдено" in z and "не построено" not in z, \
        "R19-F01: пустая карта извлечения названа «не построено»"
    assert "60%" in a, "доля пропуска не выведена из чисел этой строки"
    assert CAV in a and a.count(CAV) >= 2, "оговорка о теме не при утверждении"
    cen2 = dict(cen, acts_without_participation=1, votes=99)
    # §11: снимок приезжает из данных, а не из константы в коде. Прежняя
    # редакция держала дату жёстко, и после любой перевыгрузки карточка врала
    # бы срезом — тем самым, по которому §11 сверяет прозу с числами.
    assert SNAP in card_yaml(1, "פ", cen, True, "", SNAP), \
        "снимок не доехал до карточки"
    assert "2026-07-31T17:49:14" not in card_yaml(1, "פ", cen, True, "", SNAP), \
        "в карточке осталась зашитая дата снимка — §11 охраняет не тот срез"
    assert "99 голосованиях" in card_yaml(1, "פ", cen2, True, "", SNAP), \
        "числа карточки не следуют за переписью"
    # Блок решения по оси: есть решение — есть блок, нет — нет блока.
    axd = {"arrow": "down", "level": "moderate", "acts": 23, "alpha": 0.81,
           "theme_total": 40, "coverage": 0.575, "down": 19, "up": 4,
           "text": "вероятно ослабляла; у нас 23 актов из 40"}
    with_ax = card_yaml(1, "פ", cen, True, "", SNAP, axd)
    assert "axis_institutions:" in with_ax and "arrow: down" in with_ax
    assert "axis_institutions" not in card_yaml(1, "פ", cen, True, "", SNAP), \
        "блок оси появился без решения — клетка заполнится из ничего"
    # Отсутствие прогона — законное состояние, а не отказ.
    assert arrows({"rows": []}, None) == {}, \
        "нет прогона направлений — должно быть пусто, а не исключение"
    assert arrows({"rows": []}, Path("/нет/такого/файла.json")) == {}, \
        "несуществующий путь обязан давать пусто, а не падать"
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_cards import load_yaml_ish
    import tempfile
    tf = Path(tempfile.mkdtemp()) / "c.yaml"
    tf.write_text(with_ax, encoding="utf-8")
    back = load_yaml_ish(tf)["axis_institutions"]
    assert back["arrow"] == "down" and back["coverage"] == 0.575, \
        f"блок оси не читается обратно разборщиком: {back}"
    print(f"самопроверка build_line_cards: {n_asserts(selftest)} утверждений")
    return 0


def _dir_arg() -> Path | None:
    """`--directions <путь>`: результат платного прогона. Нет — стрелок нет."""
    if "--directions" in sys.argv:
        return Path(sys.argv[sys.argv.index("--directions") + 1])
    return None


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else
                     emit(_dir_arg()) if "--emit" in sys.argv else
                     apply_() if "--apply" in sys.argv else
                     print("нужен --selftest | --emit | --apply") or 2)
