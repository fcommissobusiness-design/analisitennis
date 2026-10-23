"""Seleziona i match della giornata da coprire.

Regole (24/10/2026):
- Main tour (Slam / Masters / ATP 500/250 / WTA 1000/500/250): TUTTI i match
  della giornata, uomini e donne.
- Challenger tour (ATP Challenger + WTA 125): MASSIMO 5 match totali, scelti
  per priorita' (round + nome torneo).
- Esclusioni comuni: doppi, qualifications-only match live/finiti, orari fuori
  banda 08:00-23:00 ora italiana (API Tennis gia' usa orario italiano).
- Cap di sicurezza: se il count main tour supera 50 (es. doppio Slam attivo),
  warning in log ma procede comunque.
"""
import json
import os
import sys
from pathlib import Path


PRIORITA_ROUND = {
    'Final': 100, 'Semi-finals': 85, 'Semi-final': 85,
    'Quarter-finals': 70, 'Quarter-final': 70,
    '1/8-finals': 55, '1/16-finals': 40, '1/32-finals': 28, '1/64-finals': 20, '1/128-finals': 15
}

PRIORITA_TORNEO_CH = {
    # ordine indicativo per Challenger: piu' prestigiosi in cima
    'ATP Challenger Men Singles': 50,
    'Challenger Men Singles': 50,
    'WTA 125': 45,
    'WTA125': 45,
    'ITF': 10,
}


def classifica_tier(match):
    """Ritorna il tier del torneo: SLAM | MASTERS | ATP | WTA | CHALLENGER | WTA125 | ITF | OTHER."""
    tipo = (match.get('event_type_type') or '').strip().lower()
    nome = (match.get('tournament_name') or '').strip().lower()

    if 'grand slam' in tipo:
        return 'SLAM'
    if 'masters' in tipo:
        return 'MASTERS'
    # Challenger: catch before ATP generic
    if 'challenger' in tipo or 'challenger' in nome:
        return 'CHALLENGER'
    # WTA 125 e' tier Challenger lato femminile
    if 'wta' in tipo and ('125' in tipo or '125' in nome):
        return 'WTA125'
    if tipo.startswith('atp') or 'atp' in tipo:
        return 'ATP'
    if tipo.startswith('wta') or 'wta' in tipo:
        return 'WTA'
    if 'itf' in tipo:
        return 'ITF'
    if 'davis cup' in tipo or 'billie jean king' in tipo:
        return 'MAIN_TEAM'
    return 'OTHER'


TIER_MAIN_TOUR = {'SLAM', 'MASTERS', 'ATP', 'WTA', 'MAIN_TEAM'}
TIER_CHALLENGER = {'CHALLENGER', 'WTA125'}


def peso_round(m):
    r = (m.get('tournament_round') or '')
    for k, v in PRIORITA_ROUND.items():
        if k.lower() in r.lower():
            return v
    if 'qualif' in r.lower() or 'quali' in r.lower():
        return 5
    return 25


def peso_torneo_ch(m):
    tipo = (m.get('event_type_type') or '').strip()
    for k, v in PRIORITA_TORNEO_CH.items():
        if k.lower() in tipo.lower():
            return v
    return 20


def orario_italiano_ok(m):
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
    s = (m.get('event_status') or '').lower()
    if 'finished' in s or 'live' in s or m.get('event_live') == '1':
        return False
    return True


def is_singolo(m):
    p1 = m.get('event_first_player', '') or ''
    p2 = m.get('event_second_player', '') or ''
    return '/' not in p1 and '/' not in p2


def seleziona(matches, max_challenger=5, cap_main=50):
    base = [m for m in matches if is_singolo(m) and not_yet_started(m) and orario_italiano_ok(m)]

    main_tour = []
    challenger = []
    for m in base:
        tier = classifica_tier(m)
        if tier in TIER_MAIN_TOUR:
            m['_tier'] = tier
            m['_round_score'] = peso_round(m)
            main_tour.append(m)
        elif tier in TIER_CHALLENGER:
            m['_tier'] = tier
            m['_round_score'] = peso_round(m)
            m['_ch_torneo_score'] = peso_torneo_ch(m)
            challenger.append(m)
        # altri tier (ITF, OTHER): ignorati

    # Main tour: TUTTI. Ordinati per round desc (prima i turni avanzati),
    # poi per orario asc (quelli piu' presto in cima all'elenco).
    main_tour.sort(key=lambda m: (-m['_round_score'], m.get('event_time') or '99:99'))

    if len(main_tour) > cap_main:
        print(f'  WARNING: main tour ha {len(main_tour)} match > cap {cap_main}, procedo comunque', file=sys.stderr)

    # Challenger: top-5 per (torneo+round) score, poi orario
    challenger.sort(key=lambda m: (-(m['_ch_torneo_score'] + m['_round_score']), m.get('event_time') or '99:99'))
    challenger = challenger[:max_challenger]

    # Rimuovi i marker interni prima di salvare
    def pulisci(m):
        for k in ('_tier', '_round_score', '_ch_torneo_score'):
            m.pop(k, None)
        return m

    out = [pulisci(m) for m in main_tour] + [pulisci(m) for m in challenger]
    return out, len(main_tour), len(challenger)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: python select_matches.py fixtures_YYYY-MM-DD.json', file=sys.stderr)
        sys.exit(1)
    fx_file = sys.argv[1]
    matches = json.loads(Path(fx_file).read_text())
    picks, n_main, n_ch = seleziona(matches)
    print(f'Selezionati {len(picks)} match: {n_main} main tour (ATP/WTA/Slam/Masters) + {n_ch} Challenger')
    for p in picks:
        tipo = (p.get('event_type_type') or '').strip()[:35]
        print(f"  [{tipo:35s}] {p.get('event_time')} - {p.get('event_first_player')} vs {p.get('event_second_player')} - {p.get('tournament_name')} ({p.get('tournament_round')})")
    out = Path(fx_file).parent / f'selected_{Path(fx_file).stem.split("_")[-1]}.json'
    out.write_text(json.dumps(picks, indent=2, ensure_ascii=False))
    print(f'Salvati in {out}')
