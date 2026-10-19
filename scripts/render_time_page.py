#!/usr/bin/env python3
"""Доля расхождений по календарным периодам; контракт: contracts/render_time_page.json.

python3 scripts/render_time_page.py --selftest
python3 scripts/render_time_page.py [--votes PATH]
Порог и сопоставление сеток объявлены до первого расчёта результатов.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import copy
import json
from pathlib import Path
import sys

from build_line_cards import _arrow_split
from direction_confidence import faction_position
from render_overview import SHORT_FRAME, css_from_mockup, esc
import yaml  # Уже используется render_axes; сохраняет апострофы в названиях.

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'site/time.html'
BREAK_THRESHOLD = 0.20  # Строго больше 20 процентных пунктов, не 20 процентов.
FORBIDDEN_PROSE = ('правительств',)  # Намеренно строгий лексический оракул.


def periods(window, months):
    """Календарная сетка, обрезанная полуоткрытым окном выгрузки [start,end)."""
    start, end = (date.fromisoformat(s[:10]) for s in window)
    if start >= end or months not in (3, 6):
        raise ValueError('Некорректное окно или шаг сетки')
    current = date(start.year, (start.month - 1) // months * months + 1, 1)
    result = []
    while current < end:
        month = current.month - 1 + months
        following = date(current.year + month // 12, month % 12 + 1, 1)
        result.append((max(current, start), min(following, end)))
        current = following
    return result


def measure(data, faction_ids, months, split):
    bins = periods(data['window'], months)
    cells = {fid: [Counter() for _ in bins] for fid in faction_ids}
    seen = {}
    for row in data['rows']:
        signature = (row['date'], row['by_faction'], row['named_total'])
        if row['vote_id'] in seen:
            if seen[row['vote_id']] != signature:
                raise ValueError('Противоречивый повтор vote_id')
            continue
        seen[row['vote_id']] = signature
        day = date.fromisoformat(row['date'][:10])
        indices = [i for i, (a, b) in enumerate(bins) if a <= day < b]
        if len(indices) != 1:
            raise ValueError(f'Голосование вне окна: {row["vote_id"]}')
        i = indices[0]
        factions, total = {}, Counter()
        for key, counts in row['by_faction'].items():
            fid = int(key.split('|', 1)[0])
            if fid in factions or any(type(n) is not int or n < 0 for n in counts.values()):
                raise ValueError('Повтор фракции или некорректный счётчик')
            factions[fid] = counts
            total.update(counts)
        if sum(total.values()) != row['named_total']:
            raise ValueError('Не все поимённые голоса связаны с фракциями: исход зала ненадёжен')
        winner = ('for' if total['for'] > total['against'] else
                  'against' if total['against'] > total['for'] else None)
        for fid in cells:
            c = factions.get(fid, {})
            cell = cells[fid][i]
            position = faction_position(c, split)
            if position is None:
                cell['split' if c.get('for', 0) + c.get('against', 0) else 'no_position'] += 1
            elif winner is None:
                cell['tie'] += 1
            else:
                cell['n'] += 1
                cell['different'] += position != winner
    return bins, cells


def share(cell):
    return cell['different'] / cell['n'] if cell['n'] else None


def breaks(half, quarter):
    """Сохранение: тот же знак и >X на квартальной границе той же даты."""
    hb, hc = half
    qb, qc = quarter
    result = []
    for fid, cells in hc.items():
        for i in range(1, len(hb)):
            before, after = share(cells[i-1]), share(cells[i])
            if before is None or after is None:
                continue
            delta = after - before
            if abs(delta) <= BREAK_THRESHOLD:
                continue
            j = next(j for j, (a, _) in enumerate(qb) if a == hb[i][0])
            qbefore, qafter = share(qc[fid][j-1]), share(qc[fid][j])
            qdelta = None if qbefore is None or qafter is None else qafter - qbefore
            survives = qdelta is not None and abs(qdelta) > BREAK_THRESHOLD and delta * qdelta > 0
            result.append(dict(fid=fid, boundary=str(hb[i][0]), delta=delta,
                               qdelta=qdelta, survives=survives))
    return result


def validate_page(doc):
    # §20: проверяется видимая проза, с распаковкой HTML-сущностей.
    from check_report_canon import text_of, c_js, c_noindex
    text = text_of(doc).casefold()
    for word in FORBIDDEN_PROSE:
        if word in text:
            raise ValueError(f'Запрещённое слово в прозе: {word}')
    if c_js({'time.html': doc})[1] or c_noindex({'time.html': doc})[1]:
        raise ValueError('Нарушение noindex или запрета JavaScript')


def label(period):
    return f'{period[0]} — {period[1] - timedelta(days=1)}'


def faction_name(names, fid):
    ru, he = names[fid]
    return f'{esc(ru)} <span lang=he dir=rtl><bdi>{esc(he)}</bdi></span>'


def matrix(measured, names):
    bins, cells = measured
    headers = ''.join(f'<th scope=col>{label(p)}</th>' for p in bins)
    rows = []
    for fid in names:  # Порядок ID, а не величины; итога по фракции нет (§13).
        values = []
        for p, c in zip(bins, cells[fid]):
            value = share(c)
            percent = f'{value:.1%}' if value is not None else '— нет доли'
            values.append(f'<td data-l="{label(p)}">{percent}<br>'
                          f'{c["different"]}/{c["n"]}<br>'
                          f'раскол: {c["split"]}; без позиции: {c["no_position"]}; '
                          f'ничья зала: {c["tie"]}</td>')
        rows.append(f'<tr><th scope=row>{faction_name(names, fid)}</th>{"".join(values)}</tr>')
    return '<table class="ov time"><thead><tr><th scope=col>Фракция</th>' + headers + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'


def page(data, names, split, digest):
    half = measure(data, names, 6, split)
    quarter = measure(data, names, 3, split)
    changes = breaks(half, quarter)
    kept = sum(x['survives'] for x in changes)
    unavailable = sum(x['qdelta'] is None for x in changes)
    lines = []
    for x in changes:
        q = 'нет доли' if x['qdelta'] is None else f'{x["qdelta"] * 100:+.1f} п.п.'
        state = ('не проверяется: нет позиции в одном из кварталов' if x['qdelta'] is None else
                 'сохраняется' if x['survives'] else 'не подтвердилось при делении на кварталы')
        lines.append(f'<tr><th scope=row>{faction_name(names, x["fid"])}</th>'
                     f'<td data-l="Граница">{x["boundary"]}</td>'
                     f'<td data-l="Полугодия">{x["delta"] * 100:+.1f} п.п.</td>'
                     f'<td data-l="Кварталы">{q}</td><td data-l="Проверка">{state}</td></tr>')
    doc = f'''<!doctype html><html lang=ru><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Голосования во времени — 25-й Кнессет</title>
<style>{css_from_mockup()}
body{{max-width:100rem}} table.time{{font-size:var(--f0)}}
table.time th,table.time td{{overflow-wrap:anywhere}}
@media(max-width:70rem){{table.time,table.time tbody,table.time tr,table.time td{{display:block;width:auto}}
table.time thead{{display:none}} table.time td:before{{content:attr(data-l);display:block;font-weight:bold}}
table.time tr{{margin-bottom:1rem}}}}
</style></head><body><nav class=crumbs><a href="index.html">Все фракции</a> · Время</nav>
{SHORT_FRAME}<h1>Как менялась доля расхождений с залом</h1>
<p class=lead>25-й Кнессет, по вопросам правового государства: только голосования по законопроектам,
попавшим в выгрузку. Это не все голосования созыва и не оценка партий.</p>
<p>Окно: {esc(data['window'][0])} — {esc(data['window'][1])}, правая граница не включена.
Снимок: {esc(data['at'])}. Строк в снимке: {len(data['rows'])}; уникальных голосований:
{len({r['vote_id'] for r in data['rows']})}. Повторов исключено:
{len(data['rows']) - len({r['vote_id'] for r in data['rows']})}.
Первый и последний периоды обрезаны границами окна.</p>
<p>В каждой клетке — доля голосований, где позиция фракции расходится с победившей стороной зала,
и дробь: число расхождений / число сравнимых голосований. Побеждает сторона с большим числом
голосов «за» или «против» по всем фракциям. При равенстве победителя нет; такие случаи исключены.
Это большинство голосов, а не проверка юридического принятия решения с особым порогом.</p>
<p>Позиция фракции — большинство среди её голосов «за» и «против», если
|за − против| / (за + против) не ниже {split:g}. Ниже — раскол, отдельное состояние,
исключённое из числителя и знаменателя. Воздержание и отсутствие не задают позиции.
«За» здесь обозначает вариант голосования, а не поддержку содержания законопроекта.</p>
<p>Счётчики под долей показывают исключения. «Без позиции» включает отсутствие фракции в записи;
по этим данным нельзя отличить неучастие от периода до её появления. Ноль сравнимых голосований
показан прочерком, а не нулевой долей. Размеры знаменателей меняются; малые числа не скрыты.</p>
<h2>Полугодия</h2>{matrix(half, names)}
<h2>Проверка делением на кварталы</h2>
<p>Скачок доли — изменение строго больше {BREAK_THRESHOLD * 100:g} процентных пунктов между
соседними полугодиями. Порог выбран для описания, не как статистическая значимость.
Скачков между полугодиями: {len(changes)}; сохраняются на кварталах: {kept};
не подтвердились при делении на кварталы: {len(changes)-kept-unavailable}; не проверяются: {unavailable}.</p>
<p>Сохранение означает тот же знак и превышение того же порога между кварталами непосредственно
по обе стороны той же границы. Например, граница 1 июля сравнивает апрель–июнь с июлем–сентябрём.
Сдвиг внутри соседнего квартала этим строгим правилом не засчитывается. Дата в таблице — граница
интервалов, не установленный день изменения поведения. Причины изменений здесь не определяются.</p>
<table class="ov time"><thead><tr><th scope=col>Фракция</th><th scope=col>Граница</th>
<th scope=col>Полугодия</th><th scope=col>Кварталы</th><th scope=col>Проверка</th></tr></thead>
<tbody>{''.join(lines)}</tbody></table>
<details><summary>Все квартальные доли и знаменатели</summary>{matrix(quarter, names)}</details>
<details><summary>Технические сведения об источниках</summary><p class=foot>Источник: data/votes_25.json; SHA-256: {digest}.
Названия: criteria/faction_names_ru.yaml. Фракции — из cards/*-k25-votes.yaml.
Полугодовые и квартальные доли рассчитаны из одного снимка.</p></details></body></html>'''
    validate_page(doc)
    return doc, changes


def selftest():
    split = float(_arrow_split())
    rows = []
    for i, day in enumerate(('2023-01-01', '2023-04-01', '2023-07-01', '2023-10-01')):
        counts = {'1|a': {'for': 2}, '2|b': {'against': 2}, '3|c': {'for': 1, 'against': 1},
                  '9|зал': {'for': 20}, '4|d': {'abstain': 1}}
        rows.append(dict(vote_id=i, date=day, by_faction=counts, named_total=27))
    data = dict(window=['2023-01-01', '2024-01-01'], rows=rows, at='test')
    for months in (3, 6):
        _, cells = measure(data, (1, 2, 3, 4), months, split)
        assert all(share(c) == 0 for c in cells[1])
        assert all(share(c) == 1 for c in cells[2])
        assert all(share(c) is None and c['split'] and not c['different'] for c in cells[3])
        assert all(share(c) is None and c['no_position'] for c in cells[4])
    print('ЗЕЛЁНЫЙ: с залом = 0; против = 1; раскол и отсутствие позиции исключены; обе сетки')
    # Инверсия победителя зала, ничья, пустые периоды и точная граница.
    rows[0]['by_faction']['9|зал'] = {'against': 20}
    assert share(measure(data, (1,), 3, split)[1][1][0]) == 1
    rows[0]['by_faction']['9|зал'] = {'abstain': 20}
    assert measure(data, (1,), 3, split)[1][1][0]['tie'] == 1
    empty = dict(data, rows=[])
    assert all(share(c) is None for c in measure(empty, (1,), 6, split)[1][1])
    assert periods(['2022-11-15', '2023-07-01'], 6) == [(date(2022,11,15), date(2023,1,1)), (date(2023,1,1), date(2023,7,1))]
    hb = periods(data['window'], 6)
    qb = periods(data['window'], 3)
    cell = lambda n: Counter(n=100, different=n)
    half = (hb, {1: [cell(10), cell(70)]})
    quarter = (qb, {1: [cell(0), cell(10), cell(70), cell(80)]})
    assert breaks(half, quarter)[0]['survives']
    quarter[1][1][2] = cell(20)
    assert not breaks(half, quarter)[0]['survives']
    quarter[1][1][2] = Counter()
    assert breaks(half, quarter)[0]['qdelta'] is None
    assert not breaks((hb, {1: [cell(0), cell(20)]}), quarter)
    duplicate = dict(data, rows=data['rows'] + [copy.deepcopy(data['rows'][0])])
    assert measure(duplicate, (1,), 6, split) == measure(data, (1,), 6, split)
    for label_, bad in (('конфликт повторов', copy.deepcopy(duplicate)),
                        ('потерянный голос', copy.deepcopy(data)),
                        ('голосование за границей окна', copy.deepcopy(data))):
        if label_ == 'конфликт повторов':
            bad['rows'][-1]['date'] = '2023-01-02'
        elif label_ == 'потерянный голос':
            bad['rows'][0]['named_total'] += 1
        else:
            bad['rows'][0]['date'] = '2024-01-01'
        try:
            measure(bad, (1,), 6, split)
        except ValueError as e:
            print(f'КРАСНЫЙ (ожидаемый, {label_}): {e}')
        else:
            raise AssertionError(f'Мёртвый оракул: {label_}')
    print('ЗЕЛЁНЫЙ: победа против, ничья, пустота, границы, сохранение и исчезновение излома')
    doc, _ = page(data, {1: ('Тест', 'אב')}, split, 'test')
    for label_, spoiled in (
        ('объяснение периодом правительства', doc.replace('</body>', '<p>Доля упала потому, что фракция вошла в правительство.</p></body>')),
        ('снят noindex', doc.replace('noindex, nofollow', 'index, follow')),
        ('сортировка через JavaScript', doc.replace('</body>', '<script>1</script></body>')),
    ):
        try:
            validate_page(spoiled)
        except ValueError as e:
            print(f'КРАСНЫЙ (ожидаемый, {label_}): {e}')
        else:
            raise AssertionError(f'Мёртвый оракул: {label_}')
    print('SELFTEST OK')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--votes', type=Path, default=ROOT / 'data/votes_25.json')
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    names = {}
    translations = yaml.safe_load((ROOT / 'criteria/faction_names_ru.yaml').read_text())['names']
    for path in sorted((ROOT / 'cards').glob('*-k25-votes.yaml')):
        card = yaml.safe_load(path.read_text())
        fid, he = int(card['faction_id']), card['party_he']
        if fid in names or not translations.get(he):
            raise ValueError('Повтор фракции или отсутствует перевод')
        names[fid] = (translations[he], he)
    if not names:
        raise ValueError('Нет фракций')
    raw = args.votes.read_bytes()
    data = json.loads(raw)
    if data['knesset'] != 25 or not data['rows']:
        raise ValueError('Пустая выгрузка или другой созыв')
    doc, changes = page(data, dict(sorted(names.items())), float(_arrow_split()), hashlib.sha256(raw).hexdigest())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding='utf-8')
    print(f'{OUT}: {len(names)} фракций, {len(data["rows"])} строк, {len({r["vote_id"] for r in data["rows"]})} уникальных голосований; изломы {len(changes)}, сохраняются {sum(x["survives"] for x in changes)}')
    for x in changes:
        q = 'нет доли' if x['qdelta'] is None else f'{x["qdelta"]*100:+.1f}'
        print(f'| {names[x["fid"]][0]} | {x["boundary"]} | {x["delta"]*100:+.1f} | {q} | {"да" if x["survives"] else "нет"} |')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as e:
        sys.exit(f'ОТКАЗ: {e}')
