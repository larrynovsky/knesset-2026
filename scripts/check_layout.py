# -*- coding: utf-8 -*-
# ПРОВЕРКА, КОТОРАЯ КРАСНЕЕТ: горизонтальной прокрутки нет ни на одной ширине.
# Требование владельца 2026-08-01 превращено в исполняемую проверку (§21).
# Рендерит ЛОКАЛЬНЫЕ файлы в Chromium и сравнивает scrollWidth с clientWidth.
import sys, pathlib
from playwright.sync_api import sync_playwright

WIDTHS = [320, 375, 414, 768, 1024, 1440]
TOL = 1  # округление субпикселей

def check(d):
    files = sorted(pathlib.Path(d).glob("*.html"))
    if not files:
        print("НЕТ ФАЙЛОВ", d); return 1
    bad = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for wdt in WIDTHS:
            pg = br.new_page(viewport={"width": wdt, "height": 900})
            for f in files:
                pg.goto("file://" + str(f.resolve()))
                # scrollWidth ослеплён любым overflow:hidden выше по дереву,
                # поэтому виновников ищем по геометрии элементов ВСЕГДА, а не
                # только когда scrollWidth уже показал вылет.
                sw, cw, who = pg.evaluate("""() => {
                    const lim = document.documentElement.clientWidth;
                    const out = [];
                    document.querySelectorAll('body *').forEach(el => {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.right > lim + 1) out.push(el.tagName +
                            (el.className ? '.' + String(el.className).split(' ')[0] : '') +
                            ' → ' + Math.round(r.right) + 'px');
                    });
                    return [document.documentElement.scrollWidth,
                            lim, out.slice(0, 5)];
                }""")
                if sw - cw > TOL or who:
                    bad.append((f.name, wdt, sw, cw, who))
            pg.close()
        br.close()
    for name, wdt, sw, cw, who in bad:
        print("КРАСНЫЙ  %-26s %4dpx: scrollWidth %d > clientWidth %d" % (name, wdt, sw, cw))
        for x in who: print("           виновник:", x)
    if bad:
        print("\nГОРИЗОНТАЛЬНАЯ ПРОКРУТКА ЕСТЬ — %d случаев" % len(bad)); return 1
    print("ЗЕЛЁНЫЙ: %d страниц × %d ширин = %d проверок, прокрутки нет нигде"
          % (len(files), len(WIDTHS), len(files)*len(WIDTHS)))
    return 0

if __name__ == "__main__":
    sys.exit(check(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mockup_v4"))
