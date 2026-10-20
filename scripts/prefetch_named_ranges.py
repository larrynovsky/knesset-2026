#!/usr/bin/env python3
"""Докачка поимённых диапазонами VoteID (владелец 20.10: «качай всё»).

По одному голосованию это счётчик §23 + две страницы по 100 строк (в перекличке ~110 строк) —
~3 запроса на голосование. Диапазоном: один счётчик §23 на диапазон и ~1,1 страницы на голосование.
Сверка та же: guarded_fetch.fetch_all сравнивает число строк диапазона со счётчиком источника.
Результат раскладывается в тот же кэш data/named_votes_cache_full/<vote_id>.json, в том же формате,
что пишет fetch_votes.fetch_named_votes; голосования диапазона, которых нет в нашем списке, отбрасываются.
Голосование из списка без строк в диапазоне пишется с пустым списком строк и печатается.
Манифест (guarded_fetch._record) — под замком; не запускать одновременно с другой выгрузкой.
"""
from __future__ import annotations
import collections, json, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import guarded_fetch as G      # noqa: E402

CACHE = ROOT / "data" / "named_votes_cache_full"
_lock = threading.Lock()
_orig = G._record


def _locked(*a, **k):
    with _lock:
        _orig(*a, **k)


G._record = _locked
SELECT = "MkId,VoteID,VoteDate,ResultCode,ResultDesc,LastName,FirstName"


def ranges(ids: list[int], span: int = 40) -> list[tuple[int, int, list[int]]]:
    """Подряд идущие нужные id, диапазон не шире span номеров (чужие голосования внутри — лишний трафик)."""
    out, cur = [], []
    for v in sorted(ids):
        if cur and v - cur[0] >= span:
            out.append((cur[0], cur[-1], cur)); cur = []
        cur.append(v)
    if cur:
        out.append((cur[0], cur[-1], cur))
    return out


def one(lo: int, hi: int, want: list[int]) -> tuple[int, list[int]]:
    rows = G.fetch_all("KNS_PlenumVoteResult", flt=f"VoteID ge {lo} and VoteID le {hi}", select=SELECT)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["VoteID"]].append(r)
    at = datetime.now(timezone.utc).isoformat()
    empty = []
    for v in want:
        if not by.get(v):
            empty.append(v)
        (CACHE / f"{v}.json").write_text(json.dumps({"vote_id": v, "rows": by.get(v, []), "at": at,
                                                     "via": f"range {lo}-{hi}"}, ensure_ascii=False), encoding="utf-8")
    return len(want), empty


def main(ns: list[int], workers: int) -> int:
    CACHE.mkdir(exist_ok=True)
    ids = set()
    for n in ns:
        vb = json.loads((ROOT / "data" / f"voted_bills_{n}.json").read_text(encoding="utf-8"))
        ids |= {r["vote_id"] for r in vb["rows"] if not (CACHE / f"{r['vote_id']}.json").exists()}
    rs = ranges(sorted(ids))
    print(f"к докачке: {len(ids)} перекличек, диапазонов {len(rs)}", flush=True)
    done, fail, empties = 0, [], []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(one, lo, hi, want): (lo, hi) for lo, hi, want in rs}
        for f in as_completed(futs):
            try:
                n, e = f.result(); done += n; empties += e
            except Exception as e:      # noqa: BLE001
                fail.append((futs[f], f"{type(e).__name__}: {str(e)[:120]}"))
                print("   ошибка", fail[-1], flush=True)
            k = len(futs) - sum(1 for x in futs if not x.done())
            if k % 25 == 0:
                print(f"   диапазонов {k}/{len(rs)} · перекличек {done} · ошибок {len(fail)}", flush=True)
    print(f"готово: {done} перекличек; пустых {len(empties)}; ошибок диапазонов {len(fail)}", flush=True)
    if empties:
        print("   без строк в источнике:", empties[:20], flush=True)
    return 1 if fail else 0


if __name__ == "__main__":
    args = [int(x) for x in sys.argv[1:] if not x.startswith("-")]
    w = next((int(x.split("=")[1]) for x in sys.argv[1:] if x.startswith("--workers=")), 6)
    sys.exit(main(args, w))
