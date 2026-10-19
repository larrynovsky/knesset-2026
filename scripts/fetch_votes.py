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
import re
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
# Горизонт ставится там, где кончились данные, а не там, где кончился
# календарь. Счётчик источника 07.10.2026: после 18.07 — 22 голосования, все
# одним заседанием 28.07; после 01.09 — ноль. Прежняя граница 2026-07-18
# отрезала последнее заседание 25-го Кнессета.
K25_END = "2026-09-01T00:00:00Z"
K25_NUM = 25

# Временные срезы (владелец 19.10: «с 2016 или ближайшей каденции до него»).
# Окно Кнессета N = [PlenumStart первого пленума N, PlenumStart первого пленума N+1)
# по KNS_KnessetDates, прочитано 19.10.2026 — второй путь к границам (KNS-L006),
# не календарь из головы. У KNS_PlenumVote нет KnessetNum: сдвиг на день тихо
# меняет корпус, поэтому даты здесь и только здесь.
WINDOWS = {
    20: ("2015-03-31T00:00:00Z", "2019-04-30T00:00:00Z"),
    21: ("2019-04-30T00:00:00Z", "2019-10-03T00:00:00Z"),
    22: ("2019-10-03T00:00:00Z", "2020-03-16T00:00:00Z"),
    23: ("2020-03-16T00:00:00Z", "2021-04-06T00:00:00Z"),
    24: ("2021-04-06T00:00:00Z", "2022-11-15T00:00:00Z"),
    25: (K25_START, K25_END),
}


def use_knesset(n: int) -> None:
    """Переключить модуль на Кнессет n. 25 — прежнее поведение байт в байт."""
    global SCAN, OUT, K25_START, K25_END, K25_NUM, NAMED_CACHE
    if n not in WINDOWS:
        raise SystemExit(f"Кнессет {n} вне WINDOWS {sorted(WINDOWS)}")
    K25_START, K25_END = WINDOWS[n]
    K25_NUM = n
    if n != 25:
        SCAN = ROOT / "data" / f"bills_scan_{n}.json"
        OUT = ROOT / "data" / f"votes_{n}.json"
        # Отдельный кэш: arrow_robustness хеширует data/named_votes_cache/* как вход
        # 25-го, и выгрузка срезов, пишущая туда, роняла бы его кэш и make report.
        NAMED_CACHE = ROOT / "data" / "named_votes_cache_slices"


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


def cache_is_valid(meta: dict, flt: str, expected: int) -> tuple[bool, str]:
    """Годен ли кэш выгрузки. Чистая функция — вся развилка здесь и проверяема.

    Механизм — не срок жизни, а сверка независимым счётчиком. Аренда (lease,
    Таненбаум §7.4.3) — обещание свежести на время, после которого клиент
    обязан опросить сервер. Здесь сервер ничего не проталкивает, поэтому
    времени доверять нечему: кэш недельной давности может быть точен, а
    часовой — устареть. Вместо срока спрашивается `$count` с тем же фильтром,
    и это тот же оракул, которому §23 уже доверяет при выгрузке.

    ЧЕСТНАЯ ГРАНИЦА, названная сразу: счётчик ловит добавление и удаление
    записей, но НЕ правку существующей. Строка, у которой сменился
    ItemTypeID, оставит счётчик неизменным и пройдёт как свежая. Закрывается
    сверкой max(LastUpdatedDate) — не сделано, потому что это второй запрос
    ради класса отказа, которого мы пока не наблюдали. `--no-cache` есть.
    """
    if meta.get("flt") != flt:
        return False, "фильтр другой"
    got = meta.get("count")
    if got != expected:
        return False, f"счётчик разошёлся: в кэше {got}, на сервере {expected}"
    if not meta.get("rows"):
        return False, "кэш пуст"
    return True, f"счётчик сошёлся: {expected}"


