#!/usr/bin/env python3
"""Read-only independent slices oracle (stdlib, no project imports).

Usage: python3 scripts/crosscheck_slices.py [--root REPO] [--selftest]
Contract/disposability: reviews/build_v75.md; personal extension: reviews/build_v77.md. Exit 1: mismatch/invalid input;
exit 0 may include SKIP and is NOT evidence of full coverage (§20–24).
"""
import argparse
from collections import defaultdict
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

THEMES = ('rule_of_law', 'economy', 'religion_state', 'security')


def recount(rows, signs, options, drop, split):
    """Reduce signed observations as bill -> faction -> set of movements."""
    bills = defaultdict(lambda: defaultdict(set))
    present = set()
    for row in rows:
        bid = row['bill_id']
        if bid not in signs:
            continue  # theme_arrows selects the theme before compose checks options
        desc = (row.get('for_option_desc') or '').strip()
        if desc not in options:
            raise ValueError('unknown for_option_desc: ' + repr(desc))
        meaning = options[desc]['sign']
        counts = row.get('by_faction') or {}
        chamber = row.get('chamber_counts', {})
        totals = [chamber.get(k, sum(int(c.get(k, 0)) for c in counts.values()))
                  for k in ('for', 'against')]
        if any(type(v) is not int or v < 0 for v in totals):
            raise ValueError('invalid chamber counts')
        total = sum(totals)
        unanimous = not total or Fraction(min(totals), total) < drop
        for fac, c in counts.items():
            f, a, abst = (int(c.get(k, 0)) for k in ('for', 'against', 'abstain'))
            if min(f, a, abst) < 0:
                raise ValueError('negative faction count')
            if unanimous:
                if total and signs[bid] and f + a + abst:
                    present.add(fac)  # consensus-only factions still have 0/0
                continue
            if not f + a or Fraction(abs(f - a), f + a) < split:
                continue
            if not signs[bid] or meaning == 'none':
                continue
            movement = signs[bid] * (-1 if meaning == 'inverts' else 1)
            movement *= 1 if f > a else -1
            bills[bid][fac].add(movement)
            present.add(fac)
    result = {}
    for fac in sorted(present):
        up = sum(v.get(fac) == {1} for v in bills.values())
        down = sum(v.get(fac) == {-1} for v in bills.values())
        n = up + down
        arrow = None if n < 3 else 'down' if 3 * down >= 2 * n else 'up' if 3 * down <= n else 'both'
        fid = fac.split('|')[0]
        if fid in result:
            raise ValueError('multiple faction names for fid ' + fid)
        result[fid] = dict(up=up, down=down, arrow=arrow)
    return result


def personal_rows(rows, members, load, cache):
    """One person's positions, with the original chamber denominator."""
    if len(members) != 1:
        raise ValueError('personal oracle requires exactly one member per line')
    name, (mid, surname) = next(iter(members.items()))
    converted, voted = [], set()
    codes = {6: 'absent', 7: 'for', 8: 'against', 9: 'abstain', 10: 'absent'}
    for row in rows:
        vid = row['vote_id']
        data = load(cache / f'{vid}.json')
        named = data['rows']
        if (data['vote_id'] != vid or len(named) != row['named_total']
                or any(r['VoteID'] != vid for r in named)
                or len({r['MkId'] for r in named}) != len(named)):
            raise ValueError(f'personal: invalid/incomplete cache vote_id={vid}')
        found = [r for r in named if r['MkId'] == mid]
        position = 'absent'
        if found:
            person = found[0]
            if person['LastName'] != surname:
                raise ValueError(f'personal: mk_id/name mismatch: {name}')
            code = person['ResultCode']
            if type(code) is not int or code not in codes:
                raise ValueError(f'personal: unknown ResultCode: {code!r}')
            position = codes[code]
            if code in (7, 8, 9):
                voted.add(vid)
        chamber = {k: sum(c.get(k, 0) for c in row['by_faction'].values())
                   for k in ('for', 'against')}
        converted.append(dict(row, by_faction={'personal': {position: 1}},
                              chamber_counts=chamber))
    return converted, {name: len(voted)}


def threshold(text, section, key):
    block = re.search(r'^' + section + r':\s*\n((?:[ \t].*\n|\n|#.*\n)*)', text, re.M)
    hits = re.findall(r'^  ' + key + r':\s*([0-9.]+)\s*(?:#.*)?$', block[1] if block else '', re.M)
    if len(hits) != 1:
        raise ValueError('missing/ambiguous threshold: ' + section + '.' + key)
    value = Fraction(hits[0])
    if not 0 < value <= 1:
        raise ValueError('invalid threshold: ' + key)
    return value


