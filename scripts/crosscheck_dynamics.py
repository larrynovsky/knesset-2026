#!/usr/bin/env python3
"""Independent read-only dynamics oracle (§10, §20–24); stdlib only.

Run with --root REPO; --selftest uses isolated synthetic files and the real CLI.
No project modules are imported. See crosscheck_dynamics.contract.md.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import date
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

THEMES = ('rule_of_law', 'economy', 'religion_state', 'security')
MEMBERS = {30836: 'איזנקוט', 30683: 'טרופר'}


def halves(window):
    start, end = (date.fromisoformat(x[:10]) for x in window)
    if start >= end:
        raise ValueError('empty/reversed window')
    edges = [start]
    for year in range(start.year, end.year + 1):
        edges.extend(d for d in (date(year, 1, 1), date(year, 7, 1)) if start < d < end)
    edges.append(end)
    return [[a.isoformat(), b.isoformat()] for a, b in zip(edges, edges[1:])]


def threshold(text, key):
    hits = re.findall(r'^  ' + key + r':\s*([0-9.]+)\s*(?:#.*)?$', text, re.M)
    if len(hits) != 1 or not 0 <= Fraction(hits[0]) <= 1:
        raise ValueError('missing/invalid threshold: ' + key)
    return Fraction(hits[0])


def signed(value):
    if type(value) is not int or value not in (-1, 0, 1):
        raise ValueError('invalid law sign: ' + repr(value))
    return value


def counts(obj):
    values = [obj.get(k, 0) for k in ('for', 'against')]
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError('invalid vote counts: ' + repr(values))
    return values


def recount(rows, bins, signs, options, drop, split):
    # Different reduction order from compose: theme / bill / faction / bin.
    observations = defaultdict(set)
    names = {}
    for row in rows:
        day = date.fromisoformat(row['date'][:10]).isoformat()
        indexes = [i for i, (a, b) in enumerate(bins) if a <= day < b]
        if len(indexes) != 1:
            raise ValueError(f'vote {row["vote_id"]}: date outside window: {day}')
        desc = (row.get('for_option_desc') or '').strip()
        if desc not in options:
            raise ValueError('unknown for_option_desc: ' + repr(desc))
        meaning = options[desc]['sign']
        if meaning not in ('carries', 'inverts', 'none'):
            raise ValueError('invalid option sign: ' + repr(meaning))
        factions = row.get('by_faction') or {}
        positions = {fac: counts(c) for fac, c in factions.items()}
        chamber = row.get('chamber_counts', {})
        totals = counts({k: chamber.get(k, sum(c[j] for c in positions.values()))
                         for j, k in enumerate(('for', 'against'))})
        total = sum(totals)
        if not total or Fraction(min(totals), total) < drop or meaning == 'none':
            continue
        bid = row.get('bill_id')
        for fac, (f, a) in positions.items():
            if not f + a or Fraction(abs(f-a), f+a) < split:
                continue
            fid = fac.split('|')[0]
            if fid in names and names[fid] != fac:
                raise ValueError('ambiguous faction ID: ' + fid)
            names[fid] = fac
            vote = (1 if f > a else -1) * (-1 if meaning == 'inverts' else 1)
            for theme in THEMES:
                direction = signs[theme].get(bid, 0)
                if direction:
                    observations[theme, bid, fid, indexes[0]].add(direction * vote)
    series = {}
    for (theme, bid, fid, i), moves in observations.items():
        cells = series.setdefault(fid, {}).setdefault(theme, [[0, 0] for _ in bins])
        if len(moves) == 1:
            cells[i][0 if moves == {1} else 1] += 1
    return series


def compare(bins, expected, actual):
    errors = []
    if actual.get('bins') != bins:
        errors.append(f'bins: expected {bins!r}, actual {actual.get("bins")!r}')
    got = actual['series']
    for fid in sorted(expected.keys() | got.keys()):
        if fid not in expected or fid not in got:
            errors.append(f'series/{fid}: missing or unexpected faction')
        e, g = expected.get(fid, {}), got.get(fid, {})
        for theme in sorted(e.keys() | g.keys()):
            if theme not in e or theme not in g:
                errors.append(f'{fid}/{theme}: missing or unexpected theme')
                continue
            if not isinstance(g[theme], list) or len(g[theme]) != len(bins):
                errors.append(f'{fid}/{theme}: invalid bin count')
                continue
            for i, (want, have) in enumerate(zip(e[theme], g[theme])):
                valid = (isinstance(have, list) and len(have) == 2
                         and all(type(v) is int and v >= 0 for v in have))
                if not valid or want != have:
                    errors.append(f'{fid}/{theme}/{bins[i]}: expected {want}, actual {have!r}')
    return errors


def check(root):
    hashes = {}
    def read(relative):
        raw = (root / relative).read_bytes()
        hashes[str(relative)] = hashlib.sha256(raw).hexdigest()
        return raw.decode('utf-8')
    def load(relative):
        return json.loads(read(relative))
    votes = load('data/votes_25.json')
    full = load('data/votes_full_25.json')
    if votes != full or len(votes['rows']) != full['matched_votes']:
        raise ValueError('site votes differ from declared full K25 export')
    bins = halves(votes['window'])
    signs = {'rule_of_law': {}}
    axis = signs['rule_of_law']
    for row in load('data/direction_arrow_2026-10-07.json')['rows']:
        q = row.get('quorum') or {}
        if q.get('kind') != 'no_quorum' and q.get('value') is not None:
            axis[row['bill']] = signed(q['value'])
    for bill, value in load('criteria/claude_tiebreak_signs_2026-10-19.json')['signs'].items():
        axis.setdefault(int(bill), signed(value))
    for theme in THEMES[1:]:
        signs[theme] = {int(b): signed(v['sign'] if isinstance(v, dict) else v)
                       for b, v in load(f'criteria/theme_signs_{theme}.json')['signs'].items()}
    # declared_before_site_full_2026-10-20: legacy signs, including 0, win.
    additions = load('criteria/full_signs_K25.json')['signs']
    if set(additions) != set(THEMES):
        raise ValueError('full K25 signs must contain all four themes')
    for theme in THEMES:
        for bill, value in additions[theme].items():
            signs[theme].setdefault(int(bill), signed(value))
    for bill in load('criteria/economy_second_reading_2026-10-20.json')['removed']:
        signs['economy'][int(bill)] = 0
    # v93 amendment: full-text disagreement also removes a new title-only sign.
    for bill, value in load('criteria/axis_second_reading_2026-10-19.json')['signs'].items():
        if value is not None and int(bill) in axis and signed(value) != axis[int(bill)]:
            axis[int(bill)] = 0
    options_path = sorted(root.glob('docs/reference/for_option_sign_*.json'))[-1]
    options = load(options_path.relative_to(root))['options']
    if any(v.get('sign') not in ('carries', 'inverts', 'none') for v in options.values()):
        raise ValueError('unclassified option in sign table')
    drop = threshold(read('criteria/declared_before_arrow_2026-10-07.yaml'), 'drop_lopsided_below')
    rule_path = sorted(root.glob('criteria/declared_before_arrow_*.yaml'))[-1]
    split = threshold(read(rule_path.relative_to(root)), 'split_below')
    personal = []
    participated = set()
    for row in votes['rows']:
        vid = row['vote_id']
        cache = load(f'data/named_votes_cache/{vid}.json')
        named = cache['rows']
        if (cache['vote_id'] != vid or len(named) != row['named_total']
                or any(r['VoteID'] != vid for r in named)
                or len({r['MkId'] for r in named}) != len(named)):
            raise ValueError(f'invalid/incomplete personal cache: {vid}')
        answers = []
        for mid, surname in MEMBERS.items():
            person = next((r for r in named if r['MkId'] == mid), None)
            code = 10
            if person:
                code = person['ResultCode']
                if person['LastName'] != surname or type(code) is not int or code not in (6, 7, 8, 9, 10):
                    raise ValueError(f'invalid personal identity/answer: {vid}/{mid}')
                if code in (7, 8, 9):
                    participated.add(mid)
            answers.append(code)
        position = {}
        if answers[0] == answers[1] and answers[0] in (7, 8):
            position['for' if answers[0] == 7 else 'against'] = 2
        chamber = {k: sum(counts(c)[j] for c in row['by_faction'].values())
                   for j, k in enumerate(('for', 'against'))}
        personal.append(dict(row, by_faction={'yashar': position}, chamber_counts=chamber))
    if participated != MEMBERS.keys():
        raise ValueError('personal: no participation for one or both members')
    expected = recount(votes['rows'] + personal, bins, signs, options, drop, split)
    errors = compare(bins, expected, load('data/dynamics_25.json'))
    for relative, digest in hashes.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            errors.append('input changed during check: ' + relative)
    for error in errors:
        print('FAIL ' + error)
    print(f'{"FAIL" if errors else "PASS"}: {len(votes["rows"])} vote rows; '
          f'{len(bins)} bins; {len(expected)} series including yashar; '
          f'{sum(len(v) for v in expected.values()) * len(bins)} up/down cells')
    print('SKIP gov: task scope is vote dynamics, not government membership')
    manifest = '\n'.join(f'{k} {v}' for k, v in sorted(hashes.items()))
    print(f'Inputs: {len(hashes)} files; manifest SHA256 {hashlib.sha256(manifest.encode()).hexdigest()}')
    return int(bool(errors))


def selftest():
    with tempfile.TemporaryDirectory(prefix='crosscheck-dynamics-') as folder:
        root = Path(folder)
        def put(path, obj):
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding='utf-8')
        rows = [dict(vote_id=i, bill_id=1, date=day, for_option_desc='yes', named_total=2,
                     by_faction={'1|a': {'for': 2}, '2|b': {'against': 2}})
                for i, day in enumerate(('2023-06-30', '2023-06-29', '2023-07-01'), 1)]
        rows[-1]['bill_id'] = 2  # New full-export law, absent from legacy signs.
        votes = dict(window=['2023-01-01', '2024-01-01'], rows=rows, matched_votes=3)
        put('data/votes_25.json', votes)
        put('data/votes_full_25.json', votes)
        for r in rows:
            put(f'data/named_votes_cache/{r["vote_id"]}.json', dict(vote_id=r['vote_id'], rows=[
                dict(VoteID=r['vote_id'], MkId=mid, LastName=name, ResultCode=7)
                for mid, name in MEMBERS.items()]))
        put('data/direction_arrow_2026-10-07.json', {'rows': [{'bill': 1, 'quorum': {'kind': 'majority', 'value': 1}}]})
        for name in ('claude_tiebreak_signs', 'axis_second_reading'):
            put(f'criteria/{name}_2026-10-19.json', {'signs': {}})
        for th in THEMES[1:]:
            put(f'criteria/theme_signs_{th}.json', {'signs': {'1': 1}})
        full_signs = {'signs': {th: {'1': -1, '2': 1} for th in THEMES}}
        put('criteria/full_signs_K25.json', full_signs)
        put('criteria/economy_second_reading_2026-10-20.json', {'removed': []})
        put('criteria/declared_before_arrow_2026-10-07.yaml', 'cleaning:\n  drop_lopsided_below: 0.025\nfaction_position:\n  split_below: 0.5\n')
        put('docs/reference/for_option_sign_test.json', {'options': {'yes': {'sign': 'carries'}}})
        actual = {'bins': [['2023-01-01', '2023-07-01'], ['2023-07-01', '2024-01-01']],
                  'series': {f: {th: deepcopy(cells) for th in THEMES} for f, cells in
                             [('1', [[1, 0], [1, 0]]), ('2', [[0, 1], [0, 1]]), ('yashar', [[1, 0], [1, 0]])]}}
        put('data/dynamics_25.json', actual)
        def run(label, wanted):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--root', str(root)],
                                    capture_output=True, text=True)
            if result.returncode != wanted or (wanted and 'FAIL' not in result.stdout + result.stderr):
                raise AssertionError(label + '\n' + result.stdout + result.stderr)
            print(f'PASS selftest {label}: CLI exit {result.returncode}')
        run('baseline (duplicate law counted once per half)', 0)
        put('criteria/economy_second_reading_2026-10-20.json', {'removed': [2]})
        run('removed economy sign surviving full-sign merge', 1)
        economy_filtered = deepcopy(actual)
        for series in economy_filtered['series'].values():
            series['economy'][1] = [0, 0]
        put('data/dynamics_25.json', economy_filtered)
        run('removed economy sign zeroed after full-sign merge', 0)
        put('criteria/economy_second_reading_2026-10-20.json', {'removed': []})
        put('data/dynamics_25.json', actual)
        put('criteria/axis_second_reading_2026-10-19.json', {'signs': {'2': -1}})
        run('new axis sign conflicting with full text cannot survive', 1)
        filtered = deepcopy(actual)
        for series in filtered['series'].values():
            series['rule_of_law'][1] = [0, 0]
        put('data/dynamics_25.json', filtered)
        run('second reading after full signs removes conflict', 0)
        put('data/dynamics_25.json', actual)
        for value in (None, 1):
            put('criteria/axis_second_reading_2026-10-19.json', {'signs': {'2': value}})
            run(f'second reading {value} preserves new sign', 0)
        put('criteria/axis_second_reading_2026-10-19.json', {'signs': {}})
        changed_signs = deepcopy(full_signs)
        changed_signs['signs']['economy']['2'] = -1
        put('criteria/full_signs_K25.json', changed_signs)
        run('new full-export sign flipped', 1)
        put('criteria/full_signs_K25.json', full_signs)
        put('criteria/theme_signs_economy.json', {'signs': {'1': 1, '2': 0}})
        zero = deepcopy(actual)
        for series in zero['series'].values():
            series['economy'][1] = [0, 0]
        put('data/dynamics_25.json', zero)
        run('legacy zero outranks new full-export sign', 0)
        put('data/dynamics_25.json', actual)
        put('criteria/theme_signs_economy.json', {'signs': {'1': 1}})
        put('criteria/theme_signs_economy.json', {'signs': {'1': -1}})
        run('law sign flipped', 1)
        put('criteria/theme_signs_economy.json', {'signs': {'1': 1}})
        moved = deepcopy(votes)
        moved['rows'][2]['date'] = '2023-06-30'
        put('data/votes_25.json', moved)
        run('site export diverges from full export', 1)
        put('data/votes_full_25.json', moved)
        run('date crossed half-year boundary', 1)
        put('data/votes_25.json', votes)
        put('data/votes_full_25.json', votes)
        broken = deepcopy(actual)
        broken['series']['1']['security'][0][0] += 1
        put('data/dynamics_25.json', broken)
        run('output count changed', 1)
        put('data/dynamics_25.json', actual)
        # Mixed readings cancel within a half; never cancel across halves.
        mixed = deepcopy(votes)
        mixed['rows'][1]['by_faction']['1|a'] = {'against': 2}
        mixed['rows'][1]['by_faction']['2|b'] = {'for': 2}
        put('data/votes_25.json', mixed)
        put('data/votes_full_25.json', mixed)
        mixed_output = deepcopy(actual)
        for fid in ('1', '2'):
            for th in THEMES:
                mixed_output['series'][fid][th][0] = [0, 0]
        put('data/dynamics_25.json', mixed_output)
        run('conflicting readings cancel only within bin', 0)
        del mixed_output['series']['1']
        put('data/dynamics_25.json', mixed_output)
        run('missing series', 1)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    try:
        return selftest() if args.selftest else check(args.root)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AssertionError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
