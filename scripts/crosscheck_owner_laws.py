#!/usr/bin/env python3
"""Independent v68/v71 owner-law recount; stdlib only, read-only inputs.
See crosscheck_owner_laws.contract.md. No renderer imports.
"""
import collections
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c for c in self.children).split())
    def find(self, tag=None, **attrs):
        return [n for c in self.children if isinstance(c, Node)
                for n in ([c] if (tag is None or c.tag == tag) and all(c.attrs.get(k) == v for k,v in attrs.items()) else []) + c.find(tag, **attrs)]

class Parser(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node(); self.stack = [self.root]; self.feed(text)
    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs); self.stack[-1].children.append(n)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(n)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag == tag:
                del self.stack[i:]; break
    def handle_data(self, text):
        self.stack[-1].children.append(text)

def page_cells(text):
    rows = {}
    for tr in Parser(text).root.find('tr'):
        key = tr.attrs.get('data-ballot-list')
        if key is None: continue
        assert key not in rows, ('duplicate ballot row',key)
        spans = tr.find('span', **{'class':'ballot-laws'})
        assert len(spans) <= 1, (key, 'duplicate law container')
        if spans:
            cells = [c.text() for c in spans[0].children if isinstance(c,Node) and c.tag=='span']
        else:
            tds = tr.find('td')
            assert tds and tds[0].text() in {'—', 'нет голосов', 'нет данных'}, (key, 'missing law cells')
            cells = [tds[0].text()]*4
        assert len(cells)==4, (key,cells)
        rows[key]=cells
    assert len(rows)==14, ('expected 14 lists',len(rows))
    return rows

def validate(rows, vid, expected):
    assert len(rows)==expected, (vid,'short read')
    assert len({r['MkId'] for r in rows})==len(rows), (vid,'duplicate MkId')
    assert all(r['VoteID']==vid and r['ResultDesc'] in {'בעד','נגד','נמנע','נוכח'} for r in rows), (vid,'invalid row')

def position(c,n):
    t=sum(c[k] for k in ('за','против','воздержались'))
    if n==0: return 'нет состава'
    if 3*t<n or t==0: return 'не голос.'
    for k in ('за','против'):
        if 2*c[k]>t: return k
    return 'нет позиции'



