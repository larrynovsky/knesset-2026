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

Сцепка голосования с законопроектом — ПРЯМЫМ КЛЮЧОМ (с 01.08.2026).

    KNS_PlenumVote(SessionID, ItemID) → KNS_PlmSessionItem(PlenumSessionID,
    ItemID) → если ItemTypeID = 2, то ItemID И ЕСТЬ идентификатор законопроекта.

Прежняя редакция утверждала здесь обратное: «ItemID указывает на пункт
повестки, не на билль», и на этом основании сшивала по нормализованному
VoteTitle. Утверждение опровергнуто замером 31.07 (probe_vote_links): из 7300
пунктов с ItemTypeID=2 в справочнике законопроектов нашлись 7299. Сшивка по
имени давала 212 связей, прямой ключ — около 1805.

Ошибка была не в коде, а в записанном основании, и жила она в докстринге
дольше, чем в поведении: любой следующий читатель принимал вопрос за решённый.
Поэтому строка не удалена, а переписана вместе с историей.

Сшивка по VoteTitle СОХРАНЕНА — но как КОНТРОЛЬ, а не запасной путь. Она
считается параллельно, и расхождение печатается. Оракул: пар, найденных только
именем, обязано быть ноль; потеря хотя бы одной прежней пары останавливает
выгрузку (P18, criteria/declared_before_directkey_2026-08-01.yaml).

Почему контроль, а не удаление: на мосте фракций 31.07 запасной путь оказался
не нужен вовсе — но узнали это, прогнав его и увидев ноль потерь, а не решив
заранее. Контроль удаляют ПОСЛЕ того, как он показал ноль.
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


def load_bills_by_id() -> dict[int, dict]:
    """Те же законопроекты, но по идентификатору — вход прямого ключа.

    Отдельная функция, а не второй возврат load_bills(): у них разные
    потребители. Сшивка по имени — контроль и уйдёт; эта останется.
    """
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    return {m["id"]: m for m in scan["matched"]}


def session_item_types(heads: list[dict]) -> dict[tuple, set]:
    """(сессия, пункт) → множество типов пункта. Основа прямого ключа.

    Сущность целиком — 168 887 строк по всем каденциям. Берётся диапазон
    SessionID НАШИХ голосований: это надмножество нужного по построению —
    любой искомый ключ имеет PlenumSessionID внутри [min, max], поэтому
    сужение не может потерять ни одной искомой пары.

    Один пункт встречается в сессии несколько раз (Ordinal); множество типов
    хранится целиком, потому что неоднозначный тип — это отдельный класс, а не
    повод выбрать любой.
    """
    sids = [h["SessionID"] for h in heads if h.get("SessionID")]
    if not sids:
        raise RuntimeError("у шапок голосований нет SessionID — прямой ключ невозможен")
    lo, hi = min(sids), max(sids)
    print(f"§23 диапазон сессий наших голосований: {lo}–{hi}")
    items = fetch_all("KNS_PlmSessionItem",
                      flt=f"PlenumSessionID ge {lo} and PlenumSessionID le {hi}",
                      select="ItemID,PlenumSessionID,ItemTypeID,ItemTypeDesc")
    print(f"пунктов повестки в диапазоне: {len(items)}")
    typ: dict[tuple, set] = collections.defaultdict(set)
    for it in items:
        typ[(it["PlenumSessionID"], it["ItemID"])].add(it["ItemTypeID"])
    return typ


