#!/usr/bin/env python3
"""Independent read-only v88 oracle. Contract/disposability: reviews/REPORT_v88.md.

Only theme_arrows.theme_arrows is reused as a calculator; fetch_votes.WINDOWS
is the declared calendar. No trajectory/slice generator imports. §20–24:
--selftest must reject in-memory forgeries; absent inputs fail closed.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys

THEMES = ('rule_of_law', 'economy', 'religion_state', 'security')
END = '2026-09-01'
PERSONAL_ROLE_FACTION = 1110  # trajectory criteria rules.personal (v88).


def periods(text):
    """Read the generated periods YAML subset, requiring every record's fields."""
    out = []
    for block in re.split(r'^  - id:', text, flags=re.M)[1:]:
        row = {}
        for key in ('faction_id', 'government', 'start', 'finish'):
            found = re.findall(r'^    ' + key + r': (\S+)\s*$', block, re.M)
            if len(found) != 1:
                raise ValueError(f'period missing/duplicate {key}')
            row[key] = int(found[0]) if key in ('faction_id', 'government') else found[0]
        date.fromisoformat(row['start'])
        date.fromisoformat(END if row['finish'] == 'null' else row['finish'])
        out.append(row)
    if not out:
        raise ValueError('empty periods')
    return out


def transition(window, records):
    start, end = (s[:10] for s in window)
    valid = [r for r in records if r['start'] < (END if r['finish'] == 'null' else r['finish'])]
    old = {r['government'] for r in valid if r['start'] <= start < (END if r['finish'] == 'null' else r['finish'])}
    new = [r['start'] for r in valid if r['government'] not in old and start < r['start'] < end]
    return [start, min(new, default=end)]


def spans_for(k, fid, records, factions, lineage, window):
    spans = []
    for r in records:
        if r['faction_id'] != fid:
            continue
        a, b = r['start'], END if r['finish'] == 'null' else r['finish']
        if k < 25:
            life = factions[fid]
            a = max(a, life['StartDate'][:10])
            b = min(b, (life.get('FinishDate') or life['StartDate'])[:10])
        if a < b:
            spans.append((a, b))
    override = lineage.get('gov_override', {}).get(str(k), {}).get(str(fid))
    if override is not None:
        spans = [tuple(s) for s in override]
    if fid in lineage.get('coalition_without_ministers', {}).get(str(k), []):
        spans = [(window[0][:10], window[1][:10])]
    return spans


def segments(window, trans, spans):
    """Partition calendar, then coalesce adjacent equal roles (even without votes)."""
    start, end = (s[:10] for s in window)
    cuts = sorted({start, end, trans[1]} | {d for span in spans for d in span if start < d < end})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        role = 'trans' if a < trans[1] else 'gov' if any(x <= a < y for x, y in spans) else 'opp'
        if out and out[-1][2] == role:
            out[-1] = (out[-1][0], b, role)
        else:
            out.append((a, b, role))
    return out


def verdict(points, theme):
    obs = [(p['role'], p['themes'].get(theme, {}).get('arrow')) for p in points if p['role'] != 'trans']
    clear = [(r, a) for r, a in obs if a in ('up', 'down')]
    by_role = {r: {a for rr, a in clear if rr == r} for r in ('gov', 'opp')}
    directions = {a for _, a in clear}
    label = 'shifts'
    if len(clear) < 2:
        label = 'few'
    elif len(directions) == 1:
        if all(by_role.values()):
            label = 'steady'
        else:
            only = next(r for r in by_role if by_role[r])
            mixed_elsewhere = any(r != only and a == 'both' for r, a in obs)
            label = ('holds_' if mixed_elsewhere else 'one_role_') + only
    elif all(len(v) == 1 for v in by_role.values()):
        label = 'by_role'
    return {'label': label, 'clear': len(clear)}


