#!/usr/bin/env python3
"""Сверка названий и преемственности по Wikidata — второй независимый канал.

Зачем именно Wikidata, а не Википедия: статьи пришлось бы парсить, а здесь то же
самое лежит структурно — метки на ru/en/he и свойства преемственности
(P1365 replaces / P1366 replaced by / P155 follows / P156 followed by).

Две задачи, и вторая важнее:
  1. ПЕРЕВОДЫ. Мои 84 русские формы — пока ничем не проверенные утверждения.
     Совпадение с независимым источником переводит их из «моё мнение»
     в «сошлось»; расхождения становятся видимым списком (§20).
  2. ПРЕЕМСТВЕННОСТЬ. Сейчас доказательство одностороннее — сколько депутатов
     перешло. Wikidata даёт то же утверждение документом. Спрашивать человека
     нужно там, где КАНАЛЫ РАСХОДЯТСЯ, а не везде подряд.

Граница, названная заранее: Wikidata знает ПАРТИИ, а KNS_Faction — ФРАКЦИИ
конкретной каденции с официальными названиями списков. Единицы разные.
Ликуд в Wikidata один, в записях Кнессета — под пятью названиями. Значит
покрытие будет частичным по построению, и это не дефект сверки.
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ROOT / "criteria" / "faction_names_ru.yaml"
DRAFT = ROOT / "criteria" / "ballot_lineage_draft.json"
OUT = ROOT / "criteria" / "wikidata_crosscheck.json"

ENDPOINT = "https://query.wikidata.org/sparql"
UA = {"User-Agent": "knesset-research/0.1 (personal research; contact via repo)",
      "Accept": "application/sparql-results+json"}
CTX = ssl.create_default_context()
MIN_EXPECTED = 80          # §23: ожидание объявлено ДО запроса

QUERY = """
SELECT ?item ?he ?ru ?en ?alt ?rel ?other ?otherHe ?otherRu WHERE {
  ?item wdt:P17 wd:Q801 .
  VALUES ?type { wd:Q7278 wd:Q1339732 wd:Q48204 wd:Q7210356 }
  ?item wdt:P31/wdt:P279* ?type .
  OPTIONAL { ?item rdfs:label ?he  FILTER(lang(?he)="he") }
  OPTIONAL { ?item rdfs:label ?ru  FILTER(lang(?ru)="ru") }
  OPTIONAL { ?item rdfs:label ?en  FILTER(lang(?en)="en") }
  OPTIONAL { ?item skos:altLabel ?alt FILTER(lang(?alt)="he") }
  OPTIONAL {
    VALUES ?rel { wdt:P1365 wdt:P1366 wdt:P155 wdt:P156 }
    ?item ?rel ?other .
    OPTIONAL { ?other rdfs:label ?otherHe FILTER(lang(?otherHe)="he") }
    OPTIONAL { ?other rdfs:label ?otherRu FILTER(lang(?otherRu)="ru") }
  }
}
"""

REL = {"P1365": "заменяет", "P1366": "заменён на", "P155": "предшественник",
       "P156": "преемник"}


def sparql(q: str) -> list[dict]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
        return json.loads(r.read())["results"]["bindings"]


def load_my_names() -> dict[str, str]:
    out = {}
    for line in NAMES.read_text(encoding="utf-8").splitlines():
        if line.startswith("  ") and not line.strip().startswith("#") and ": " in line:
            he, ru = line.strip().split(": ", 1)
            out[he.strip()] = ru.strip()
    return out


def norm(s: str) -> str:
    return (s or "").strip().replace('"', "").replace("״", "").replace("'", "")


def main() -> int:
    print("запрос к Wikidata…")
    rows = sparql(QUERY)
    items: dict[str, dict] = {}
    for r in rows:
        qid = r["item"]["value"].rsplit("/", 1)[-1]
        it = items.setdefault(qid, {"qid": qid, "he": None, "ru": None, "en": None,
                                    "alt": set(), "rel": []})
        for k in ("he", "ru", "en"):
            if k in r and not it[k]:
                it[k] = r[k]["value"]
        if "alt" in r:
            it["alt"].add(r["alt"]["value"])
        if "other" in r and "rel" in r:
            p = r["rel"]["value"].rsplit("/", 1)[-1]
            it["rel"].append({"p": p, "kind": REL.get(p, p),
                              "qid": r["other"]["value"].rsplit("/", 1)[-1],
                              "he": r.get("otherHe", {}).get("value"),
                              "ru": r.get("otherRu", {}).get("value")})

    print(f"  сущностей: {len(items)} (ожидалось >= {MIN_EXPECTED})")
    if len(items) < MIN_EXPECTED:
        print("§23: получено меньше объявленного ожидания — запрос или охват сломан",
              file=sys.stderr)
        return 1

    # индекс: ивритская метка и алиасы -> сущность
    idx: dict[str, dict] = {}
    for it in items.values():
        for n in filter(None, [it["he"], *it["alt"]]):
            idx.setdefault(norm(n), it)

    mine = load_my_names()
    agree, differ, missing = [], [], []
    for he, my_ru in mine.items():
        hit = idx.get(norm(he))
        if not hit:
            missing.append({"he": he, "mine": my_ru})
            continue
        wd_ru, wd_en = hit["ru"], hit["en"]
        rec = {"he": he, "mine": my_ru, "wikidata_ru": wd_ru, "wikidata_en": wd_en,
               "qid": hit["qid"]}
        if wd_ru and norm(wd_ru).lower() == norm(my_ru).lower():
            agree.append(rec)
        elif wd_ru:
            differ.append(rec)
        else:
            rec["note"] = "в Wikidata нет русской метки"
            differ.append(rec)

    print(f"\nПЕРЕВОДЫ: сошлось {len(agree)} · разошлось {len(differ)} · "
          f"нет в Wikidata {len(missing)}  (из {len(mine)})")
    if differ:
        print("\n  расхождения (моё → Wikidata):")
        for d in differ[:25]:
            print(f"    {d['mine'][:34]:<36} → {str(d['wikidata_ru'])[:34]:<36} "
                  f"{d.get('note','')} [{d['qid']}]")

    # --- второй канал: преемственность ---
    links = []
    for it in items.values():
        for r in it["rel"]:
            links.append({"from_qid": it["qid"], "from_he": it["he"], "from_ru": it["ru"],
                          "kind": r["kind"], "to_qid": r["qid"],
                          "to_he": r["he"], "to_ru": r["ru"]})
    print(f"\nПРЕЕМСТВЕННОСТЬ: связей в Wikidata {len(links)}")

    # сверка с вопросами черновика
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    confirmed, silent = [], []
    for c in draft["chains"]:
        for s in c["chain"]:
            if s["step"] != "ВОПРОС":
                continue
            frm = idx.get(norm(c["anchor"]))
            for a in s.get("alternatives", []):
                to = idx.get(norm(a["name"]))
                if not (frm and to):
                    continue
                hit = [l for l in links
                       if {l["from_qid"], l["to_qid"]} == {frm["qid"], to["qid"]}]
                rec = {"anchor": c["anchor"], "anchor_ru": c.get("anchor_ru"),
                       "knesset": s["knesset"], "cand": a["name"], "cand_ru": a.get("ru"),
                       "shared": a["shared"], "overlap": a["overlap"]}
                (confirmed if hit else silent).append(
                    {**rec, "wikidata": [h["kind"] for h in hit]} if hit else rec)

    print(f"  вопросов, где Wikidata ПОДТВЕРЖДАЕТ кандидата: {len(confirmed)}")
    for c in confirmed[:15]:
        print(f"    к{c['knesset']} {str(c['anchor_ru'])[:26]:<28} ← "
              f"{str(c['cand_ru'])[:26]:<28} {c['wikidata']} "
              f"(перешло {c['shared']})")

    OUT.write_text(json.dumps(
        {"agree": agree, "differ": differ, "missing": missing,
         "links": links, "confirmed": confirmed},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
