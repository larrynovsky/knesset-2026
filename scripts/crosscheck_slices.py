#!/usr/bin/env python3
"""Read-only independent slices oracle (stdlib, no project imports).

Usage: python3 scripts/crosscheck_slices.py [--root REPO] [--selftest]
Contract/disposability: reviews/build_v75.md. Exit 1: mismatch/invalid input;
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
    lin = load(root / 'criteria' / 'slice_lineage_2026-10-19.json')['lines']
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
    checked = 0
    for n, paths in ready:
        votes, raw = load(paths[0])['rows'], load(paths[1])['signs']
        expected = {}
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
            if 'personal' in cell:
                print(f'SKIP {loc}/personal: requires named-vote cache, outside faction-link inputs')
        print(f'RECOUNT K{n}: {len(votes)} raw rows, {len(expected)} themes')
    for path, digest in fingerprints.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append('input changed during check: ' + str(path))
        print(f'INPUT {path.relative_to(root)} sha256={digest}')
    for error in errors:
        print('FAIL ' + error)
    print(f'CHECKED {checked} link-theme cells; mismatches={len(errors)}; skipped inputs are not verified')
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
        def run(label, code):
            p = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--root', str(root)],
                               capture_output=True, text=True)
            if p.returncode != code or (code == 1 and 'FAIL ' not in p.stdout):
                raise AssertionError((label, p.returncode, p.stdout, p.stderr))
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
