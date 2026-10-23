"""Seleziona i 2-3 match top della giornata da coprire.

Regole:
- Priorità torneo: Slam > Masters > ATP 500 > ATP 250 > WTA 1000 > WTA 500 > WTA 250 > Challenger > ITF
- Priorità fase: Finale > SF > QF > R16 > R32 > R64 > R128 > quali
- Boost se almeno un giocatore top-50 ATP o top-50 WTA (via standings)
- Orari filtro: prime diurne (10-18) o prime serali (18-23) ora italiana - no partite notturne USA
- Target: 3 articoli se c'è almeno un ATP 500+, 2 altrimenti
- Max 1 Challenger/giorno
"""
import json
import sys
from pathlib import Path
from datetime import datetime

PRIORITA_TORNEO = {
    'Grand Slam': 100, 'Grand Slam Men Singles': 100, 'Grand Slam Women Singles': 100,
    'ATP Masters': 85, 'Masters': 85,
    'ATP 500': 70, 'ATP500': 70, 'WTA 1000': 72, 'WTA1000': 72,
    'ATP 250': 55, 'ATP250': 55, 'WTA 500': 55, 'WTA500': 55,
    'WTA 250': 45, 'WTA250': 45,
    'Challenger': 30, 'ATP Challenger Men Singles': 30, 'Challenger Men Singles': 30,
    'ITF': 15,
    'Davis Cup': 60, 'Billie Jean King Cup': 55
}

PRIORITA_ROUND = {
    'Final': 100, 'Semi-finals': 80, 'Semi-final': 80,
    'Quarter-finals': 65, 'Quarter-final': 65,
    '1/8-finals': 50, '1/16-finals': 35, '1/32-finals': 25, '1/64-finals': 20, '1/128-finals': 15
}


def peso_torneo(m):
    tipo = (m.get('event_type_type') or '').strip()
    for k, v in PRIORITA_TORNEO.items():
        if k.lower() in tipo.lower():
            return v
    return 10


def peso_round(m):
    r = (m.get('tournament_round') or '')
    for k, v in PRIORITA_ROUND.items():
        if k.lower() in r.lower():
            return v
    if 'qualif' in r.lower() or 'quali' in r.lower():
        return 5
    return 20


def orario_italiano_ok(m):
    """Filtra orari sensati per audience italiana (08:00 - 23:30)."""
    t = (m.get('event_time') or '').strip()
    if not t:
        return True
    try:
        h, _ = t.split(':')
        h = int(h)
        return 8 <= h <= 23
    except Exception:
        return True


def not_yet_started(m):
    """Esclude match gia' live/finiti."""
    s = (m.get('event_status') or '').lower()
    if 'finished' in s or 'live' in s or m.get('event_live') == '1':
        return False
    return True


def score(m):
    return peso_torneo(m) * 2 + peso_round(m)


def seleziona(matches, max_pick=3):
    candidati = [m for m in matches if not_yet_started(m) and orario_italiano_ok(m)]
    candidati.sort(key=score, reverse=True)

    picks = []
    challenger_count = 0
    for m in candidati:
        tipo = (m.get('event_type_type') or '').lower()
        is_ch = 'challenger' in tipo or 'itf' in tipo
        if is_ch:
            if challenger_count >= 1:
                continue
            challenger_count += 1
        picks.append(m)
        if len(picks) >= max_pick:
            break

    # Se non c'e' nessun ATP500+ scendo a 2 articoli
    best = picks[0] if picks else None
    if best and peso_torneo(best) < 55 and len(picks) == 3:
        picks = picks[:2]

    return picks


if __name__ == '__main__':
    fx_file = sys.argv[1] if len(sys.argv) > 1 else None
    if not fx_file:
        print('Uso: python select_matches.py fixtures_YYYY-MM-DD.json', file=sys.stderr)
        sys.exit(1)
    matches = json.loads(Path(fx_file).read_text())
    picks = seleziona(matches)
    print(f'Selezionati {len(picks)} match:')
    for p in picks:
        print(f"  [{score(p):3d}] {p.get('event_time')} - {p.get('event_first_player')} vs {p.get('event_second_player')} - {p.get('tournament_name')} ({p.get('tournament_round')})")
    out = Path(fx_file).parent / f'selected_{Path(fx_file).stem.split("_")[-1]}.json'
    out.write_text(json.dumps(picks, indent=2, ensure_ascii=False))
    print(f'Salvati in {out}')
