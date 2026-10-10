#!/usr/bin/env python3
"""CLAUDE.md §23 — выгрузка, которая не может тихо недобрать.

Класс отказа, ради которого написан модуль: операция отчитывается об успехе,
возвращает правдоподобный результат, и он неполон. `$top=200` отдаёт 100 строк
с HTTP 200 и без предупреждения; сто фракций — совершенно нормальное число,
из него получаются аккуратные и ложные выводы.

Единственное, что реально ловит такое, — ожидание объёма, полученное ДРУГИМ
путём, и сверка до использования данных.

⚠️ Честная граница этой защиты: `?$count=true` идёт на тот же сервер с тем же
фильтром. Проверка независима от МОЕЙ логики пагинации, но НЕ независима от
серверной логики фильтрации. Если сервер неверно применит $filter, счётчик
соврёт согласованно с выборкой, и §23 этого не заметит. Это не лечится здесь.
"""
from __future__ import annotations

import json
import http.client
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "knesset-research/0.1"}
CTX = ssl.create_default_context()
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"
_ROOT = Path(__file__).resolve().parent.parent
# Снимок в git — доказательство §23 для читателя репозитория.
MANIFEST = _ROOT / "data" / "MANIFEST.json"
# Рантайм-буфер ВНЕ git (data/* заигнорено). Развязка введена 2026-07-30:
# манифест — write-back кэш, и он терял записи при каждой доставке.
# post-receive делает `git reset --hard bare/main`, а MANIFEST.json
# отслеживается — значит все записи о выгрузках, сделанных после последнего
# коммита манифеста, стирались. Проверено: обе записи канала Б исчезли между
# 16:26 и 17:23 того же дня. Антипаттерн из Таненбаума §7.5.4 дословно:
# «отсутствие механизма обработки отказов — данные теряются без возможности
# восстановления». Лечение — тоже оттуда: явный flush вместо надежды.
# Неотслеживаемый файл `reset --hard` не трогает, поэтому буфер переживает push.
RUNTIME = _ROOT / "data" / "manifest" / f"{socket.gethostname()}.json"


class ShortRead(RuntimeError):
    """Выгрузка вернула не столько, сколько обещал независимый счётчик."""


# Повтор на обрыве сети. Это НЕ оптимизация: 07.10.2026 выгрузка поимённых
# умерла на 994-м голосовании из 1809 на RemoteDisconnected, и час работы
# пропал целиком, потому что строки жили только в памяти. Лестница
# минимализма прямо исключает экономию на «обработке ошибок, теряющей
# данные» — это ровно тот случай. Повторяется только обрыв и 5xx: на 4xx
# повтор бессмыслен и маскирует неверный запрос.
RETRY_ON = (http.client.RemoteDisconnected, http.client.IncompleteRead,
            ConnectionResetError, TimeoutError, socket.timeout)


def _get(url: str, timeout: int = 60, attempts: int = 4) -> dict:
    last: Exception | None = None
    for k in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                # 2026-10-10: Studio получил 303 → maintenance-page-geo, и
                # HTML уехал в json.loads. JSONDecodeError в post-receive
                # читался как «состав каденций неполон» — отказ источника
                # превращался в утверждение о данных (§7: source_missing ≠
                # observed). Повтор здесь бессмыслен: гео-заглушка не
                # пройдёт через 2**k секунд, поэтому отказ немедленный.
                ct = r.headers.get_content_type()
                if ct != "application/json":
                    raise ShortRead(
                        f"сервер отдал {ct!r} вместо JSON; конечный адрес "
                        f"{r.geturl()[:120]} — это отказ источника, не данные")
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            last = e
        except (urllib.error.URLError, *RETRY_ON) as e:
            inner = getattr(e, "reason", None)
            if isinstance(e, urllib.error.URLError) and not isinstance(
                    inner, (*RETRY_ON, OSError)):
                raise
            last = e
        if k + 1 < attempts:
            time.sleep(2 ** k)
    raise ShortRead(f"сеть не отдала {url[:80]}… за {attempts} попыток: {last!r}")


