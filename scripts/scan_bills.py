#!/usr/bin/env python3
"""Проход по чек-листу: какие законопроекты 25-го Кнессета относятся к оси.

ПЕРВЫЙ ШАГ ПОСЛЕ ГРАНИЦЫ §3. Критерии утверждены владельцем 2026-07-28
коммитом 783ef50; всё, что здесь собирается, — данные.

Что делает: скачивает все законопроекты 25-го Кнессета и законы, прогоняет
широкий ивритский лексический фильтр, сверяется с оракулом отбора из
criteria/keyvotes.yaml (9 актов, известных ДО обращения к данным).

Чего НЕ делает: не смотрит, кто как голосовал. Классификацию направления
(-1/0/+1) делает следующий шаг — она суждение, не лексика.

Фильтр НАМЕРЕННО широкий: чек-лист требует ПЕРЕПИСИ, а не отбора. Лучше
взять лишнее и отсеять на классификации, чем пропустить и не узнать об этом.
Оракул ловит обратную ошибку — пропуск известного.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guarded_fetch import fetch_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "bills_scan.json"
K25_START, K25_END = "2022-11-15", "2026-07-18"

# Лексика чек-листа. Группы соответствуют пунктам A-F в criteria/keyvotes.yaml.
# Широко и с запасом: рекалл важнее точности, точность даёт следующий шаг.
LEX = {
    "A_суд": ["שופט", "שופטים", "בית המשפט", "בתי המשפט", "בג\"ץ", "בגץ",
              "בית משפט עליון", "הוועדה לבחירת שופטים", "ועדה לבחירת שופטים",
              "ביקורת שיפוטית", "סבירות", "פסקת ההתגברות", "התגברות",
              "נציב תלונות הציבור על שופטים", "לשכת עורכי הדין", "עורכי הדין",
              "הרכב", "הרכבים", "שפיטה", "בוררות", "סמכות שיפוט"],
    "B_парламент": ["ועדת חקירה", "חקירה פרלמנטרית", "תקנון הכנסת", "סיעות האופוזיציה",
                    "האופוזיציה", "חוק-יסוד", "חוק יסוד", "חקיקה", "קריאה טרומית"],
    "C_надзор": ["היועץ המשפטי לממשלה", "היועצים המשפטיים", "יועץ משפטי",
                 "מבקר המדינה", "נציב", "פרקליט המדינה", "הפרקליטות",
                 "נציבות שירות המדינה", "מח\"ש", "מחש", "הפצ\"ר", "הפרקליט הצבאי",
                 "שב\"כ", "השירות הכללי", "המוסד", "מפכ\"ל", "המשטרה", "משטרה",
                 "מינוי", "מינויים", "פיטורי", "כהונה"],
    "D_выборы": ["ועדת הבחירות", "הבחירות לכנסת", "אחוז החסימה", "מימון מפלגות",
                 "פיזור הכנסת", "רשימת מועמדים", "פסילת רשימה"],
    "E_свободы": ["עמותות", "עמותה", "מלכ\"ר", "תרומות ממדינות זרות", "מימון זר",
                  "רשות השידור", "תאגיד השידור", "כאן", "שידור", "שידורים",
                  "עיתונ", "חופש הביטוי", "הפגנה", "הפגנות", "מחאה",
                  "לשון הרע", "צנזורה", "הרשות השנייה"],
    "F_чрезвычайное": ["מצב חירום", "תקנות שעת חירום", "שעת חירום",
                       "סמכויות חירום", "השלטון המקומי", "רשויות מקומיות"],
}

# Оракул отбора: акты, известные из открытых источников ДО обращения к данным.
# Список продублирован из criteria/keyvotes.yaml намеренно — скрипт обязан
# падать сам, не полагаясь на то, что кто-то сверит глазами.
ORACLE = [
    ("2022-12-27", ["הממשלה"], "Основной закон о правительстве, поправка 11"),
    ("2022-12-28", ["המשטרה", "משטרה"], "Указ о полиции, поправка 37"),
    ("2023-03-23", ["הממשלה"], "Основной закон о правительстве, поправка 12"),
    ("2023-07-24", ["השפיטה", "סבירות"], "Отмена стандарта разумности"),
    ("2025-03-04", ["נציב", "שופטים"], "Омбудсмен по жалобам на судей"),
    ("2025-03-27", ["השפיטה", "שופטים"], "Комиссия по назначению судей"),
    ("2026-07-15", ["היועץ המשפטי", "יועץ משפטי"], "Закон о юрсоветнике"),
    ("2026-07-16", ["שידור", "שידורים"], "Реформа вещания"),
]


def hits(text: str) -> dict[str, list[str]]:
    t = text or ""
    out = {}
    for grp, words in LEX.items():
        m = [w for w in words if w in t]
        if m:
            out[grp] = m
    return out


def main() -> int:
    print("законопроекты 25-го Кнессета…")
    bills = fetch_all("KNS_Bill", flt="KnessetNum eq 25",
                      select="Id,Name,KnessetNum,TypeDesc,SubTypeDesc,StatusID,PublicationDate")
    print("законы (KNS_IsraelLaw)…")
    laws = fetch_all("KNS_IsraelLaw", flt=f"PublicationDate ge {K25_START}T00:00:00Z",
                     select="Id,Name,PublicationDate,LawTypeDesc")

    matched = []
    for b in bills:
        h = hits(b.get("Name", ""))
        if h:
            matched.append({"kind": "bill", "id": b["Id"], "name": b.get("Name", "").strip(),
                            "type": b.get("SubTypeDesc"), "status": b.get("StatusID"),
                            "date": (b.get("PublicationDate") or "")[:10], "groups": h})
    for l in laws:
        h = hits(l.get("Name", ""))
        if h:
            matched.append({"kind": "law", "id": l["Id"], "name": l.get("Name", "").strip(),
                            "type": l.get("LawTypeDesc"),
                            "date": (l.get("PublicationDate") or "")[:10], "groups": h})

    by_grp: dict[str, int] = {}
    for m in matched:
        for g in m["groups"]:
            by_grp[g] = by_grp.get(g, 0) + 1

    print(f"\nзаконопроектов всего: {len(bills)} · законов: {len(laws)}")
    print(f"совпало с чек-листом: {len(matched)}  ({len(matched) * 100 // max(len(bills) + len(laws), 1)}%)")
    for g, n in sorted(by_grp.items(), key=lambda x: -x[1]):
        print(f"   {g:<18} {n}")

    # --- оракул отбора -------------------------------------------------------
    print("\nоракул отбора — обязаны найтись ВСЕ:")
    misses = []
    for date, words, title in ORACLE:
        year = date[:4]
        found = [m for m in matched
                 if any(w in m["name"] for w in words)
                 and (m["date"][:4] == year or not m["date"])]
        mark = "✓" if found else "✗ НЕ НАЙДЕН"
        if not found:
            misses.append(title)
        print(f"   {mark:<12} {date}  {title}  → кандидатов {len(found)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"matched": matched, "counts": by_grp,
                               "bills_total": len(bills), "laws_total": len(laws),
                               "oracle_misses": misses},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{OUT.relative_to(ROOT)}")
    if misses:
        print(f"\nОРАКУЛ КРАСНЫЙ: не найдено {len(misses)} — сломан проход, а не список",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
