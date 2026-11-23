#!/usr/bin/env python3
"""Selettore del POOL LOCALE di foto d'azione tennis (vedi build_cover_pool.py).

Usato da write_article.py come fallback PRIMA del venue Commons: per i match
senza foto giocatore disponibile, pesca una foto d'azione locale (giocatore
in campo) invece di uno stadio vuoto ripetuto.

Si integra col dedup globale esistente: l'argomento `exclude` contiene i
'File:'/title gia' usati come cover in altri articoli, e qui vengono evitati.
La scelta varia in modo deterministico per slug, cosi' articoli diversi
prendono foto diverse anche a parita' di exclude.

pick_from_pool() restituisce None se il pool non esiste o e' tutto escluso,
lasciando il controllo al fallback venue.
"""
from __future__ import annotations
import json, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'public/covers/pool/manifest.json'


def _load_manifest() -> list[dict]:
    try:
        return json.loads(MANIFEST.read_text(encoding='utf-8'))
    except Exception:
        return []


# --- Genere delle foto del pool (per non mettere una foto WTA su un match
# maschile e viceversa) -------------------------------------------------------
# Le foto del pool portano il genere nel titolo del file ("...ATP...", "...WTA...",
# "Female...") o nel nome di un giocatore identificabile. Quelle senza segnale
# chiaro (campo/azione anonima) restano NEUTRE e valgono per entrambi i generi.
_TITLE_WOMEN = ('wta', 'female', ' women', 'bouzkov', 'tatjana maria',
                'wickmayer', 'yanina')
_TITLE_MEN = ('atp', 'berdych', 'cilic', 'amir rezaiennehzad')


def _photo_gender(title: str) -> str:
    """'W', 'M' o '' (neutro) dal titolo del file del pool."""
    t = (title or '').lower()
    if any(h in t for h in _TITLE_WOMEN):
        return 'W'
    if any(h in t for h in _TITLE_MEN):
        return 'M'
    return ''


def gender_from_categoria(cat: str) -> str:
    """Genere atteso del match dalla categoria dell'articolo.

    ATP e Challenger sono circuiti maschili; WTA (qui include anche gli ITF
    femminili W15/W50) e' femminile. Slam (misto), ITF generico e sconosciuto
    -> '' = nessun filtro (comportamento storico, nessun rischio di regressione).
    """
    c = (cat or '').strip().upper()
    if c in ('ATP', 'CHALLENGER'):
        return 'M'
    if c == 'WTA':
        return 'W'
    return ''


def pick_from_pool(slug_hint: str = '', exclude=None, gender: str = '') -> dict | None:
    """Sceglie una foto d'azione dal pool locale.

    `gender` ('M'/'W'/'') filtra via le foto del genere opposto: su un match
    maschile non finisce una foto d'azione femminile riconoscibile e viceversa.
    Le foto neutre restano sempre candidabili. Se il filtro svuota i candidati
    si ricade senza filtro (meglio una foto che niente).

    Ritorna un dict compatibile con write_article:
      {'pool_src': '<path assoluto locale>', 'title': ..., 'credit': ...}
    oppure None se il pool e' vuoto o tutte le foto sono gia' in `exclude`.
    """
    excl = set(exclude or ())
    pool = _load_manifest()
    if not pool:
        return None

    # Candidati non ancora usati altrove (dedup globale per title).
    liberi = [p for p in pool if p.get('title') not in excl]
    # Se tutte usate (pool piu' piccolo del numero di articoli), ricadi
    # sull'intero pool: meglio una ripetizione d'azione variata per slug
    # che uno stadio vuoto. La variazione per slug riduce le collisioni.
    candidati = liberi or pool
    if not candidati:
        return None

    # Verifica che il file esista davvero su disco.
    candidati = [p for p in candidati
                 if (ROOT / 'public' / p['file'].lstrip('/')).exists()]
    if not candidati:
        return None

    # Filtro di genere: tieni neutre + stesso genere. Se svuota, non filtrare.
    if gender in ('M', 'W'):
        coerenti = [p for p in candidati
                    if _photo_gender(p.get('title', '')) in ('', gender)]
        if coerenti:
            candidati = coerenti

    idx = int(hashlib.md5((slug_hint or 'x').encode()).hexdigest(), 16) % len(candidati)
    scelta = candidati[idx]
    return {
        'pool_src': str(ROOT / 'public' / scelta['file'].lstrip('/')),
        'title': scelta['title'],
        'credit': scelta.get('credit', ''),
    }
