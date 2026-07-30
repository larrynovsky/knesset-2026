#!/usr/bin/env python3
"""Настоящее согласие вендоров: пересчёт по кэшу без K2d-отказа. Ноль вызовов API.

Зачем. Прогон v11c дал согласие 71,4% по общему знаку — но на 28 актах из 57,
потому что 48 ответов из 112 отвергнуты правилом K2d. Отвергнуты не случайно:
у ВСЕХ отклонённых знак ≠ 0 (28 минусов, 20 плюсов, ни одного нуля). Уцелевшая
выборка смещена к нулям и к простым актам, и сравнивать её с порогом 85% нельзя
ни в ту, ни в другую сторону.

Что делает скрипт. Разбирает те же кэшированные ответы «мягко» — все проверки
формы сохранены, снята ТОЛЬКО K2d, — и считает те же три уровня согласия
на полной базе. Это не отмена правила: правило остаётся в проде. Это ответ
на вопрос, каким было бы согласие, если бы приёмка не выбрасывала половину.

ОДНОРАЗОВЫЙ. Вопрос закрывается одним числом; после ответа файл удаляется.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "llm_cache"
sys.path.insert(0, str(ROOT / "scripts"))
from classify_direction import k3_pairs                     # noqa: E402
SIGNS = {-1, 0, 1}


def parse_soft(txt: str) -> dict | None:
    """Тот же разбор, что в проде, минус K2d. Остальные проверки формы на месте."""
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    ov = d.get("overall")
    if not isinstance(ov, dict) or ov.get("sign") not in SIGNS | {None}:
        return None
    norms = d.get("norms")
    if not isinstance(norms, list):
        return None
    for n in norms:
        if not isinstance(n, dict) or n.get("sign") not in SIGNS | {None}:
            return None
        if not str(n.get("checklist_item") or "").strip():
            return None
    return d


def strongest_item(d: dict):
    for n in d.get("norms", []):
        if n.get("strongest"):
            return n.get("checklist_item")
    return None


def main() -> int:
    by_bill: dict[str, dict] = collections.defaultdict(dict)
    hard_ok: dict[str, set] = collections.defaultdict(set)
    for f in sorted(CACHE.glob("*.json")):
        vendor, bill, _ = f.name.split("_", 2)
        txt = json.loads(f.read_text(encoding="utf-8")).get("txt", "")
        d = parse_soft(txt)
        if d is None:
            continue
        by_bill[bill][vendor] = d
        ov = d["overall"]
        if not (ov.get("sign") not in (None, 0) and len(d.get("norms", [])) > 1
                and not str(ov.get("basis_note") or "").strip()):
            hard_ok[bill].add(vendor)          # прошёл бы и с K2d

    both_soft = [b for b, v in by_bill.items() if len(v) == 2]
    both_hard = [b for b in both_soft if len(hard_ok[b]) == 2]
    print(f"актов в кэше: {len(by_bill)}")
    print(f"оба вендора разобраны БЕЗ K2d: {len(both_soft)}")
    print(f"оба вендора прошли бы С K2d:   {len(both_hard)}  ← база прогона v11c\n")

    def agree(bills):
        a = collections.Counter()
        for b in bills:
            va, vo = by_bill[b]["anthropic"], by_bill[b]["openai"]
            a["sign"] += va["overall"].get("sign") == vo["overall"].get("sign")
            a["count"] += len(va.get("norms", [])) == len(vo.get("norms", []))
            a["strong"] += strongest_item(va) == strongest_item(vo)
        return a

    for label, bills in (("БЕЗ K2d (полная база)", both_soft),
                         ("С K2d (база v11c)", both_hard)):
        if not bills:
            continue
        a = agree(bills)
        n = len(bills)
        print(f"{label}: {n} актов")
        print(f"   общий знак:       {a['sign']:>3}/{n}  = {a['sign']/n:.1%}"
              f"   {'✓ порог 85%' if a['sign']/n >= 0.85 else '✗ ниже порога 85%'}")
        print(f"   число норм:       {a['count']:>3}/{n}  = {a['count']/n:.1%}")
        print(f"   сильнейшая норма: {a['strong']:>3}/{n}  = {a['strong']/n:.1%}\n")

    # --- вопросы 4 и 5: асимметрия отказов и куда делись K3-пары OpenAI -------
    print("АСИММЕТРИЯ ОТКАЗОВ — свойство ответов или невнимательность к полю?")
    for v in ("anthropic", "openai"):
        ds = [d for b in by_bill for vv, d in by_bill[b].items() if vv == v]
        rejected = [d for d in ds if d["overall"].get("sign") not in (None, 0)
                    and len(d.get("norms", [])) > 1
                    and not str(d["overall"].get("basis_note") or "").strip()]
        norms = [len(d.get("norms", [])) for d in ds]
        nonzero = sum(1 for d in ds if d["overall"].get("sign") not in (None, 0))
        print(f"   {v:10} ответов {len(ds):>3} · норм в среднем "
              f"{sum(norms)/max(len(norms),1):.1f} · со знаком ≠0 {nonzero:>3} · "
              f"отвергнуто K2d {len(rejected):>3}")

    print("\nK3-ПАРЫ: считались ли они в отвергнутых (было O=7, стало O=0)")
    for v in ("anthropic", "openai"):
        acc = rej = 0
        for b in by_bill:
            d = by_bill[b].get(v)
            if not d:
                continue
            p = k3_pairs(d.get("norms", []))
            if v in hard_ok[b]:
                acc += p
            else:
                rej += p
        print(f"   {v:10} пар в принятых {acc:>3} · пар в ОТВЕРГНУТЫХ {rej:>3} "
              f"· всего {acc + rej}")

    print("\nМНОЖЕСТВА ПУНКТОВ (оракул K6) на полной базе:")
    for v in ("anthropic", "openai"):
        multi = tot = 0
        for b in by_bill:
            d = by_bill[b].get(v)
            if not d:
                continue
            tot += 1
            if len({n.get("checklist_item") for n in d.get("norms", [])}) > 1:
                multi += 1
        print(f"   {v:10} актов с >1 пунктом {multi:>3}/{tot} = {multi/max(tot,1):.0%}")

    print("\nПРОЧЕРКИ (K7) на полной базе:")
    for v in ("anthropic", "openai"):
        n = sum(1 for b in by_bill if by_bill[b].get(v)
                for x in by_bill[b][v].get("norms", []) if x.get("sign") is None)
        print(f"   {v:10} норм-прочерков {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
