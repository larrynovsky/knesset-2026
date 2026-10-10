#!/usr/bin/env python3
"""Оракул нижней границы состава: >=120 уникальных депутатов за каденцию.

§20–24: только сохранённые входы, без сети и записи манифеста. CLI:
  python3 scripts/check_knesset_120.py [--data-dir DIR] [--selftest]
DIR по умолчанию — data/ проекта. Обязательные JSON-массивы:
  KNS_Faction.json: Id, KnessetNum;
  KNS_PersonToPosition_54.json: PersonID, FactionID, KnessetNum,
    полная выборка KNS_PersonToPosition с фильтром PositionID eq 54.
Допускаются дополнительные поля; PositionID, если есть, обязан быть 54.
Горизонт канала А фиксирован: каденции 16–25, включая отсутствующие в файлах.

Это НЕ проверка одновременных 120 мест: без дат нельзя отличить замену от
двойного мандата. >120 людей за каденцию (и во фракции) допустимы. Успех
доказывает лишь нижнюю границу, не полноту выгрузки (§23) и не её свежесть.
Коды: 0 — граница соблюдена; 1 — недобор; 2 — вход не проверяем;
3 — внутренняя ошибка. Все отказы блокируют генерацию, пропуска нет.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SEATS = 120
FIRST_KNESSET = 16
LAST_KNESSET = 25


def load_rows(path: Path, fields: tuple[str, ...]) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError(f"{path}: файл отсутствует") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{path}: файл не читается: {exc}") from exc
    if not raw.strip():
        raise ValueError(f"{path}: пустой файл (нет JSON)")
    if raw.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise ValueError(f"{path}: HTML вместо JSON (возможна заглушка доступа)")
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: некорректный JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise ValueError(f"{path}: ожидается JSON-массив записей")
    # KnessetNum = 0 — законное значение источника: 15 исторических партий
    # (מפא"י, חירות, אגודת ישראל…) в KNS_Faction записаны нулевой каденцией.
    # Выгрузка 2026-10-10 показала это первой же записью 35 (Id 83). Отвергать
    # их — значит объявить настоящий источник непригодным; они просто вне
    # горизонта 16–25 и ниже отбрасываются по k.
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or any(
            type(row.get(key)) is not int
            or row[key] < (0 if key == "KnessetNum" else 1) for key in fields
        ):
            raise ValueError(f"{path}: запись {i}: нужны положительные целые "
                             f"{fields} (KnessetNum допускает 0)")
        if "PositionID" in row and (
            type(row["PositionID"]) is not int or row["PositionID"] != 54
        ):
            raise ValueError(f"{path}: запись {i}: требуется PositionID=54")
    return rows


def main(data_dir: Path) -> int:
    try:
        factions_path = data_dir / "KNS_Faction.json"
        members_path = data_dir / "KNS_PersonToPosition_54.json"
        factions = load_rows(factions_path, ("Id", "KnessetNum"))
        members = load_rows(members_path, ("PersonID", "FactionID", "KnessetNum"))
        fac_kn = {f["Id"]: f["KnessetNum"] for f in factions}
        if len(fac_kn) != len(factions):
            raise ValueError(f"{factions_path}: повторяющиеся Id фракций")
        persons = {k: set() for k in range(FIRST_KNESSET, LAST_KNESSET + 1)}
        for i, row in enumerate(members):
            k = row["KnessetNum"]
            if k not in persons:
                continue
            if fac_kn.get(row["FactionID"]) != k:
                raise ValueError(f"{members_path}: запись {i}: FactionID отсутствует "
                                 "в справочнике или относится к другой каденции")
            persons[k].add(row["PersonID"])
    except ValueError as exc:
        print(f"ВХОД ОРАКУЛА 120 НЕПРИГОДЕН: {exc}. Состав не проверен.", file=sys.stderr)
        return 2

    bad = False
    for k, ids in persons.items():
        if len(ids) < SEATS:
            print(f"ОРАКУЛ 120 КРАСНЫЙ: к{k}: {len(ids)} уникальных депутатов "
                  f"за каденцию, требуется >= {SEATS}.", file=sys.stderr)
            bad = True
    if bad:
        return 1
    print(f"Оракул 120: нижняя граница соблюдена для каденций "
          f"{FIRST_KNESSET}–{LAST_KNESSET}; одновременный состав не проверялся.")
    return 0


def selftest() -> int:
    """§20–22: реальные файлы и CLI; все записи только во временном каталоге."""
    import subprocess
    import tempfile

    # Исполняем только блок оракула из настоящего шаблона: без git/reset/сборки.
    template = Path(__file__).with_name("post-receive.template").read_text()
    gate = template.split("# Оракул нижней границы:", 1)[1].split("# §24 —", 1)[0]
    gate = "# Оракул нижней границы:" + gate
    with tempfile.TemporaryDirectory(prefix="knesset-120-") as tmp:
        root = Path(tmp)
        (root / "data").symlink_to(root, target_is_directory=True)
        (root / "scripts").mkdir()
        (root / "scripts" / "check_knesset_120.py").symlink_to(Path(__file__).resolve())
        fp = root / "KNS_Faction.json"
        mp = root / "KNS_PersonToPosition_54.json"
        factions = [{"Id": k, "KnessetNum": k}
                    for k in range(FIRST_KNESSET, LAST_KNESSET + 1)]
        members = [{"PersonID": p, "FactionID": k, "KnessetNum": k}
                   for k in range(FIRST_KNESSET, LAST_KNESSET + 1)
                   for p in range(1, SEATS + 1)]
        fp.write_text(json.dumps(factions))
        mp.write_text(json.dumps(members))

        def expect(code: int, fragment: str) -> None:
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                   "--data-dir", tmp], capture_output=True, text=True)
            output = proc.stdout + proc.stderr
            assert proc.returncode == code and fragment in output, (proc.returncode, output)
            print(output.strip())
            hook = subprocess.run(["sh", "-c",
                                   'WORK="$1"; PY="$2"; say() { echo "$1"; };\n'
                                   + gate + '\necho GENERATION_REACHED\n',
                                   "selftest", tmp, sys.executable], cwd=tmp,
                                  capture_output=True, text=True)
            assert hook.returncode == (0 if code == 0 else 1), hook
            assert ("GENERATION_REACHED" in hook.stdout) == (code == 0), hook.stdout
            assert fragment in hook.stdout, hook.stdout
            if code == 2:
                assert "вход оракула 120 непригоден" in hook.stdout, hook.stdout
                assert "обнаружил недобор" not in hook.stdout, hook.stdout
            elif code == 1:
                assert "обнаружил недобор" in hook.stdout, hook.stdout

        expect(0, "нижняя граница соблюдена")
        mp.write_text(json.dumps(members[:-1]))
        expect(1, "к25: 119 уникальных депутатов")
        mp.write_text("")
        expect(2, "пустой файл (нет JSON)")
        mp.unlink()
        expect(2, "файл отсутствует")
        mp.write_text("<!DOCTYPE html><html>Access denied</html>")
        expect(2, "HTML вместо JSON")
        mp.write_text("{")
        expect(2, "некорректный JSON")
        mp.write_text("{}")
        expect(2, "ожидается JSON-массив")
        mp.write_text('[{"PersonID": null}]')
        expect(2, "нужны положительные целые")
        mp.write_text(json.dumps(members + [members[0]]))
        expect(0, "нижняя граница соблюдена")
        mp.write_text(json.dumps(members + [{"PersonID": 121, "FactionID": 25,
                                            "KnessetNum": 25}]))
        expect(0, "нижняя граница соблюдена")
        mp.write_text("[]")
        expect(1, "к25: 0 уникальных депутатов")
        mp.write_text(json.dumps(members))
        # Историческая партия с KnessetNum 0 — принять; Id 0 — отвергнуть.
        fp.write_text(json.dumps(factions + [{"Id": 83, "KnessetNum": 0}]))
        expect(0, "нижняя граница соблюдена")
        fp.write_text(json.dumps(factions + [{"Id": 0, "KnessetNum": 25}]))
        expect(2, "нужны положительные целые")
        fp.write_text(json.dumps(factions[:-1]))
        expect(2, "FactionID отсутствует")
        mp.write_text(json.dumps([m for m in members if m["KnessetNum"] != 25]))
        expect(1, "к25: 0 уникальных депутатов")
    print("selftest: OK — недобор и непригодный вход различены")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    try:
        sys.exit(selftest() if args.selftest else main(args.data_dir))
    except Exception as exc:
        print(f"ВНУТРЕННЯЯ ОШИБКА ОРАКУЛА 120: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(3)