def link_head(h: dict, typ: dict[tuple, set],
              bills_by_id: dict[int, dict]) -> tuple[str, dict | None]:
    """Прямой ключ для одной шапки голосования: (класс, законопроект или None).

    Классы взаимно исключающие и покрывают ВСЕ шапки — это проверяется в main
    и здесь же тестируется.

    Несущее — САМО наличие двух отсевов, а не их порядок. Первая редакция
    докстринга утверждала, что порядок веток несущий; поломка порядка на
    селф-тесте не покраснела, и утверждение оказалось неверным: при типе,
    содержащем 2 и что-то ещё, обе ветки дают отказ в сшивке, меняется только
    ярлык класса. Записано так, потому что переоценка собственной проверки —
    ровно тот дефект, который этот модуль сегодня и чинил.
    """
    ts = typ.get((h.get("SessionID"), h.get("ItemID")))
    if ts is None:
        return "нет пункта повестки", None
    if len(ts) > 1:
        return "тип пункта неоднозначен", None
    if 2 not in ts:
        return "пункт не законопроект", None
    b = bills_by_id.get(h.get("ItemID"))
    if b is None:
        return "законопроект вне переписи", None
    return "сшито прямым ключом", b


def fetch_headers() -> list[dict]:
    """Шапки голосований 25-го Кнессета. §10: опции «за»/«против» обязательны."""
    flt = f"VoteDateTime ge {K25_START} and VoteDateTime lt {K25_END}"
    print(f"§23 ожидание для KNS_PlenumVote: спрашиваю независимым счётчиком…")
    return fetch_all(
        "KNS_PlenumVote", flt=flt,
        select="Id,VoteDateTime,ItemID,SessionID,VoteTitle,VoteSubject,"
               "IsNoConfidenceInGov,ForOptionDesc,AgainstOptionDesc,VoteStatusDesc")


def _nm(s) -> str:
    return " ".join(str(s or "").split()).strip()


