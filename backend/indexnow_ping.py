"""Notifica istantanea dei nuovi URL a IndexNow (Bing, Yandex, Seznam, Naver...).

IndexNow spinge gli URL ai motori invece di aspettare la scoperta: utile per
velocizzare l'indicizzazione su Bing (che alimenta anche ChatGPT Search e
Copilot: leva GEO oltre che SEO). Google non partecipa a IndexNow, per Google
restano sitemap + richieste manuali in Search Console.

Uso:
  python3 indexnow_ping.py [YYYY-MM-DD]

Senza data usa oggi. Invia: gli articoli di quella data + le pagine che
cambiano di conseguenza (home, /oggi, hub classifiche). Idempotente e
innocuo se rieseguito (reinviare lo stesso URL non penalizza).
"""
import sys
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import requests

HOST = 'analisitennis.it'
SITE = f'https://{HOST}'
KEY = '880da7f29e93a4c3f04e40585fc57242'
KEY_LOCATION = f'{SITE}/{KEY}.txt'
ENDPOINT = 'https://api.indexnow.org/indexnow'

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'


def _slug_from_file(p: Path) -> str:
    # Lo slug URL dell'articolo = nome file senza estensione.
    return p.stem


def raccogli_url(giorno: str):
    urls = set()
    # Articoli del giorno
    for p in sorted(ARTICOLI.glob(f'{giorno}-*.md')):
        urls.add(f'{SITE}/articoli/{_slug_from_file(p)}')
    # Pagine che cambiano quando esce la nuova giornata
    urls.add(f'{SITE}/')
    urls.add(f'{SITE}/oggi')
    return sorted(urls)


def ping(urls):
    if not urls:
        print('[indexnow] nessun URL da inviare')
        return 0
    payload = {
        'host': HOST,
        'key': KEY,
        'keyLocation': KEY_LOCATION,
        'urlList': urls,
    }
    try:
        r = requests.post(ENDPOINT, json=payload, timeout=30,
                          headers={'Content-Type': 'application/json; charset=utf-8'})
        print(f'[indexnow] inviati {len(urls)} URL -> HTTP {r.status_code}')
        # 200 e 202 = accettato. 403 = chiave non valida/non trovata.
        if r.status_code not in (200, 202):
            print(f'[indexnow] risposta: {r.text[:300]}')
        return 0 if r.status_code in (200, 202) else 1
    except Exception as e:
        print(f'[indexnow] errore invio: {e}')
        return 1


if __name__ == '__main__':
    giorno = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    urls = raccogli_url(giorno)
    print(f'[indexnow] giorno {giorno}: {len(urls)} URL')
    for u in urls:
        print('  ', u)
    sys.exit(ping(urls))