def check(root):
    fingerprints = {}
    def read(path):
        raw = path.read_bytes()
        fingerprints[path] = hashlib.sha256(raw).hexdigest()
        return raw.decode('utf-8')
    def load(path):
        return json.loads(read(path))
    errors, ready = [], []
    for n in range(20, 25):
        paths = [root / 'data' / f'votes_{n}.json', root / 'criteria' / f'slice_signs_K{n}.json']
        missing = [str(p.relative_to(root)) for p in paths if not p.exists()]
        if missing:
            print(f'SKIP K{n}: missing ' + ', '.join(missing))
        else:
            ready.append((str(n), paths))
    if not (root / 'data/slices.json').exists():
        print('MISSING data/slices.json: no result to compare')
    if not ready:
        print('NO COVERAGE: 0 cells checked; no available votes/signs pair')
        return 0
    lineage = load(root / 'criteria' / 'slice_lineage_2026-10-19.json')
    lin = lineage['lines']
    tables = sorted((root / 'docs/reference').glob('for_option_sign_*.json'))
    rules = sorted((root / 'criteria').glob('declared_before_arrow_*.yaml'))
    if not tables or not rules:
        raise ValueError('missing sign table or declared arrow rule')
    options = load(tables[-1])['options']
    if any(v.get('sign') not in ('carries', 'inverts', 'none') for v in options.values()):
        raise ValueError('invalid sign table')
    rule = read(rules[-1])
    drop = threshold(rule, 'cleaning', 'drop_lopsided_below')
    split = threshold(rule, 'faction_position', 'split_below')
    target = root / 'data/slices.json'
    actual = load(target)['lines'] if target.exists() else {}
    if not target.exists():
        errors.append('missing data/slices.json (votes/signs available)')
    for extra in set(actual) - set(lin):
        errors.append(f'extra ballot line {extra}')
    checked = personal_checked = 0
    for n, paths in ready:
        votes, raw = load(paths[0])['rows'], load(paths[1])['signs']
        expected, theme_signs = {}, {}
        named_cache = {}
        def named_load(path):
            if path not in named_cache:
                named_cache[path] = load(path)
            return named_cache[path]
        for th in THEMES:
            if th not in raw:
                print(f'SKIP K{n}/{th}: theme signs missing')
                continue
            signs = {}
            for bid, val in raw[th].items():
                sign = val['sign'] if isinstance(val, dict) else val
                if type(sign) is not int or sign not in (-1, 0, 1):
                    raise ValueError(f'invalid sign K{n}/{th}/{bid}')
                signs[int(bid)] = sign
            theme_signs[th] = signs
            expected[th] = recount(votes, signs, options, drop, split)
        for line, by_k in lin.items():
            loc = f'{line}/K{n}'
            # Спецификация 19.10: звено без единого голоса в выгрузке Кнессета (фракция
            # возникла после роспуска) не выводится. Проверяется по сырым ключам by_faction.
            present = {k.split('|')[0] for r in votes for k in r.get('by_faction', {})}
            wanted = [w for w in by_k.get(n, []) if str(w[0]) in present]
            cell = actual.get(line, {}).get(n)
            if not isinstance(cell, dict) or not isinstance(cell.get('links'), list):
                errors.append(loc + ': missing cell/links')
                continue
            links = cell['links']
            if [str(v.get('fid')) for v in links] != [str(v[0]) for v in wanted]:
                errors.append(loc + ': lineage fids/order differ')
            for i, spec in enumerate(wanted):
                if i >= len(links):
                    continue
                for th, values in expected.items():
                    exp = values.get(str(spec[0]), dict(up=None, down=None, arrow=None))
                    got = links[i].get('themes', {}).get(th, {})
                    checked += 1
                    for key in ('up', 'down', 'arrow'):
                        if key not in got or type(got[key]) is not type(exp[key]) or got[key] != exp[key]:
                            errors.append(f'{loc}/link[{i}] fid={spec[0]}/{th}/{key}: expected {exp[key]!r}, got {got.get(key, "<missing>")!r}')
            members = lineage.get('personal_ids', {}).get(line, {})
            if members and expected:
                personal_checked += 1
                pv, stats = personal_rows(votes, members, named_load,
                                         root / 'data/named_votes_cache_slices')
                got = cell.get('personal')
                if not isinstance(got, dict):
                    errors.append(loc + '/personal: missing personal cell')
                elif 'none' in got:
                    if any(stats.values()) or 'stats' in got or 'themes' in got:
                        errors.append(f'{loc}/personal/none: expected zero votes, recounted {stats}')
                else:
                    if (got.get('stats') != stats or not all(stats.values())
                            or any(type(v) is not int for v in got.get('stats', {}).values())):
                        errors.append(f'{loc}/personal/stats: expected {stats}, got {got.get("stats")}')
                    for th, signs in theme_signs.items():
                        exp = recount(pv, signs, options, drop, split).get(
                            'personal', dict(up=None, down=None, arrow=None))
                        values = got.get('themes', {}).get(th, {})
                        for key, val in exp.items():
                            if key not in values or type(values[key]) is not type(val) or values[key] != val:
                                errors.append(f'{loc}/personal/{th}/{key}: expected {val!r}, got {values.get(key, "<missing>")!r}')
                print(f'PERSONAL {loc}: {stats}')
            elif 'personal' in cell:
                if not members:
                    errors.append(loc + '/personal: no personal_ids specification')
                else:
                    print(f'SKIP {loc}/personal: theme signs missing')
        print(f'RECOUNT K{n}: {len(votes)} raw rows, {len(expected)} themes')
    for path, digest in fingerprints.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append('input changed during check: ' + str(path))
        print(f'INPUT {path.relative_to(root)} sha256={digest}')
    for error in errors:
        print('FAIL ' + error)
    print(f'CHECKED {checked} link-theme cells; {personal_checked} personal cells; mismatches={len(errors)}; skipped inputs are not verified')
    return int(bool(errors))