def count(entity: str, flt: str = "") -> int:
    """Независимый путь к величине. Форма `/$count` отдаёт 404 — только эта."""
    url = f"{BASE}/{entity}?$format=json&$count=true&$top=0"
    if flt:
        url += "&$filter=" + urllib.parse.quote(flt)
    r = _get(url)
    if "@odata.count" not in r:
        raise ShortRead(f"{entity}: сервер не вернул @odata.count — ожидание неполучаемо")
    return int(r["@odata.count"])


def fetch_all(
    entity: str,
    flt: str = "",
    select: str = "",
    expected: int | None = None,
    unchecked_reason: str = "",
    pause: float = 0.35,
) -> list[dict]:
    """Полная выгрузка со сверкой объёма.

    Семантика (первая редакция была неверна — см. ниже):
      expected=int  — сверять с этим числом;
      expected=None — ДЕФОЛТ: взять ожидание независимым путём через count();
      unchecked_reason="..." — единственный способ обойти сверку, и он громкий.

    Первая редакция требовала unchecked_reason при expected=None, из-за чего
    безопасный путь (авто-count) был недостижим: корректный вызов падал.
    Защита, блокирующая правильное использование, — не защита, а поломка;
    это зеркало слишком широкого grep'а в §9-правиле (2026-07-27).
    """
    if unchecked_reason:
        print(f"   §23 СВЕРКА ПРОПУЩЕНА для {entity}: {unchecked_reason}")
        expected = None
    elif expected is None:
        expected = count(entity, flt)

    params = ["$format=json"]
    if flt:
        params.append("$filter=" + urllib.parse.quote(flt))
    if select:
        params.append("$select=" + select)
    url = f"{BASE}/{entity}?" + "&".join(params)

    out: list[dict] = []
    pages = 0
    while url:
        r = _get(url)
        out.extend(r.get("value", []))
        url = r.get("@odata.nextLink")
        pages += 1
        if url:
            time.sleep(pause)

    if expected is not None and len(out) != expected:
        raise ShortRead(
            f"§23 ТИХИЙ НЕДОБОР: {entity} — ожидалось {expected}, получено {len(out)} "
            f"за {pages} стр. Данные НЕ отдаются наверх. "
            f"Фильтр: {flt or '(нет)'}"
        )

    _record(entity, flt, expected, len(out), pages)
    return out


def require_join(left: set, right: set, name: str, min_overlap: int = 1) -> int:
    """§23, пункт 4: соединение объявляет ожидание и падает на пустоте.

    Повод (2026-07-28): build_lineage_candidates соединял KNS_Faction.Id с
    KNS_PersonToPosition.FactionID, поле оказалось пустым для PositionID=43,
    пересечение вышло нулевым — и скрипт отчитался «545 фракций, 0 развилок,
    решать нечего». Ноль связей прочитался как «всё авторазрешилось».

    Тот же класс, что тихий недобор, только по другой оси: не «данных пришло
    меньше», а «данные не соединились». Отчёт об успехе в обоих случаях.
    """
    inter = left & right
    if len(inter) < min_overlap:
        raise ShortRead(
            f"§23 ПУСТОЕ СОЕДИНЕНИЕ [{name}]: слева {len(left)} ключей, "
            f"справа {len(right)}, пересечение {len(inter)} < {min_overlap}. "
            "Ноль связей — это отказ, а не результат «связывать нечего». "
            f"Примеры слева: {sorted(left)[:5]}; справа: {sorted(right)[:5]}"
        )
    return len(inter)