def recount(root):
    def read(rel): return (root/rel).read_text(encoding='utf-8')
    def get(rel): return json.loads(read(rel))
    ballot=get('criteria/ballot_2026.json')['lists'];assert len(ballot)==14
    marks=[int(x) for x in re.findall(r'^  (\d+):\n    mark: недопустимо$',read('criteria/owner_marks_2026-10-10.yaml'),re.M)]
    assert len(marks)==4
    vdata=get('data/votes_25.json');votes=vdata['rows']
    full=get('data/votes_full_25.json')
    assert vdata==full and len(votes)==full['matched_votes'], 'site votes differ from declared full K25 export'
    # One vote may link to several bills; require consistent vote metadata.
    headers={}
    for r in votes:
        signature=tuple(r[k] for k in ('date','named_total','for_option_desc','against_option_desc'))
        assert r['vote_id'] not in headers or headers[r['vote_id']]==signature
        headers[r['vote_id']]=signature
    mem=collections.defaultdict(set)
    for r in get('data/KNS_PersonToPosition_54.json'):
        if r['KnessetNum']==25: mem[r['PersonID']].add(r['FactionID'])
    factions={r['Id']:r['Name'] for r in get('data/KNS_Faction.json') if r['KnessetNum']==25}
    assert all(f in factions for row in ballot for f in row.get('factions',[]))
    upper=collections.Counter(f for fs in mem.values() for f in fs)
    trans={'בעד':'за','נגד':'против','נמנע':'воздержались','נוכח':'присутствовал без голоса'}
    cache={}
    def named(r):
        vid=r['vote_id']
        if vid not in cache:
            obj=get(f'data/named_votes_cache/{vid}.json');assert obj['vote_id']==vid
            validate(obj['rows'],vid,r['named_total']);cache[vid]=obj['rows']
        return cache[vid]
    results=[]
    for bid in marks:
        stages=[r for r in votes if r['bill_id']==bid]
        thirds=[r for r in stages if r['for_option_desc']=='לקבל את הצעת החוק בקריאה שלישית']
        candidates=thirds or [r for r in stages if r['for_option_desc']=='להעביר את הצעת החוק לוועדה שתקבע ועדת הכנסת להכנה לקריאה ראשונה']
        assert candidates, ('no final stage',bid)
        final=max(candidates,key=lambda r:(r['date'],r['vote_id']))
        assert sum(r['date']==final['date'] for r in candidates)==1
        day=final['date'][:10];possible={};active_day=set()
        for r in votes:
            if r['date'][:10]!=day: continue
            active={int(k.split('|')[0]) for k in r['by_faction']}
            active_day.update(active)
            for x in named(r):
                p=x['MkId'];assert p in mem, ('unmapped',p)
                possible[p]=possible.get(p,mem[p]) & active
        assert all(possible.values()), ('inconsistent membership',bid)
        mapping={p:next(iter(fs)) for p,fs in possible.items() if len(fs)==1}
        raw=named(final);assert all(x['MkId'] in mapping for x in raw), ('ambiguous final vote',bid)
        counts=collections.defaultdict(collections.Counter)
        for x in raw:
            f=mapping[x['MkId']];k=trans[x['ResultDesc']];counts[f][k]+=1
        details={}
        for f in sorted({f for b in ballot for f in b.get('factions',[])}):
            c=counts[f];seen={p for p,ff in mapping.items() if ff==f};t=sum(c[k] for k in ('за','против','воздержались'))
            lo,hi=len(seen),upper[f];assert lo<=hi and t<=lo
            pset={position(c,n) for n in range(max(lo,t,1),hi+1)}
            pos=next(iter(pset)) if len(pset)==1 and lo else 'не установлено'
            if f not in active_day: pos='фракции не было'
            details[f]=dict(pos=pos)
        personal=[x for x in raw if x['LastName'] in {'טרופר','איזנקוט','אייזנקוט'}]
        assert all(x['FirstName'] in {'חילי','גדי','גד'} for x in personal)
        pc=collections.Counter(trans[x['ResultDesc']] for x in personal)
        assert len(personal)<=2
        results.append(dict(details=details,pc=pc))

    expected={}; unknown=set()
    for b in ballot:
        parts={}
        for i,r in enumerate(results,1):
            if b.get('personal'):
                parts[i]={'yashar':position(r['pc'],2)}
            else:
                parts[i]={str(f):r['details'][f]['pos'] for f in b.get('factions',[])}
            if 'не установлено' in parts[i].values(): unknown.add((b['he'],i))
        expected[b['he']]=parts
    return ballot, expected, unknown


def labels(text):
    # Parentheses contain faction names or minority counts, not the main position.
    text = re.sub(r'\([^)]*\)', '', text)
    pattern = r'фракции не было|нет большинства|нет позиции|не голос\.|воздержались|нет голосов|нет данных|против|за|—'
    assert not re.sub(pattern, '', text).replace('·', '').strip(), ('unknown cell text', text)
    return re.findall(pattern, text)


def compare(ballot, expected, unknown, pages):
    errors = []
    checked = 0
    if len(unknown) > 5:
        errors.append(f'неопределимо {len(unknown)} клеток; разрешено не более 5')
    for name in ('index.html', 'cheatsheet.html'):
        rows = page_cells(pages[name])
        assert set(rows) == set(expected), (name, 'ballot rows differ')
        for b in ballot:
            for i, parts in expected[b['he']].items():
                if (b['he'], i) in unknown:
                    continue
                want = list(dict.fromkeys(parts.values()))
                actual = labels(rows[b['he']][i-1])
                if not want:
                    matches = actual in (['—'], ['нет голосов'], ['нет данных'])
                else:
                    matches = actual == want
                checked += 1
                if not matches:
                    errors.append(f'{name}: {b["ru"]}, закон {i}: {actual} != {want or ["нет данных"]}')
    for number, b in enumerate(ballot, 1):
        name = f'l-{number}.html'
        cells = {}
        for td in Parser(pages[name]).root.find('td'):
            if 'data-short-law' not in td.attrs:
                continue
            key = (int(td.attrs['data-short-law']), td.attrs.get('data-fid'))
            assert key not in cells, (name, 'duplicate cell', key)
            cells[key] = td.text()
        wanted = {(i, fid): value for i, parts in expected[b['he']].items()
                  for fid, value in parts.items()}
        assert set(cells) == set(wanted), (name, 'missing/extra cells', set(wanted)-set(cells), set(cells)-set(wanted))
        # New lists have a no-history paragraph instead of a short-law table.
        if not wanted:
            assert 'голосов нет' in Parser(pages[name]).root.text(), (name, 'missing no-history statement')
        for key, value in wanted.items():
            if value == 'не установлено':
                continue
            checked += 1
            if labels(cells[key]) != [value]:
                errors.append(f'{name}: {b["ru"]}, закон {key[0]}, фракция {key[1]}: {cells[key]} != {value}')
    return checked, errors


