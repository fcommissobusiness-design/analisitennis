"""Recupera il palinsesto tennis del giorno da API Tennis."""
import os
import sys
import json
import requests
from datetime import date, datetime
from pathlib import Path

K = os.environ.get('API_TENNIS_KEY')
if not K:
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith('API_TENNIS_KEY='):
                K = line.split('=', 1)[1].strip()
                break
if not K:
    print('API_TENNIS_KEY mancante. Metti la chiave in backend/.env', file=sys.stderr)
    sys.exit(1)

BASE = 'https://api.api-tennis.com/tennis/'


def fetch(method, **params):
    params.update(method=method, APIkey=K)
    r = requests.get(BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_fixtures(d=None):
    d = d or date.today().isoformat()
    data = fetch('get_fixtures', date_start=d, date_stop=d)
    out = data.get('result', [])
    return [m for m in out if '/' not in (m.get('event_first_player') or '')
            and '/' not in (m.get('event_second_player') or '')]


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    matches = fetch_fixtures(d)
    out = Path(__file__).parent / f'fixtures_{d}.json'
    out.write_text(json.dumps(matches, indent=2, ensure_ascii=False))
    print(f'Salvati {len(matches)} match in {out}')