def _record(entity: str, flt: str, expected: int, got: int, pages: int) -> None:
    """Манифест выгрузки: обе цифры рядом, чтобы расхождение было видно глазом.

    Поле `host` — лечение R4 (две копии data/ без протокола согласованности).
    28.07 холодный старт прогнал самопроверку на MacBook, она записала строку
    в ЛОКАЛЬНЫЙ манифест, и check_artifacts честно доложил о непроверенной
    выгрузке KNS_Position — которой никто не делал. Манифест без имени машины
    не отвечает на вопрос «чьё это состояние», а два независимых data/ этот
    вопрос задают постоянно.
    """
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(RUNTIME.read_text()) if RUNTIME.exists() else {}
    except Exception:  # noqa: BLE001
        data = {}
    data[f"{entity}|{flt}"] = {
        "expected": expected,
        "got": got,
        "pages": pages,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": socket.gethostname(),
    }
    RUNTIME.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def sync_manifest() -> tuple[int, int]:
    """Явный flush буфера в отслеживаемый снимок. Возвращает (было, стало).

    Тот самый `sync()`, отсутствие которого делает write-back кэш ненадёжным.

    Полный путь доказательства, потому что писатель и вычислитель — разные
    машины (§19): выгрузка идёт на Studio и пишет туда буфер; MacBook забирает
    буфер `scp larry@studio:'~/knesset/data/manifest/*.json' data/manifest/`,
    зовёт `--sync` и коммитит снимок. Поле `host` в каждой записи отвечает на
    вопрос «чьё это состояние», поэтому буферы двух машин сливаются без потерь.
    Не вызывается автоматически: автоматический flush прятал бы момент, когда
    доказательство §23 попадает в git, а именно этот момент и надо видеть в
    диффе. Зовётся руками или из post-receive после генерации.
    """
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    try:
        snap = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    except Exception:  # noqa: BLE001
        snap = {}
    before = len(snap)
    # Слияние по времени записи, а не по алфавиту имён буферов. 2026-10-10:
    # `snap.update()` в порядке glob отдавал победу Studio.local.json
    # (S > M), и запись 31.07 (4515) затирала свежую с MacBook (4518);
    # `--sync` печатал «стало 1822», а unsynced() продолжал краснеть на том
    # же ключе — flush, который не flush. Побеждает новейшее `at`.
    for f in sorted((_ROOT / "data" / "manifest").glob("*.json")):
        try:
            buf = json.loads(f.read_text())
        except Exception as exc:  # noqa: BLE001
            raise ShortRead(f"буфер {f.name} не читается: {exc}") from exc
        for k, v in buf.items():
            if k not in snap or str(v.get("at", "")) >= str(snap[k].get("at", "")):
                snap[k] = v
    MANIFEST.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
    return before, len(snap)


def unsynced() -> list[str]:
    """Ключи, которые есть в буфере и отсутствуют/расходятся в снимке.

    Это и есть детектор потери: непустой список означает, что выгрузка была,
    а следа в git нет. Читается механизмом §24.
    """
    try:
        snap = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    except Exception:  # noqa: BLE001
        snap = {}
    out: list[str] = []
    for f in (_ROOT / "data" / "manifest").glob("*.json"):
        try:
            buf = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            out.append(f"{f.name}: буфер не читается")
            continue
        for k, v in buf.items():
            s = snap.get(k)
            # Сравниваем КЛЮЧ и ЦИФРЫ, но НЕ время. Первая редакция сверяла
            # `at`, и тогда каждый повторный прогон той же выгрузки выглядел
            # расхождением: post-receive на Studio при каждой генерации зовёт
            # build_periods, тот честно перевыгружает KNS_Faction, время
            # меняется — и §24 краснел на штатной работе. Сторож, который
            # кричит на норму, обучает себя игнорировать; это опаснее, чем
            # его отсутствие, потому что выглядит как защита.
            # Настоящий сигнал — ключ, которого git никогда не видел, или
            # изменившиеся цифры. Повторная выгрузка с тем же результатом
            # новым доказательством не является.
            # Исключение одно: снимок уже держит БОЛЕЕ ПОЗДНЮЮ выгрузку того
            # же ключа с другой машины. Старый буфер тогда не «потерян», а
            # превзойдён — иначе после слияния по `at` вторая машина вечно
            # краснела бы на своей же устаревшей записи.
            if s is not None and str(s.get("at", "")) > str(v.get("at", "")):
                continue
            if s is None or (s.get("expected"), s.get("got")) != (
                    v.get("expected"), v.get("got")):
                out.append(k)
    return sorted(set(out))