def selftest():
    import tempfile
    # Fail at the full-export boundary before requiring other production inputs.
    with tempfile.TemporaryDirectory(prefix='crosscheck-owner-full-') as folder:
        root = Path(folder)
        for rel, text in (
            ('criteria/ballot_2026.json', json.dumps({'lists': [{}] * 14})),
            ('criteria/owner_marks_2026-10-10.yaml', ''.join(f'  {i}:\n    mark: недопустимо\n' for i in range(4))),
            ('data/votes_25.json', json.dumps({'rows': []})),
            ('data/votes_full_25.json', json.dumps({'rows': [{'vote_id': 1}], 'matched_votes': 1})),
        ):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        try:
            recount(root)
        except AssertionError as exc:
            assert str(exc) == 'site votes differ from declared full K25 export'
        else:
            raise AssertionError('stale sample accepted')
    print('REJECTED site sample differing from full K25 export')
    c = collections.Counter({'против': 1})
    assert position(c, 3) == 'против' and position(c, 4) == 'не голос.'
    assert position(c, 2) == 'против'
    assert position(collections.Counter({'за': 1, 'против': 1}), 2) == 'нет позиции'
    for rows, n in [([], 1), ([{'MkId': 1, 'VoteID': 1, 'ResultDesc': 'בעד'}]*2, 2)]:
        try:
            validate(rows, 1, n)
        except AssertionError:
            pass
        else:
            raise AssertionError('invalid raw cache accepted')
    ballot = [{'he': str(n), 'ru': str(n)} for n in range(14)]
    expected = {b['he']: {i: {'1': 'за'} for i in range(1, 5)} for b in ballot}
    body = ''.join(f'<tr data-ballot-list="{b["he"]}"><td><span class="ballot-laws">'
                   + '<span><b>за</b></span>'*4 + '</span></td></tr>' for b in ballot)
    pages = {name: body for name in ('index.html', 'cheatsheet.html')}
    pages.update({f'l-{n}.html': ''.join(f'<td data-short-law="{i}" data-fid="1"><b>за</b></td>'
                                      for i in range(1, 5)) for n in range(1, 15)})
    assert compare(ballot, expected, set(), pages) == (168, [])
    for name in pages:
        mutant = dict(pages)
        mutant[name] = pages[name].replace('<b>за</b>', '<b>против</b>', 1)
        assert compare(ballot, expected, set(), mutant)[1], ('flip survived', name)
        mutant[name] = ''
        try:
            compare(ballot, expected, set(), mutant)
        except AssertionError:
            pass
        else:
            raise AssertionError(('missing cells survived', name))
    unknown = {(str(n), 1) for n in range(6)}
    assert not compare(ballot, expected, set(list(unknown)[:5]), pages)[1]
    assert compare(ballot, expected, unknown, pages)[1]
    print('OK selftest: clean HTML; flipped cell and missing cells on all 16 pages; unknown >5; threshold; raw cache')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--site', type=Path, help='HTML directory override (e.g. mutation copy)')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if not __debug__:
        print('FAIL: assertions required; do not run with -O', file=sys.stderr)
        return 1
    try:
        if args.selftest:
            selftest()
            return 0
        ballot, expected, unknown = recount(args.root)
        site = args.site or args.root/'site'
        names = ['index.html', 'cheatsheet.html'] + [f'l-{n}.html' for n in range(1, len(ballot)+1)]
        pages = {name: (site/name).read_text(encoding='utf-8') for name in names}
        checked, errors = compare(ballot, expected, unknown, pages)
        print(f'Сверено отрисованных клеток: {checked}; неопределимо уникальных клеток списка × закона: {len(unknown)} (предел 5)')
        for b, i in sorted(unknown):
            print(f'НЕОПРЕДЕЛИМО: {b}, закон {i}')
        for error in errors:
            print('РАСХОЖДЕНИЕ: ' + error)
        print('FAIL' if errors else 'OK: независимый пересчёт 4 законов совпал')
        return 1 if errors else 0
    except (AssertionError, OSError, ValueError, KeyError, TypeError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
