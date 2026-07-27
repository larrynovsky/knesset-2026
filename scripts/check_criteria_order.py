#!/usr/bin/env python3
"""CLAUDE.md §3 — критерии отбора коммитятся РАНЬШЕ данных.

Единственная защита главного правила проекта. Постфактумный отбор
голосований невозможно обнаружить проверкой результата (Snyder, LSQ 1992) —
только проверкой порядка. Порядок доказывает git-история.

Правило:
  первый коммит, вводящий criteria/, обязан быть предком первого коммита,
  вводящего cards/ или data-манифест.

  Любой коммит, ТРОГАЮЩИЙ criteria/ после этой границы, обязан иметь
  subject с префиксом `criteria-revision:` — пересмотр легален, тихий
  пересмотр нет.

Выход: 0 — порядок цел · 1 — нарушен · 2 — внутренняя ошибка (это блок, не warn:
отказ инструмента суждения не означает отсутствия нарушения).
"""
from __future__ import annotations   # системный python3 на MacBook < 3.10

import subprocess
import sys

WATCHED_DATA = ["cards/", "data/MANIFEST.json"]
REVISION_PREFIX = "criteria-revision:"


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def first_add(path: str) -> str | None:
    """Хеш коммита, впервые добавившего файл под path. None — не появлялся."""
    out = git("log", "--diff-filter=A", "--format=%H", "--reverse", "--", path)
    return out.splitlines()[0] if out else None


def is_ancestor(a: str, b: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b]).returncode == 0


def main() -> int:
    crit = first_add("criteria/")
    data = None
    for p in WATCHED_DATA:
        c = first_add(p)
        if c and (data is None or is_ancestor(c, data)):
            data = c

    if data is None:
        print("§3 OK: данных ещё нет — нарушать нечего.")
        return 0

    if crit is None:
        print("§3 НАРУШЕН: данные появились, а criteria/ не существует.", file=sys.stderr)
        print(f"  первый коммит с данными: {data[:9]}", file=sys.stderr)
        print("  Критерии обязаны быть зафиксированы ДО первого взгляда", file=sys.stderr)
        print("  на результаты. См. CLAUDE.md §3.", file=sys.stderr)
        return 1

    if not is_ancestor(crit, data):
        print("§3 НАРУШЕН: criteria/ не предшествуют данным.", file=sys.stderr)
        print(f"  criteria/ введены в {crit[:9]}", file=sys.stderr)
        print(f"  данные введены в  {data[:9]}", file=sys.stderr)
        return 1

    # Коммиты, трогавшие criteria/ после границы, обязаны быть помечены.
    after = git("log", "--format=%H%x00%s", f"{data}..HEAD", "--", "criteria/")
    bad = []
    for line in after.splitlines():
        if not line:
            continue
        h, _, subj = line.partition("\x00")
        if not subj.startswith(REVISION_PREFIX):
            bad.append((h[:9], subj))

    if bad:
        print("§3 НАРУШЕН: тихий пересмотр критериев после появления данных.", file=sys.stderr)
        for h, subj in bad:
            print(f"  {h}  {subj}", file=sys.stderr)
        print(f"  Пересмотр легален, но обязан нести префикс '{REVISION_PREFIX}'", file=sys.stderr)
        print("  и поле «что заставило пересмотреть». См. CLAUDE.md §3.", file=sys.stderr)
        return 1

    print(f"§3 OK: criteria/ ({crit[:9]}) предшествуют данным ({data[:9]}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # блокируем, а не пропускаем
        print(f"§3 ОШИБКА ПРОВЕРКИ (это блок, не warn): {exc}", file=sys.stderr)
        sys.exit(2)
