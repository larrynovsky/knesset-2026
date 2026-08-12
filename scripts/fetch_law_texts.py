#!/usr/bin/env python3
"""Ф3 плана: статья базового закона в редакции НА ДАТУ АКТА.

Объём и ожидания объявлены ДО первого запроса:
criteria/declared_before_lawfetch_2026-08-12.yaml (71 закон, 203 адреса).

§23-exempt НЕ ставится: ожидание объявлено, сверка ниже, расхождение — отказ.
guarded_fetch не используется намеренно: он умеет OData и SQL со счётчиком
`$count`, здесь источник другой, и притворяться, что проверка та же, было бы
хуже, чем честно провести свою и сослаться на объявленный файл.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ. Не синтезирует текст «после поправки»: решение
владельца 12.08 — «до» плюс дифф, реконструкция только для простой замены и
с пометкой. Не решает, какие статьи нужны: это дело resolve_law_ref.

БЕЗОПАСНОСТЬ (R4 плана, WSTG-INPV-19). Хост в allowlist и в коде. Ни один
URL из данных не выгружается: адрес страницы строится из имени закона, а не
берётся из поля. Это решение, а не забывчивость.
"""
from __future__ import annotations

import inspect
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_direction import norm_he                      # noqa: E402
from probe_wikisource import CTX, UA, PAUSE, pick_revision  # noqa: E402
from resolve_law_ref import refs                            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEXTDIR = ROOT / "data" / "bill_texts"
OUT = ROOT / "data" / "law_texts.json"
DECLARED = ROOT / "criteria" / "declared_before_lawfetch_2026-08-12.yaml"

ALLOWED_HOSTS = {"he.wikisource.org"}
API = "https://he.wikisource.org/w/api.php"

RX_ACT_DATE = re.compile(r"\((\d{1,2})\.(\d{1,2})\.(\d{4})\)")
RX_SEC = re.compile(r"\{\{ח:סעיף\*?\|([^|}\n]*)")
RX_CUT = re.compile(r"\{\{ח:(?:סעיף\*?|קטע\d?|סוף)\|?")


