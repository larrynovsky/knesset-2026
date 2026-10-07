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
import json, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import n_asserts   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CAV = "по вопросам правового государства"
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
    return f"""
axis_institutions:
  arrow: {ax['arrow']}
  level: {ax['level']}
  acts: {ax['acts']}
  theme_total: {ax['theme_total']}
  coverage: {ax['coverage']}
  down: {ax['down']}
  up: {ax['up']}
  text: >-
    {ax['text']}
"""


def card_yaml(fid: int, he: str, cen: dict, in_gov: bool, b_status: str,
              snap: str, ax: dict | None = None) -> str:
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
    if in_gov:
        frame = ("фракция входила в правительство в наблюдаемый период, и её "
                 "голосование по правительственным законопроектам может "
                 "отражать коалиционную дисциплину, а не предпочтение по "
                 "предмету; голосованиями это не разделяется")
        bnote = "партия правила, сопоставление обязательств не построено"
    else:
        frame = ("каналы денег и должностей у этой строки пусты по устройству "
                 "измерения: соглашения она не подписывала, портфелей не "
                 "держала. Это свойство измерителя, а не партии, и читать "
                 "пустоту как «к этой вопросов нет» — ошибка того же рода, "
                 "что читать её как обвинение")
        bnote = "ноль периодов в правительстве доказан criteria/periods.yaml"
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
  Фракция участвовала в {cen['votes']} голосованиях {CAV},
  охватив {cen['acts']} актов из {cen['acts_in_theme_total']}.
  Что означало «за» в каждом случае, читается из поля смысла опции, а не
  предполагается. Направление голосований документ не утверждает.
  Канал денег: {bnote}. Канал должностей: источник не выгружался ни разу —
  это наша авария, и к этой партии она отношения не имеет.

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
        data/votes_25.json — все голосования по этим вопросам, у каждого
        проверено, участвовала ли фракция {fid}; снимок {snap}
    - источник: >-
        criteria/periods.yaml, 17 периодов у 14 фракций — {bnote}
    - источник: >-
        data/coverage_matrix.json — статусы каналов Б и В у этой строки
        различены, а не слиты
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
                                      load_directions, alpha, sign_table)
    rule = arrow_rule()
    rule["split_below"] = float(_arrow_split())
    dirs, units, _ = load_directions(directions_path)
    a = alpha(units)
    per, theme, _ = compose(votes["rows"], dirs, sign_table(), rule)
    out = {}
    for fac, entry in per.items():
        fid = int(str(fac).split("|")[0])
        out[fid] = cell(entry, len(theme), a, RU.get(fid, str(fid)), rule)
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
        out[name] = card_yaml(fid, he, cen, fid in gov, "", snap,
                              ax_all.get(fid))
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
    axd = {"arrow": "down", "level": "moderate", "acts": 23,
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
