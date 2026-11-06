"""Scarica le classifiche ATP e WTA da API Tennis e le salva come JSON
in src/data/ per la generazione delle pagine /classifica-atp e /classifica-wta.
Lanciato dalla pipeline giornaliera (daily.sh) per tenerle aggiornate."""
import json
import sys
from datetime import datetime
from pathlib import Path

from fetch_fixtures import fetch

TOP_N = 100
OUT = Path(__file__).resolve().parent.parent / 'src' / 'data'


def _rows(event_type: str):
    data = fetch('get_standings', event_type=event_type)
    res = data.get('result', []) or []
    out = []
    for r in res:
        try:
            place = int(r.get('place'))
        except (TypeError, ValueError):
            continue
        name = (r.get('player') or '').strip()
        if not name or place < 1:
            continue
        out.append({
            'place': place,
            'player': name,
            'points': r.get('points') or '',
            'country': r.get('country') or '',
            'movement': r.get('movement') or '',
        })
    out.sort(key=lambda x: x['place'])
    return out[:TOP_N]


def _punti(r):
    try:
        return int(str(r.get('points', '')).replace('.', '').replace(',', '').replace(' ', '') or 0)
    except (TypeError, ValueError):
        return 0


def _sane(rows):
    """Controllo di sanita' sul dato classifica, per non far finire live una
    risposta API anomala (ne' propagarla ai profili). Ritorna (ok, motivo)."""
    if len(rows) < 50:
        return False, f'solo {len(rows)} righe (<50)'
    if rows[0]['place'] != 1:
        return False, f"prima posizione {rows[0]['place']} != 1"
    if any(not r.get('player') for r in rows):
        return False, 'nomi vuoti presenti'
    vals = [_punti(r) for r in rows]
    inversioni = sum(1 for i in range(len(vals) - 1) if vals[i] < vals[i + 1])
    if inversioni > 3:  # qualche pari-merito o assestamento e' tollerato
        return False, f'{inversioni} inversioni nei punti (ordine incoerente)'
    return True, 'ok'


def main():
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('Europe/Rome'))
    except Exception:
        now = datetime.now()
    OUT.mkdir(parents=True, exist_ok=True)
    for et, fname in (('ATP', 'standings-atp.json'), ('WTA', 'standings-wta.json')):
        try:
            rows = _rows(et)
        except Exception as e:
            print(f'[standings] {et} errore: {e}', file=sys.stderr)
            continue
        if not rows:
            print(f'[standings] {et}: 0 righe, salto (non sovrascrivo)', file=sys.stderr)
            continue
        ok, motivo = _sane(rows)
        if not ok:
            print(f'[standings] {et}: dato ANOMALO ({motivo}), salto per non '
                  f'sovrascrivere la classifica buona', file=sys.stderr)
            continue
        payload = {
            'circuito': et,
            'aggiornato_il': now.strftime('%Y-%m-%dT%H:%M'),
            'righe': rows,
        }
        (OUT / fname).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f'[standings] {et}: salvate {len(rows)} posizioni in {fname}')


if __name__ == '__main__':
    main()
