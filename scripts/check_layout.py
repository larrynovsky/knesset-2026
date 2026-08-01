# -*- coding: utf-8 -*-
"""Горизонтальной прокрутки нет ни на одной ширине — и её не прячут.

Требование владельца 2026-08-01, превращённое в исполняемую проверку (§21).
Рендерит ЛОКАЛЬНЫЕ файлы в Chromium на шести ширинах.

ДВЕ ПРОВЕРКИ, А НЕ ОДНА. Первая редакция сравнивала scrollWidth с clientWidth
и была зелёной на подложенном блоке в 1600px: её ослеплял `overflow-x:hidden`
в проверяемом же CSS. Поэтому:

  1. ГЕОМЕТРИЯ — ни один элемент не выходит за вьюпорт. Считается по
     bounding-box, а не по scrollWidth: scrollWidth врёт под любым
     overflow:hidden выше по дереву.
  2. ЗАПРЕТ МАСКИРОВКИ — вычисленный overflow-x со значением hidden/clip
     на html, body или контейнере во всю ширину — отказ САМ ПО СЕБЕ,
     независимо от того, есть ли вылет сегодня. Он не устраняет вылет,
     а обрезает контент молча.

Каждая проверка носит при себе подложенное нарушение (`--selftest`):
не покрасневшая на своём мутанте проверка мертва, и узнать это иначе нельзя.

    python3 scripts/check_layout.py <каталог>
    python3 scripts/check_layout.py <каталог> --selftest
"""
import sys, shutil, pathlib, tempfile
from playwright.sync_api import sync_playwright

WIDTHS = [320, 375, 414, 768, 1024, 1440]
TOL = 1  # округление субпикселей

PROBE = """() => {
  const lim = document.documentElement.clientWidth;
  const wide = [], masked = [];
  for (const el of document.querySelectorAll('html, body, *')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > lim + 1)
      wide.push(el.tagName + (el.className ? '.' + String(el.className).split(' ')[0] : '')
                + ' → ' + Math.round(r.right) + 'px');
    const ox = getComputedStyle(el).overflowX;
    if ((ox === 'hidden' || ox === 'clip') && (el === document.documentElement
        || el === document.body || r.width >= lim - 1))
      masked.push(el.tagName + (el.className ? '.' + String(el.className).split(' ')[0] : '')
                  + ' overflow-x:' + ox);
  }
  return [wide.slice(0, 4), masked.slice(0, 4)];
}"""


def measure(d):
    """→ (N осмотренных пар страница×ширина, [проблемы])"""
    files = sorted(pathlib.Path(d).glob("*.html"))
    if not files:
        return 0, [f"в {d} нет ни одного HTML — проверять нечего"]
    problems, n = [], 0
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for w in WIDTHS:
            pg = br.new_page(viewport={"width": w, "height": 900})
            for f in files:
                pg.goto("file://" + str(f.resolve()))
                wide, masked = pg.evaluate(PROBE)
                n += 1
                for x in wide:
                    problems.append(f"{f.name} @{w}px вылет: {x}")
                for x in masked:
                    problems.append(f"{f.name} @{w}px маскировка: {x}")
            pg.close()
        br.close()
    return n, problems


# ────────────────────────────────────────────────────────────────── мутанты
MUTANTS = [
    ("блок шириной 200vw",
     lambda s: s.replace("</body>", '<div style="width:200vw">широко</div></body>')),
    ("вылет, замаскированный overflow:hidden",
     lambda s: s.replace("</body>", '<div style="overflow:hidden"><div style="width:200vw">широко</div></div></body>')
                .replace("*{box-sizing:border-box}", "*{box-sizing:border-box}html{overflow-x:hidden}")),
    ("маскировка без вылета — запрещена сама по себе",
     lambda s: s.replace("*{box-sizing:border-box}", "*{box-sizing:border-box}body{overflow-x:hidden}")),
    ("nowrap в таблице обзора",
     lambda s: s.replace("table.ov th,table.ov td{padding",
                         "table.ov th,table.ov td{white-space:nowrap;padding")),
]


def selftest(d):
    src = sorted(pathlib.Path(d).glob("*.html"))
    if not src:
        print(f"ОТКАЗ: в {d} нет HTML"); return 1
    print("── чистый вход: обязан быть зелёным")
    n, problems = measure(d)
    if problems:
        for p in problems[:6]: print("   ", p)
        print("САМОПРОВЕРКА ПРОВАЛЕНА: чистый вход красный"); return 1
    print(f"   {n} проверок (страница × ширина), прокрутки нет\n")

    print("── подложенные нарушения: каждое обязано покраснеть")
    dead = []
    for label, mut in MUTANTS:
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            for f in src:
                shutil.copy(f, t / f.name)
            target = t / "index.html" if (t / "index.html").exists() else t / src[0].name
            before = target.read_text(encoding="utf-8")
            after = mut(before)
            if after == before:
                print(f"   ПУСТЫШКА {label}")
                dead.append(f"{label}: МУТАНТ НИЧЕГО НЕ ИЗМЕНИЛ")
                continue
            target.write_text(after, encoding="utf-8")
            _, problems = measure(t)
            red = bool(problems)
            print(f"   {'КРАСНЫЙ' if red else 'ЗЕЛЁНЫЙ'}  {label}"
                  + (f"  ← {problems[0][:70]}" if red else ""))
            if not red:
                dead.append(f"{label}: НЕ ПОКРАСНЕЛА")
    print()
    if dead:
        for x in dead: print("ПРОВАЛ:", x)
        print(f"САМОПРОВЕРКА ПРОВАЛЕНА: не пойманы {len(dead)} из {len(MUTANTS)}")
        return 1
    print(f"САМОПРОВЕРКА ПРОЙДЕНА: {len(MUTANTS)} подложенных нарушений, все пойманы")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = args[0] if args else "site"
    if "--selftest" in sys.argv:
        sys.exit(selftest(d))
    n, problems = measure(d)
    if problems:
        for p in problems[:20]: print("КРАСНЫЙ ", p)
        print(f"\nОТКАЗ: {len(problems)} нарушений на {n} проверках")
        sys.exit(1)
    if n == 0:
        print("ОТКАЗ: осмотрено 0 пар страница×ширина — проверка ничего не проверила")
        sys.exit(1)
    pages = len(sorted(pathlib.Path(d).glob("*.html")))
    print(f"ЗЕЛЁНЫЙ: {pages} страниц × {len(WIDTHS)} ширин = {n} проверок, "
          f"прокрутки нет нигде, маскировки нет нигде")
    sys.exit(0)
