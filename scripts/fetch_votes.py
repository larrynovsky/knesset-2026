#!/usr/bin/env python3
"""Канал А, недостающее звено: КТО КАК ГОЛОСОВАЛ (§9, §10, §23).

До 30.07 в проекте не было ни одной поимённой записи голосования. Классификация
направления описывала СВОЙСТВО ЗАКОНА; чтобы карточка сказала «партия X
голосовала за акт, ослабляющий сдержки», нужен этот скрипт.

Что здесь сделано и почему именно так:

§9  — только OdataV4/ParliamentInfo. Запрещённый сводом легаси-эндпоинт отдаёт
      HTTP 200 и ноль записей за 25-й Кнессет; адрес здесь не называется даже
      в комментарии — pre-commit ловит его подстрокой, и это правильнее, чем
      точный grep: имя в комментарии рано или поздно переезжает в код.
      Выгрузка идёт через guarded_fetch, где адрес зашит.
§10 — ForOptionDesc/AgainstOptionDesc сохраняются ВСЕГДА. Без них «за» не имеет
      смысла: в одном голосовании это «принять закон», в другом «отклонить
      предложение». Классификация без чтения этих полей запрещена.
§23 — три сверки объёма, каждая объявлена до выгрузки:
      шапки голосований, мост персона→фракция, поимённые по каждому голосованию.

Мост MkId ↔ фракция. SOURCES утверждал «моста Person.Id ↔ vip_id в API НЕТ».
Разведка 30.07 (probe_votes_shape/probe_votes_join) показала иное: MkId из
KNS_PlenumVoteResult совпадает с KNS_PersonToPosition.PersonID у подавляющего
большинства депутатов 25-го Кнессета. Утверждение свода уточнено данными,
но НЕ отменено: несшитые остаются, они считаются и печатаются, а не прячутся.

Сцепка голосования с законопроектом — по VoteTitle. ItemID указывает на пункт
повестки, не на билль; VoteSubject у 25-го Кнессета пуст у части записей, тогда
как VoteTitle заполнен у всех 200 проверенных и содержит название законопроекта
дословно. Сшивка идёт по нормализованному ивриту (та же функция, что проверяет
цитаты в classify_direction) и объявляет ожидание до сверки.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import norm_he          # noqa: E402  та же нормализация, что у цитат
from guarded_fetch import fetch_all, count      # noqa: E402  §23

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "data" / "bills_scan.json"
OUT = ROOT / "data" / "votes_25.json"

# Границы 25-го Кнессета. Проверено 2026-07-27, записано в SOURCES.
# KNS_PlenumVote НЕ имеет поля KnessetNum — режется по дате, и это ловушка,
# а не удобство: сдвиг границы на день тихо меняет корпус.
K25_START = "2022-11-15T00:00:00Z"
K25_END = "2026-07-18T00:00:00Z"
K25_NUM = 25


def load_bills() -> dict[str, dict]:
    """Наши законопроекты: нормализованное имя → запись из чек-листа."""
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    out = {}
    for m in scan["matched"]:
        n = norm_he(m["name"])
        if n:
            out.setdefault(n, m)          # первое вхождение; дубли имён считаем ниже
    return out


def fetch_headers() -> list[dict]:
    """Шапки голосований 25-го Кнессета. §10: опции «за»/«против» обязательны."""
    flt = f"VoteDateTime ge {K25_START} and VoteDateTime lt {K25_END}"
    print(f"§23 ожидание для KNS_PlenumVote: спрашиваю независимым счётчиком…")
    return fetch_all(
        "KNS_PlenumVote", flt=flt,
        select="Id,VoteDateTime,ItemID,SessionID,VoteTitle,VoteSubject,"
               "IsNoConfidenceInGov,ForOptionDesc,AgainstOptionDesc,VoteStatusDesc")


def fetch_faction_bridge() -> dict[int, list[dict]]:
    """PersonID → список членств во фракциях с датами (25-й Кнессет).

    Даты нужны не для красоты: §1 требует единицу «партия × период», и депутат,
    сменивший фракцию в середине каденции, обязан считаться по той фракции,
    в которой он состоял НА ДАТУ ГОЛОСОВАНИЯ, а не по последней.
    """
    rows = fetch_all("KNS_PersonToPosition", flt=f"KnessetNum eq {K25_NUM}",
                     select="PersonID,FactionID,FactionName,StartDate,FinishDate")
    bridge: dict[int, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if r.get("FactionID"):
            bridge[r["PersonID"]].append(r)
    return bridge


def faction_at(bridge: dict[int, list[dict]], person: int, when: str):
    """Фракция депутата НА ДАТУ голосования. None — если моста нет вовсе."""
    memberships = bridge.get(person)
    if not memberships:
        return None
    d = when[:10]
    for m in memberships:
        start = (m.get("StartDate") or "")[:10]
        finish = (m.get("FinishDate") or "9999-12-31")[:10]
        if start <= d <= finish:
            return (m["FactionID"], (m.get("FactionName") or "").strip())
    # Дат не хватило: у части записей FinishDate пуст, а StartDate позже голоса.
    # Возвращаем единственное членство, если оно одно, иначе честный None —
    # догадка о партии хуже отсутствия записи.
    uniq = {(m["FactionID"], (m.get("FactionName") or "").strip()) for m in memberships}
    return uniq.pop() if len(uniq) == 1 else None


def fetch_named_votes(vote_id: int) -> list[dict]:
    """Поимённые по одному голосованию. §23: ожидание берётся счётчиком."""
    return fetch_all("KNS_PlenumVoteResult", flt=f"VoteID eq {vote_id}",
                     select="MkId,VoteID,VoteDate,ResultCode,ResultDesc,LastName,FirstName")


# Коды результата 25-го Кнессета (SOURCES): 6 присутствовал · 7 за · 8 против
# · 9 воздержался · 10 отсутствовал. С легаси-схемой НЕ совпадают.
RESULT = {6: "present", 7: "for", 8: "against", 9: "abstain", 10: "absent"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-matched", type=int, default=None,
                    help="§23: сколько наших законопроектов ожидаем найти среди "
                         "голосований. Объявляется ДО прогона.")
    ap.add_argument("--limit-votes", type=int, default=0,
                    help="сколько сшитых голосований выкачать поимённо (0 = все)")
    a = ap.parse_args()

    bills = load_bills()
    print(f"наших законопроектов в чек-листе: {len(bills)} (по нормализованному имени)")

    heads = fetch_headers()
    print(f"голосований 25-го Кнессета: {len(heads)}")

    # --- сшивка голосование ↔ законопроект ---------------------------------
    matched, unmatched_titles = [], 0
    for h in heads:
        n = norm_he(h.get("VoteTitle") or "")
        b = bills.get(n)
        if b is None:
            unmatched_titles += 1
            continue
        matched.append({**h, "bill_id": b["id"], "bill_name": b["name"],
                        "groups": b.get("groups")})
    bills_hit = {m["bill_id"] for m in matched}
    print(f"\nСШИВКА ПО НАЗВАНИЮ (VoteTitle ↔ имя законопроекта):")
    print(f"   голосований сшито: {len(matched)} · не сшито: {unmatched_titles}")
    print(f"   наших законопроектов найдено: {len(bills_hit)} из {len(bills)}"
          f" ({len(bills_hit)/max(len(bills),1):.0%})")
    if a.expect_matched is not None:
        ok = abs(len(bills_hit) - a.expect_matched) <= max(5, a.expect_matched * 0.2)
        print(f"   объявлено было {a.expect_matched} — "
              f"{'в пределах' if ok else '⚠ ВНЕ объявленного (§23)'}")
    if not matched:
        print("§23 ОТКАЗ: ни одного совпадения. Сшивка по названию не работает — "
              "данные наверх не отдаются.")
        return 1

    bridge = fetch_faction_bridge()
    print(f"\nмост персона→фракция: {len(bridge)} персон 25-го Кнессета")

    targets = matched[:a.limit_votes] if a.limit_votes else matched
    print(f"выкачиваю поимённые по {len(targets)} голосованиям…\n")

    rows, unbridged = [], collections.Counter()
    for i, h in enumerate(targets, 1):
        named = fetch_named_votes(h["Id"])
        by_fac: dict = collections.defaultdict(collections.Counter)
        for r in named:
            fac = faction_at(bridge, r.get("MkId"), r.get("VoteDate") or "")
            if fac is None:
                unbridged[r.get("MkId")] += 1
                continue
            by_fac[fac][RESULT.get(r.get("ResultCode"), "other")] += 1
        rows.append({
            "vote_id": h["Id"], "date": h["VoteDateTime"],
            "bill_id": h["bill_id"], "bill_name": h["bill_name"],
            "groups": h.get("groups"),
            # §10: без этих двух полей знак голоса не имеет смысла
            "for_option_desc": h.get("ForOptionDesc"),
            "against_option_desc": h.get("AgainstOptionDesc"),
            "no_confidence": h.get("IsNoConfidenceInGov"),
            "status": h.get("VoteStatusDesc"),
            "named_total": len(named),
            "by_faction": {f"{fid}|{fname}": dict(c) for (fid, fname), c in by_fac.items()},
        })
        if i % 25 == 0 or i == len(targets):
            print(f"   [{i}/{len(targets)}] голосов собрано {sum(r['named_total'] for r in rows)}")

    total_named = sum(r["named_total"] for r in rows)
    lost = sum(unbridged.values())
    print(f"\nПОИМЁННЫХ ГОЛОСОВ: {total_named}")
    print(f"НЕ СШИЛИСЬ С ФРАКЦИЕЙ: {lost} голосов от {len(unbridged)} персон "
          f"({lost/max(total_named,1):.1%})")
    if unbridged:
        print(f"   MkId без моста (топ): {[m for m, _ in unbridged.most_common(8)]}")
        print("   Это НЕ округляется до нуля: их голоса не попадают ни в одну партию,")
        print("   и доля выше нескольких процентов делает партийный агрегат неполным.")

    facs = collections.Counter()
    for r in rows:
        for key, c in r["by_faction"].items():
            facs[key] += sum(c.values())
    print("\nфракции в собранных голосованиях:")
    for key, n in facs.most_common():
        print(f"   {key:44} голосов {n}")

    OUT.write_text(json.dumps({
        "at": datetime.now(timezone.utc).isoformat(),
        "knesset": K25_NUM, "window": [K25_START, K25_END],
        "headers_total": len(heads),
        "matched_votes": len(matched), "matched_bills": len(bills_hit),
        "bills_in_checklist": len(bills),
        "expected_matched_bills": a.expect_matched,
        "named_total": total_named,
        "unbridged_votes": lost, "unbridged_persons": len(unbridged),
        "rows": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{OUT}")
    return 0


def selftest() -> int:
    """Оракул механики. Красное здесь = фракция депутата определяется неверно,
    и партийный агрегат молча приписывает голоса не той партии."""
    bridge = {
        7: [{"FactionID": 1095, "FactionName": "ש\"ס",
             "StartDate": "2022-11-15T00:00:00", "FinishDate": "2024-01-01T00:00:00"},
            {"FactionID": 1096, "FactionName": "הליכוד",
             "StartDate": "2024-01-02T00:00:00", "FinishDate": None}],
        8: [{"FactionID": 1101, "FactionName": "יהדות התורה",
             "StartDate": "2030-01-01T00:00:00", "FinishDate": None}],
    }
    assert faction_at(bridge, 7, "2023-05-01T10:00:00+03:00")[0] == 1095, \
        "голос до перехода приписан не той фракции"
    assert faction_at(bridge, 7, "2025-05-01T10:00:00+03:00")[0] == 1096, \
        "голос после перехода приписан не той фракции"
    assert faction_at(bridge, 8, "2023-05-01T10:00:00+03:00")[0] == 1101, \
        "единственное членство обязано применяться, даже если даты не покрыли"
    assert faction_at(bridge, 999, "2023-05-01T10:00:00+03:00") is None, \
        "персона без моста обязана давать None, а не догадку"
    print("самопроверка fetch_votes пройдена: 4 утверждения")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
