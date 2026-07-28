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

Побочный продукт — docs/reference/ENFORCEMENT.md: таблица «§ → механизм»,
СГЕНЕРИРОВАННАЯ из кода, а не написанная рукой. Свод заявляет Enforcement сам
о себе; сгенерированная таблица показывает, правда ли это.

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
        m = re.search(r"\*Enforcement:\*\s*\*\*(LIVE|PARTIAL|MANUAL)\*\*", body)
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
    """Самая важная проверка: заявленный LIVE обязан иметь код, который его знает."""
    for num, r in sorted(rules.items(), key=lambda x: int(x[0])):
        claimed, mentioned = r["enforcement"], hits.get(num, set())
        if claimed == "LIVE" and not mentioned:
            fail(f"§{num} заявлен LIVE, но НИ ОДИН файл в scripts/ его не упоминает — "
                 f"свод врёт о себе ({r['title']})")
        elif claimed == "MANUAL" and mentioned:
            note(f"§{num} заявлен MANUAL, но код его знает ({', '.join(sorted(mentioned))}) — "
                 "свод отстал, поднять до PARTIAL/LIVE")


# --------------------------------------------- B. обход guarded_fetch (§23)
def check_no_fetch_bypass() -> None:
    """Отсутствие импорта guarded_fetch в файле, который сам ходит в OData."""
    for f in code_files():
        if f.suffix != ".py" or f.name in ("guarded_fetch.py", "check_artifacts.py"):
            continue  # guard — эталон; сам детектор содержит образцы, которые ищет
        txt = f.read_text(encoding="utf-8", errors="replace")
        if ODATA_MARK not in txt or "urlopen(" not in txt:
            continue
        if "guarded_fetch" in txt:
            continue
        m = re.search(re.escape(EXEMPT_MARK) + r"\s*(\S.*)", txt)
        if m:
            note(f"§23 обход объявлен в {f.name}: {m.group(1).strip()[:70]}")
            continue
        fail(f"§23 ОБХОД: {f.name} сам ходит в OData через urlopen, не использует "
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
        if "period_id" not in txt:
            fail(f"§1: {c.relative_to(ROOT)} без period_id")
        if "counter_search" not in txt:
            fail(f"§4: {c.relative_to(ROOT)} без отчёта о поиске опровержения")
        if not manifest:
            fail(f"§23: {c.relative_to(ROOT)} существует, а data/MANIFEST.json пуст — "
                 "данные пришли путём, не оставившим следа")
            break


# ------------------------------------------------------------ E. артефакт
def write_enforcement(rules: dict, hits: dict) -> None:
    ENFORCEMENT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ENFORCEMENT — что реально стоит на страже",
        "",
        "**Файл СГЕНЕРИРОВАН** `scripts/check_artifacts.py`. Руками не править:",
        "правка будет затёрта, а расхождение с кодом — это и есть то, что файл ловит.",
        "",
        "Столбец «заявлено» берётся из `CLAUDE.md`, столбец «код знает» — из",
        "упоминаний `§N` в `scripts/`. Расхождение означает, что свод говорит о себе",
        "неправду. Совпадение НЕ означает, что механизм хорош: он ловит отсутствие",
        "носителя, а не его качество (§24).",
        "",
        "| § | правило | заявлено | код знает |",
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
    rules = parse_rules()
    if not rules:
        fail("не разобрал ни одного § из CLAUDE.md — сломан парсер или формат свода")
        return 1
    hits = rules_mentioned_in_code()
    check_enforcement_claims(rules, hits)
    check_no_fetch_bypass()
    check_manifest()
    check_cards()
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
