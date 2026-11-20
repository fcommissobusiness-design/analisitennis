#!/usr/bin/env python3
"""Health check live post-deploy: SEO + GEO + raggiungibilita' articoli.

Usato dalla pipeline streaming (Fase A e Fase B) a chiusura dei blocchi finali.
Zero dipendenze interne al progetto: parla solo HTTP col sito live.

Cosa verifica:
  SEO
    - homepage 200
    - sitemap.xml 200 e parsabile
    - robots.txt 200 e cita la Sitemap
  GEO
    - llms.txt 200 e contiene sezioni chiave
    - catalog.json 200 (motore AI custom)
  Spot-check contenuti
    - N URL passati come --sample tornano 200 (con retry: il deploy
      Cloudflare Builds puo' metterci 1-3 min dopo il push)

Uso:
  python3 health_check.py [--sample URL1 URL2 ...] [--wait 120] [--json]

Flag:
  --wait N   attende fino a N secondi perche' il deploy arrivi (default 120)
  --sample   URL da campionare (es. articoli appena pushati)
  --json     output JSON

Exit code:
  0 PASS, 1 WARN (qualche risorsa mancante), 2 FAIL (home giu')
"""
from __future__ import annotations
import argparse, json, sys, time, re
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

SITE = 'https://analisitennis.it'
UA = 'AnalisiTennisHealthCheck/1.0 (+https://analisitennis.it)'


def _get(url: str, timeout: int = 15) -> tuple[int, str]:
    try:
        req = Request(url, headers={'User-Agent': UA})
        with urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', errors='replace')
            return (r.status, body)
    except HTTPError as e:
        return (e.code, '')
    except URLError:
        return (0, '')
    except Exception:
        return (0, '')


def _wait_for(url: str, max_wait: int) -> int:
    """Poll url ogni 15s fino a 200 o max_wait."""
    deadline = time.time() + max_wait
    delay = 5
    while time.time() < deadline:
        code, _ = _get(url, timeout=10)
        if code == 200:
            return code
        time.sleep(delay)
        delay = min(delay + 5, 20)
    return code


def check_seo() -> list[tuple[str, str]]:
    out = []
    code, _ = _get(SITE + '/')
    out.append(('PASS' if code == 200 else 'FAIL', f'homepage {code}'))

    code, body = _get(SITE + '/sitemap.xml')
    if code == 200 and '<urlset' in body:
        n = body.count('<url>')
        out.append(('PASS', f'sitemap.xml 200, {n} URL'))
    else:
        out.append(('WARN', f'sitemap.xml {code}'))

    code, body = _get(SITE + '/robots.txt')
    if code == 200 and 'Sitemap:' in body:
        out.append(('PASS', 'robots.txt 200 + Sitemap: presente'))
    elif code == 200:
        out.append(('WARN', 'robots.txt 200 ma nessun "Sitemap:"'))
    else:
        out.append(('WARN', f'robots.txt {code}'))
    return out


def check_geo() -> list[tuple[str, str]]:
    out = []
    code, body = _get(SITE + '/llms.txt')
    if code == 200:
        sezioni = sum(1 for k in ('Giocatori', 'Tornei', 'Guide', 'Record') if k in body)
        out.append(('PASS' if sezioni >= 2 else 'WARN', f'llms.txt 200, {sezioni}/4 sezioni chiave'))
    else:
        out.append(('WARN', f'llms.txt {code}'))

    code, body = _get(SITE + '/catalog.json')
    if code == 200:
        try:
            data = json.loads(body)
            n = len(data) if isinstance(data, (list, dict)) else 0
            out.append(('PASS', f'catalog.json 200, {n} elementi'))
        except Exception:
            out.append(('WARN', 'catalog.json 200 ma non parsabile'))
    else:
        out.append(('WARN', f'catalog.json {code}'))
    return out


def check_samples(urls: list[str], max_wait: int) -> list[tuple[str, str]]:
    """Attende fino a max_wait che gli URL diventino 200."""
    out = []
    if not urls:
        return out
    for url in urls:
        code = _wait_for(url, max_wait)
        if code == 200:
            out.append(('PASS', f'sample 200: {url}'))
        else:
            out.append(('WARN', f'sample {code}: {url}'))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', nargs='*', default=[], help='URL da campionare post-deploy')
    ap.add_argument('--wait', type=int, default=120, help='Secondi di attesa deploy (default 120)')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    # Attendi homepage prima di tutto (= deploy partito)
    if args.wait:
        _wait_for(SITE + '/', args.wait)

    results = []
    results += check_seo()
    results += check_geo()
    results += check_samples(args.sample, max_wait=max(60, args.wait))

    fails = sum(1 for lvl, _ in results if lvl == 'FAIL')
    warns = sum(1 for lvl, _ in results if lvl == 'WARN')
    passes = sum(1 for lvl, _ in results if lvl == 'PASS')

    if args.json:
        print(json.dumps({
            'pass': passes, 'warn': warns, 'fail': fails,
            'items': [{'level': l, 'msg': m} for l, m in results],
        }, ensure_ascii=False, indent=2))
    else:
        for lvl, msg in results:
            marker = {'PASS': '  ✓', 'WARN': '  ⚠', 'FAIL': '  ✗'}[lvl]
            print(f'{marker} [{lvl}] {msg}')
        verdict = 'FAIL' if fails else ('WARN' if warns else 'PASS')
        print(f'[health-check] verdetto={verdict} pass={passes} warn={warns} fail={fails}')

    if fails:
        return 2
    if warns:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
