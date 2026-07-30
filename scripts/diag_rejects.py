#!/usr/bin/env python3
"""Почему разбор отверг ответ. Диагностика по КЭШУ, без единого вызова API.

Прогон v11c дал 41 unparsed из 114 вызовов, и все причины слились в одно слово.
parse() возвращает None по девяти разным поводам — от «не JSON» до «нет
basis_note», — и приписать все отказы одному правилу значит поставить диагноз
по симптому. Кэш ответов, заведённый в том же прогоне, хранит сырые тексты:
разбор повторяется локально столько раз, сколько нужно, и бесплатно.

Скрипт НИЧЕГО не чинит. Он только называет причину каждого отказа.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "llm_cache"
SIGNS = {-1, 0, 1}


def why(txt: str) -> str:
    """Та же логика, что в classify_direction.parse, но с названием причины.

    Дублирование условий здесь осознанное и временное: единственная задача —
    поставить диагноз одному прогону. Если правило приживётся, причина должна
    вернуться В parse (возвращать не None, а (None, reason)), и этот файл
    удаляется. Пока он одноразовый и помечен таким.
    """
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return "не-JSON (обрыв или проза вместо объекта)"
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return "битый JSON"

    ov = d.get("overall")
    if not isinstance(ov, dict):
        return "нет объекта overall"
    s = ov.get("sign")
    if s is not None and s not in SIGNS:
        return "знак вне шкалы"
    if s is not None:
        for f in ("quote_he", "quote_ru", "confidence", "argument_against"):
            if not str(ov.get(f) or "").strip():
                return f"overall без поля {f}"

    norms = d.get("norms")
    if not isinstance(norms, list):
        return "нет списка norms"
    for n in norms:
        if not isinstance(n, dict):
            return "норма не объект"
        ns = n.get("sign")
        if ns is not None and ns not in SIGNS:
            return "знак нормы вне шкалы"
        if ns is None:
            bd = n.get("bidirectional")
            if not isinstance(bd, dict) or not all(
                    str(bd.get(k) or "").strip() for k in ("toward_minus", "toward_plus")):
                return "K7: прочерк без обоих направлений"
        if not str(n.get("checklist_item") or "").strip():
            return "норма без пункта чек-листа"
        if not str(n.get("quote_he") or "").strip():
            return "норма без цитаты"
    if sum(1 for n in norms if n.get("strongest")) > 1:
        return "K2b: больше одной сильнейшей"
    if (ov.get("sign") not in (None, 0) and len(norms) > 1
            and not str(ov.get("basis_note") or "").strip()):
        return "K2d: нет basis_note при знаке≠0 и норм>1"
    return "ПРИНЯТ"


def main() -> int:
    files = sorted(CACHE.glob("*.json"))
    if not files:
        print("кэш пуст — нечего диагностировать")
        return 1
    by_reason = collections.Counter()
    by_vendor = collections.defaultdict(collections.Counter)
    samples: dict[str, list] = collections.defaultdict(list)
    basis_ctx = []

    for f in files:
        vendor = f.name.split("_", 1)[0]
        d = json.loads(f.read_text(encoding="utf-8"))
        r = why(d.get("txt", ""))
        by_reason[r] += 1
        by_vendor[vendor][r] += 1
        if r != "ПРИНЯТ" and len(samples[r]) < 3:
            samples[r].append(f.name)
        # для K2d: сколько норм и какой знак у отклонённых по этой причине
        if r.startswith("K2d"):
            m = re.search(r"\{.*\}", d.get("txt", ""), re.S)
            obj = json.loads(m.group(0))
            basis_ctx.append((obj["overall"].get("sign"), len(obj.get("norms", []))))

    total = sum(by_reason.values())
    print(f"ответов в кэше: {total}\n")
    print("ПРИЧИНЫ:")
    for r, n in by_reason.most_common():
        print(f"   {n:>4}  {r}")
    print("\nПО ВЕНДОРАМ:")
    for v, c in by_vendor.items():
        ok = c.get("ПРИНЯТ", 0)
        print(f"   {v:10} принято {ok}/{sum(c.values())}")
        for r, n in c.most_common():
            if r != "ПРИНЯТ":
                print(f"      {n:>3}  {r}")

    if basis_ctx:
        norms = [n for _, n in basis_ctx]
        print(f"\nОТКЛОНЁННЫЕ ПО K2d: {len(basis_ctx)}")
        print(f"   норм в ответе: мин {min(norms)} · медиана "
              f"{sorted(norms)[len(norms)//2]} · макс {max(norms)}")
        print(f"   знаки: {collections.Counter(s for s, _ in basis_ctx).most_common()}")
        print("   Вопрос, который этим НЕ решается: был ли знак действительно дан")
        print("   по одной норме. Кодбук требует пометку именно в этом случае,")
        print("   а код — при любых норм>1. Это разные условия.")

    print("\nпримеры файлов по причинам:")
    for r, fs in samples.items():
        print(f"   {r}: {', '.join(fs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