def session_item_types(heads: list[dict], use_cache: bool = True) -> dict[tuple, set]:
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
    flt = f"PlenumSessionID ge {lo} and PlenumSessionID le {hi}"
    print(f"§23 диапазон сессий наших голосований: {lo}–{hi}")

    # Кэш: 13 402 записи, десять минут выгрузки, и они не меняются между
    # прогонами одного дня. За 01.08.2026 эта выгрузка была повторена четыре
    # раза — сорок минут ожидания одного и того же. Правило годности — в
    # cache_is_valid, там же его граница.
    cf = ROOT / "data" / f"plm_session_items_{lo}_{hi}.json"
    items = None
    if use_cache:
        expected = count("KNS_PlmSessionItem", flt)
        if cf.exists():
            meta = json.loads(cf.read_text(encoding="utf-8"))
            ok, why = cache_is_valid(meta, flt, expected)
            print(f"кэш пунктов повестки: {'ГОДЕН' if ok else 'НЕГОДЕН'} — {why}")
            if ok:
                items = meta["rows"]
        else:
            print("кэш пунктов повестки: нет файла")
    if items is None:
        items = fetch_all("KNS_PlmSessionItem", flt=flt,
                          select="ItemID,PlenumSessionID,ItemTypeID,ItemTypeDesc")
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps({"flt": flt, "count": len(items), "rows": items},
                                 ensure_ascii=False), encoding="utf-8")
        print(f"кэш пунктов повестки записан: {cf.name}")
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


def law_head(name: str) -> str:
    """Имя закона до первой скобки: «какой закон», без «какая поправка».

    `חוק יסוד: הממשלה (תיקון - כשירות)` и `חוק יסוד: הממשלה (תיקון מס' 3)` —
    один закон, разные поправки. Их одинаковый `law_head` не делает их одним
    актом и НЕ является основанием склеить: он только объясняет, почему
    голосование могло попасть в один пункт повестки с другой поправкой.
    """
    return norm_he(re.split(r"[(（]", name or "", 1)[0])


def classify_divergence(by_name_pairs: set, direct: dict,
                        by_id: dict) -> dict[str, list]:
    """Три класса расхождения прямого ключа и сшивки по имени.

    Классы объявлены до разбора в
    criteria/declared_before_divergence_2026-08-01.yaml (коммит c9a646b).
    Прежний оракул P18 требовал ровно ноль расхождений и был опровергнут
    прогоном: посылка «имя бедно, но проверено» неверна — при одноимённых
    актах `load_bills` брала первого встречного, то есть наугад.

    Разбиение обязано быть полным: пара, не попавшая ни в один класс, — отказ.
    """
    out: dict[str, list] = {"тёзка": [], "содержательное": [], "потеря": []}
    for vid, nb in sorted(by_name_pairs):
        db = direct.get(vid)
        if db == nb:
            continue                       # ключи согласны — не расхождение
        if db is None:
            out["потеря"].append((vid, nb, None))
        elif norm_he(by_id[nb]["name"]) == norm_he(by_id[db]["name"]):
            out["тёзка"].append((vid, nb, db))
        else:
            out["содержательное"].append((vid, nb, db))
    return out


