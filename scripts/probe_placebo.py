#!/usr/bin/env python3
"""Ф23 — негативный контроль: находит ли методика связь там, где её быть не может.

Инструмент, который везде находит зазор, — не инструмент. Обе проверки ниже
устроены как негативное тестирование: нарушается условие, необходимое для
того, чтобы связь вообще могла существовать. Признак выбора контроля НЕ
смотрит на исход — иначе проверка тавтологична.

ПЛАЦЕБО-ПЕРИОД: утверждения карточки выбранного соглашения проверяются
на бюджете года перед первым бюджетным годом. Без утверждений — НЕ ПРОВЕРЕНО.
Это контроль номенклатуры, а не доказательство поведения партии.
ПЛАЦЕБО-ВЕТКА: для каждой найденной ветки — до десяти чужих веток
сопоставимого размера (±50%), с прежним зерном и порогами 25%/50%.
Все найденные ветки исключаются из контроля. Пустой контроль — отказ.
Поиск проверяется на совпадение терминов, не на осмысленность кандидата.
Ожидания ШАС: criteria/declared_before_2026-07-31.yaml. Перенос контроля
на другую партию не доказывает предметную чуждость случайной ветки.

§23: выгрузка контрольного года — guarded_fetch с объявленным ожиданием.
    python3 scripts/probe_placebo.py --agreement CA37-Shas.txt
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guarded_fetch as gf  # noqa: E402
import map_commitments as mc  # noqa: E402
import validate_cards as vc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TAKANOT = ROOT / "data" / "budget_takanot.json"
SEED = 20260731


def load_placebo_year(data_dir: Path, placebo_year: int) -> list[dict]:
    """Контрольный бюджет: существующий кеш либо полная выгрузка (§23)."""
    cache = data_dir / f"budget_takanot_{placebo_year}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["rows"]
    rows = gf.fetch_sql(
        "raw_budget",
        "code, parent, title, year, net_allocated, net_executed",
        "year, code", where=f"year = {placebo_year}")
    cache.write_text(json.dumps({"year": placebo_year, "rows": rows},
                                ensure_ascii=False), encoding="utf-8")
    return rows


def probe(a: dict, mapping: dict, rows_now: list[dict], data_dir: Path) -> int:
    years = a["budget_years"]
    rows_now = [r for r in rows_now if r["year"] in years and len(r["code"]) == 10]
    commitments = [dict(c, id=str(c["line"])) for c in mapping["items"]
                   if c["category"] == "commitment"]
    mc.require_quotes(commitments)
    branches = sorted({c["code"][:8] for it in commitments for c in it["candidates"]})
    if not commitments or not branches:
        raise SystemExit("ОТКАЗ: нет обязательств или найденных веток для плацебо")
    card_path = ROOT / "cards" / f"{mc.slug(a)}-{a['period_id']}.yaml"
    card = vc.load_yaml_ish(card_path) if card_path.exists() else None
    if card and card["period_id"] != a["period_id"]:
        raise SystemExit("ОТКАЗ: период карточки расходится с соглашением")
    claims = card["commitments"] if card else []
    placebo_year = min(years) - 1
    label = ", ".join(map(str, years))

    print("=" * 72)
    print(f"Ф23.1 ПЛАЦЕБО-ПЕРИОД: год перед первым бюджетным годом — {placebo_year}")
    print("=" * 72)
    rows22 = load_placebo_year(data_dir, placebo_year) if claims else []
    t22 = [r["title"] or "" for r in rows22 if len(r["code"]) == 10]
    t_now = [r["title"] or "" for r in rows_now if len(r["code"]) == 10]
    print(f"строк уровня תקנה: {placebo_year} — {len(t22)}, {label} — {len(t_now)}")

    verdicts = []
    for c in claims:
        concl = c.get("conclusion") or ""
        for term in vc.REF_ABSENT.findall(concl):
            n22 = sum(1 for t in t22 if term in t)
            nnow = sum(1 for t in t_now if term in t)
            same = (n22 == 0) == (nnow == 0)
            verdicts.append(same)
            print(f"  «{term}»: в {placebo_year} — {n22}, в {label} — {nnow}"
                  f"  -> {'ТО ЖЕ САМОЕ' if same else 'РАЗЛИЧАЕТСЯ'}")
        for code in vc.REF_NOCODE.findall(concl):
            n22 = sum(1 for r in rows22 if r["code"] == code)
            nnow = sum(1 for r in rows_now if r["code"] == code)
            same = (n22 == 0) == (nnow == 0)
            verdicts.append(same)
            print(f"  код {code}: в {placebo_year} — {n22}, в {label} — {nnow}"
                  f"  -> {'ТО ЖЕ САМОЕ' if same else 'РАЗЛИЧАЕТСЯ'}")

    if not verdicts:
        print("НЕ ПРОВЕРЕНО: нет утверждений карточки об отсутствии слов/кодов")
    all_same = verdicts and all(verdicts)
    print(f"\nИТОГ 23.1: {'НЕ ПРОВЕРЕНО' if not verdicts else ('ожидание ПОДТВЕРДИЛОСЬ' if all_same else 'ожидание НЕ подтвердилось')}")
    if all_same:
        print("  Утверждения об отсутствии истинны и в контрольном году. Значит они")
        print("  говорят о бюджетной номенклатуре, а не о поведении партии.")
        print("  Формулировку вывода карточки надо ослаблять (§15).")
    elif verdicts:
        print("  Номенклатура различается между годами; причина этим не установлена.")

    print("\n" + "=" * 72)
    print("Ф23.2 ПЛАЦЕБО-ВЕТКА: поиск по терминам на случайной чужой ветке")
    print("=" * 72)
    # ПОПРАВКА К КОНТРОЛЮ, а не к порогу. Первая редакция брала ОДНУ случайную
    # ветку из всех и вытянула 00002501 с шестью строками против сорока
    # четырёх у настоящей. Ветка, где нечего искать, не находит ничего по
    # объёму, а не по различению предмета: контроль был бессилен и прошёл бы
    # при любой методике. Исправление: сопоставимый размер (±50% строк) и
    # десять веток вместо одной, зерно то же. Порог 50% не тронут.
    failed = False
    for branch_real in branches:
        real = [r for r in rows_now if r["code"].startswith(branch_real) and len(r["code"]) == 10]
        size_real = len(real)
        if not size_real:
            raise SystemExit(f"ОТКАЗ: найденная ветка {branch_real} отсутствует в бюджете")
        by_branch: dict[str, list] = {}
        for r in rows_now:
            if len(r["code"]) == 10 and r["code"][:8] not in branches:
                by_branch.setdefault(r["code"][:8], []).append(r)
        pool = sorted(b for b, rs in by_branch.items()
                      if 0.5 * size_real <= len(rs) <= 1.5 * size_real)
        picked = random.Random(SEED).sample(pool, min(10, len(pool)))
        if not picked:
            raise SystemExit(f"ОТКАЗ: нет сопоставимых контрольных веток для {branch_real}")
        print(f"настоящая {branch_real}: {size_real} строк")
        print(f"сопоставимых по размеру веток: {len(pool)}; взято {len(picked)} "
              f"(зерно {SEED})")

        terms_by_c, dfs_by_c = {}, {}
        for c in commitments:
            t = c.get("terms") or mc.terms_of(c["quote_he"])
            terms_by_c[c["id"]] = t
            dfs_by_c[c["id"]] = {x: mc.doc_freq(rows_now, x) for x in t}

        shares = []
        for branch in picked:
            sub = by_branch[branch]
            hit = sum(1 for c in commitments
                      if mc.search(sub, terms_by_c[c["id"]], years, dfs_by_c[c["id"]]))
            shares.append(hit / len(commitments))
            print(f"  ветка {branch} ({len(sub):3d} строк): кандидаты для "
                  f"{hit} из {len(commitments)}")

        hits_real = sum(1 for c in commitments
                        if mc.search(real, terms_by_c[c["id"]], years, dfs_by_c[c["id"]]))
        n = len(commitments)
        share = sorted(shares)[len(shares) // 2] if shares else 0
        print(f"\nИТОГ 23.2: медианная доля по чужим веткам — {share:.0%}; "
              f"худшая {max(shares):.0%}; на своей ветке — {hits_real} из {n} "
              f"({hits_real/n:.0%})")
        if share >= 0.5:
            print("  ОТКАЗ МЕТОДИКИ ПОИСКА: он не различает предмет. Порог 50%")
            print("  объявлен ДО прогона. Подкручивать пороги запрещено — это уже")
            print("  делалось четырежды 30 июля и не дало ничего.")
            failed = True
        elif share <= 0.25:
            print("  Ожидание подтвердилось: поиск различает предмет ветки.")
        else:
            print("  Между порогами: не различили. Записывается как исход.")
    return int(failed)


def main() -> int:
    args = mc.cli_args()
    if args.selftest:
        return mc.selftest()
    text, sha = mc.rule_text_and_sha()
    selected = mc.select_agreements(text, args)
    rows = json.loads((args.data_dir / TAKANOT.name).read_text(encoding="utf-8"))["rows"]
    failed = False
    for a in selected:
        mapping = json.loads((args.data_dir / f"commitment_map_{mc.slug(a)}.json").read_text(encoding="utf-8"))
        mc.validate_mapping(mapping, a, sha)
        print(f"Соглашение {a['file']}, период {a['period_id']}")
        failed |= bool(probe(a, mapping, rows, args.data_dir))
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except gf.ShortRead as exc:
        print(f"\n§23 ОТКАЗ: {exc}", file=sys.stderr)
        sys.exit(1)
