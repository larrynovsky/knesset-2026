#!/usr/bin/env python3
"""Ф0.5 плана: разведка Викитекста — есть ли РЕДАКЦИЯ НА ДАТУ АКТА.

§23-exempt: это разведка ФОРМЫ источника, а не выгрузка данных. Объявленный
объём здесь невозможен по устройству задачи — мы выясняем, что вообще отдаёт
API и есть ли у страниц история ревизий. Ни один артефакт данных этот скрипт
не создаёт; выгрузка пойдёт через guarded_fetch отдельным модулем.

ЗАЧЕМ ИМЕННО ЭТО. Проба 12.08 показала: 9 из 11 базовых актов в открытой базе
есть. Но «страница существует» и «существует редакция на декабрь 2022» —
разные утверждения, и второе не измерено (P35). Без него риск R1 плана
открыт: подставив СЕГОДНЯШНЮЮ редакцию, мы дадим вендору норму, которой на
момент акта не было, и он рассудит о ней увереннее, чем раньше.

Хост зафиксирован в коде и не приходит из данных — SSRF-шаблон (R4) на этом
шаге не возникает. Он возникнет у fetch_law_texts, и там будет allowlist.

    python3 scripts/probe_wikisource.py --selftest
    python3 scripts/probe_wikisource.py
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://he.wikisource.org/w/api.php"
UA = {"User-Agent": "knesset-research/0.1 (personal document; contact via github)"}
CTX = ssl.create_default_context()

# Страницы взяты из замера docs/explanation/base_text_probe_2026-08-12.md.
# Дата — внесение соответствующих актов пилота (19.12.2022 и 26.12.2022).
TARGETS = [
    ("חוק-יסוד: השפיטה", "2022-12-19", "2196169"),
    ("חוק-יסוד: הממשלה", "2022-12-19", "2195773"),
    ("חוק יסודות התקציב", "2022-12-26", "2197276"),
    ("חוק עבודת נשים", "2022-12-19", "2197645"),
    ("פקודת המשטרה", "2022-12-19", "2196637"),
]


def pick_revision(revs: list, on_date: str) -> dict | None:
    """Последняя ревизия НЕ ПОЗЖЕ даты. Сердце R1, потому и с проверкой.

    Пустой список, все ревизии позже даты, ревизия ровно в дату — три случая,
    в которых легко ошибиться молча. Возврат None означает «редакции на эту
    дату у нас нет» и обязан читаться как отказ, а не как «взять свежую».
    """
    fit = [r for r in revs if r.get("timestamp", "")[:10] <= on_date]
    return max(fit, key=lambda r: r["timestamp"]) if fit else None


def api(params: dict) -> dict:
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    req = urllib.request.Request(f"{API}?{q}", headers=UA)
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def probe(title: str, on_date: str) -> dict:
    meta = api({"action": "query", "prop": "revisions", "titles": title,
                "rvlimit": 500, "rvprop": "ids|timestamp", "rvdir": "newer"})
    page = (meta.get("query", {}).get("pages") or [{}])[0]
    if page.get("missing"):
        return {"title": title, "exists": False}
    revs = page.get("revisions", [])
    at = pick_revision(revs, on_date)
    out = {"title": title, "exists": True, "revisions": len(revs),
           "first": revs[0]["timestamp"][:10] if revs else None,
           "last": revs[-1]["timestamp"][:10] if revs else None,
           "on_date": on_date, "revid_at_date": at and at["revid"],
           "ts_at_date": at and at["timestamp"][:10]}
    if at:
        body = api({"action": "query", "prop": "revisions", "titles": title,
                    "revids": at["revid"], "rvprop": "content", "rvslots": "main"})
        p = (body.get("query", {}).get("pages") or [{}])[0]
        txt = p["revisions"][0]["slots"]["main"]["content"]
        out["chars"] = len(txt)
        out["has_section_markup"] = "{{ח:" in txt or "==" in txt
    return out


def selftest() -> int:
    r = [{"revid": 1, "timestamp": "2020-01-01T00:00:00Z"},
         {"revid": 2, "timestamp": "2022-12-19T10:00:00Z"},
         {"revid": 3, "timestamp": "2023-05-05T00:00:00Z"}]
    assert pick_revision(r, "2022-12-19")["revid"] == 2, \
        "ревизия РОВНО в дату акта входит: акт вносят в тот же день, и норма "\
        "в этот день уже такая"
    assert pick_revision(r, "2022-12-18")["revid"] == 1, \
        "берётся последняя НЕ ПОЗЖЕ даты, а не ближайшая по модулю"
    assert pick_revision(r, "2019-01-01") is None, \
        "все ревизии позже даты — это ОТКАЗ, а не повод взять свежую (R1)"
    assert pick_revision([], "2022-12-19") is None
    assert pick_revision(r, "2030-01-01")["revid"] == 3
    print("самопроверка probe_wikisource пройдена: 5 утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    print(f"разведка Викитекста, {datetime.now(timezone.utc).date()} — "
          "форма источника, не выгрузка (§23-exempt)")
    ok = 0
    for title, on_date, bill in TARGETS:
        try:
            r = probe(title, on_date)
        except Exception as e:
            print(f"  {title[:34]:<34} ОШИБКА {type(e).__name__}: {e}"[:120])
            continue
        if not r["exists"]:
            print(f"  {title[:34]:<34} страницы НЕТ")
            continue
        got = r["ts_at_date"] or "—"
        ok += bool(r["revid_at_date"])
        print(f"  {title[:34]:<34} ревизий {r['revisions']:>4} "
              f"({r['first']}..{r['last']}) · на {r['on_date']}: {got} "
              f"· знаков {r.get('chars', 0):>7} · разметка "
              f"{'есть' if r.get('has_section_markup') else 'НЕТ'} · акт {bill}")
    print(f"\nредакция на дату акта достижима: {ok} из {len(TARGETS)}")
    print("P35 объявлял две трети — сверять с этим числом, а не с ощущением")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