def dump_divergences(root: Path, cls3: dict[str, list], heads: list[dict],
                     by_id: dict[int, dict], typ: dict[tuple, set]) -> int:
    """Материал для человеческих вердиктов: 42 случая с обеих сторон ключа.

    Гейт §3 в main требует вердикт по каждому содержательному расхождению и
    каждой потере. Вынести вердикт, не видя случая, нельзя — а увидеть его
    было нечем: разбор печатал только числа по классам. Эта ветка печатает
    сами случаи и заодно отвечает на P22–P24, объявленные 01.08.2026 в
    criteria/declared_before_divergence_2026-08-01.yaml ДО этого разбора.

    Ничего не решает за человека: вердикт в выводе пустой.
    """
    hb = {h["Id"]: h for h in heads}
    sids = [h["SessionID"] for h in heads if h.get("SessionID")]
    lo, hi = min(sids), max(sids)
    rows = json.loads((root / "data" / f"plm_session_items_{lo}_{hi}.json")
                      .read_text(encoding="utf-8"))["rows"]
    pair_n: collections.Counter = collections.Counter(
        (r["PlenumSessionID"], r["ItemID"]) for r in rows)

    cases = [(v, n, d, "содержательное") for v, n, d in cls3["содержательное"]]
    cases += [(v, n, d, "потеря") for v, n, d in cls3["потеря"]]
    assert len(cases) == len(cls3["содержательное"]) + len(cls3["потеря"]), (
        "случаи потерялись между классами и выводом")

    same_law = uniq = 0
    out = []
    for vid, nb, db, klass in cases:
        h = hb[vid]
        nm, dm = by_id[nb], (by_id[db] if db is not None else None)
        one = pair_n[(h.get("SessionID"), h.get("ItemID"))] == 1
        uniq += one
        law = dm is not None and law_head(nm["name"]) == law_head(dm["name"])
        same_law += law
        out.append({"vote_id": vid, "class": klass, "date": h["VoteDateTime"][:10],
                    "vote_title": h.get("VoteTitle"), "session": h.get("SessionID"),
                    "item": h.get("ItemID"), "by_name": {"id": nb, "name": nm["name"]},
                    "direct": None if dm is None else {"id": db, "name": dm["name"]},
                    "same_law_head": law, "pair_unique": one, "verdict": ""})

    n39 = len(cls3["содержательное"])
    print(f"\nP22 · один закон, разные поправки: {same_law} из {n39} "
          f"({same_law / max(n39, 1):.0%}) — объявлено «половина и более»")
    print(f"P23 · пара (сессия, пункт) единственна: {uniq} из {len(cases)} "
          f"({uniq / max(len(cases), 1):.0%}) — объявлено «80% и более»")
    print(f"P24 · потерь прямого ключа: {len(cls3['потеря'])}")
    dst = root / "data" / "vote_link_divergences.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(out)} случаев -> {dst}")
    print("Вердикты пустые: решает человек, не этот код.")
    return 0


def load_adjudication(root: Path) -> dict[int, str]:
    """Вердикты по содержательным расхождениям: vote_id → вердикт.

    Разбор — человеческий и версионируемый. Отсутствие файла не «мягкая
    деградация»: без него содержательные расхождения останавливают сборку.
    Формат нарочно плоский, чтобы не тащить разборщик: строки вида
    `<vote_id>: <вердикт>` под ключом `verdicts:`.
    """
    files = sorted((root / "criteria").glob("vote_link_adjudication_*.yaml"))
    if not files:
        return {}
    out: dict[int, str] = {}
    inside = False
    for line in files[-1].read_text(encoding="utf-8").splitlines():
        if line.startswith("verdicts:"):
            inside = True
            continue
        if inside:
            if line and not line.startswith(" "):
                inside = False
                continue
            k, _, v = line.strip().partition(":")
            if k.isdigit() and v.strip():
                out[int(k)] = v.strip()
    return out


def fetch_headers() -> list[dict]:
    """Шапки голосований 25-го Кнессета. §10: опции «за»/«против» обязательны."""
    flt = f"VoteDateTime ge {K25_START} and VoteDateTime lt {K25_END}"
    print(f"§23 ожидание для KNS_PlenumVote: спрашиваю независимым счётчиком…")
    if K25_NUM == 20:
        # Замер 19.10: $count по всему окну 20-го (7 537 голосований) сервер не
        # отдаёт — пустой ответ, тайм-аут. По годам отдаёт. Ожидание объявляется
        # по каждому году отдельно, сумма окон = окно Кнессета (смыкание ниже).
        cuts = [K25_START] + [f"{y}-01-01T00:00:00Z" for y in range(2016, 2020)] + [K25_END]
        cuts = sorted(c for c in cuts if K25_START <= c <= K25_END)
        out = []
        for lo, hi in zip(cuts, cuts[1:]):
            out += fetch_all("KNS_PlenumVote", flt=f"VoteDateTime ge {lo} and VoteDateTime lt {hi}",
                             select="Id,VoteDateTime,ItemID,SessionID,VoteTitle,VoteSubject,"
                                    "IsNoConfidenceInGov,ForOptionDesc,AgainstOptionDesc,VoteStatusDesc")
        # Источник сам отдаёт дубли строк (замер 19.10: голосование 37161 трижды в окне 2016;
        # в 25-м — 1809 строк на 1806 голосований), и $count считает их тоже. Дубль — не
        # перекрытие окон: окна смыкаются по WINDOWS и cuts. Сворачиваем по Id и называем число.
        seen, uniq = set(), []
        for h in out:
            if h["Id"] not in seen:
                seen.add(h["Id"]); uniq.append(h)
        print(f"   дублей строк источника свёрнуто: {len(out) - len(uniq)}")
        return uniq
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


