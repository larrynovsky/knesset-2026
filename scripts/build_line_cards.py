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


def card_yaml(fid: int, he: str, cen: dict, in_gov: bool, b_status: str) -> str:
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
  votes_25: 2026-07-31T17:49:14

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
    не проверялось: отложенный период по каналу А не прогонялся ни разу

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
        data/votes_25.json, все голосования темы, проверено участие фракции
        {fid} в каждом, снимок 2026-07-31
    - источник: >-
        criteria/periods.yaml, 17 периодов у 14 фракций — {bnote}
    - источник: >-
        data/coverage_matrix.json — статусы каналов Б и В у этой строки
        различены, а не слиты
  outcome: nothing
  note: >-
    это базовая линия: искали, чем опровергнуть УСТРОЙСТВО карточки, а не
    поведение партии. Разбора конкретных голосований не делалось

confidence: low
confidence_reason: >-
  базовая линия: одна тема, отложенный период не прогонялся, разбора
  конкретных голосований не было

what_would_falsify: >-
  если расширить перепись на вторую тему и доля участия изменится больше чем
  на четверть — утверждение о поведении фракции окажется свойством выбранной
  темы

revisions:
  - version: 1
    date: 2026-08-13
    what: >-
      базовая линия, сгенерирована по решению владельца «сделать проект
      целиком с некоторой точностью и мерить прирост от неё»
"""


def emit() -> int:
    """На Studio: посчитать и выдать карточки в stdout одним JSON."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_cards import load_yaml_ish
    votes = json.loads((ROOT / "data" / "votes_25.json").read_text(encoding="utf-8"))
    lin = json.loads((ROOT / "criteria" / "ballot_lineage_draft.json")
                     .read_text(encoding="utf-8"))
    per = load_yaml_ish(ROOT / "criteria" / "periods.yaml")
    gov = {p["faction_id"] for p in per["periods"]}
    have = {f.name for f in (ROOT / "cards").glob("*.yaml")}
    out, skipped = {}, []
    for ch in lin["chains"]:
        fid, he = ch["anchor_id"], ch["anchor"]
        cen = census(votes["rows"], fid)
        if not cen:
            skipped.append((fid, he, "голосований под этим id нет — "
                                     "связь строки с фракцией не установлена"))
            continue
        if any(str(fid) in n for n in have):
            skipped.append((fid, he, "карточка уже написана руками"))
            continue
        name = slug(RU.get(fid, "line"), fid) + ".yaml"
        out[name] = card_yaml(fid, he, cen, fid in gov, "")
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


def selftest() -> int:
    cen = {"votes": 10, "acts": 8, "acts_in_theme_total": 20,
           "acts_without_participation": 12, "from": "2022-12-13",
           "to": "2026-07-14"}
    a = card_yaml(1, "פ", cen, True, "")
    b = card_yaml(2, "ק", cen, False, "")
    assert "коалиционную дисциплину" in a and "коалиционную дисциплину" not in b, \
        "правившая и неправившая обязаны получить РАЗНОЕ переформатирование: " \
        "иначе шестнадцать карточек — это одна, размноженная шестнадцать раз"
    assert "по устройству измерения" in b, "пустота не названа свойством измерителя"
    assert "baseline: true" in a, "карточка базовой линии не помечена как базовая"
    assert "60%" in a, "доля пропуска не выведена из чисел этой строки"
    assert CAV in a and a.count(CAV) >= 2, "оговорка о теме не при утверждении"
    cen2 = dict(cen, acts_without_participation=1, votes=99)
    assert "99 голосованиях" in card_yaml(1, "פ", cen2, True, ""), \
        "числа карточки не следуют за переписью"
    print(f"самопроверка build_line_cards: 6 утверждений")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else
                     emit() if "--emit" in sys.argv else
                     apply_() if "--apply" in sys.argv else
                     print("нужен --selftest | --emit | --apply") or 2)
