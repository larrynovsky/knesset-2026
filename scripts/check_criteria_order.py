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

Два режима, и второй появился потому, что первого не хватало:

  без аргументов        — смотрит ИСТОРИЮ. Обнаруживает нарушение, которое
                          уже произошло.
  --commit-msg FILE     — смотрит ИНДЕКС и сообщение готовящегося коммита.
                          Предотвращает нарушение до попадания в историю.
                          Ставится хуком commit-msg.

Почему второй режим обязателен (проверено прогоном 2026-07-29, §22).
В pre-commit коммита ещё нет в `git log`, поэтому исторический режим его
не видит: тихая правка критериев проходила, а падал СЛЕДУЮЩИЙ коммит —
любой, даже не трогающий criteria/. Защита работала с задержкой в один
коммит и предъявляла счёт не тому изменению. Хуже: к моменту отказа автор
уже посмотрел на данные, то есть §3 был нарушен по существу, а исправление
требовало переписывания истории. Это §24 буквально: механизм защищал
собственный вызов, а не правило.

Выход: 0 — порядок цел · 1 — нарушен · 2 — внутренняя ошибка (это блок, не warn:
отказ инструмента суждения не означает отсутствия нарушения).
Самопроверка решающей логики: python3 scripts/check_criteria_order.py --selftest
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


def violates(subject: str, staged_criteria: bool, boundary: bool) -> bool:
    """Всё решение режима --commit-msg в одной чистой функции.

    Вынесена из main намеренно: это единственное место, где принимается
    решение «блок или пропуск», и оно обязано быть проверяемым без git,
    без файлов и без сети. См. --selftest.
    """
    return boundary and staged_criteria and not subject.startswith(REVISION_PREFIX)


def subject_of(msg_path: str) -> str:
    """Первая непустая строка сообщения, не считая комментариев git."""
    with open(msg_path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    return ""


def check_commit_msg(msg_path: str) -> int:
    boundary = any(first_add(p) for p in WATCHED_DATA)
    staged = git("diff", "--cached", "--name-only", "--", "criteria/")
    subject = subject_of(msg_path)

    if not violates(subject, bool(staged), boundary):
        return 0

    print("§3 ОТКАЗ: тихая правка критериев после появления данных.", file=sys.stderr)
    for p in staged.splitlines():
        print(f"  в индексе: {p}", file=sys.stderr)
    print(f"  subject:   {subject[:70]}", file=sys.stderr)
    print(f"  Пересмотр легален, но обязан нести префикс '{REVISION_PREFIX}'", file=sys.stderr)
    print("  и поле «что заставило пересмотреть». См. CLAUDE.md §3.", file=sys.stderr)
    return 1


def selftest() -> int:
    """Оракул решающей логики. Красное здесь = §3 больше не охраняется."""
    cases = [
        # (subject, criteria в индексе, граница наступила, ожидается блок)
        ("правка лексикона", True, True, True),        # то, ради чего всё
        ("criteria-revision: K4 расширил ось", True, True, False),
        ("правка лексикона", True, False, False),      # границы ещё нет
        ("рефакторинг скриптов", False, True, False),  # критериев в индексе нет
        ("", True, True, True),                        # пустое сообщение не лазейка
    ]
    bad = [c for c in cases if violates(c[0], c[1], c[2]) != c[3]]
    if bad:
        print(f"САМОПРОВЕРКА ПРОВАЛЕНА на {len(bad)} случаях: {bad}", file=sys.stderr)
        return 1
    print(f"самопроверка §3 пройдена: {len(cases)} случая решающей логики")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--commit-msg" in sys.argv:
        i = sys.argv.index("--commit-msg")
        if i + 1 >= len(sys.argv):
            print("§3: --commit-msg требует путь к файлу сообщения", file=sys.stderr)
            return 2
        return check_commit_msg(sys.argv[i + 1])

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