NAMED_CACHE = ROOT / "data" / "named_votes_cache"


def fetch_named_votes(vote_id: int, use_cache: bool = True) -> list[dict]:
    """Поимённые по одному голосованию. §23: ожидание берётся счётчиком.

    КЭШ ПО ГОЛОСОВАНИЮ, ЧТОБЫ ОБРЫВ НЕ СТОИЛ ЧАСА. 07.10.2026 выгрузка
    умерла на 994-м голосовании из 1809, и все 994 пропали: они жили только
    в памяти. Повтор в guarded_fetch закрывает одиночный обрыв, но не падение
    процесса, не Ctrl-C и не разряженный ноутбук.

    Граница, которую надо знать: кэш делает возобновлённый прогон СМЕСЬЮ
    моментов. Для поимённых результатов прошедшего голосования это почти
    безопасно — голосование состоялось, перекличка по нему не меняется. Почти,
    а не точно: 07.10 тот же источник потерял 5 голосований из нашего окна
    задним числом. Поэтому у каждой записи стоит `at`, прогон печатает возраст
    самой старой взятой из кэша, а `--no-vote-cache` выключает кэш целиком.
    """
    f = NAMED_CACHE / f"{vote_id}.json"
    if use_cache and f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        return d["rows"]
    rows = fetch_all("KNS_PlenumVoteResult", flt=f"VoteID eq {vote_id}",
                     select="MkId,VoteID,VoteDate,ResultCode,ResultDesc,LastName,FirstName")
    NAMED_CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"vote_id": vote_id, "rows": rows,
                             "at": datetime.now(timezone.utc).isoformat()},
                            ensure_ascii=False), encoding="utf-8")
    return rows


