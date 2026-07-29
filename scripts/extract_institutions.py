#!/usr/bin/env python3
"""K4: перечень институтов извлекается ИЗ КОРПУСА, а не из головы автора.

Зачем модуль существует. K4 расширил ось на «любой институт, чьи назначения
или полномочия меняются политическим решением», и назвал классы — президент,
раввинат, муниципалитеты, Банк Израиля, силовые назначения, регуляторы, — но
не перечень органов и не ивритские термины. Написать этот перечень по памяти
означало бы предъявить читателю МОЁ слово о том, что важно; §0 требует
выводить из источников. Решение владельца (Р7, 2026-07-29): извлекать
из корпуса, внешний реестр госорганов искать отдельно и держать ОРАКУЛОМ
ПОЛНОТЫ — он краснеет на органе, которого в моём перечне нет.

Вход — ПОЛНЫЙ список названий (7491), не отфильтрованные 934. Извлечение
из отфильтрованного дало бы замкнутый круг: старый лексикон находит ровно
то, что старый лексикон уже нашёл, и это выглядело бы как замер.

Локальная модель, а не фронтир: CLAUDE.md разрешает Ollama для массовых
операций над ивритским текстом, где не нужен фронтир-класс. Извлечение
упоминаний — именно такая операция. Решение о том, какой институт войдёт
в ось, моделью НЕ принимается: она возвращает кандидатов, отбор — суждение,
и оно фиксируется отдельно.

ОРАКУЛ ВЫДУМКИ. Всякая извлечённая строка обязана дословно встречаться хотя бы
в одном названии своего батча. Не встречается — это не институт, а пересказ,
и он считается отдельно. Проверка стоит одну строку и ловит ровно тот класс
отказа, который в пилоте классификации остался незамеченным: 13 из 57 цитат
не находились в исходном тексте.
"""
from __future__ import annotations

import json
import random
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ROOT / "data" / "bills_all_names.json"
OUT = ROOT / "data" / "institutions_raw.json"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:14b"
BATCH = 60
SEED = 20260729          # посев назван, чтобы выборка воспроизводилась (§14)

PROMPT = """לפניך שמות של הצעות חוק בכנסת. הוצא מהם את כל שמות המוסדות,
הרשויות, הגופים הציבוריים ובעלי התפקידים הממלכתיים המוזכרים.

כללים:
- העתק כל שם בדיוק כפי שהוא מופיע בטקסט, ללא שינוי.
- אל תמציא שמות שלא מופיעים.
- אל תכלול שמות של חוקים, נושאים או פעולות — רק מוסדות ובעלי תפקיד.
- החזר JSON בלבד: {{"institutions": ["...", "..."]}}

השמות:
{names}"""


def ask(names: list[str]) -> list[str]:
    body = json.dumps({
        "model": MODEL, "prompt": PROMPT.format(names="\n".join(names)),
        "stream": False, "format": "json",
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = json.loads(r.read())["response"]
    try:
        got = json.loads(raw).get("institutions", [])
    except json.JSONDecodeError:
        return []
    return [s.strip() for s in got if isinstance(s, str) and s.strip()]


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    rows = json.loads(NAMES.read_text(encoding="utf-8"))
    names = [r["name"] for r in rows if r.get("name")]

    if limit:
        random.Random(SEED).shuffle(names)
        names = names[:limit]
    print(f"названий на вход: {len(names)} (посев {SEED})" if limit
          else f"названий на вход: {len(names)} — весь корпус")

    found, invented, done = Counter(), Counter(), 0
    batches = [names[i:i + BATCH] for i in range(0, len(names), BATCH)]
    for i, batch in enumerate(batches, 1):
        joined = "\n".join(batch)
        for s in ask(batch):
            # ОРАКУЛ ВЫДУМКИ: извлечённое обязано дословно быть во входе батча.
            (found if s in joined else invented)[s] += 1
        done += len(batch)
        if i % 5 == 0 or i == len(batches):
            print(f"  [{i}/{len(batches)}] обработано {done} · "
                  f"кандидатов {len(found)} · выдумано {sum(invented.values())}")

    # §23: вход и обработанное обязаны совпасть. Молчаливая потеря батча
    # выглядела бы как «институтов меньше, чем есть».
    if done != len(names):
        print(f"§23 ОТКАЗ: на входе {len(names)}, обработано {done}", file=sys.stderr)
        return 1

    OUT.write_text(json.dumps({
        "model": MODEL, "seed": SEED, "names_in": len(names), "batch": BATCH,
        "found": found.most_common(), "invented": invented.most_common(50),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nкандидатов-институтов: {len(found)}")
    print(f"выдумано моделью (нет во входе): {len(invented)} уникальных, "
          f"{sum(invented.values())} упоминаний")
    print("\nтоп-30 по частоте:")
    for s, n in found.most_common(30):
        print(f"  {n:>4}  {s}")
    print(f"\n{OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