def fetch_faction_bridge() -> tuple[dict, dict]:
    """Два моста от голосующего к фракции. Возвращает (по PersonID, по ФИО).

    ПОЧЕМУ ДВА. MkId в поимённых голосах и PersonID в позициях — РАЗНЫЕ
    пространства идентификаторов, как и предупреждал свод (SOURCES, ловушка 3).
    Первая версия этого скрипта считала их одним: пять проверенных депутатов
    совпали, и я записал «мост есть». Прогон на 2869 голосах дал 22,5% сшивки,
    ШАС получила десять голосов вместо сотен — то есть партийный агрегат был бы
    неверен, а не пуст, и это худший исход.

    Замер (probe_mk_bridge, 20 000 голосов, 120 голосующих — ровно число
    мандатов): прямой мост покрывает 45 из 120 (38%), сшивка по ФИО — 120 из 120
    при НУЛЕ неоднозначностей. Поэтому ФИО — основной путь, а совпадение
    идентификаторов остаётся быстрой проверкой для тех, у кого оно есть.

    Однофамильцы не гадаются: если под одним ФИО несколько персон с фракцией,
    запись не сшивается вовсе и попадает в счётчик несшитых.
    """
    rows = fetch_all("KNS_PersonToPosition", flt=f"KnessetNum eq {K25_NUM}",
                     select="PersonID,FactionID,FactionName,StartDate,FinishDate")
    by_person: dict[int, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if r.get("FactionID"):
            by_person[r["PersonID"]].append(r)

    persons = fetch_all("KNS_Person", select="Id,LastName,FirstName")
    by_name: dict[tuple, set] = collections.defaultdict(set)
    for p in persons:
        if p["Id"] in by_person:
            by_name[(_nm(p.get("LastName")), _nm(p.get("FirstName")))].add(p["Id"])
    return by_person, by_name


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


def resolve_person(by_person: dict, by_name: dict, rec: dict) -> int | None:
    """MkId голоса → PersonID позиций. Сначала прямое совпадение, потом ФИО.

    Возврат None означает «не сшилось» и НИКОГДА не означает «наверное вот этот»:
    неоднозначное ФИО оставляет голос вне партийного агрегата, и он считается.
    """
    mk = rec.get("MkId")
    if mk in by_person:
        return mk
    cands = by_name.get((_nm(rec.get("LastName")), _nm(rec.get("FirstName"))), set())
    return cands.copy().pop() if len(cands) == 1 else None


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

    bills = load_bills()                      # контроль: по имени
    bills_by_id = load_bills_by_id()          # основной путь: по идентификатору
    print(f"наших законопроектов в чек-листе: {len(bills_by_id)} "
          f"(по имени схлопывается до {len(bills)} — дубли имён считаются здесь)")

    heads = fetch_headers()
    print(f"голосований 25-го Кнессета: {len(heads)}")

    # --- сшивка голосование ↔ законопроект ---------------------------------
    # ОСНОВНОЙ ПУТЬ: прямой ключ. КОНТРОЛЬ: имя. См. докстринг модуля.
    typ = session_item_types(heads)
    matched, cls = [], collections.Counter()
    for h in heads:
        klass, b = link_head(h, typ, bills_by_id)
        cls[klass] += 1
        if b is not None:
            matched.append({**h, "bill_id": b["id"], "bill_name": b["name"],
                            "groups": b.get("groups")})

    # Разбиение обязано покрывать ВСЕ заголовки. Неполное разбиение — тихая
    # потеря, а тихая потеря на этом проекте трижды выглядела как аккуратный
    # отчёт. Поэтому отказ, а не строчка в выводе.
    assert sum(cls.values()) == len(heads), (
        f"классы не покрывают все заголовки: {sum(cls.values())} против {len(heads)}")

    bills_hit = {m["bill_id"] for m in matched}
    print("\nСШИВКА ПРЯМЫМ КЛЮЧОМ (SessionID, ItemID → ItemTypeID=2 → BillID):")
    for k, n in cls.most_common():
        print(f"   {n:>6}  {k}")
    print(f"   наших законопроектов найдено: {len(bills_hit)} из {len(bills_by_id)}"
          f" ({len(bills_hit)/max(len(bills_by_id),1):.0%})")

    # --- КОНТРОЛЬ: прежняя сшивка по имени ---------------------------------
    by_name_pairs = set()
    for h in heads:
        b = bills.get(norm_he(h.get("VoteTitle") or ""))
        if b is not None:
            by_name_pairs.add((h["Id"], b["id"]))
    direct_pairs = {(m["Id"], m["bill_id"]) for m in matched}
    only_name = by_name_pairs - direct_pairs
    print(f"\nКОНТРОЛЬ · сшивка по имени: {len(by_name_pairs)} пар · "
          f"прямым ключом: {len(direct_pairs)} · "
          f"найдено ТОЛЬКО именем: {len(only_name)}")

    # P18: прямой ключ обязан быть строго богаче, а не другим. Объявлено до
    # прогона в criteria/declared_before_directkey_2026-08-01.yaml.
    if only_name:
        print("§3/P18 ОТКАЗ: прямой ключ потерял пары, которые находило имя. "
              "Это значит, что ключи не вложены, а расходятся, и вопрос «какой "
              "из двух прав» не решён. Данные наверх не отдаются.")
        print(f"   примеры потерянных пар: {sorted(only_name)[:10]}")
        return 1

    if a.expect_matched is not None:
        ok = abs(len(bills_hit) - a.expect_matched) <= max(5, a.expect_matched * 0.2)
        print(f"   объявлено было {a.expect_matched} — "
              f"{'в пределах' if ok else '⚠ ВНЕ объявленного (§23)'}")
    if not matched:
        print("§23 ОТКАЗ: ни одного совпадения. Прямой ключ не работает — "
              "данные наверх не отдаются.")
        return 1

    by_person, by_name = fetch_faction_bridge()
    print(f"\nмост персона→фракция: {len(by_person)} персон с фракцией, "
          f"{len(by_name)} уникальных ФИО (сшивка по ФИО — основной путь, см. docstring)")

    targets = matched[:a.limit_votes] if a.limit_votes else matched
    print(f"выкачиваю поимённые по {len(targets)} голосованиям…\n")

    rows, unbridged = [], collections.Counter()
    for i, h in enumerate(targets, 1):
        named = fetch_named_votes(h["Id"])
        by_fac: dict = collections.defaultdict(collections.Counter)
        for r in named:
            pid = resolve_person(by_person, by_name, r)
            fac = faction_at(by_person, pid, r.get("VoteDate") or "") if pid else None
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
        "link_method": "direct_key:(SessionID,ItemID)->KNS_PlmSessionItem.ItemTypeID=2",
        "link_classes": dict(cls),
        "control_by_name_pairs": len(by_name_pairs),
        "control_only_name_pairs": len(only_name),
        "matched_votes": len(matched), "matched_bills": len(bills_hit),
        "bills_in_checklist": len(bills_by_id),
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

    # resolve_person: прямой id важнее ФИО, однофамильцы не гадаются
    by_name = {("כהן", "יעקב"): {7}, ("לוי", "משה"): {11, 12}}
    assert resolve_person(bridge, by_name, {"MkId": 7, "LastName": "кто-то"}) == 7, \
        "прямое совпадение id обязано срабатывать первым"
    assert resolve_person(bridge, by_name,
                          {"MkId": 99999, "LastName": "כהן", "FirstName": "יעקב"}) == 7, \
        "сшивка по ФИО не сработала — а она покрывает 120 из 120 голосующих"
    assert resolve_person(bridge, by_name,
                          {"MkId": 99999, "LastName": "לוי", "FirstName": "משה"}) is None, \
        "однофамильцы обязаны давать None: догадка приписала бы голос чужой партии"
    assert resolve_person(bridge, by_name,
                          {"MkId": 99999, "LastName": "אין", "FirstName": "כזה"}) is None, \
        "неизвестное ФИО обязано давать None"

    # link_head: прямой ключ. Красное здесь = голосование приписано не тому
    # закону, либо пункт-не-законопроект молча сошёл за законопроект.
    # ВСЕ отрицательные случаи лежат В ПЕРЕПИСИ. Первая редакция этого теста
    # брала их снаружи, и он был зелёным даже когда обе проверки снимали: пункт
    # не сшивался не потому, что тип неверен, а потому что акта нет в переписи.
    # Негативный контроль обязан быть сопоставим по мощности с позитивным.
    typ = {(500, 1042100): {2},          # чистый законопроект
           (500, 1057405): {2, 7},       # тип неоднозначен, акт В ПЕРЕПИСИ
           (500, 1057406): {7},          # не законопроект, акт В ПЕРЕПИСИ
           (500, 900001): {2}}           # чистый тип 2, но акта нет в переписи
    corpus = {i: {"id": i, "name": f"акт {i}", "groups": None}
              for i in (1042100, 1057405, 1057406)}
    assert link_head({"SessionID": 500, "ItemID": 1042100}, typ, corpus) \
        == ("сшито прямым ключом", corpus[1042100]), "чистый тип 2 обязан сшиваться"
    assert link_head({"SessionID": 500, "ItemID": 1057405}, typ, corpus)[1] is None, \
        "неоднозначный тип обязан отсекаться: иначе пункт «и закон, и что-то ещё» " \
        "приписал бы голосование закону, которого в нём не обсуждали"
    assert link_head({"SessionID": 500, "ItemID": 1057406}, typ, corpus)[1] is None, \
        "пункт не-законопроект обязан не сшиваться, даже если ItemID есть в переписи"
    assert link_head({"SessionID": 500, "ItemID": 900001}, typ, corpus) \
        == ("законопроект вне переписи", None), "чужой закон не входит в корпус"
    assert link_head({"SessionID": 999, "ItemID": 1042100}, typ, corpus)[0] \
        == "нет пункта повестки", "чужая сессия не имеет права дать связь"
    # покрытие: пять входов дают пять РАЗНЫХ классов, ни один не схлопывается
    seen = {link_head({"SessionID": s, "ItemID": i}, typ, corpus)[0]
            for s, i in [(500, 1042100), (500, 1057405), (500, 1057406),
                         (500, 900001), (999, 1)]}
    assert len(seen) == 5, f"классы обязаны различаться, получено {seen}"

    print("самопроверка fetch_votes пройдена: 14 утверждений (8 мост, 6 прямой ключ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
