#!/usr/bin/env python3
"""CLAUDE.md §24 — артефакты, отсутствие которых само есть нарушение.

Разница, ради которой написан модуль:

  ПРОВЕРКА ПРИСУТСТВИЯ — валидатор смотрит, заполнено ли поле. Обходится тем,
  что объект не создаётся или не проходит через валидатор. Защищает вызов.

  ПРОВЕРКА ОТСУТСТВИЯ — артефакт обязан существовать там, где обязан.
  Забыванием не обходится: забывание И ЕСТЬ обнаруживаемое состояние.

Честная граница (заимствована у health-os §15 дословно по смыслу):
эти проверки ловят отсутствие НОСИТЕЛЯ, а не его качество. Зелёный отчёт
доказывает, что артефакт создан, а не что он осмыслен. Пустой по существу,
но структурно полный артефакт пройдёт — и это принято, потому что
осмысленность машинно неотличима.

Побочный продукт — docs/reference/ENFORCEMENT.md: заявленный Enforcement
и упоминания правил в коде. Упоминание не подтверждает работу механизма
(инвариант mention_is_not_mechanism в subsystem_intent.yaml).

Выход: 0 — чисто · 1 — нарушения · 2 — внутренняя ошибка (блок, не warn).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE = ROOT / "CLAUDE.md"
SCRIPTS = ROOT / "scripts"
CARDS = ROOT / "cards"
CRITERIA = ROOT / "criteria"
MANIFEST = ROOT / "data" / "MANIFEST.json"
ENFORCEMENT = ROOT / "docs" / "reference" / "ENFORCEMENT.md"

CODE_GLOBS = ("*.py", "git-hooks/*", "post-receive.template")
# Первая редакция ловила по хосту knesset.gov.il и обвиняла скрипт, который
# всего лишь качал PDF соглашений. §23 — про выгрузку МНОЖЕСТВА записей,
# то есть про OData, а не про весь домен.
ODATA_MARK = "OdataV4/ParliamentInfo"
# Второй источник массовых данных, добавлен 2026-07-30 (канал Б). obudget
# отдаёт строки страницами по 1000 независимо от запроса — тот же класс тихого
# недобора, что $top=200 в OData. Пока хост не стоял в этом списке, любой новый
# скрипт обходил §23 МОЛЧА: guarded_fetch не мог его увидеть, потому что не
# вызывался. Это ровно тот дефект, ради которого §24 написан, — второй раз.
OBUDGET_MARK = "next.obudget.org"
BULK_MARKS = (ODATA_MARK, OBUDGET_MARK)
# Явный, громкий и считаемый обход — по образцу `# silent-ok:` из health-os §7.
EXEMPT_MARK = "§23-exempt:"

problems: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def note(msg: str) -> None:
    notes.append(msg)


# --------------------------------------------------------------- разбор свода
def parse_rules() -> dict[str, dict]:
    """§N -> {title, enforcement}. Свод — единственный дом деклараций."""
    text = CLAUDE.read_text(encoding="utf-8")
    blocks = re.split(r"^\*\*§(\d+)\s*—\s*", text, flags=re.M)
    out: dict[str, dict] = {}
    for i in range(1, len(blocks), 2):
        num, body = blocks[i], blocks[i + 1]
        title = body.split("**", 1)[0].strip()
        # Первая редакция требовала ровно `**MANUAL**` и молча отдавала "?" на
        # `**MANUAL.**` — точка внутри жирного. Тихий недобор в собственном
        # стороже: 20 правил из 24 выпали из проверки, потому что она
        # придирается только к заявленному LIVE. Поймал сгенерированный
        # артефакт, что и есть его назначение (§24, 2026-07-28).
        m = re.search(r"\*Enforcement:\*\s*\*\*(LIVE|PARTIAL|MANUAL)[.,: ]*\*\*", body)
        out[num] = {"title": title[:70], "enforcement": m.group(1) if m else "?"}
    return out


def code_files() -> list[Path]:
    files: list[Path] = []
    for g in CODE_GLOBS:
        files.extend(SCRIPTS.glob(g))
    return [f for f in files if f.is_file()]


def rules_mentioned_in_code() -> dict[str, set[str]]:
    """§N -> имена файлов, где он упомянут. Механизм обязан называть своё правило."""
    hits: dict[str, set[str]] = {}
    for f in code_files():
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for num in set(re.findall(r"§(\d+)", txt)):
            hits.setdefault(num, set()).add(f.name)
    return hits


# ------------------------------------------------------ A. свод против кода
def check_enforcement_claims(rules: dict, hits: dict) -> None:
    """LIVE требует упоминания; обратное неверно и механизм не доказан."""
    for num, r in sorted(rules.items(), key=lambda x: int(x[0])):
        claimed, mentioned = r["enforcement"], hits.get(num, set())
        if claimed == "?":
            # Неразобранное заявление опаснее любого заявления: правило молча
            # выпадает из проверки. Нечитаемый свод — отказ, а не пропуск.
            fail(f"§{num}: не разобрано поле Enforcement — правило выпало бы из "
                 f"проверки незамеченным ({r['title']})")
        elif claimed == "LIVE" and not mentioned:
            fail(f"§{num} заявлен LIVE, но НИ ОДИН файл в scripts/ его не упоминает — "
                 f"свод врёт о себе ({r['title']})")
        # MANUAL с упоминаниями допустим: это не свидетельство механизма.
        # Список остаётся в ENFORCEMENT.md, без шума на каждом коммите.


# --------------------------------------------- B. обход guarded_fetch (§23)
def check_no_fetch_bypass() -> None:
    """Отсутствие импорта guarded_fetch в файле, который сам ходит в OData."""
    for f in code_files():
        if f.suffix != ".py" or f.name in ("guarded_fetch.py", "check_artifacts.py"):
            continue  # guard — эталон; сам детектор содержит образцы, которые ищет
        txt = f.read_text(encoding="utf-8", errors="replace")
        if not any(m in txt for m in BULK_MARKS) or "urlopen(" not in txt:
            continue
        # Требуется ИМПОРТ, а не упоминание. Первая редакция принимала любое
        # вхождение слова `guarded_fetch` — и тогда КОММЕНТАРИЙ глушил детектор.
        # Найдено 2026-07-30 на себе: я дописал в docstring probe_phase0 фразу
        # «рабочая выгрузка идёт через guarded_fetch.fetch_sql», и файл стал
        # выглядеть защищённым. Тот же класс, что названная дыра проверки (A):
        # упоминание доказывает намерение, а не работу механизма — только здесь
        # оно ещё и ОТКЛЮЧАЕТ проверку, а не просто ничего не доказывает.
        if re.search(r"^\s*(?:import\s+guarded_fetch|from\s+guarded_fetch\s+import)",
                     txt, flags=re.M):
            continue
        m = re.search(re.escape(EXEMPT_MARK) + r"\s*(\S.*)", txt)
        if m:
            note(f"§23 обход объявлен в {f.name}: {m.group(1).strip()[:70]}")
            continue
        fail(f"§23 ОБХОД: {f.name} сам ходит в источник массовых данных "
             f"(OData или obudget) через urlopen, не использует "
             f"guarded_fetch и не несёт пометки `{EXEMPT_MARK} <причина>` — "
             "выгрузка без объявленного ожидания объёма")


# ------------------------------------------------- C. манифест выгрузок (§23)
def check_manifest() -> None:
    if not MANIFEST.exists():
        note("data/MANIFEST.json отсутствует — выгрузок ещё не было")
        return
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        fail(f"data/MANIFEST.json нечитаем: {e}")
        return
    unchecked = [k for k, v in data.items() if v.get("expected") is None]
    if unchecked:
        note(f"§23: выгрузок без сверки объёма — {len(unchecked)}: {', '.join(unchecked[:5])}")
    for k, v in data.items():
        if v.get("expected") is not None and v.get("expected") != v.get("got"):
            fail(f"§23: в манифесте расхождение {k}: ожидалось {v['expected']}, "
                 f"записано {v.get('got')}")

    # Выгрузка была, а следа в git нет. До 30.07 это состояние было НЕВИДИМО:
    # манифест лежал в рабочем дереве, post-receive делал `git reset --hard`,
    # и записи исчезали — молчание проверки не отличалось от «выгрузок не было».
    # Теперь рантайм-буфер живёт вне git и переживает сброс, а расхождение
    # буфера со снимком ловится здесь.
    try:
        sys.path.insert(0, str(SCRIPTS))
        from guarded_fetch import unsynced  # noqa: PLC0415  §23
        left = unsynced()
    except Exception as e:  # noqa: BLE001
        fail(f"§23: детектор рассинхронизации манифеста не работает: {e}")
        return
    if left:
        fail(f"§23: выгрузок без следа в git — {len(left)}: "
             f"{', '.join(left[:4])}. Буфер помнит, снимок нет. "
             "Лечится: python3 scripts/guarded_fetch.py --sync && "
             "git add data/MANIFEST.json")


# ------------------------------------ D. карточки против справочников (§1,§7)
def check_cards() -> None:
    cards = sorted(CARDS.rglob("*.yaml")) if CARDS.exists() else []
    if not cards:
        note("карточек ещё нет — проверки §1/§7/§23-покрытия спят, но НЕ отключены")
        return
    periods = CRITERIA / "periods.yaml"
    if not periods.exists():
        fail(f"§1: карточек {len(cards)}, а criteria/periods.yaml НЕТ — "
             "период наблюдения не из справочника")
    manifest = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    for c in cards:
        txt = c.read_text(encoding="utf-8", errors="replace")
        # §1 — единица наблюдения РАЗЛИЧАЕТСЯ по каналам (поправка свода
        # 01.08): партия × период для денег, фракция × Кнессет для
        # голосований. Это третье место в проекте, где правило было написано
        # для канала Б и запрещало канал А; первые два — §1 и §7 в
        # validate_cards, найдены в тот же день. Проверка отсутствия
        # оказалась проверкой ОДНОЙ формы, и потому запрещала другую.
        if "period_id" not in txt and "unit: faction_knesset" not in txt:
            fail(f"§1: {c.relative_to(ROOT)} без period_id и без "
                 "объявленной единицы faction_knesset")
        if "counter_search" not in txt:
            fail(f"§4: {c.relative_to(ROOT)} без отчёта о поиске опровержения")
        if not manifest:
            fail(f"§23: {c.relative_to(ROOT)} существует, а data/MANIFEST.json пуст — "
                 "данные пришли путём, не оставившим следа")
            break


# --------------------------------------- E. установлен ли хук (§20, §24)
def check_hooks_installed() -> None:
    """Отслеживаемый хук и установленный обязаны совпадать.

    Повод (2026-07-30): `scripts/git-hooks/commit-msg` с 29.07 зовёт и §3,
    и квитанцию ponytail — а в `.git/hooks/commit-msg` лежала прежняя редакция,
    занятая одним ponytail'ом. Переустановить забыли. Предупредительный режим
    §3 не вызывался НИОТКУДА, и это не было видно ничем: механизм есть, файл
    в репозитории есть, в отчётах он считался работающим (§20).

    Класс отказа тот же, что у §23: шаг отчитался об успехе («хук написан»)
    и тихо не сделал того, чего от него ждали. Установка — тоже операция,
    и у неё тоже обязан быть оракул.

    Хуки не отслеживаются git по устройству, поэтому единственная возможная
    проверка — сверка содержимого двух файлов. Она ловит расхождение, а не
    правильность хука.
    """
    src_dir = SCRIPTS / "git-hooks"
    dst_dir = ROOT / ".git" / "hooks"
    if not src_dir.is_dir():
        note("scripts/git-hooks/ нет — установку проверять нечем")
        return
    if not dst_dir.is_dir():
        note(".git/hooks/ недоступен (не рабочее дерево?) — установку не проверить")
        return
    for src in sorted(src_dir.iterdir()):
        if not src.is_file():
            continue
        dst = dst_dir / src.name
        if not dst.exists():
            fail(f"хук {src.name} НЕ УСТАНОВЛЕН: есть scripts/git-hooks/{src.name}, "
                 f"нет .git/hooks/{src.name}. Механизм, который не вызывается, "
                 "не работает (§20). Лечится: "
                 f"cp scripts/git-hooks/{src.name} .git/hooks/ && "
                 f"chmod +x .git/hooks/{src.name}")
            continue
        a = src.read_text(encoding="utf-8", errors="replace")
        b = dst.read_text(encoding="utf-8", errors="replace")
        if a != b:
            fail(f"хук {src.name} РАСХОДИТСЯ с отслеживаемым: "
                 f"scripts/git-hooks/{src.name} ({len(a)} б) против "
                 f".git/hooks/{src.name} ({len(b)} б). Работает установленный, "
                 "а читают отслеживаемый — это два источника правды. Лечится "
                 f"переустановкой либо правкой отслеживаемого.")


# ------------------------------------------------------------ F. артефакт
def write_enforcement(rules: dict, hits: dict) -> None:
    ENFORCEMENT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ENFORCEMENT — заявления свода и упоминания в коде",
        "",
        "**Файл СГЕНЕРИРОВАН** `scripts/check_artifacts.py`. Руками не править:",
        "правка будет затёрта, а расхождение с кодом — это и есть то, что файл ловит.",
        "",
        "Столбец «заявлено» берётся из `CLAUDE.md`, «файлы с упоминанием» — из",
        "текстового поиска `§N` в `scripts/`, включая комментарии и ссылки на чужие своды.",
        "Упоминание не механизм (инвариант `mention_is_not_mechanism` в",
        "`subsystem_intent.yaml`): оно не доказывает ни наличие проверки, ни её работу.",
        "MANUAL с упоминаниями допустим; оснований повышать Enforcement здесь нет.",
        "Проверка (A) блокирует LIVE без упоминаний, но их наличие не подтверждает LIVE.",
        "",
        "| § | правило | заявлено | файлы с упоминанием |",
        "|---|---|---|---|",
    ]
    for num, r in sorted(rules.items(), key=lambda x: int(x[0])):
        m = ", ".join(sorted(hits.get(num, set()))) or "—"
        lines.append(f"| §{num} | {r['title']} | {r['enforcement']} | {m} |")
    live = sum(1 for r in rules.values() if r["enforcement"] == "LIVE")
    lines += ["", f"Всего правил: {len(rules)} · заявлено LIVE: {live} · "
                  f"упомянуто в коде: {len(hits)}"]
    ENFORCEMENT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if "--selftest" in sys.argv:
        # Настоящий файл с одним комментарием: сканер видит текст, не защиту.
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mention_only.py").write_text("# §22\n", encoding="utf-8")
            with patch.multiple(sys.modules[__name__], SCRIPTS=root,
                                ENFORCEMENT=root / "ENFORCEMENT.md",
                                problems=[], notes=[]):
                rules = {"22": {"title": "только комментарий", "enforcement": "MANUAL"}}
                hits = rules_mentioned_in_code()
                assert hits == {"22": {"mention_only.py"}}, hits
                check_enforcement_claims(rules, hits)
                assert not problems and not notes, (problems, notes)
                assert rules["22"]["enforcement"] == "MANUAL"
                write_enforcement(rules, hits)
                doc = ENFORCEMENT.read_text(encoding="utf-8")
                assert "| MANUAL | mention_only.py |" in doc
                assert "Упоминание не механизм" in doc
                assert "код знает" not in doc
                rules["22"]["enforcement"] = "LIVE"
                check_enforcement_claims(rules, {})
                assert len(problems) == 1, "LIVE без упоминания должен краснеть"
        print("check_artifacts selftest: комментарий не механизм; LIVE без упоминания — отказ")
        return 0
    rules = parse_rules()
    if not rules:
        fail("не разобрал ни одного § из CLAUDE.md — сломан парсер или формат свода")
        return 1
    hits = rules_mentioned_in_code()
    check_enforcement_claims(rules, hits)
    check_no_fetch_bypass()
    check_manifest()
    check_cards()
    check_hooks_installed()
    write_enforcement(rules, hits)

    for n in notes:
        print(f"  · {n}")
    if problems:
        print("\nНАРУШЕНИЯ (§24):", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1
    print(f"§24 OK: правил {len(rules)}, артефакт ENFORCEMENT.md обновлён.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"§24 ОШИБКА ПРОВЕРКИ (это блок, не warn): {exc}", file=sys.stderr)
        sys.exit(2)
