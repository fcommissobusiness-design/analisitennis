"""Seleziona i match della giornata da coprire.

Regola (24/10/2026 serale): cap globale + ranking per importanza.
Si prendono i TOP-N match per score di importanza, dove N e' il cap totale
giornaliero (default 15, override via env ANALISITENNIS_MAX_ARTICOLI).

Lo score e' un combinato peso_tier + peso_round:
- SLAM finale   = 1100 (importanza massima)
- SLAM SF       = 1085
- SLAM QF       = 1070
- SLAM 1R       = 1015
- MASTERS finale= 1000
- MASTERS SF    = 985
- MASTERS 1R    = 915
- ATP500 finale = 900 / 1R = 815
- WTA1000 finale= 1000 (= Masters)
- ATP250 1R     = 715
- CH finale     = 500 / QF = 470 / 1R = 415
- WTA125 ≈ CH

Esclusioni: doppi, match live/finiti, orari fuori banda 08:00-23:00 italiana,
ITF e OTHER.
"""
import json
import os
import sys
from pathlib import Path


# Peso per tier: scala 10 (Slam) -> 2 (ITF)
PESO_TIER = {
    'SLAM': 10,
    'MASTERS': 9,
    'WTA1000': 9,         # parificato a Masters
    'ATP500': 8,
    'WTA500': 8,
    'ATP250': 7,
    'WTA250': 7,
    'MAIN_TEAM': 7,       # Davis Cup, BJK Cup
    'ATP': 7,             # fallback ATP non classificabile
    'WTA': 7,             # fallback WTA non classificabile
    'CHALLENGER': 4,
    'WTA125': 4,
    'ITF': 2,
    'OTHER': 0,
}

# Peso per fase del torneo
PESO_ROUND = {
    'Final': 100,
    'Semi-finals': 85, 'Semi-final': 85,
    'Quarter-finals': 70, 'Quarter-final': 70,
    '1/8-finals': 55,
    '1/16-finals': 40,
    '1/32-finals': 28,
    '1/64-finals': 20,
    '1/128-finals': 15,
}


def classifica_tier(match):
    """Classifica il tier esatto del torneo."""
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
    # Distinzione WTA 1000 / 500 / 250: non sempre nel tipo, provo nome
    if 'wta' in tipo:
        if '1000' in nome or '1000' in tipo: return 'WTA1000'
        if '500' in nome or '500' in tipo: return 'WTA500'
        if '250' in nome or '250' in tipo: return 'WTA250'
        return 'WTA'
    if 'atp' in tipo:
        if '500' in nome or '500' in tipo: return 'ATP500'
        if '250' in nome or '250' in tipo: return 'ATP250'
        return 'ATP'
    if 'itf' in tipo:
        return 'ITF'
    if 'davis cup' in tipo or 'billie jean king' in tipo:
        return 'MAIN_TEAM'
    return 'OTHER'


def peso_round(m):
    r = (m.get('tournament_round') or '')
    for k, v in PESO_ROUND.items():
        if k.lower() in r.lower():
            return v
    if 'qualif' in r.lower() or 'quali' in r.lower():
        return 5
    return 25


def score_importanza(m):
    """Score di importanza complessivo: peso_tier * 100 + peso_round."""
    tier = classifica_tier(m)
    t_pt = PESO_TIER.get(tier, 0)
    r_pt = peso_round(m)
    return t_pt * 100 + r_pt


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


def seleziona(matches, cap_totale=15):
    """Restituisce i top-N match per score di importanza."""
    base = [m for m in matches if is_singolo(m) and not_yet_started(m) and orario_italiano_ok(m)]
    # Escludi tier OTHER / ITF (ignorati per il blog)
    base = [m for m in base if classifica_tier(m) not in ('ITF', 'OTHER')]

    for m in base:
        m['_score'] = score_importanza(m)
        m['_tier'] = classifica_tier(m)

    # Ordina per score desc; a parita' di score, prima gli orari piu' presto
    base.sort(key=lambda m: (-m['_score'], m.get('event_time') or '99:99'))

    picks = base[:cap_totale]

    # Breakdown per log
    breakdown = {}
    for m in picks:
        tier = m['_tier']
        breakdown[tier] = breakdown.get(tier, 0) + 1

    # Pulisci marker interni
    for m in picks:
        for k in ('_tier', '_score'):
            m.pop(k, None)
    return picks, breakdown


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: python select_matches.py fixtures_YYYY-MM-DD.json', file=sys.stderr)
        sys.exit(1)
    fx_file = sys.argv[1]
    cap = int(os.environ.get('ANALISITENNIS_MAX_ARTICOLI', '15'))
    matches = json.loads(Path(fx_file).read_text())
    picks, breakdown = seleziona(matches, cap_totale=cap)
    bd_str = ', '.join(f'{k}:{v}' for k, v in sorted(breakdown.items(), key=lambda x: -x[1]))
    print(f'Cap totale: {cap}. Selezionati {len(picks)} match ({bd_str})')
    for p in picks:
        tier = classifica_tier(p)
        score = score_importanza(p)
        tipo = (p.get('event_type_type') or '').strip()[:28]
        print(f"  [score {score:4d} - {tier:10s}] {p.get('event_time')} - {p.get('event_first_player')} vs {p.get('event_second_player')} - {p.get('tournament_name')} ({p.get('tournament_round')})")
    out = Path(fx_file).parent / f'selected_{Path(fx_file).stem.split("_")[-1]}.json'
    out.write_text(json.dumps(picks, indent=2, ensure_ascii=False))
    print(f'Salvati in {out}')