def personal(rows, load, data):
    converted = []
    people = {30836: 'איזנקוט', 30683: 'טרופר'}
    observed = set()
    for row in rows:
        cached = load(data / 'named_votes_cache' / f"{row['vote_id']}.json")
        named = cached['rows']
        if (cached['vote_id'] != row['vote_id'] or len(named) != row['named_total']
                or any(r['VoteID'] != row['vote_id'] for r in named)
                or len({r['MkId'] for r in named}) != len(named)):
            raise ValueError(f"incomplete named cache {row['vote_id']}")
        positions = []
        for mid, surname in people.items():
            found = next((r for r in named if r['MkId'] == mid), None)
            if found is None:
                positions.append('absent')
                continue
            if found['LastName'] != surname or found['ResultCode'] not in (6, 7, 8, 9, 10):
                raise ValueError(f'personal identity/code mismatch {mid}')
            pos = {6: 'absent', 7: 'for', 8: 'against', 9: 'abstain', 10: 'absent'}[found['ResultCode']]
            positions.append(pos)
            if pos != 'absent':
                observed.add(mid)
        counts = Counter(positions)
        chamber = {key: sum(c.get(key, 0) for c in row['by_faction'].values()) for key in ('for', 'against')}
        converted.append(dict(row, by_faction={'yashar|ישר!': {p: n for p, n in counts.items() if n == 2}}, chamber_counts=chamber))
    if observed != set(people):
        raise ValueError('personal identity has no observed votes')
    return converted


def differences(expected, actual, path='$'):
    out = []
    if type(expected) is not type(actual):
        return [(path, expected, actual)]
    if isinstance(expected, dict):
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                out.append((path + '/' + key, expected.get(key, '<missing>'), actual.get(key, '<missing>')))
            else:
                out.extend(differences(expected[key], actual[key], path + '/' + key))
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            out.append((path + '/length', len(expected), len(actual)))
        for i, (a, b) in enumerate(zip(expected, actual)):
            out.extend(differences(a, b, f'{path}[{i}]'))
    elif expected != actual:
        out.append((path, expected, actual))
    return out


def lineage_checks(tracks, lineage, factions):
    errors = []
    for ballot, lines in tracks.items():
        assigned = defaultdict(set)
        for track in lines:
            for k, fids in track['links'].items():
                for fid in fids:
                    loc = f'tracks/{ballot}/{track["name"]}/{k}/{fid}'
                    if fid == 'yashar':
                        if ballot != 'דרך' or k != '25':
                            errors.append((loc, 'personal דרך K25', 'invalid'))
                        continue
                    if fid not in factions or factions[fid]['KnessetNum'] != int(k):
                        errors.append((loc, f'KNS_Faction K{k}', factions.get(fid)))
                    if int(k) < 25 and fid not in {l[0] for l in lineage['lines'][ballot].get(k, [])}:
                        errors.append((loc, 'same ballot in slice_lineage', 'absent'))
                    assigned[k].add(fid)
        for k, links in lineage['lines'][ballot].items():
            for fid, *_ in links:
                if fid not in assigned[k]:
                    errors.append((f'tracks/{ballot}/{k}', fid, 'missing predecessor'))
    # Literal name checks independent of positional ID assignments in criteria.
    stems = {'Дегель ха-Тора': 'דגל התורה', 'Агудат Исраэль': 'אגודת ישראל'}
    for lines in tracks.values():
        for track in lines:
            stem = stems.get(track['name'])
            if stem:
                for k, fids in track['links'].items():
                    for fid in fids:
                        name = factions.get(fid, {}).get('Name', '')
                        if stem not in name and not name.startswith('יהדות התורה'):
                            errors.append((f'name/{track["name"]}/{k}/{fid}', stem + ' or joint יהדות התורה', name))
    return errors


