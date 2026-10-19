#!/usr/bin/env python3
"""§14, §20: воспроизводимая чувствительность стрелок к ошибкам знаков."""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from direction_confidence import arrow_rule, compose, sign_table
from theme_arrows import THEMES, arrow_of, load_signs
from build_line_cards import RU, _arrow_split, axis_directions

ROOT = Path(__file__).resolve().parent.parent
RUNS, SEED = 2000, 35
PS = (0.10, 0.17, 0.33)
TITLES = {"rule_of_law": "Суд, парламент, свободы", **THEMES}
LEGEND = "Устойчивость: ? — шаткая, ?? — ненадёжна (стрелка может смениться, если каждый десятый знак закона ошибочен)"


def inputs_sha(root: Path = ROOT) -> str:
    """Hash names and bytes, including membership of optional input families."""
    from render_method import ARROW, VOTES
    paths = {root / p.relative_to(ROOT) for p in (ARROW, VOTES)}
    paths.update(root / "scripts" / name for name in (
        "arrow_robustness.py", "direction_confidence.py", "theme_arrows.py",
        "build_line_cards.py", "validate_cards.py", "render_method.py"))
    for pattern in ("criteria/theme_signs_*.json", "criteria/claude_tiebreak_signs_*.json",
                    "criteria/axis_second_reading_*.json", "criteria/declared_before_arrow_*.yaml",
                    "docs/reference/for_option_sign_*.json"):
        paths.update(root.glob(pattern))
    digest = hashlib.sha256(json.dumps([RUNS, SEED, PS]).encode())
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run() -> None:
    sha = inputs_sha()
    output = ROOT / "data" / "arrow_robustness.json"
    try:
        cached = json.loads(output.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cached = None
    if isinstance(cached, dict) and cached.get("inputs_sha") == sha:
        print(f"устойчивость: кэш верен (sha {sha})")
        return
    data = build()
    # Не выдаём расчёт за актуальный, если входы менялись во время симуляции.
    if inputs_sha() != sha:
        raise RuntimeError("входы устойчивости изменились во время расчёта")
    data["inputs_sha"] = sha
    (ROOT / "reviews" / "arrow_robustness_v35.md").write_text(review(data), encoding="utf-8")
    # Уникальный временный файл: параллельный читатель не увидит обрезанный JSON.
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                            prefix=".arrow_robustness-", delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
    Path(tmp.name).replace(output)


def label(rate: float) -> str:
    return "устойчива" if rate >= .95 else "шаткая" if rate >= .80 else "ненадёжна"


def flip(signs: dict, selected: list) -> dict:
    changed = dict(signs)
    for bid in selected:
        changed[bid] = -changed[bid]
    return changed


def simulate(rows: list, signs: dict, table: dict, rule: dict,
             min_acts: int = 3, runs: int = RUNS) -> dict:
    # Отбор по закону; нулевые знаки и законы вне снимка не переворачиваем.
    factions = sorted({fac for r in rows for fac in (r.get("by_faction") or {})})
    rows = [r for r in rows if r.get("bill_id") in signs]
    population = sorted({r["bill_id"] for r in rows if signs[r["bill_id"]] in (-1, 1)})
    baseline, _, _ = compose(rows, signs, table, rule)
    result = {}
    for fac in factions:
        entry = baseline.get(fac, {})
        up, down = entry.get("up", 0), entry.get("down", 0)
        result[fac] = {"arrow": arrow_of(up, down, min_acts), "up": up, "down": down,
                       "retained": {}, "rates": {}}
    flips = {}
    for p in PS:
        rng = random.Random(SEED)
        count = int(len(population) * p + .5)
        flips[f"{p:.2f}"] = count
        hits = dict.fromkeys(factions, 0)
        for _ in range(runs):
            changed = flip(signs, rng.sample(population, count))
            per, _, _ = compose(rows, changed, table, rule)
            for fac in factions:
                entry = per.get(fac, {})
                current = arrow_of(entry.get("up", 0), entry.get("down", 0), min_acts)
                hits[fac] += current == result[fac]["arrow"]
        for fac in factions:
            # Отсутствующая стрелка не получает ложную уверенность 100%.
            available = result[fac]["arrow"] is not None
            result[fac]["retained"][f"{p:.2f}"] = hits[fac] if available else None
            result[fac]["rates"][f"{p:.2f}"] = hits[fac] / runs if available else None
    for entry in result.values():
        rate = entry["rates"]["0.10"]
        entry["label"] = label(rate) if rate is not None else None
    return {"signed_laws": len(population), "flips": flips,
            "factions": {fac.split("|", 1)[0]: dict(v, faction=fac) for fac, v in result.items()}}


def build() -> dict:
    from render_method import ARROW, VOTES
    votes = json.loads(VOTES.read_text(encoding="utf-8"))
    axis, _ = axis_directions(ARROW)
    rule = dict(arrow_rule(), split_below=float(_arrow_split()))
    table = sign_table()
    topics = {}
    for topic in TITLES:
        topics[topic] = simulate(votes["rows"], axis if topic == "rule_of_law" else load_signs(topic),
                                 table, rule, min_acts=1 if topic == "rule_of_law" else 3)
        print(f"{topic}: {len(topics[topic]['factions'])} фракций", flush=True)
    return {"runs": RUNS, "seed": SEED, "probabilities": list(PS),
            "sampling": "uniform without replacement; round-half-up(p * signed laws in votes); shared across factions/readings",
            "topics": topics}


def review(data: dict) -> str:
    lines = ["# v35 — устойчивость стрелок", "",
             "2000 прогонов на тему и p; seed=35. В каждом прогоне равновероятно выбираются",
             "round-half-up(p × N) разных законов со знаком ±1 и голосованиями в снимке.",
             "Знак меняется у закона целиком, для всех чтений и фракций. Нули не меняются.",
             "Пересчёт — compose() и arrow_of(), порог 2/3; минимумы публикации: ось 1, темы 3 закона.",
             "Доля — сохранение исходной стрелки (включая ↕), а не вероятность правильности знака.",
             "Отсутствующая стрелка: н/д. Пороги: ≥95% устойчива; ≥80% шаткая; иначе ненадёжна.", "",
             "Расхождение моделей не равно установленной частоте ошибок. Сценарии p не учитывают",
             "систематические и связанные ошибки; устойчивость не подтверждает истинность вывода.", "",
             "Синтетика: 100:0 (100 законов) — устойчива; 50:50 как доли (2:2 закона) — ненадёжна.",
             "При 50:50 законах (N=100) ↕ устойчива: равные доли сами по себе не означают ненадёжность.",
             "Дополнительный контроль у границы направления: 67:33 (N=100) — ненадёжна.", "",
             "| Фракция | Тема | p | Сохранение | При p=0.10 |",
             "|---|---|---:|---:|---|"]
    for topic, values in data["topics"].items():
        for fid, entry in sorted(values["factions"].items(), key=lambda x: int(x[0])):
            for p, rate in entry["rates"].items():
                value = "н/д" if rate is None else f"{100 * rate:.2f}%"
                lines.append(f"| {RU.get(int(fid), entry['faction'])} ({fid}) | {TITLES[topic]} | {p} | {value} | {entry['label'] if p == '0.10' and entry['label'] else '—'} |")
    return "\n".join(lines) + "\n"


def selftest() -> None:
    from unittest.mock import patch
    from tempfile import TemporaryDirectory
    # Список независим от discovery внутри inputs_sha: исключённый файл краснеет.
    fixtures = ["data/votes_25.json", "data/direction_arrow_2026-10-07.json",
                "criteria/theme_signs_economy.json", "criteria/theme_signs_religion_state.json",
                "criteria/theme_signs_security.json", "criteria/claude_tiebreak_signs_test.json",
                "criteria/axis_second_reading_test.json", "criteria/declared_before_arrow_test.yaml",
                "docs/reference/for_option_sign_test.json"]
    fixtures += ["scripts/" + name for name in (
        "arrow_robustness.py", "direction_confidence.py", "theme_arrows.py",
        "build_line_cards.py", "validate_cards.py", "render_method.py")]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name in fixtures:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("1")
        baseline = inputs_sha(root)
        for name in fixtures:
            path = root / name
            path.write_text("0")
            assert inputs_sha(root) != baseline, f"вход исключён из хеша: {name}"
            path.write_text("1")
        for name, value in (("RUNS", RUNS + 1), ("SEED", SEED + 1), ("PS", (.11, .17, .33))):
            with patch(__name__ + "." + name, value):
                assert inputs_sha(root) != baseline, name
        optional = root / "criteria/axis_second_reading_extra.json"
        optional.write_text("1")
        assert inputs_sha(root) != baseline
        optional.unlink()
        assert inputs_sha(root) == baseline
        # Имитация мутанта: байты одного входа перестали влиять на хеш.
        original_read = Path.read_bytes
        omitted = root / fixtures[0]
        with patch.object(Path, "read_bytes", lambda p: b"1" if p == omitted else original_read(p)):
            omitted.write_text("0")
            try:
                assert inputs_sha(root) != baseline, "вход исключён из хеша"
            except AssertionError:
                pass
            else:
                raise AssertionError("мутант хеша выжил")
        assert inputs_sha(root) != baseline
    with patch(__name__ + ".inputs_sha", return_value="test-sha"), \
         patch.object(Path, "read_text", return_value='{"inputs_sha": "test-sha"}'), \
         patch(__name__ + ".build", side_effect=AssertionError("симуляция при верном кэше")):
        run()
    rows = [{"bill_id": i, "vote_id": i, "for_option_desc": "test",
             "by_faction": {"1|A": {"for": 10}, "2|B": {"against": 10}}} for i in range(100)]
    table, rule = {"test": {"sign": "carries"}}, {"split_below": .5, "drop_below": .1}
    def check():
        strong = simulate(rows, dict.fromkeys(range(100), 1), table, rule)["factions"]["1"]
        balanced = simulate(rows, {i: 1 if i < 50 else -1 for i in range(100)}, table, rule)["factions"]["1"]
        small = simulate(rows[:4], {0: 1, 1: 1, 2: -1, 3: -1}, table, rule)["factions"]["1"]
        edge = simulate(rows, {i: 1 if i < 68 else -1 for i in range(100)}, table, rule)["factions"]["1"]
        assert strong["label"] == balanced["label"] == "устойчива"
        assert balanced["arrow"] == "both"
        assert edge["label"] == "ненадёжна" and small["rates"]["0.33"] < .8, "отключение переворотов не обнаружено"
        assert label(.95) == "устойчива" and label(.80) == "шаткая" and label(.7999) == "ненадёжна"
    check()
    with patch(__name__ + ".flip", side_effect=lambda signs, selected: signs):
        try:
            check()
        except AssertionError as exc:
            assert "отключение переворотов" in str(exc)
        else:
            raise AssertionError("мутант выжил")
    assert flip({1: 1, 2: -1, 3: 0}, [1, 2]) == {1: -1, 2: 1, 3: 0}
    print("самопроверка arrow_robustness пройдена; мутант без переворотов красный")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run()
