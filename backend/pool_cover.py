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


def pick_from_pool(slug_hint: str = '', exclude=None) -> dict | None:
    """Sceglie una foto d'azione dal pool locale.

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

    idx = int(hashlib.md5((slug_hint or 'x').encode()).hexdigest(), 16) % len(candidati)
    scelta = candidati[idx]
    return {
        'pool_src': str(ROOT / 'public' / scelta['file'].lstrip('/')),
        'title': scelta['title'],
        'credit': scelta.get('credit', ''),
    }