def selftest():
    with tempfile.TemporaryDirectory(prefix='crosscheck-v75-') as tmp:
        root = Path(tmp)
        def put(name, value):
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(value), encoding='utf-8')
        rows = [dict(bill_id=i, for_option_desc='pass', by_faction={
            '1|A': {'for': 3}, '2|B': {'against': 3}}) for i in range(1, 4)]
        signs = {'signs': {'economy': {str(i): {'sign': 1} for i in range(1, 4)}}}
        lineage = {'lines': {'A': {'20': [[1, 'party']]}}}
        slices = {'lines': {'A': {'20': {'links': [dict(fid=1, themes={
            'economy': dict(up=3, down=0, arrow='up')})]}}}}
        put('data/votes_20.json', {'rows': rows})
        put('criteria/slice_signs_K20.json', signs)
        put('criteria/slice_lineage_2026-10-19.json', lineage)
        put('data/slices.json', slices)
        put('docs/reference/for_option_sign_test.json', {'options': {'pass': {'sign': 'carries'}}})
        (root / 'criteria/declared_before_arrow_test.yaml').write_text(
            'cleaning:\n  drop_lopsided_below: 0.025\nfaction_position:\n  split_below: 0.5\n')
        def run(label, code, message=None):
            p = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--root', str(root)],
                               capture_output=True, text=True)
            if p.returncode != code or (code == 1 and 'FAIL ' not in p.stdout + p.stderr):
                raise AssertionError((label, p.returncode, p.stdout, p.stderr))
            if message and message not in p.stdout + p.stderr:
                raise AssertionError((label, 'missing diagnostic', message, p.stdout, p.stderr))
            print(f'PASS {label}: exit {code}')
        run('clean fixture', 0)
        changed = copy.deepcopy(signs)
        changed['signs']['economy']['1']['sign'] = -1
        put('criteria/slice_signs_K20.json', changed)
        run('mutated bill sign', 1)
        put('criteria/slice_signs_K20.json', signs)
        put('criteria/slice_lineage_2026-10-19.json', {'lines': {'A': {'20': [[2, 'party']]}}})
        run('mutated lineage faction', 1)
        put('criteria/slice_lineage_2026-10-19.json', lineage)
        changed = copy.deepcopy(slices)
        changed['lines']['A']['20']['links'][0]['themes']['economy']['arrow'] = 'down'
        put('data/slices.json', changed)
        run('mutated slices word', 1)
        put('data/slices.json', slices)
        run('restored fixture', 0)
        # Expected values are literal; only the named vote changes in the mutant.
        lineage['personal_ids'] = {'A': {'Хили Тропер': [30683, 'טרופר']}}
        lineage['lines']['B'] = {'20': []}
        lineage['personal_ids']['B'] = {'Йоаз Хендель': [30680, 'הנדל']}
        slices['lines']['A']['20']['personal'] = {
            'stats': {'Хили Тропер': 3},
            'themes': {'economy': dict(up=3, down=0, arrow='up')}}
        slices['lines']['B'] = {'20': {'links': [], 'personal': {'none': 'no votes'}}}
        for row in rows:
            row.update(vote_id=row['bill_id'], named_total=1)
            put(f"data/named_votes_cache_slices/{row['vote_id']}.json", {
                'vote_id': row['vote_id'], 'rows': [dict(VoteID=row['vote_id'],
                    MkId=30683, LastName='טרופר', ResultCode=7)]})
        put('data/votes_20.json', {'rows': rows + [rows[0]]})  # stats deduplicates vote_id
        put('criteria/slice_lineage_2026-10-19.json', lineage)
        put('data/slices.json', slices)
        run('personal clean fixture and absent Hendel', 0)
        cache_path = root / 'data/named_votes_cache_slices/1.json'
        original = json.loads(cache_path.read_text())
        changed = copy.deepcopy(original)
        changed['rows'][0]['ResultCode'] = 8
        put('data/named_votes_cache_slices/1.json', changed)
        run('mutated Troper vote code', 1, 'A/K20/personal/economy/up: expected 2, got 3')
        put('data/named_votes_cache_slices/1.json', original)
        changed = copy.deepcopy(slices)
        changed['lines']['A']['20']['personal'] = {'none': 'no votes'}
        put('data/slices.json', changed)
        run('false personal.none with actual votes', 1)
        changed = copy.deepcopy(slices)
        changed['lines']['A']['20']['personal']['stats']['Хили Тропер'] = 4
        put('data/slices.json', changed)
        run('mutated personal stats', 1)
        put('data/slices.json', slices)
        changed = copy.deepcopy(original)
        changed['rows'] = []
        put('data/named_votes_cache_slices/1.json', changed)
        run('incomplete named cache', 1)
        put('data/named_votes_cache_slices/1.json', original)
        run('personal restored fixture', 0)
        for code in (9, 6, 10, None):
            changed = copy.deepcopy(original)
            changed['rows'] = ([] if code is None else
                               [dict(original['rows'][0], ResultCode=code)])
            put('data/named_votes_cache_slices/1.json', changed)
            adjusted = [dict(r, named_total=0) if r['vote_id'] == 1 and code is None else r
                        for r in rows]
            put('data/votes_20.json', {'rows': adjusted})
            target = copy.deepcopy(slices)
            target['lines']['A']['20']['personal'] = {
                'stats': {'Хили Тропер': 3 if code == 9 else 2},
                'themes': {'economy': dict(up=2, down=0, arrow=None)}}
            put('data/slices.json', target)
            run(f'personal abstain/present/absent code={code}', 0)
    opts = {v: {'sign': v} for v in ('carries', 'inverts', 'none')}
    def calc(extra, signs=None):
        return recount(extra, signs or {i: 1 for i in range(1, 9)}, opts, Fraction(1, 40), Fraction(1, 2))
    def row(bid, f=3, a=0, desc='carries', chamber=None):
        return dict(bill_id=bid, for_option_desc=desc, by_faction={'1|A': {'for': f, 'against': a}},
                    chamber_counts=chamber or {'for': 40, 'against': 40})
    assert calc([row(1), row(1), row(2), row(3, desc='inverts')])['1'] == dict(up=2, down=1, arrow='up')
    assert calc([row(1), row(1, desc='inverts')])['1'] == dict(up=0, down=0, arrow=None)
    assert calc([row(1), row(2, desc='inverts'), row(3, desc='inverts')])['1']['arrow'] == 'down'
    assert calc([row(1), row(2), row(3, desc='inverts'), row(4, desc='inverts')])['1']['arrow'] == 'both'
    assert calc([row(1), row(2)])['1']['arrow'] is None
    assert calc([row(1, 0, 3)])['1']['down'] == 1
    assert calc([row(1)], {1: -1})['1']['down'] == 1
    assert calc([row(1, 3, 1)])['1']['up'] == 1  # Rice exactly 0.5
    assert calc([row(1, 2, 1)]) == {}
    assert calc([row(1, chamber={'for': 39, 'against': 1})])['1']['up'] == 1
    assert calc([row(1, chamber={'for': 40, 'against': 1})])['1']['up'] == 0
    assert calc([row(1, desc='none')]) == {}
    assert calc([row(1)], {1: 0}) == {}
    try:
        calc([row(1, desc='unknown', chamber={'for': 40, 'against': 0})])
    except ValueError:
        pass
    else:
        raise AssertionError('unknown option hidden by unanimity')
    print('PASS arithmetic boundaries: deduplication, conflict, inversion, Rice, chamber threshold, none/zero, unknown option')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    try:
        sys.exit(selftest() if args.selftest else check(args.root))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f'FAIL invalid input: {exc}', file=sys.stderr)
        sys.exit(1)
