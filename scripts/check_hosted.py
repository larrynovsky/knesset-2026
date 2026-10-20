#!/usr/bin/env python3
"""§16/§21: внешняя проверка выложенного сайта — pull, а не доверие rsync.

Каждый файл site/ скачивается по HTTPS и сверяется по sha256; лишних файлов
на сервере не видно (листинга нет) — их ловит --delete при выкладке, здесь не проверяется.
Плюс: X-Robots-Tag noindex на каждом ответе, HSTS, robots.txt без Disallow,
служебные пути отдают 404. Запуск на Studio, где лежит site/ (§21).

    python3 scripts/check_hosted.py "$(cat ~/.knesset_secrets/site_url)" site
    python3 scripts/check_hosted.py --selftest
"""
import hashlib, sys, urllib.error, urllib.request
from pathlib import Path

FORBIDDEN = [".git/HEAD", "report/", "data/MANIFEST.json", "criteria/", ".env"]


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, b""


def judge(local, remote, forbidden):
    """local: {path: bytes}; remote: {path: (status, headers, body)}; forbidden: {path: status}."""
    bad = []
    if not local:
        bad.append("ноль локальных файлов — сравнивать нечего (KNS-L005)")
    for p, data in sorted(local.items()):
        st, h, body = remote.get(p, (None, {}, b""))
        if st != 200:
            bad.append(f"{p}: HTTP {st}")
            continue
        if hashlib.sha256(body).digest() != hashlib.sha256(data).digest():
            bad.append(f"{p}: содержимое на сервере отличается (устаревшая выкладка?)")
        if "noindex" not in h.get("x-robots-tag", ""):
            bad.append(f"{p}: нет X-Robots-Tag noindex")
        if "max-age" not in h.get("strict-transport-security", ""):
            bad.append(f"{p}: нет HSTS")
        if p.endswith(".html") and b"noindex" not in body:
            bad.append(f"{p}: нет meta noindex")
        if p == "robots.txt" and b"disallow" in body.lower():
            bad.append("robots.txt содержит Disallow (§16: мешает прочитать noindex)")
    if "robots.txt" not in local:
        bad.append("robots.txt отсутствует")
    for p, st in forbidden.items():
        if st != 404:
            bad.append(f"/{p}: HTTP {st}, ожидался 404")
    return bad


def selftest():
    html = b'<meta name="robots" content="noindex, nofollow">x'
    ok_h = {"x-robots-tag": "noindex, nofollow", "strict-transport-security": "max-age=86400"}
    local = {"index.html": html, "robots.txt": b"User-agent: *\nAllow: /\n"}
    good = {p: (200, ok_h, b) for p, b in local.items()}
    fb = {p: 404 for p in FORBIDDEN}
    assert judge(local, good, fb) == [], judge(local, good, fb)
    stale = dict(good, **{"index.html": (200, ok_h, html + b"old")})
    assert any("отличается" in x for x in judge(local, stale, fb))
    nohdr = dict(good, **{"index.html": (200, {"strict-transport-security": "max-age=1"}, html)})
    assert any("X-Robots-Tag" in x for x in judge(local, nohdr, fb))
    assert any(".git" in x for x in judge(local, good, dict(fb, **{".git/HEAD": 200})))
    assert judge({}, {}, fb), "пустая выборка обязана краснеть"
    print("selftest OK: устаревший файл, снятый заголовок, открытый .git, пустая выборка — красные")


def main():
    if sys.argv[1:] == ["--selftest"]:
        return selftest()
    base, root = sys.argv[1].rstrip("/"), Path(sys.argv[2])
    local = {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    remote = {p: fetch(f"{base}/{p}") for p in local}
    forbidden = {p: fetch(f"{base}/{p}")[0] for p in FORBIDDEN}
    bad = judge(local, remote, forbidden)
    for b in bad:
        print("КРАСНОЕ:", b)
    print(f"сверено файлов: {len(local)}; служебных путей: {len(forbidden)}; нарушений: {len(bad)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
