#!/usr/bin/env python3
"""Покрытие бюллетеня: строка × канал × статус наблюдаемости.

ЗАЧЕМ. Три недели прогресс проекта мерился долей классифицированных актов —
величиной, которая может дойти до ста процентов и не дать ни одной строки
бюллетеня. 13.08 разовый счёт показал, что канал А покрывает 15 строк из 16,
канал Б одну, канал В ноль. Такой счёт обязан жить в репозитории (§14), иначе
он повторит судьбу вердикта «канал А не даёт направления»: число в переписке,
механизма нет, из чистого клона не получается.

СТАТУСЫ — те же четыре, что у §7, и это не совпадение. Вопрос «что у нас есть
по этой партии» и вопрос «имеем ли мы право на вывод» — один вопрос:

    observed            смотрели, свидетельства есть — только отсюда вывод
    not_exposed         партия не могла быть наблюдаема в этом канале
    source_missing      источник обязан был дать и не дал; это авария
    lineage_unresolved  связь строки со фракцией не установлена

Различение not_exposed и source_missing — центральное. Пока они слиты,
невыгруженный источник неотличим от отсутствия полномочий, и технический
долг превращается в политический вывод. Канал В сейчас — ровно этот случай:
ноль записей означает «не выгружали», а НЕ «партии ничего не делали».

ЧЕГО ЭТОТ СКРИПТ НЕ ДЕЛАЕТ. Не решает, не выбирает, не ходит в сеть и не
судит о качестве. Он считает наличие носителя — ту же границу, что §24
называет честной: зелёная клетка доказывает, что данные есть, а не что они
осмысленны.

    python3 scripts/coverage_matrix.py --selftest
    python3 scripts/coverage_matrix.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import n_asserts            # noqa: E402
from validate_cards import load_yaml_ish            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LINEAGE = ROOT / "criteria" / "ballot_lineage_draft.json"
PERIODS = ROOT / "criteria" / "periods.yaml"
VOTES = ROOT / "data" / "votes_25.json"
CARDS = ROOT / "cards"
OUT = ROOT / "data" / "coverage_matrix.json"

OBSERVED, NOT_EXPOSED, SOURCE_MISSING, UNRESOLVED = (
    "observed", "not_exposed", "source_missing", "lineage_unresolved")


def gov_faction_ids(periods: dict) -> set:
    """Фракции с хотя бы одним периодом в правительстве.

    Разбор — общим разборщиком карточек, а не своей регуляркой: он отказывает
    на незнакомой конструкции вместо тихого пропуска, и это ровно то свойство,
    которое здесь нужно. Пустой результат при непустом файле — отказ ниже.
    """
    return {p["faction_id"] for p in periods.get("periods", [])
            if p.get("faction_id") is not None}


def votes_index(votes: dict) -> dict:
    """faction_id -> {голосований, актов}. Ключ голосований — «id|название»."""
    idx: dict[int, dict] = {}
    for row in votes.get("rows", []):
        for key in (row.get("by_faction") or {}):
            fid, _, name = str(key).partition("|")
            if not fid.isdigit():
                continue
            cell = idx.setdefault(int(fid), {"votes": 0, "acts": set(),
                                             "name": name})
            cell["votes"] += 1
            if row.get("bill_id"):
                cell["acts"].add(row["bill_id"])
    for cell in idx.values():
        cell["acts"] = len(cell["acts"])
    return idx


def channel_a(anchor_id: int, idx: dict) -> tuple:
    """Голосования. Ноль — это НЕ «партия не голосовала»."""
    cell = idx.get(anchor_id)
    if cell:
        return OBSERVED, f"{cell['votes']} голосований, {cell['acts']} актов"
    return UNRESOLVED, ("под этим id голосований в выгрузке нет; сказать "
                        "«фракция не голосовала» мы не имеем права")


def channel_b(anchor_id: int, gov: set, maps: dict) -> tuple:
    """Деньги. Канал покрывает только подписавших соглашение — это его предел,
    а не наша недоработка, и потому not_exposed, а не source_missing."""
    if anchor_id in maps:
        return OBSERVED, f"{maps[anchor_id]} обязательств сопоставлено"
    if anchor_id not in gov:
        return NOT_EXPOSED, ("ноль периодов в правительстве: соглашения нет "
                             "по устройству канала, а не по нашей вине")
    return SOURCE_MISSING, "партия правила, сопоставление не построено"


def channel_c(anchor_id: int, gov: set) -> tuple:
    """Должности. Источник существует, публикуется ежегодно и не выгружался
    ни разу. Поэтому у ВСЕХ строк здесь source_missing — включая партии,
    никогда не бывшие в правительстве.

    Соблазн был поставить им not_exposed: у них и правда нет портфелей.
    Это была бы ошибка того самого класса, ради которого §7 разделяет два
    статуса: пока источник не выгружен, мы не знаем, что в нём про них
    написано, — годовой отчёт канцелярии премьера перечисляет исполнение
    решений правительства, а не только министров. Ноль от невыгрузки нельзя
    называть нулём по существу.
    """
    return SOURCE_MISSING, "источник не выгружался ни разу (PDF, годовой отчёт)"


def build(lineage: dict, votes: dict, periods: dict, maps: dict) -> dict:
    idx = votes_index(votes)
    gov = gov_faction_ids(periods)
    rows = []
    for ch in lineage["chains"]:
        aid = ch["anchor_id"]
        a, a_note = channel_a(aid, idx)
        b, b_note = channel_b(aid, gov, maps)
        c, c_note = channel_c(aid, gov)
        rows.append({"anchor_id": aid, "line": ch["anchor"],
                     "chain_len": len(ch.get("chain") or []),
                     "a": {"status": a, "note": a_note},
                     "b": {"status": b, "note": b_note},
                     "c": {"status": c, "note": c_note}})
    seen = {ch["anchor_id"] for ch in lineage["chains"]}
    orphans = [{"faction_id": f, "name": cell["name"], "votes": cell["votes"]}
               for f, cell in sorted(idx.items()) if f not in seen]
    return {"lines": rows, "unmatched_factions": orphans,
            "counts": {"lines": len(rows),
                       "a_observed": sum(r["a"]["status"] == OBSERVED for r in rows),
                       "b_observed": sum(r["b"]["status"] == OBSERVED for r in rows),
                       "c_observed": sum(r["c"]["status"] == OBSERVED for r in rows)}}


MARK = {OBSERVED: "есть", NOT_EXPOSED: "не экспонирована",
        SOURCE_MISSING: "ИСТОЧНИКА НЕТ", UNRESOLVED: "связь не установлена"}


def render(m: dict) -> str:
    w = max(len(r["line"][:44]) for r in m["lines"])
    out = [f"{'строка бюллетеня'.ljust(w)} | {'А голосования':<22} | "
           f"{'Б деньги':<18} | В должности"]
    for r in m["lines"]:
        out.append(f"{r['line'][:44].ljust(w)} | "
                   f"{MARK[r['a']['status']]:<22} | "
                   f"{MARK[r['b']['status']]:<18} | {MARK[r['c']['status']]}")
    c = m["counts"]
    out.append("")
    out.append(f"строк {c['lines']}: канал А наблюдаем у {c['a_observed']}, "
               f"Б у {c['b_observed']}, В у {c['c_observed']}")
    if m["unmatched_factions"]:
        out.append(f"фракций с голосованиями вне всех цепочек: "
                   f"{len(m['unmatched_factions'])}")
        for o in m["unmatched_factions"]:
            out.append(f"   {o['votes']:>4}  {o['faction_id']}  {o['name'][:50]}")
    return "\n".join(out)


def selftest() -> int:
    lin = {"chains": [
        {"anchor_id": 1, "anchor": "правившая с картой", "chain": [{}, {}]},
        {"anchor_id": 2, "anchor": "правившая без карты", "chain": [{}]},
        {"anchor_id": 3, "anchor": "никогда не правившая", "chain": [{}]},
        {"anchor_id": 4, "anchor": "без голосований", "chain": [{}]}]}
    votes = {"rows": [
        {"bill_id": 10, "by_faction": {"1|А": {}, "2|Б": {}, "3|В": {}}},
        {"bill_id": 11, "by_faction": {"1|А": {}, "3|В": {}}},
        {"bill_id": 11, "by_faction": {"9|Чужая": {}}}]}
    periods = {"periods": [{"faction_id": 1}, {"faction_id": 2}]}
    m = build(lin, votes, periods, {1: 21})

    # ГЛАВНЫЙ ОРАКУЛ: строка без данных обязана ОСТАТЬСЯ в таблице со
    # статусом. Исчезновение строки — тот самый способ, которым отчёт о
    # покрытии врёт в свою пользу: знаменатель уменьшается вместе с
    # числителем, и доля растёт от потери данных.
    assert len(m["lines"]) == len(lin["chains"]), \
        "строка выпала из матрицы — покрытие посчитано по уцелевшим"
    assert [r["anchor_id"] for r in m["lines"]] == [1, 2, 3, 4], \
        "порядок строк обязан повторять объявленную преемственность"

    by = {r["anchor_id"]: r for r in m["lines"]}
    assert by[4]["a"]["status"] == UNRESOLVED, \
        "ноль голосований — это «связь не установлена», а не «не голосовала»"
    assert by[1]["a"]["status"] == OBSERVED and "2 голосований" in by[1]["a"]["note"]
    assert by[1]["b"]["status"] == OBSERVED
    assert by[2]["b"]["status"] == SOURCE_MISSING, \
        "партия правила, карты нет — это авария, а не отсутствие полномочий"
    assert by[3]["b"]["status"] == NOT_EXPOSED, \
        "ноль периодов в правительстве — предел канала, а не наша недоработка"
    assert by[2]["b"]["status"] != by[3]["b"]["status"], \
        "СЛИЯНИЕ ЭТИХ ДВУХ СТАТУСОВ И ЕСТЬ ЗАПРЕЩЁННОЕ §7: невыгруженный " \
        "источник стал бы неотличим от отсутствия полномочий"

    # Канал В: ни одной not_exposed, даже у никогда не правившей.
    assert all(r["c"]["status"] == SOURCE_MISSING for r in m["lines"]), \
        "источник канала В не выгружался — ноль здесь наш, а не партийный"

    # Фракция с голосованиями вне всех цепочек не имеет права пропасть.
    assert [o["faction_id"] for o in m["unmatched_factions"]] == [9], \
        "фракция вне цепочек обязана быть названа: потеря в эту сторону " \
        "выглядит как полное покрытие"
    assert m["counts"]["a_observed"] == 3 and m["counts"]["c_observed"] == 0

    txt = render(m)
    for r in m["lines"]:
        assert r["line"][:44] in txt, "строка не дошла до печати"
    assert "9" in txt and "Чужая" in txt, "несопоставленная фракция не напечатана"
    print(f"самопроверка coverage_matrix: {n_asserts(selftest)} утверждений")
    return 0


def commitment_maps() -> dict:
    """faction_id -> число сопоставленных обязательств. Ключ берётся из
    period_id карточки-источника («1095-gov37»), а не из имени файла."""
    out = {}
    for p in sorted((ROOT / "data").glob("commitment_map_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        pid = str(d.get("period_id") or "")
        head = pid.split("-", 1)[0]
        if head.isdigit():
            out[int(head)] = len(d.get("items") or [])
    return out


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    missing = [p for p in (LINEAGE, PERIODS, VOTES) if not p.exists()]
    if missing:
        print("нет входа, матрица не считается: "
              + ", ".join(str(p) for p in missing))
        print("  Это отказ, а не пустая таблица: пустая таблица здесь")
        print("  неотличима от «покрытия нет» (§7).")
        return 2
    periods = load_yaml_ish(PERIODS)
    if not gov_faction_ids(periods):
        print(f"ОТКАЗ: {PERIODS} разобран, но ни одного faction_id — "
              "разбор молча деградировал, а не файл опустел")
        return 1
    m = build(json.loads(LINEAGE.read_text(encoding="utf-8")),
              json.loads(VOTES.read_text(encoding="utf-8")),
              periods, commitment_maps())
    m["source"] = {"lineage": LINEAGE.name, "votes_at":
                   json.loads(VOTES.read_text(encoding="utf-8")).get("at"),
                   "cards": len(list(CARDS.glob("*.yaml")))}
    OUT.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(render(m))
    print(f"\nкарточек в репозитории: {m['source']['cards']}")
    print(f"снимок голосований: {m['source']['votes_at']}")
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