# ============================================================ obudget (SQL)
# Второй источник, добавлен 2026-07-30 для канала Б. Тот же §23-контракт,
# другой протокол: obudget принимает ГОТОВЫЙ SQL строкой в URL.
#
# Ловушка того же класса, что $top=200 в OData, и она измерена:
# page_size жёстко 1000 независимо от запроса, страницы с нуля, число страниц
# в поле `pages`. Запрос на 5 970 строк отдаёт 1 000 с HTTP 200 и без
# предупреждения (проверено 2026-07-30).
BUDGET_API = "https://next.obudget.org/api/query"


class UnsafeLiteral(ValueError):
    """Литерал, который нельзя безопасно вставить в SQL-строку."""


def _sql_literal(s: str) -> str:
    """Единственный законный способ положить строку в SQL для obudget.

    Параметризации у этого API нет. Возражение «это же наш собственный
    запрос» не принимается: термины поиска приходят из OCR-текста и из
    редактируемого criteria/*.yaml, то есть из-за границы доверия
    (OWASP WSTG-INPV-05). Ломается не безопасность публичной read-only базы —
    ломается §23: HTTP 200, правдоподобные строки, условие ДРУГОЕ.

    Двойная кавычка внутри одинарных для Postgres безопасна и проверена —
    а она есть в каждом ивритском сокращении вроде ש"ס и מלש"ח, поэтому
    запрещать её нельзя. Запрещаются: обратный слеш, точка с запятой
    (разрыв на два оператора) и управляющие символы.
    """
    if "\\" in s or ";" in s or any(ord(c) < 32 for c in s):
        raise UnsafeLiteral(f"недопустимый символ в литерале: {s!r}")
    return "'" + s.replace("'", "''") + "'"


def _budget_get(query: str, page: int | None = None, timeout: int = 120) -> dict:
    url = BUDGET_API + "?query=" + urllib.parse.quote(query)
    if page is not None:
        url += f"&page={page}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read())


def count_sql(table: str, where: str = "") -> int:
    """Независимый путь к величине: ОТДЕЛЬНЫЙ count(1), а не поле total выдачи.

    Поле `total` приходит той же выдачей и потому не независимо от неё.
    Честная граница та же, что у @odata.count: запрос идёт на тот же сервер
    с тем же WHERE. Проверка независима от НАШЕЙ пагинации, но не от
    серверной фильтрации.
    """
    q = f"select count(1) as n from {table}"
    if where:
        q += f" where {where}"
    r = _budget_get(q)
    rows = r.get("rows") or []
    if not rows or "n" not in rows[0]:
        raise ShortRead(f"{table}: count(1) не вернул числа — ожидание неполучаемо")
    return int(rows[0]["n"])


def fetch_sql(
    table: str,
    select: str,
    order_by: str,
    where: str = "",
    expected: int | None = None,
    unchecked_reason: str = "",
    pause: float = 0.2,
) -> list[dict]:
    """Полная выгрузка из obudget со сверкой объёма. Семантика как у fetch_all.

    `order_by` обязателен и не имеет разумного дефолта: без явного порядка
    страницы не гарантируют устойчивости, и строки могут повториться или
    пропасть — тихо, с HTTP 200. Пустой order_by поэтому отказ, а не
    «возьму первую колонку».
    """
    if not order_by:
        raise ValueError("fetch_sql: order_by обязателен — пагинация без "
                         "порядка теряет строки молча")
    if unchecked_reason:
        print(f"   §23 СВЕРКА ПРОПУЩЕНА для {table}: {unchecked_reason}")
        expected = None
    elif expected is None:
        expected = count_sql(table, where)

    q = f"select {select} from {table}"
    if where:
        q += f" where {where}"
    q += f" order by {order_by}"

    out: list[dict] = []
    page, pages = 0, 1
    while page < pages:
        r = _budget_get(q, page=page)
        out.extend(r.get("rows") or [])
        pages = int(r.get("pages") or 1)
        page += 1
        if page < pages:
            time.sleep(pause)

    if expected is not None and len(out) != expected:
        raise ShortRead(
            f"§23 ТИХИЙ НЕДОБОР: {table} — ожидалось {expected}, получено "
            f"{len(out)} за {page} стр. Данные НЕ отдаются наверх. "
            f"WHERE: {where or '(нет)'}"
        )

    _record(f"obudget:{table}", where, expected, len(out), page)
    return out