def check(root, data):
    hashes = {}
    def read(path):
        raw = path.read_bytes()
        hashes[path] = hashlib.sha256(raw).hexdigest()
        return raw.decode('utf-8')
    def load(path):
        return json.loads(read(path))
    sys.path.insert(0, str(root / 'scripts'))
    from fetch_votes import WINDOWS
    from theme_arrows import theme_arrows
    # Fingerprint the permitted calculator and its local rule/config dependencies.
    for name in ('crosscheck_trajectory.py', 'fetch_votes.py', 'theme_arrows.py',
                 'direction_confidence.py', 'build_line_cards.py', 'classify_direction.py'):
        read(root / 'scripts' / name)
    for pattern in ('criteria/declared_before_arrow_*.yaml',
                    'docs/reference/for_option_sign_*.json',
                    'docs/reference/vote_names_ru_*.json'):
        paths = sorted(root.glob(pattern))
        if not paths:
            raise ValueError('missing calculator input: ' + pattern)
        read(paths[-1])
    rules = load(root / 'criteria/trajectory_2026-10-20.json')
    lineage = load(root / 'criteria/slice_lineage_2026-10-19.json')
    factions = {r['Id']: r for r in load(data / 'KNS_Faction.json')}
    factions.update({r['Id']: r for r in load(data / 'kns_faction_20_24.json')})
    records, transitions, votes, signs = {}, {}, {}, {}
    for k in range(20, 26):
        records[k] = periods(read(root / 'criteria/periods.yaml' if k == 25 else data / f'periods_{k}.yaml'))
        transitions[str(k)] = transition(WINDOWS[k], records[k])
        dump = load(data / f'votes_{k}.json')
        votes[k] = dump['rows']
        if len(votes[k]) != dump['matched_votes']:
            raise ValueError(f'K{k}: matched_votes/rows mismatch')
        if any(not WINDOWS[k][0][:10] <= r['date'][:10] < WINDOWS[k][1][:10] for r in votes[k]):
            raise ValueError(f'K{k}: vote outside window')
        if k < 25:
            raw = load(root / f'criteria/slice_signs_K{k}.json')['signs']
        else:
            axis = load(data / 'direction_arrow_2026-10-07.json')
            sg = {str(r['bill']): r['quorum']['value'] for r in axis['rows']
                  if r.get('quorum', {}).get('value') is not None and r['quorum'].get('kind') != 'no_quorum'}
            for bid, val in load(root / 'criteria/claude_tiebreak_signs_2026-10-19.json')['signs'].items():
                sg.setdefault(bid, val)
            for bid, val in load(root / 'criteria/axis_second_reading_2026-10-19.json')['signs'].items():
                if bid in sg and val is not None and val != sg[bid]:
                    sg[bid] = 0
            raw = {th: load(root / f'criteria/theme_signs_{th}.json')['signs'] for th in THEMES if th != 'rule_of_law'}
            raw['rule_of_law'] = sg
        signs[k] = {}
        for th in THEMES:
            signs[k][th] = {int(b): s['sign'] if isinstance(s, dict) else s for b, s in raw[th].items()}
            if any(type(s) is not int or s not in (-1, 0, 1) for s in signs[k][th].values()):
                raise ValueError(f'invalid signs K{k}/{th}')
    person = personal(votes[25], load, data)
    expected = {'rules_version': rules['version'], 'transition': transitions, 'lines': {}}
    for ballot, tracks in rules['tracks'].items():
        result = []
        for track in tracks:
            points = []
            for kn, fids in track['links'].items():
                k = int(kn)
                for fid in fids:
                    source = person if fid == 'yashar' else votes[k]
                    matching = [r for r in source if any(key.split('|')[0] == str(fid) for key in r['by_faction'])]
                    spans = spans_for(k, PERSONAL_ROLE_FACTION if fid == 'yashar' else fid, records[k], factions, lineage, WINDOWS[k])
                    for a, b, role in segments(WINDOWS[k], transitions[kn], spans):
                        selected = [r for r in matching if a <= r['date'][:10] < b]
                        if not selected:
                            continue
                        themes = {}
                        for th in THEMES:
                            if not signs[k][th]:
                                continue
                            value = theme_arrows(th, {'rows': selected}, signs=signs[k][th]).get(fid, {})
                            themes[th] = {key: value.get(key) for key in ('arrow', 'up', 'down')}
                        days = [r['date'][:10] for r in selected]
                        points.append(dict(k=kn, fid=str(fid), role=role, **{'from': min(days), 'to': max(days)}, votes=len(selected), themes=themes))
            points.sort(key=lambda p: (p['k'], p['from'], p['fid']))
            result.append(dict(name=track['name'], points=points, verdict={th: verdict(points, th) for th in THEMES}))
        expected['lines'][ballot] = result
    actual = load(data / 'trajectory.json')
    errors = differences(expected, actual) + lineage_checks(rules['tracks'], lineage, factions)
    for path, digest in hashes.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append((str(path), digest, 'input changed during check'))
    count = sum(len(t['points']) for ts in expected['lines'].values() for t in ts)
    print(f'CHECKED {sum(map(len, expected["lines"].values()))} tracks; {count} points; {len(hashes)} input files; mismatches={len(errors)}')
    for path, a, b in errors:
        print('FAIL', path, 'expected=', json.dumps(a, ensure_ascii=False), 'actual=', json.dumps(b, ensure_ascii=False))
    print('INPUT trajectory sha256=' + hashes[data / 'trajectory.json'])
    return errors, expected, hashes


