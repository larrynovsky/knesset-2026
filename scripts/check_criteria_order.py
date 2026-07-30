#!/usr/bin/env python3
"""CLAUDE.md §3 — критерии отбора коммитятся РАНЬШЕ данных.

Единственная защита главного правила проекта. Постфактумный отбор
голосований невозможно обнаружить проверкой результата (Snyder, LSQ 1992) —
только проверкой порядка. Порядок доказывает git-история.

Правило:
  первый коммит, вводящий criteria/, обязан быть предком первого коммита,
  вводящего cards/ или data-манифест.

  После этой границы РАЗЛИЧАЮТСЯ два действия, и это различение — суть
  редакции 2026-07-30:

    ИЗМЕНЕНИЕ существующего файла criteria/ — обязан префикс
      `criteria-revision:`. Это и есть тот трюк, против которого §3 написан:
      посмотреть на результаты и подкрутить критерий.

    ДОБАВЛЕНИЕ нового файла для канала, по которому данных ЕЩЁ НЕТ — законно
      без префикса, но файл обязан объявить свой канал и то, чем этот канал
      опознаётся в репозитории. Сторож проверяет, что таких данных на момент
      добавления действительно не было.

Почему различение обязательно (иначе §3 деградирует сам).
Свод формулирует правило как «раньше, чем появится первый артефакт данных
ПО СООТВЕТСТВУЮЩЕМУ КАНАЛУ». Прежняя реализация каналов не различала:
любое касание criteria/ после границы требовало ярлыка «пересмотр». Тогда
новый критерий нового канала обязан лгать о себе, что он пересмотр, — а
когда ярлык стоит на всём, читать его перестают, и НАСТОЯЩИЙ пересмотр
становится невидим в шуме. Поймано 2026-07-30 на criteria/budget_mapping.yaml:
новый критерий канала Б был отвергнут как тихая правка.

Объявление в файле критериев — две строки-комментария, поэтому годятся и
yaml, и json, и парсер не нужен (stdlib, ступень 2 лестницы):

    # §3-channel: B-budget
    # §3-data-markers: obudget:*, cards/*budget*

Маркеры сверяются с КЛЮЧАМИ data/MANIFEST.json и с путями дерева на момент,
предшествующий добавлению. Манифест выбран потому, что он отслеживается git и
его ключи называют источник (`KNS_Faction|`, `obudget:raw_budget|`), тогда как
сами выгрузки в git не попадают — data/ заигнорен.

Честная граница, называю сразу: объявленные маркеры пишет автор файла.
Неверный или слишком узкий маркер сторож не поймает. Он ловит то, что
проверяемо: файл обязан объявить канал ДО данных, объявление публично, и
несоответствие видно в диффе. Это доказывает, что заявление сделано, а не
что оно правдиво (§24, честная граница — дословно оттуда).

Два режима, и второй появился потому, что первого не хватало:

  без аргументов        — смотрит ИСТОРИЮ. Обнаруживает нарушение, которое
                          уже произошло.
  --commit-msg FILE     — смотрит ИНДЕКС и сообщение готовящегося коммита.
                          Предотвращает нарушение до попадания в историю.
                          Ставится хуком commit-msg.

⚠️ Второй режим существовал с 29.07 и НЕ ВЫЗЫВАЛСЯ: правильный
scripts/git-hooks/commit-msg (он зовёт и §3, и квитанцию ponytail) не был
переустановлен в .git/hooks на MacBook — там лежала прежняя редакция, занятая
одним ponytail'ом. Механизм был, механизм не работал, и в отчётах считался
работающим (§20). Обнаружено 2026-07-30 тем, что нарушение прошло, а счёт был
предъявлен следующему коммиту — ровно как предсказано абзацем ниже. С этого дня
несовпадение установленного хука с отслеживаемым ловит check_artifacts.

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

import fnmatch
import json
import subprocess
import sys

WATCHED_DATA = ["cards/", "data/MANIFEST.json"]
REVISION_PREFIX = "criteria-revision:"
CRITERIA_DIR = "criteria/"
BOUNDARY_MARK = "ГРАНИЦА §3"
CHANNEL_MARK = "# §3-channel:"
MARKERS_MARK = "# §3-data-markers:"


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def git_or_empty(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def first_add(path: str) -> str | None:
    """Хеш коммита, впервые добавившего файл под path. None — не появлялся."""
    out = git("log", "--diff-filter=A", "--format=%H", "--reverse", "--", path)
    return out.splitlines()[0] if out else None


def is_ancestor(a: str, b: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b]).returncode == 0


# ------------------------------------------------------- чистая логика решения
def parse_channel(text: str) -> tuple[str, list[str]]:
    """Объявление канала из файла критериев. Пустое — значит не объявлено."""
    channel, markers = "", []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(CHANNEL_MARK):
            channel = s[len(CHANNEL_MARK):].strip()
        elif s.startswith(MARKERS_MARK):
            markers = [m.strip() for m in s[len(MARKERS_MARK):].split(",") if m.strip()]
    return channel, markers


def check_added(path: str, text: str, prior_keys: list[str],
                prior_paths: list[str]) -> str | None:
    """Законно ли ДОБАВЛЕНИЕ этого файла критериев. None — законно."""
    if BOUNDARY_MARK not in text:
        return (f"{path}: добавлен без блока «{BOUNDARY_MARK}» — заявление о том, "
                "что автор видел и чего не видел, обязательно")
    channel, markers = parse_channel(text)
    if not channel:
        return f"{path}: не объявлен `{CHANNEL_MARK} <id>`"
    if not markers:
        return f"{path}: не объявлены `{MARKERS_MARK} <glob, glob>`"
    hits = [k for k in prior_keys if any(fnmatch.fnmatch(k, m) for m in markers)]
    hits += [p for p in prior_paths if any(fnmatch.fnmatch(p, m) for m in markers)]
    if hits:
        return (f"{path}: данные канала «{channel}» уже существовали на момент "
                f"добавления критерия: {hits[:3]}")
    return None


def decide(subject: str, modified: list[str], added_problems: list[str],
           boundary: bool) -> str | None:
    """Единственное место, где принимается решение «блок или пропуск».

    Вынесена намеренно: обязана быть проверяемой без git, без файлов и без
    сети. См. --selftest.
    """
    if not boundary:
        return None
    if subject.startswith(REVISION_PREFIX):
        return None                     # помеченный пересмотр законен всегда
    if modified:
        return ("изменение существующих критериев без префикса: "
                + ", ".join(sorted(modified)))
    if added_problems:
        return "; ".join(added_problems)
    return None


# ------------------------------------------------------------ состояние «до»
def manifest_keys_at(ref: str) -> list[str]:
    txt = git_or_empty("show", f"{ref}:data/MANIFEST.json")
    if not txt.strip():
        return []
    try:
        return list(json.loads(txt).keys())
    except Exception:                   # повреждённый манифест — не наша забота
        return []


def tree_paths_at(ref: str) -> list[str]:
    return git_or_empty("ls-tree", "-r", "--name-only", ref).splitlines()


def split_status(raw: str, at_head_paths: list[str] | None = None
                 ) -> tuple[list[str], list[str]]:
    """`A\\tpath` -> (modified, added). Повторное добавление = изменение.

    Лазейка, которую это закрывает: удалить файл критериев и добавить заново,
    чтобы статус стал A и ярлык стал не нужен.
    """
    modified, added = [], []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        st, path = parts[0].strip(), parts[-1].strip()
        if st.startswith("A") and (at_head_paths is None or path not in at_head_paths):
            added.append(path)
        else:
            modified.append(path)
    return modified, added


def check_commit_msg(msg_path: str) -> int:
    boundary = any(first_add(p) for p in WATCHED_DATA)
    raw = git_or_empty("diff", "--cached", "--name-status", "--", CRITERIA_DIR)
    head_paths = tree_paths_at("HEAD")
    modified, added = split_status(raw, head_paths)
    # Повторное добавление уже существовавшего в истории пути — не добавление,
    # а изменение: удалить файл и завести заново не должно снимать ярлык.
    real_added = []
    for p in added:
        (modified if first_add(p) else real_added).append(p)
    added = real_added

    prior_keys, prior_paths = manifest_keys_at("HEAD"), head_paths
    problems = []
    for p in added:
        text = git_or_empty("show", f":{p}")
        prob = check_added(p, text, prior_keys, prior_paths)
        if prob:
            problems.append(prob)

    subject = subject_of(msg_path)
    reason = decide(subject, modified, problems, boundary)
    if reason is None:
        return 0

    print("§3 ОТКАЗ до попадания в историю:", file=sys.stderr)
    print(f"  {reason}", file=sys.stderr)
    print(f"  subject: {subject[:70]}", file=sys.stderr)
    print(f"  Пересмотр легален, но обязан нести префикс '{REVISION_PREFIX}'",
          file=sys.stderr)
    print("  и поле «что заставило пересмотреть». См. CLAUDE.md §3.", file=sys.stderr)
    return 1


def subject_of(msg_path: str) -> str:
    """Первая непустая строка сообщения, не считая комментариев git."""
    with open(msg_path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    return ""


def selftest() -> int:
    """Оракул решающей логики. Красное здесь = §3 больше не охраняется."""
    ok = True

    # --- decide: то, ради чего всё
    cases = [
        # (subject, modified, added_problems, boundary, ожидается блок)
        ("правка лексикона", ["criteria/keyvotes.yaml"], [], True, True),
        ("criteria-revision: K4 расширил ось", ["criteria/keyvotes.yaml"], [], True, False),
        ("правка лексикона", ["criteria/keyvotes.yaml"], [], False, False),
        ("рефакторинг скриптов", [], [], True, False),
        ("", ["criteria/keyvotes.yaml"], [], True, True),
        ("Ф1: новый критерий канала Б", [], [], True, False),
        ("Ф1: новый критерий канала Б", [], ["criteria/x.yaml: не объявлен канал"], True, True),
        # помеченный пересмотр гасит и претензию к добавленному файлу — обход
        # легален, потому что он ВИДЕН в истории
        ("criteria-revision: и то и это", [], ["criteria/x.yaml: нет блока"], True, False),
    ]
    bad = [c for c in cases if (decide(c[0], c[1], c[2], c[3]) is not None) != c[4]]
    if bad:
        print(f"decide: ПРОВАЛ на {len(bad)} случаях: {bad}", file=sys.stderr)
        ok = False

    # --- parse_channel
    text = ("# §3-channel: B-budget\n"
            "# §3-data-markers: obudget:*, cards/*budget*\n"
            "version: '1.0'\n")
    if parse_channel(text) != ("B-budget", ["obudget:*", "cards/*budget*"]):
        print(f"parse_channel: ПРОВАЛ -> {parse_channel(text)}", file=sys.stderr)
        ok = False
    if parse_channel("version: '1.0'") != ("", []):
        print("parse_channel: необъявленное прочиталось как объявленное", file=sys.stderr)
        ok = False

    # --- check_added: главный случай и все отказы
    good = f"# {BOUNDARY_MARK}\n" + text
    subcases = [
        ("данных канала нет", good, ["KNS_Faction|"], ["scripts/x.py"], False),
        ("данные канала уже есть", good, ["obudget:raw_budget|year=2023"], [], True),
        ("карточка канала уже есть", good, [], ["cards/shas-budget.yaml"], True),
        ("нет блока границы", text, [], [], True),
        ("нет канала", f"# {BOUNDARY_MARK}\n# §3-data-markers: obudget:*\n", [], [], True),
        ("нет маркеров", f"# {BOUNDARY_MARK}\n# §3-channel: B\n", [], [], True),
    ]
    for name, txt, keys, paths, expect_block in subcases:
        got = check_added("criteria/t.yaml", txt, keys, paths)
        if (got is not None) != expect_block:
            print(f"check_added [{name}]: ПРОВАЛ -> {got}", file=sys.stderr)
            ok = False

    # --- split_status: повторное добавление не должно выглядеть добавлением
    m, a = split_status("A\tcriteria/new.yaml\nM\tcriteria/old.yaml\n",
                        ["criteria/old.yaml"])
    if (m, a) != (["criteria/old.yaml"], ["criteria/new.yaml"]):
        print(f"split_status: ПРОВАЛ -> {m}, {a}", file=sys.stderr)
        ok = False
    m, a = split_status("A\tcriteria/old.yaml\n", ["criteria/old.yaml"])
    if a or m != ["criteria/old.yaml"]:
        print(f"split_status: пере-добавление прошло как добавление -> {m}, {a}",
              file=sys.stderr)
        ok = False

    # Три инварианта, которые обязаны держаться всегда — assert'ом, а не
    # печатью. Печать сообщает; assert останавливает. Если §3 когда-нибудь
    # начнут «чинить», сломав одно из этих трёх, самопроверка обязана упасть,
    # а не напечатать строчку в общем потоке.
    assert decide("правка лексикона", ["criteria/keyvotes.yaml"], [], True) is not None, \
        "§3: правка существующих критериев после границы обязана блокироваться"
    assert decide("criteria-revision: повод", ["criteria/keyvotes.yaml"], [], True) is None, \
        "§3: помеченный пересмотр обязан проходить — иначе ярлык бесполезен"
    assert check_added("criteria/t.yaml", good, ["obudget:raw_budget|"], []) is not None, \
        "§3: добавление критерия при уже существующих данных канала — нарушение"

    if not ok:
        return 1
    n = len(cases) + len(subcases) + 7
    print(f"самопроверка §3 пройдена: {n} утверждений решающей логики")
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

    crit = first_add(CRITERIA_DIR)
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

    # Коммиты, трогавшие criteria/ после границы: изменение против добавления.
    after = git("log", "--format=%H%x00%s", f"{data}..HEAD", "--", CRITERIA_DIR)
    bad: list[tuple[str, str, str]] = []
    added_total = validated = skipped_by_prefix = 0
    for line in after.splitlines():
        if not line:
            continue
        h, _, subj = line.partition("\x00")
        raw = git_or_empty("show", "--format=", "--name-status", h, "--", CRITERIA_DIR)
        modified, added = split_status(raw)
        # A, но не первое появление пути в истории → это пере-добавление.
        real_added, readded = [], []
        for p in added:
            (real_added if first_add(p) == h else readded).append(p)
        modified += readded

        prior_keys = manifest_keys_at(f"{h}^")
        prior_paths = tree_paths_at(f"{h}^")
        problems = []
        for p in real_added:
            txt = git_or_empty("show", f"{h}:{p}")
            prob = check_added(p, txt, prior_keys, prior_paths)
            if prob:
                problems.append(prob)
        added_total += len(real_added)

        reason = decide(subj, modified, problems, True)
        if reason:
            bad.append((h[:9], subj, reason))
        elif subj.startswith(REVISION_PREFIX):
            # Помеченный пересмотр гасит проверку добавленных файлов целиком.
            # Считаем их отдельно, иначе итоговая строка соврёт: «все с
            # объявленным каналом» про файлы, у которых канал не проверялся.
            skipped_by_prefix += len(real_added)
        else:
            validated += len(real_added)

    if bad:
        print("§3 НАРУШЕН: тихий пересмотр критериев после появления данных.",
              file=sys.stderr)
        for h, subj, reason in bad:
            print(f"  {h}  {subj}", file=sys.stderr)
            print(f"            {reason}", file=sys.stderr)
        print(f"  Пересмотр легален, но обязан нести префикс '{REVISION_PREFIX}'",
              file=sys.stderr)
        print("  и поле «что заставило пересмотреть». См. CLAUDE.md §3.", file=sys.stderr)
        return 1

    tail = ""
    if skipped_by_prefix:
        tail = (f", из них {skipped_by_prefix} НЕ проверены — их коммит помечен "
                f"'{REVISION_PREFIX}', а ярлык гасит проверку канала")
    print(f"§3 OK: criteria/ ({crit[:9]}) предшествуют данным ({data[:9]}); "
          f"добавлений после границы: {added_total}, "
          f"с проверенным каналом: {validated}{tail}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # блокируем, а не пропускаем
        print(f"§3 ОШИБКА ПРОВЕРКИ (это блок, не warn): {exc}", file=sys.stderr)
        sys.exit(2)
