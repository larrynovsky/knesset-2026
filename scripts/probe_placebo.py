#!/usr/bin/env python3
"""Ф23 — негативный контроль: находит ли методика связь там, где её быть не может.

Инструмент, который везде находит зазор, — не инструмент. Обе проверки ниже
устроены как негативное тестирование: нарушается условие, необходимое для
того, чтобы связь вообще могла существовать. Признак выбора контроля НЕ
смотрит на исход — иначе проверка тавтологична.

ПЛАЦЕБО-ПЕРИОД. Утверждения карточки ШАС прогоняются по бюджету 2022 года —
до подписания соглашения. Связь невозможна хронологически.
Объявленное ожидание (criteria/declared_before_2026-07-31.yaml, коммит
6a38d58, ДО прогона): утверждения «слова X нет среди названий статей»
ожидаются ИСТИННЫМИ и в 2022. Если подтвердится — отсутствие микв и синагог
в номенклатуре есть КОНСТАНТА классификации, а не след невыполнения, и
формулировку вывода придётся ослабить правкой по §15.

ПЛАЦЕБО-ВЕТКА. Поиск кандидатов по терминам обязательств ШАС прогоняется на
ветке, выбранной случайно с зафиксированным зерном, вне 00220102. Связь
невозможна предметно.
Объявленное ожидание: доля обязательств с правдоподобным кандидатом — не
выше четверти. Половина и более = поиск не различает предмет, и это отказ
методики поиска, а не повод подкрутить порог.

§23: выгрузка 2022 идёт через guarded_fetch с объявленным ожиданием.

    python3 scripts/probe_placebo.py
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
CARD = ROOT / "cards" / "shas-1095-gov37.yaml"
TAKANOT = ROOT / "data" / "budget_takanot.json"
SEED = 20260731
PLACEBO_YEAR = 2022
BRANCH_REAL = "00220102"


def load_2022() -> list[dict]:
    """Названия статей уровня תקנה за 2022. Года нет в основной выгрузке."""
    cache = ROOT / "data" / "budget_takanot_2022.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["rows"]
    rows = gf.fetch_sql(
        "raw_budget",
        "code, parent, title, year, net_allocated, net_executed",
        "year, code", where=f"year = {PLACEBO_YEAR}")
    cache.write_text(json.dumps({"year": PLACEBO_YEAR, "rows": rows},
                                ensure_ascii=False), encoding="utf-8")
    return rows


def main() -> int:
    card = vc.load_yaml_ish(CARD)
    commitments = card["commitments"]
    rows_now = json.loads(TAKANOT.read_text(encoding="utf-8"))["rows"]

    print("=" * 72)
    print("Ф23.1 ПЛАЦЕБО-ПЕРИОД: те же утверждения по бюджету 2022")
    print("=" * 72)
    rows22 = load_2022()
    t22 = [r["title"] or "" for r in rows22 if len(r["code"]) == 10]
    t_now = [r["title"] or "" for r in rows_now if len(r["code"]) == 10]
    print(f"строк уровня תקנה: {PLACEBO_YEAR} — {len(t22)}, 2023–2025 — {len(t_now)}")

    verdicts = []
    for c in commitments:
        concl = c.get("conclusion") or ""
        for term in vc.REF_ABSENT.findall(concl):
            n22 = sum(1 for t in t22 if term in t)
            nnow = sum(1 for t in t_now if term in t)
            same = (n22 == 0) == (nnow == 0)
            verdicts.append(same)
            print(f"  «{term}»: в {PLACEBO_YEAR} — {n22}, в 2023–2025 — {nnow}"
                  f"  -> {'ТО ЖЕ САМОЕ' if same else 'РАЗЛИЧАЕТСЯ'}")
        for code in vc.REF_NOCODE.findall(concl):
            n22 = sum(1 for r in rows22 if r["code"] == code)
            nnow = sum(1 for r in rows_now if r["code"] == code)
            same = (n22 == 0) == (nnow == 0)
            verdicts.append(same)
            print(f"  код {code}: в {PLACEBO_YEAR} — {n22}, в 2023–2025 — {nnow}"
                  f"  -> {'ТО ЖЕ САМОЕ' if same else 'РАЗЛИЧАЕТСЯ'}")

    all_same = verdicts and all(verdicts)
    print(f"\nИТОГ 23.1: {'ожидание ПОДТВЕРДИЛОСЬ' if all_same else 'ожидание НЕ подтвердилось'}")
    if all_same:
        print("  Утверждения об отсутствии истинны и ДО соглашения. Значит они")
        print("  говорят о бюджетной номенклатуре, а не о поведении партии.")
        print("  Формулировку вывода карточки надо ослаблять (§15).")
    else:
        print("  Хотя бы одно утверждение различает период до и после —")
        print("  оно несёт информацию о поведении, а не только о номенклатуре.")

    print("\n" + "=" * 72)
    print("Ф23.2 ПЛАЦЕБО-ВЕТКА: поиск по терминам на случайной чужой ветке")
    print("=" * 72)
    # ПОПРАВКА К КОНТРОЛЮ, а не к порогу. Первая редакция брала ОДНУ случайную
    # ветку из всех и вытянула 00002501 с шестью строками против сорока
    # четырёх у настоящей. Ветка, где нечего искать, не находит ничего по
    # объёму, а не по различению предмета: контроль был бессилен и прошёл бы
    # при любой методике. Исправление: сопоставимый размер (±50% строк) и
    # десять веток вместо одной, зерно то же. Порог 50% не тронут.
    real = [r for r in rows_now if r["code"].startswith(BRANCH_REAL) and len(r["code"]) == 10]
    size_real = len(real)
    by_branch: dict[str, list] = {}
    for r in rows_now:
        if len(r["code"]) == 10 and not r["code"].startswith(BRANCH_REAL):
            by_branch.setdefault(r["code"][:8], []).append(r)
    pool = sorted(b for b, rs in by_branch.items()
                  if 0.5 * size_real <= len(rs) <= 1.5 * size_real)
    picked = random.Random(SEED).sample(pool, min(10, len(pool)))
    print(f"настоящая {BRANCH_REAL}: {size_real} строк")
    print(f"сопоставимых по размеру веток: {len(pool)}; взято {len(picked)} "
          f"(зерно {SEED})")

    years = [2023, 2024, 2025]
    terms_by_c, dfs_by_c = {}, {}
    for c in commitments:
        t = mc.terms_of(c.get("quote_he") or "")
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
    elif share <= 0.25:
        print("  Ожидание подтвердилось: поиск различает предмет ветки.")
    else:
        print("  Между порогами: не различили. Записывается как исход.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except gf.ShortRead as exc:
        print(f"\n§23 ОТКАЗ: {exc}", file=sys.stderr)
        sys.exit(1)