if __name__ == "__main__" and "--sync" in sys.argv:
    was, now = sync_manifest()
    print(f"манифест синхронизирован: было {was} записей, стало {now}")
    left = unsynced()
    if left:
        print(f"ПРОВАЛ: после flush осталось несинхронизированным: {left}")
        raise SystemExit(1)
    raise SystemExit(0)

if __name__ == "__main__":
    # Самопроверка §23: механизм обязан краснеть, а не рассказывать о себе.
    #
    # Пишет во ВРЕМЕННЫЙ манифест, а не в data/ (лечение R4). Самопроверка
    # намеренно провоцирует обход сверки — и до 29.07 этот учебный обход
    # оседал в настоящем манифесте как строка о выгрузке KNS_Position,
    # которой не было. Механизм §24 читал её и докладывал о непроверенной
    # выгрузке. Проверяющий, загрязняющий то, что проверяет, — источник
    # ложного сигнала, а не защита.
    RUNTIME = Path(tempfile.gettempdir()) / "knesset_selfcheck_manifest.json"
    if RUNTIME.exists():
        RUNTIME.unlink()
    print(f"самопроверка guarded_fetch (буфер: {RUNTIME})")

    n = count("KNS_Faction")
    print(f"  независимый счётчик KNS_Faction: {n}")

    rows = fetch_all("KNS_Faction", select="Id,Name,KnessetNum")
    print(f"  полная выгрузка: {len(rows)} — сверка пройдена")

    print("  провокация: подсовываю заведомо неверное ожидание...")
    try:
        fetch_all("KNS_Faction", select="Id,Name", expected=100)
        print("  ПРОВАЛ САМОПРОВЕРКИ: недобор не пойман")
        raise SystemExit(1)
    except ShortRead as e:
        print(f"  OK, поймано: {str(e)[:90]}...")

    print("  обход сверки обязан быть громким и попадать в манифест...")
    fetch_all("KNS_Position", unchecked_reason="проверка громкости обхода")
    rec = json.loads(RUNTIME.read_text()).get("KNS_Position|")
    if rec and rec.get("expected") is None:
        print(f"  OK, записано как непроверенное: {rec}")
    else:
        print(f"  ПРОВАЛ САМОПРОВЕРКИ: обход не отмечен в манифесте: {rec}")
        raise SystemExit(1)

    # ---- obudget: экранирование литерала и §23 на SQL-пути -----------------
    print("экранирование литерала: ивритские кавычки обязаны проходить...")
    for ok in ('ש"ס', 'מלש"ח', "בתי כנסת", "רשת מעיין החינוך התורני"):
        got = _sql_literal(ok)
        if got != "'" + ok + "'":
            print(f"  ПРОВАЛ: {ok!r} -> {got!r}")
            raise SystemExit(1)
    if _sql_literal("ו'תו") != "'ו''תו'":
        print("  ПРОВАЛ: апостроф не удвоен")
        raise SystemExit(1)
    print("  OK: двойная кавычка сохранена, апостроф удвоен")
    # assert, а не печать: если экранирование сломают, самопроверка обязана
    # остановиться, а не сообщить об этом строчкой в общем потоке.
    assert _sql_literal('ש"ס') == "'" + 'ש"ס' + "'", "ивритская кавычка сломана"
    assert _sql_literal("a'b") == "'a''b'", "апостроф не удвоен"

    print("экранирование литерала: разрыв оператора обязан отвергаться...")
    for bad in ("x; drop table budget", "a\\b", "line\nbreak"):
        try:
            _sql_literal(bad)
            print(f"  ПРОВАЛ САМОПРОВЕРКИ: {bad!r} не отвергнут")
            raise SystemExit(1)
        except UnsafeLiteral:
            pass
    print("  OK: `;`, обратный слеш и перевод строки отвергнуты")

    print("§23 на SQL-пути: сверка через отдельный count(1)...")
    W = "year = 2025 and length(code) = 2"
    n_sql = count_sql("raw_budget", W)
    rows = fetch_sql("raw_budget", "code, title", "code", where=W)
    if len(rows) != n_sql:
        print(f"  ПРОВАЛ: count(1)={n_sql}, выгрузка={len(rows)}")
        raise SystemExit(1)
    print(f"  OK: count(1) и выгрузка совпали на {n_sql} строках")

    print("  провокация на SQL-пути: заведомо неверное ожидание...")
    try:
        fetch_sql("raw_budget", "code", "code", where=W, expected=n_sql + 1)
        print("  ПРОВАЛ САМОПРОВЕРКИ: недобор на SQL-пути не пойман")
        raise SystemExit(1)
    except ShortRead as e:
        print(f"  OK, поймано: {str(e)[:90]}...")

    print("  order_by без значения обязан быть отказом, а не догадкой...")
    try:
        fetch_sql("raw_budget", "code", "", where=W)
        print("  ПРОВАЛ САМОПРОВЕРКИ: пустой order_by пропущен")
        raise SystemExit(1)
    except ValueError:
        print("  OK: пустой order_by отвергнут")

    # ---- flush буфера: детектор потери обязан краснеть -------------------
    print("манифест как write-back кэш: потеря записи обязана быть видна...")
    _tmp_snap = Path(tempfile.gettempdir()) / "knesset_selfcheck_SNAPSHOT.json"
    _tmp_dir = Path(tempfile.gettempdir()) / "knesset_selfcheck_bufdir"
    _tmp_dir.mkdir(exist_ok=True)
    (_tmp_dir / "host.json").write_text(json.dumps(
        {"X|": {"expected": 1, "got": 1, "pages": 1, "at": "T1", "host": "h"}}))
    _tmp_snap.write_text("{}")
    _real_root, _real_manifest = _ROOT, MANIFEST
    _ROOT = _tmp_dir.parent / "knesset_selfcheck_root"
    (_ROOT / "data").mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.rmtree(_ROOT / "data" / "manifest", ignore_errors=True)
    shutil.copytree(_tmp_dir, _ROOT / "data" / "manifest")
    MANIFEST = _ROOT / "data" / "MANIFEST.json"
    MANIFEST.write_text("{}")
    assert unsynced() == ["X|"], "потеря записи НЕ обнаружена — детектор мёртв"
    was, now = sync_manifest()
    assert (was, now) == (0, 1), f"flush не сработал: {was} -> {now}"
    assert unsynced() == [], "после flush детектор всё ещё жалуется"
    # Повторный прогон той же выгрузки НЕ расхождение: меняется только время.
    (_ROOT / "data" / "manifest" / "host.json").write_text(json.dumps(
        {"X|": {"expected": 1, "got": 1, "pages": 1, "at": "T2", "host": "h"}}))
    assert unsynced() == [], "повторный прогон принят за потерю — сторож кричит на норму"
    # А изменившиеся цифры — расхождение, и оно обязано быть видно.
    (_ROOT / "data" / "manifest" / "host.json").write_text(json.dumps(
        {"X|": {"expected": 2, "got": 2, "pages": 1, "at": "T2", "host": "h"}}))
    assert unsynced() == ["X|"], "изменившиеся цифры не пойманы"
    # Две машины, один ключ: файл, ПОЗДНИЙ по алфавиту, держит СТАРУЮ запись.
    # Воспроизводит 2026-10-10: Studio.local.json (31.07, 4515) затирал
    # MacBook-…json (10.10, 4518). Побеждать обязано новейшее `at`, и старый
    # буфер после этого не должен читаться как потеря.
    (_ROOT / "data" / "manifest" / "a-new.json").write_text(json.dumps(
        {"Y|": {"expected": 4518, "got": 4518, "pages": 46, "at": "2026-10-10T12:46:43", "host": "a"}}))
    (_ROOT / "data" / "manifest" / "z-old.json").write_text(json.dumps(
        {"Y|": {"expected": 4515, "got": 4515, "pages": 46, "at": "2026-07-31T14:27:32", "host": "z"}}))
    sync_manifest()
    _snap = json.loads(MANIFEST.read_text())
    assert _snap["Y|"]["got"] == 4518, \
        f"слияние по алфавиту: старая запись затёрла новую ({_snap['Y|']['got']})"
    assert "Y|" not in unsynced(), "превзойдённый старый буфер читается как потеря"
    _ROOT, MANIFEST = _real_root, _real_manifest
    print("  OK: потеря обнаружена, flush её закрыл, новейшая запись побеждает")

    # ---- повтор на обрыве: обязан пережить обрыв и НЕ прятать 4xx --------
    print("повтор на обрыве сети: обрыв переживается, 404 — нет...")
    _real_open = urllib.request.urlopen
    _calls = {"n": 0}

    class _Fake:
        def __init__(self, payload, ct="application/json",
                     url="https://example.invalid/x"):
            self._p, self._ct, self._u = payload, ct, url

        class _H:
            def __init__(self, ct): self._ct = ct
            def get_content_type(self): return self._ct

        @property
        def headers(self): return self._H(self._ct)
        def geturl(self): return self._u
        def read(self): return json.dumps(self._p).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _flaky(req, **kw):
        _calls["n"] += 1
        if _calls["n"] < 3:
            raise http.client.RemoteDisconnected("оборвано")
        return _Fake({"ok": True})

    urllib.request.urlopen = _flaky
    try:
        assert _get("https://example.invalid/x") == {"ok": True}, \
            "повтор не довёл запрос до успеха"
        assert _calls["n"] == 3, f"попыток {_calls['n']}, а обрывов было два"
        _calls["n"] = 0

        def _always(req, **kw):
            _calls["n"] += 1
            raise http.client.RemoteDisconnected("оборвано")

        urllib.request.urlopen = _always
        try:
            _get("https://example.invalid/x", attempts=2)
            print("  ПРОВАЛ: бесконечный обрыв не стал отказом")
            raise SystemExit(1)
        except ShortRead:
            assert _calls["n"] == 2, "повторов больше объявленного"

        def _404(req, **kw):
            _calls["n"] += 1
            raise urllib.error.HTTPError("u", 404, "no", {}, None)

        _calls["n"] = 0
        urllib.request.urlopen = _404
        try:
            _get("https://example.invalid/x")
            print("  ПРОВАЛ: 404 проглочен повтором")
            raise SystemExit(1)
        except urllib.error.HTTPError:
            assert _calls["n"] == 1, \
                "404 повторялся — повтор маскирует неверный запрос"

        # Гео-заглушка: 303 → HTML с кодом 200. Это должен быть отказ с
        # адресом, а не JSONDecodeError, который читатель примет за дефект
        # данных. Провокация воспроизводит Studio 2026-10-10 дословно.
        def _geo(req, **kw):
            _calls["n"] += 1
            return _Fake(None, ct="text/html",
                         url="https://www.knesset.gov.il/maintenance-page-geo")

        _calls["n"] = 0
        urllib.request.urlopen = _geo
        try:
            _get("https://example.invalid/x")
            print("  ПРОВАЛ: HTML-заглушка принята за JSON")
            raise SystemExit(1)
        except ShortRead as e:
            assert "maintenance-page-geo" in str(e), \
                "отказ не называет конечный адрес"
            assert _calls["n"] == 1, "гео-заглушка повторялась"
        print("  OK: обрыв пережит, лимит соблюдён, 404 не повторяется, "
              "HTML вместо JSON — отказ с адресом")
    finally:
        urllib.request.urlopen = _real_open

    print("самопроверка пройдена")