def selftest():
    def point(role, arrow):
        return dict(k='20', fid='1', role=role, **{'from': '2016-01-01', 'to': '2016-02-01'}, votes=3,
                    themes={'economy': dict(arrow=arrow, up=3, down=0)})
    cases = [([], 'few'), ([('gov','up')], 'few'), ([('gov','up'),('opp','up')], 'steady'),
             ([('gov','up'),('opp','down')], 'by_role'), ([('gov','up'),('gov','up'),('opp','both')], 'holds_gov'),
             ([('opp','up'),('opp','up'),('gov','both')], 'holds_opp'),
             ([('gov','up'),('gov','up')], 'one_role_gov'), ([('opp','down'),('opp','down')], 'one_role_opp'),
             ([('gov','up'),('gov','down'),('opp','down')], 'shifts')]
    for args, label in cases:
        ps = [point(*a) for a in args]
        assert verdict(ps + [point('trans','down')], 'economy') == {'label': label, 'clear': sum(a in ('up','down') for _,a in args)}
    window = ('2015-01-01', '2020-01-01')
    rec = [dict(government=33,start='2015-01-01',finish='2015-05-14'),dict(government=34,start='2015-05-14',finish='2020-01-01')]
    assert transition(window, rec) == ['2015-01-01','2015-05-14']
    assert transition(window, rec[:1]) == list(window)
    seg = segments(window, ['2015-01-01','2015-05-14'], [('2016-05-30','2018-11-18')])
    assert [s[2] for s in seg] == ['trans','opp','gov','opp']
    assert next(r for a,b,r in seg if a <= '2016-05-30' < b) == 'gov'
    assert next(r for a,b,r in seg if a <= '2018-11-18' < b) == 'opp'
    # Equal roles on either side of a government interval remain separate even
    # when the intervening interval contains no sampled votes.
    assert len([s for s in seg if s[2] == 'opp']) == 2
    life = {1: {'StartDate':'2016-01-01', 'FinishDate':'2017-01-01'}}
    records = [dict(faction_id=1,start='2015-01-01',finish='2018-01-01')]
    assert spans_for(20,1,records,life,{},window) == [('2016-01-01','2017-01-01')]
    assert spans_for(20,1,records,life,{'gov_override':{'20':{'1':[['2016-05-01','2016-06-01']]}}},window) == [('2016-05-01','2016-06-01')]
    assert spans_for(20,1,[],life,{'coalition_without_ministers':{'20':[1]}},window) == [window]
    # The historical 1098 interval is open; personal votes must instead leave
    # government at the end of 1110's interval, per rules.personal.
    personal_records = [
        dict(faction_id=1098, start='2023-10-12', finish='null'),
        dict(faction_id=1110, start='2023-10-12', finish='2024-06-13')]
    personal_window = ('2022-11-15', END)
    personal_segments = segments(personal_window, ['2022-11-15', '2022-12-29'],
                                spans_for(25, PERSONAL_ROLE_FACTION, personal_records, {}, {}, personal_window))
    assert personal_segments == [
        ('2022-11-15', '2022-12-29', 'trans'),
        ('2022-12-29', '2023-10-12', 'opp'),
        ('2023-10-12', '2024-06-13', 'gov'),
        ('2024-06-13', END, 'opp')]
    baseline = {'transition': ['2015-01-01','2015-05-14'], 'points': [point('gov','up')], 'verdict': {'label':'few','clear':1}}
    assert not differences(baseline, copy.deepcopy(baseline))
    mutants = []
    for key, value in [('k','25'),('fid','2'),('role','opp'),('from','2016-01-02'),('to','2016-02-02'),('votes',4)]:
        bad = copy.deepcopy(baseline); bad['points'][0][key] = value; mutants.append((key,bad))
    for key, value in [('arrow','down'),('up',4),('down',1)]:
        bad = copy.deepcopy(baseline); bad['points'][0]['themes']['economy'][key] = value; mutants.append((key,bad))
    for key, value in [('label','steady'),('clear',2)]:
        bad = copy.deepcopy(baseline); bad['verdict'][key] = value; mutants.append((key,bad))
    bad = copy.deepcopy(baseline); bad['points'] = []; mutants.append(('missing point',bad))
    bad = copy.deepcopy(baseline); bad['transition'][1]='2015-05-15'; mutants.append(('transition',bad))
    for name,bad in mutants:
        assert differences(baseline,bad), f'escaped forgery: {name}'
        print('REJECTED',name)
    # Lineage and name mutations go through the actual mapping checker.
    lin = {'lines': {'ג': {'20': [[1,'party']]}}}
    tracks = {'ג': [{'name':'Дегель ха-Тора','links':{'20':[1]}}]}
    fac = {1:{'Name':'דגל התורה','KnessetNum':20}}
    assert not lineage_checks(tracks,lin,fac)
    for track_name in ('Дегель ха-Тора', 'Агудат Исраэль'):
        joint_tracks = {'ג': [{'name': track_name, 'links': {'20': [1]}}]}
        assert not lineage_checks(joint_tracks, lin, {1: {'Name': 'יהדות התורה', 'KnessetNum': 20}})
        other = 'אגודת ישראל' if track_name == 'Дегель ха-Тора' else 'דגל התורה'
        assert lineage_checks(joint_tracks, lin, {1: {'Name': other, 'KnessetNum': 20}})
    for name, changed in [('swapped party', {1:{'Name':'אגודת ישראל','KnessetNum':20}}),
                          ('wrong knesset', {1:{'Name':'דגל התורה','KnessetNum':21}})]:
        assert lineage_checks(tracks,lin,changed); print('REJECTED',name)
    rows = [dict(vote_id=1,named_total=2,by_faction={'1098|Gantz':{'for':10},'2|B':{'against':10}})]
    cache = dict(vote_id=1,rows=[dict(MkId=30836,LastName='איזנקוט',VoteID=1,ResultCode=7),
                                dict(MkId=30683,LastName='טרופר',VoteID=1,ResultCode=7)])
    result = personal(rows,lambda _: cache,Path('/unused'))[0]
    assert result['by_faction'] == {'yashar|ישר!':{'for':2}}
    assert result['chamber_counts'] == {'for':10,'against':10}
    for label, field, value in [('wrong identity','LastName','wrong'),('invalid code','ResultCode',99),
                                ('wrong vote','VoteID',2)]:
        bad = copy.deepcopy(cache); bad['rows'][0][field] = value
        try:
            personal(rows,lambda _: bad,Path('/unused'))
        except ValueError:
            print('REJECTED',label)
        else:
            raise AssertionError(label)
    bad = copy.deepcopy(cache); bad['rows'][0]['ResultCode'] = 8
    assert personal(rows,lambda _: bad,Path('/unused'))[0]['by_faction'] == {'yashar|ישר!':{}}
    print(f'PASS {len(mutants)+5} in-memory forgeries; 9 verdict cases; transition/interval/personal boundaries; v88 personal role and joint-list controls')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parent.parent / 'data')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    try:
        sys.exit(selftest() if args.selftest else int(bool(check(args.root, args.data)[0])))
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        print('FAIL invalid input:', exc, file=sys.stderr)
        sys.exit(1)