def check_host(url: str) -> str:
    """Единственная дверь наружу. Хост не из данных — и всё равно проверяется.

    Проверка стоит здесь не потому, что сегодня URL может прийти из выгрузки,
    а потому, что завтра кто-нибудь (я) решит «удобнее взять ссылку из поля».
    Тогда красное будет тут, а не в чужой сети.
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"хост вне allowlist: {host!r}")
    return url


def api(params: dict, tries: int = 4) -> dict:
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    url = check_host(f"{API}?{q}")
    for i in range(tries):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=60, context=CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 5 * 2 ** i)
    raise RuntimeError("недостижимо")


def act_date(text: str) -> str | None:
    """Дата внесения — из самого акта. Нет даты — ОТКАЗ, а не «возьмём свежую»."""
    m = RX_ACT_DATE.findall(text)
    if not m:
        return None
    d, mo, y = m[-1]
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def article(wikitext: str, num: str) -> str | None:
    """Вырезать статью N по разметке. Не эвристика по тексту — разбор шаблонов."""
    for m in RX_SEC.finditer(wikitext):
        if m.group(1).strip() != num:
            continue
        start = m.end()
        nxt = RX_CUT.search(wikitext, start)
        return wikitext[m.start():nxt.start() if nxt else len(wikitext)].strip()
    return None


def flatten(t: str) -> str:
    """Снять вики-разметку, СОХРАНИВ её параметры.

    Полное удаление шаблонов теряет текст: заголовок статьи живёт ВНУТРИ
    {{ח:סעיף|15|זכות עמידה}}, и якорь «זכות עמידה» исчезал вместе со скобками.
    Убираем имя шаблона и разделители, слова оставляем.
    """
    t = re.sub(r"\{\{\s*ח:[^|}]*\|?", " ", t)
    return t.replace("}}", " ").replace("|", " ")


RX_SERVICE = re.compile(r"\b(?:או|וכן|סעיף|סעיפים|פסקה|פסקאות|תוספת)\b")


def is_reference_anchor(q: str) -> bool:
    """Якорь-перечень: акт правит ССЫЛКИ, а не текст.

    «22, 23 או 43ד» и «סעיפים 24 או 43ד» — это списки номеров статей. Искать
    их в тексте статьи бессмысленно: они проверяют не то, для чего оракул
    заведён, и попадали в промахи, занижая долю.

    Правило намеренно БЕЗ ЧИСЛОВОГО ПОРОГА: порог, подобранный после
    просмотра девяти промахов, был бы подгонкой под увиденное. Правило
    качественное — вычеркнуть номера, пунктуацию и служебные слова; если не
    осталось ни одного слова хотя бы из трёх ивритских букв, якорь указывает
    на ссылку, а не на текст.
    """
    rest = RX_SERVICE.sub(" ", q)
    rest = re.sub(r"[^א-ת ]+", " ", rest)
    return not any(len(w) >= 3 for w in rest.split())


def oracle_hits(anchors: list, base_text: str, law_text: str = "") -> dict:
    """Оракул из диффа: якоря ЭТОГО адреса обязаны найтись в ЭТОЙ статье.

    Три исхода, а не два, и это главное отличие от первой редакции:

      hit     — якорь в статье. Вытянуто то, что надо;
      in_law  — якоря в статье нет, но он ЕСТЬ в законе. Значит вытянут не
                тот кусок: адрес указывает не на ту статью, либо текст живёт
                вне разметки статей (преамбула). Дефект РАЗБОРА;
      miss    — якоря нет нигде. Вытянут не тот закон или не та редакция.
                Дефект ВЫГРУЗКИ.

    Сливать эти два случая — значит не знать, что чинить. До 12.08 они были
    слиты.

    Сравнение через norm_he — ту же нормализацию, что у цитат карточки. Она
    снимает разницу ивритского макафа «־» и дефиса-минуса, на которой проект
    горел дважды и потерял здесь два якоря из девяти.
    """
    art = norm_he(flatten(base_text))
    law = norm_he(flatten(law_text)) if law_text else ""
    r = {"hit": 0, "in_law": 0, "miss": 0, "skipped": 0}
    for q in anchors:
        if is_reference_anchor(q):
            r["skipped"] += 1
            continue
        n = norm_he(q)
        if n and n in art:
            r["hit"] += 1
        elif n and law and n in law:
            r["in_law"] += 1
        else:
            r["miss"] += 1
    return r


def selftest() -> int:
    assert check_host("https://he.wikisource.org/w/api.php")
    for bad in ("https://evil.example/api", "http://127.0.0.1:8080/x",
                "https://he.wikisource.org.evil.example/x"):
        try:
            check_host(bad)
            raise AssertionError(f"allowlist пропустил {bad}")
        except ValueError:
            pass
    assert act_date("הונחה ביום י\"ח בכסלו התשפ\"ג (12.12.2022)") == "2022-12-12"
    assert act_date("без даты вовсе") is None, \
        "нет даты — ОТКАЗ: молчаливый переход на свежую редакцию и есть R1"

    wt = ("{{ח:סעיף|14|כותרת}} טקסט ראשון\n"
          "{{ח:סעיף|15|זכות עמידה}} לא ייזקק בית המשפט לבקשה\n"
          "{{ח:תת|(ד)}} פסקה\n"
          "{{ח:סעיף|16|אחר}} טקסט אחרון")
    a15 = article(wt, "15")
    assert a15 and "זכות עמידה" in a15 and "טקסט אחרון" not in a15, \
        "статья режется по разметке и не съедает следующую"
    assert "פסקה" in a15, "подпункты статьи остаются внутри неё"
    assert article(wt, "99") is None, "нет статьи — None, а не пустая строка"

    assert oracle_hits(["לא ייזקק בית המשפט"], wt)["hit"] == 1, \
        "якорь «до» обязан находиться в базовом тексте"
    assert oracle_hits(["טקסט שאינו קיים כלל"], wt)["miss"] == 1, \
        "ненайденный якорь — сигнал, что вытянуто не то, и он обязан "\
        "быть виден числом, а не утонуть"
    assert oracle_hits([], wt) == {"hit": 0, "in_law": 0, "miss": 0, "skipped": 0}, \
        "адрес без якорей не даёт ни попадания, ни промаха: он вне замера"
    # Разметка не должна прятать якорь: в вики между словами стоят шаблоны.
    assert oracle_hits(["זכות עמידה"], "{{ח:סעיף|15|זכות עמידה}} טקסט")["hit"] == 1

    # --- ТРИ ИСХОДА ВМЕСТО ДВУХ -------------------------------------------
    # «Нет в статье» и «нет нигде» — разные диагнозы: первый чинится разбором,
    # второй выгрузкой. До 12.08 они были слиты, и было непонятно, что чинить.
    r = oracle_hits(["ובהיותו בן חורין"], "{{ח:סעיף|1|כותרת}} טקסט אחר",
                    "{{ח:פתיח}} ובהיותו בן חורין {{ח:סעיף|1|כותרת}} טקסט אחר")
    assert r == {"hit": 0, "in_law": 1, "miss": 0, "skipped": 0}, \
        "якорь есть в законе, но не в статье — это дефект РАЗБОРА, и он "\
        "обязан отличаться от «нет нигде»"
    r = oracle_hits(["אין כזה טקסט בשום מקום"], "{{ח:סעיף|1|א}} טקסט", "{{ח:סעיף|1|א}} טקסט")
    assert r["miss"] == 1 and r["in_law"] == 0, \
        "нет нигде — дефект ВЫГРУЗКИ, другой диагноз и другое лечение"

    # --- МАКАФ ------------------------------------------------------------
    assert oracle_hits(["חד-ערכי"], "{{ח:סעיף|2|א}} מזהה חד־ערכי של אדם")["hit"] == 1, \
        "ивритский макаф «־» и дефис-минус «-» — один и тот же текст; на "\
        "этом различии проект горел дважды"

    # --- ЯКОРЬ-ПЕРЕЧЕНЬ ----------------------------------------------------
    for ref in ("22, 23 או 43ד", "סעיפים 24 או 43ד", "(3), 27 או 43ד"):
        assert is_reference_anchor(ref), f"перечень номеров не текст: {ref}"
    for txt in ("חד-ערכי", "התפקידים", "לא ייזקק בית המשפט"):
        assert not is_reference_anchor(txt), f"это текст нормы: {txt}"
    assert oracle_hits(["22, 23 או 43ד"], wt)["skipped"] == 1, \
        "якорь-перечень выпадает из замера, а не считается промахом: он "\
        "проверяет не то, для чего оракул заведён"
    print(f"самопроверка fetch_law_texts пройдена: "
          f"{sum(1 for _ in re.finditer('assert ', inspect.getsource(selftest)))} утверждений")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not DECLARED.exists():
        print(f"нет {DECLARED.name} — объём не объявлен, выгрузка запрещена (§23)")
        return 2

    need: dict[str, dict] = {}
    no_date = 0
    for p in sorted(TEXTDIR.glob("*.txt")):
        txt = p.read_text(encoding="utf-8")
        d = act_date(txt)
        for r in refs(txt):
            if r["kind"] != "article" or not r["law"]:
                continue
            if not d:
                no_date += 1
                continue
            need.setdefault(r["law"], {"arts": set(), "dates": set(), "bills": set()})
            need[r["law"]]["arts"].add(r["article"])
            need[r["law"]]["dates"].add(d)
            need[r["law"]]["bills"].add(p.stem)

    print(f"объявлено 71 закон · к выгрузке {len(need)} · "
          f"адресов без даты акта {no_date}")

    rows, full = [], {}
    stats = {"page": 0, "missing": 0, "rev": 0, "art": 0, "key": 0}
    for i, (law, info) in enumerate(sorted(need.items()), 1):
        on = min(info["dates"])
        try:
            meta = api({"action": "query", "prop": "revisions", "titles": law,
                        "rvlimit": 500, "rvprop": "ids|timestamp", "rvdir": "newer"})
        except Exception as e:
            rows.append({"law": law, "status": f"error:{type(e).__name__}"})
            continue
        page = (meta.get("query", {}).get("pages") or [{}])[0]
        if page.get("missing"):
            stats["missing"] += 1
            rows.append({"law": law, "status": "page_missing"})
            print(f"  [{i}/{len(need)}] {law[:40]:<40} страницы нет")
            continue
        stats["page"] += 1
        at = pick_revision(page.get("revisions", []), on)
        if not at:
            rows.append({"law": law, "status": "no_revision_at_date", "on": on})
            print(f"  [{i}/{len(need)}] {law[:40]:<40} нет редакции на {on}")
            continue
        stats["rev"] += 1
        body = api({"action": "query", "prop": "revisions", "revids": at["revid"],
                    "rvprop": "content", "rvslots": "main"})
        pb = (body.get("query", {}).get("pages") or [{}])[0]
        rv = pb.get("revisions") or []
        if not rv:
            rows.append({"law": law, "status": "no_content", "revid": at["revid"]})
            continue
        wt = rv[0]["slots"]["main"]["content"]
        key = re.search(r"\{\{ח:מאגר\|(\d+)\}\}", wt)
        stats["key"] += bool(key)
        got = {a: article(wt, a) for a in sorted(info["arts"])}
        found = {a: t for a, t in got.items() if t}
        stats["art"] += len(found)
        full[law] = wt
        rows.append({"law": law, "status": "ok", "on": on, "revid": at["revid"],
                     "ts": at["timestamp"][:10], "israel_law_id": key and key.group(1),
                     "articles_wanted": sorted(info["arts"]),
                     "articles_found": sorted(found),
                     "articles": found, "bills": sorted(info["bills"])})
        print(f"  [{i}/{len(need)}] {law[:40]:<40} рев.{at['timestamp'][:10]} "
              f"статей {len(found)}/{len(info['arts'])} "
              f"ключ {key.group(1) if key else '—'}")

    orc = {"hit": 0, "in_law": 0, "miss": 0, "skipped": 0}
    by_law = {r["law"]: r for r in rows if r.get("status") == "ok"}
    for p in sorted(TEXTDIR.glob("*.txt")):
        for r in refs(p.read_text(encoding="utf-8")):
            row = by_law.get(r.get("law") or "")
            if not row or r["kind"] != "article" or not r.get("anchors"):
                continue
            base = (row["articles"] or {}).get(r["article"])
            if base:
                for k, v in oracle_hits(r["anchors"], base,
                                        full.get(r["law"], "")).items():
                    orc[k] += v

    OUT.write_text(json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(), "declared_laws": 71,
         "attempted": len(need), "stats": stats, "rows": rows},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nстраниц найдено {stats['page']} из {len(need)} "
          f"(объявлено было не менее 45 — P38)")
    print(f"ключ {{{{ח:מאגר}}}} есть у {stats['key']} из {stats['page']} (P39)")
    print(f"статей вырезано {stats['art']} (P40 — по адресам, см. ниже)")
    judged = orc["hit"] + orc["in_law"] + orc["miss"]
    print(f"\nОРАКУЛ ДИФФА — три исхода, а не два:")
    print(f"   в статье (годно)        {orc['hit']:>4}"
          + (f"  ({100*orc['hit']/judged:.0f}%)" if judged else ""))
    print(f"   в законе, но не в статье {orc['in_law']:>3}  ← дефект РАЗБОРА:"
          " адрес указывает не туда")
    print(f"   нет нигде                {orc['miss']:>3}  ← дефект ВЫГРУЗКИ:"
          " не тот закон или не та редакция")
    print(f"   якорь-перечень вне замера {orc['skipped']:>2}  (акт правит ссылки,"
          " а не текст)")
    print("Сливать «не в статье» и «нет нигде» значит не знать, что чинить.")
    print(f"\n{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
