#!/usr/bin/env python3
"""Параллельная докачка поимённых для fetch_votes --full (владелец 20.10: «качай всё»).

Последовательно одна перекличка — ~5,5 с (счётчик §23 + страница + пауза), ~14 тыс. перекличек —
почти сутки. Здесь — те же вызовы fetch_votes.fetch_named_votes (тот же §23 через guarded_fetch,
тот же кэш data/named_votes_cache_full), только в несколько потоков. Манифест выгрузки
(guarded_fetch._record) пишется под замком: файл общий, запись — чтение+перезапись целиком.
Запускать, когда другой выгрузки нет (замок защищает только потоки этого процесса).
"""
from __future__ import annotations
import json, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import guarded_fetch as G      # noqa: E402
import fetch_votes as F        # noqa: E402

_lock = threading.Lock()
_orig = G._record


def _locked(*a, **k):
    with _lock:
        _orig(*a, **k)


G._record = _locked


def main(ns: list[int], workers: int) -> int:
    todo = []
    for n in ns:
        F.use_knesset(n, full=True)
        vb = json.loads((ROOT / "data" / f"voted_bills_{n}.json").read_text(encoding="utf-8"))
        todo += [r["vote_id"] for r in vb["rows"] if not (F.NAMED_CACHE / f"{r['vote_id']}.json").exists()]
    todo = sorted(set(todo))
    print(f"к докачке перекличек: {len(todo)}", flush=True)
    done, fail = 0, []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(F.fetch_named_votes, v): v for v in todo}
        for f in as_completed(futs):
            try:
                f.result(); done += 1
            except Exception as e:      # noqa: BLE001 — недокачанное печатается, не прячется
                fail.append((futs[f], str(e)[:120]))
                if len(fail) <= 3 or len(fail) % 100 == 0:
                    print(f"   ошибка {futs[f]}: {type(e).__name__}: {str(e)[:160]}", flush=True)
            if (done + len(fail)) % 200 == 0:
                print(f"   {done + len(fail)}/{len(todo)} · ошибок {len(fail)}", flush=True)
    print(f"готово: {done}, ошибок: {len(fail)}", flush=True)
    for v, e in fail[:20]:
        print("   НЕ СКАЧАНО", v, e)
    return 1 if fail else 0


if __name__ == "__main__":
    args = [int(x) for x in sys.argv[1:] if not x.startswith("-")]
    w = next((int(x.split("=")[1]) for x in sys.argv[1:] if x.startswith("--workers=")), 8)
    sys.exit(main(args, w))
