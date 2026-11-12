"""Decide se un articolo-pronostico deve andare in NOINDEX (restare pubblicato
per utenti e link interni, ma tolto dall'indice Google e dalla sitemap).

Motivo (12/11/2026): Google scansiona ma NON indicizza ~440 articoli su match
minori (ATP250/Challenger tra giocatori poco noti). Troppa roba sottile abbassa
la qualita' percepita dell'intero sito. Si mette in noindex SOLO il materiale
chiaramente poco rilevante, con criterio conservativo: nel dubbio si indicizza.

Segnale chiave mancante nella selezione (select_matches): il RANKING dei
giocatori. Un ATP500 tra due #80 non ha volume di ricerca; un ATP250 con un top
40 si'. Qui si aggancia il ranking (standings-ext, fino a #300) per cognome.

Regola -> INDEX (noindex False) se ANCHE SOLO UNO:
  - torneo marquee: Slam / Masters / WTA1000 (volume a prescindere);
  - giocatore di richiamo (STAR_SURNAMES, featured_star);
  - il migliore dei due e' entro la soglia ranking (ATP<=KEEP_ATP, WTA<=KEEP_WTA);
  - FINALE (secca) di un ATP500 / WTA500.
Altrimenti NOINDEX.
"""
from __future__ import annotations
import json, re, unicodedata
from pathlib import Path

from select_matches import classifica_tier, featured_star

DATA = Path(__file__).resolve().parent.parent / 'src' / 'data'

KEEP_ATP = 50   # miglior giocatore entro questo rank ATP -> si indicizza
KEEP_WTA = 45   # idem lato WTA
MARQUEE = {'SLAM', 'MASTERS', 'WTA1000'}


def _norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _tokens(name: str):
    n = _norm(name)
    n = re.sub(r'[^a-z\s.\-]', ' ', n)
    return [t for t in re.split(r'[\s.\-]+', n) if t]


def _surname(name: str) -> str:
    t = _tokens(name)
    return t[-1] if t else ''


def _initial(name: str) -> str:
    t = _tokens(name)
    return t[0][0] if t and t[0] else ''


_cache: dict[str, dict] = {}


def _load(circ: str) -> dict:
    if circ in _cache:
        return _cache[circ]
    lut: dict[str, list] = {}
    try:
        rows = json.loads((DATA / f'standings-{circ}-ext.json').read_text())['righe']
        for r in rows:
            sn = _surname(r['player'])
            if not sn:
                continue
            lut.setdefault(sn, []).append((_initial(r['player']), int(r['place'])))
    except Exception:
        pass
    _cache[circ] = lut
    return lut


def player_rank(name: str, circ: str) -> int:
    """Rank del giocatore (1..300) o 999 se fuori top 300 / non trovato.
    Match per cognome; a parita' di cognome preferisce l'iniziale giusta."""
    lut = _load(circ)
    cand = lut.get(_surname(name))
    if not cand:
        return 999
    ini = _initial(name)
    exact = [p for (i, p) in cand if i == ini]
    return min(exact) if exact else min(p for (_, p) in cand)


def _circuit(match) -> str:
    return 'wta' if 'wta' in (match.get('event_type_type') or '').lower() else 'atp'


def should_noindex(match) -> tuple[bool, str]:
    """(noindex, motivo). Conservativo: nel dubbio indicizza (ritorna False)."""
    tier = classifica_tier(match)
    if tier in MARQUEE:
        return False, f'marquee {tier}'
    if featured_star(match):
        return False, 'star'
    circ = _circuit(match)
    r1 = player_rank(match.get('event_first_player', ''), circ)
    r2 = player_rank(match.get('event_second_player', ''), circ)
    best = min(r1, r2)
    keep = KEEP_WTA if circ == 'wta' else KEEP_ATP
    if best <= keep:
        return False, f'top player #{best}'
    rnd = (match.get('tournament_round') or '').lower()
    if 'final' in rnd and 'semi' not in rnd and tier in ('ATP500', 'WTA500'):
        return False, f'finale {tier}'
    bl = best if best < 999 else '300+'
    return True, f'thin ({tier}, miglior rank #{bl})'