# Коды результата 25-го Кнессета (SOURCES): 6 присутствовал · 7 за · 8 против
# · 9 воздержался · 10 отсутствовал. С легаси-схемой НЕ совпадают.
RESULT = {6: "present", 7: "for", 8: "against", 9: "abstain", 10: "absent"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-matched", type=int, default=None,
                    help="§23: сколько наших законопроектов ожидаем найти среди "
                         "голосований. Объявляется ДО прогона.")
    ap.add_argument("--no-cache", action="store_true",
                    help="не доверять кэшу пунктов повестки, выгрузить заново")
    ap.add_argument("--limit-votes", type=int, default=0,
                    help="сколько сшитых голосований выкачать поимённо (0 = все)")
    ap.add_argument("--no-vote-cache", action="store_true",
                    help="не брать поимённые из кэша по голосованию, качать заново")
    ap.add_argument("--dump-divergences", action="store_true",
                    help="напечатать сами расхождения и выйти: материал для "
                         "вердиктов, которых требует гейт §3. Ничего не решает.")
    ap.add_argument("--knesset", type=int, default=25,
                    help="номер Кнессета (срезы 20–24); по умолчанию 25")
    a = ap.parse_args()
    use_knesset(a.knesset)

    bills = load_bills()                      # контроль: по имени
    bills_by_id = load_bills_by_id()          # основной путь: по идентификатору
    print(f"наших законопроектов в чек-листе: {len(bills_by_id)} "
          f"(по имени схлопывается до {len(bills)} — дубли имён считаются здесь)")

    heads = fetch_headers()
    print(f"голосований {K25_NUM}-го Кнессета: {len(heads)}")

    # --- сшивка голосование ↔ законопроект ---------------------------------
    # ОСНОВНОЙ ПУТЬ: прямой ключ. КОНТРОЛЬ: имя. См. докстринг модуля.
    typ = session_item_types(heads, use_cache=not a.no_cache)
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
    direct_by_vote = {m["Id"]: m["bill_id"] for m in matched}
    only_name = by_name_pairs - direct_pairs
    print(f"\nКОНТРОЛЬ · сшивка по имени: {len(by_name_pairs)} пар · "
          f"прямым ключом: {len(direct_pairs)} · расходятся: {len(only_name)}")

    # Оракул трёх классов. Заменил P18 («ноль расхождений»), опровергнутый
    # прогоном 01.08: посылка «имя бедно, но проверено» неверна.
    cls3 = classify_divergence(by_name_pairs, direct_by_vote, bills_by_id)
    assert sum(len(v) for v in cls3.values()) == len(only_name), (
        f"разбиение расхождений неполно: {sum(len(v) for v in cls3.values())} "
        f"против {len(only_name)}")
    for k, v in cls3.items():
        print(f"   {len(v):>4}  {k}")

    if a.dump_divergences:
        return dump_divergences(ROOT, cls3, heads, bills_by_id, typ)

    verdicts = load_adjudication(ROOT)
    need = [t for t in cls3["содержательное"] + cls3["потеря"]
            if t[0] not in verdicts]
    if need and K25_NUM != 25:
        # §3-exempt: срезы 20–24. Вердикты по расхождениям прямого ключа и имени
        # писались для 25-го; для срезов владелец 19.10 поставил покрытие выше
        # точности. Основной путь — прямой ключ (7299/7300 на 25-м); расхождения
        # не молчат: число печатается и пишется в выход как control_unadjudicated.
        print(f"\n§3-exempt (срез {K25_NUM}): {len(need)} расхождений без вердикта "
              f"— берётся прямой ключ, расхождения записаны в выход")
        need_exempt = len(need)
        need = []
    else:
        need_exempt = 0
    if need:
        print(f"\n§3 ОТКАЗ: {len(need)} расхождений без вердикта в "
              f"criteria/vote_link_adjudication_*.yaml. Содержательное "
              f"расхождение и потеря не решаются механически: молчание о них "
              f"тихо выбирает один ключ из двух. Данные наверх не отдаются.")
        for vid, nb, db in need[:8]:
            print(f"   голосование {vid}: имя → {nb}, ключ → {db}")
        return 1
    print(f"   вердиктов прочитано: {len(verdicts)}")

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
    from_cache = []
    for i, h in enumerate(targets, 1):
        cf = NAMED_CACHE / f"{h['Id']}.json"
        if not a.no_vote_cache and cf.exists():
            from_cache.append(json.loads(cf.read_text(encoding="utf-8"))["at"])
        named = fetch_named_votes(h["Id"], use_cache=not a.no_vote_cache)
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

    if from_cache:
        oldest = min(from_cache)
        print(f"\nиз кэша по голосованию взято {len(from_cache)} из "
              f"{len(targets)}; самая старая запись — {oldest[:19]}. "
              f"Возобновлённый прогон — смесь моментов, и это видно здесь, "
              f"а не в примечании (--no-vote-cache выключает кэш).")
    OUT.write_text(json.dumps({
        "at": datetime.now(timezone.utc).isoformat(),
        "knesset": K25_NUM, "window": [K25_START, K25_END],
        "headers_total": len(heads),
        "link_method": "direct_key:(SessionID,ItemID)->KNS_PlmSessionItem.ItemTypeID=2",
        "link_classes": dict(cls),
        "control_by_name_pairs": len(by_name_pairs),
        "control_only_name_pairs": len(only_name),
        "control_unadjudicated": need_exempt,
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

    # classify_divergence: три класса. Случаи различаются ТОЛЬКО тем полем,
    # которое их и разделяет, — иначе проверка пройдёт по посторонней причине,
    # как уже случилось с первой редакцией теста link_head выше.
    cb = {1: {"id": 1, "name": "חוק א (תיקון 1)"},
          2: {"id": 2, "name": "חוק א (תיקון 1)"},   # ТЁЗКА первого
          3: {"id": 3, "name": "חוק ב (תיקון 5)"}}   # другое имя
    pairs = {(10, 1), (11, 1), (12, 1), (13, 1)}
    dirmap = {10: 1,      # ключи согласны — не расхождение
              11: 2,      # найден тёзка
              12: 3}      # найден акт с другим именем; 13 не найден вовсе
    c = classify_divergence(pairs, dirmap, cb)
    assert [t[0] for t in c["тёзка"]] == [11], f"тёзка: {c['тёзка']}"
    assert [t[0] for t in c["содержательное"]] == [12], f"сод.: {c['содержательное']}"
    assert [t[0] for t in c["потеря"]] == [13], f"потеря: {c['потеря']}"
    assert sum(len(v) for v in c.values()) == 3, \
        "согласная пара не имеет права попасть в расхождения"
    # разбиение полно: каждая расходящаяся пара ровно в одном классе
    seen = [t[0] for v in c.values() for t in v]
    assert sorted(seen) == [11, 12, 13] and len(set(seen)) == 3, \
        f"классы пересеклись или потеряли пару: {seen}"

    # cache_is_valid: кэш выгрузки. Красное здесь = сшивка идёт по неполному
    # набору пунктов повестки, голосования тихо получают «нет пункта», и у
    # партии пропадают свидетельства, которых на самом деле хватало.
    F = "PlenumSessionID ge 1 and PlenumSessionID le 9"
    good = {"flt": F, "count": 2, "rows": [{"a": 1}, {"a": 2}]}
    assert cache_is_valid(good, F, 2)[0], "сошедшийся кэш обязан быть годен"
    assert not cache_is_valid(good, F, 3)[0], \
        "счётчик разошёлся — кэш обязан быть негоден, иначе устаревание тихое"
    assert not cache_is_valid(good, "другой фильтр", 2)[0], \
        "кэш другого фильтра не имеет права сойти за этот"
    assert not cache_is_valid({"flt": F, "count": 0, "rows": []}, F, 0)[0], \
        "пустой кэш негоден даже при сошедшемся счётчике: ноль строк — это " \
        "либо обрыв записи, либо фильтр ни во что, и оба надо перепроверить"
    assert not cache_is_valid({}, F, 2)[0], "кэш без метаданных негоден"
    # причина обязана называться, а не просто «негоден»
    assert "счётчик" in cache_is_valid(good, F, 3)[1], \
        "отказ без названной причины не даёт понять, что чинить"

    # load_adjudication: отсутствие файла даёт пустоту, а не догадку
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    (tmp / "criteria").mkdir()
    assert load_adjudication(tmp) == {}, "нет файла ⇒ пусто, и это отказ выше"
    (tmp / "criteria" / "vote_link_adjudication_2026-01-01.yaml").write_text(
        "verdicts:\n  10: ключ прав, имя выбрало тёзку\n  13: пункта нет\n"
        "прочее:\n  99: не вердикт\n", encoding="utf-8")
    v = load_adjudication(tmp)
    assert v == {10: "ключ прав, имя выбрало тёзку", 13: "пункта нет"}, v
    assert 99 not in v, "строка вне блока verdicts не имеет права стать вердиктом"

    # Окна срезов смыкаются: конец N == начало N+1. Дыра = потерянные голосования,
    # нахлёст = голос записан двум Кнессетам.
    ks = sorted(WINDOWS)
    for x, y in zip(ks, ks[1:]):
        assert WINDOWS[x][1] == WINDOWS[y][0], f"окна {x} и {y} не смыкаются"

    print("самопроверка fetch_votes пройдена: 29 утверждений "
          "(8 мост, 6 прямой ключ, 8 расхождения, 6 кэш)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
