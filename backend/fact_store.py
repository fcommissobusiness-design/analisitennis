"""Magazzino dei fatti verificati di AnalisiTennis.

Perche' esiste
--------------
Il 4 novembre 2026 un lettore ha segnalato alla redazione che il profilo di
Weronika Falkowska la descriveva mancina quando e' destra. Il controllo che ne
e' seguito ha mostrato che non era un caso isolato: i profili di giocatori e
tornei erano scritti dal modello SENZA alcun ancoraggio ai dati, e il campo
`mano` era perfino chiesto come scelta binaria obbligata "destro|mancino",
quindi su centinaia di giocatori era una tirata a indovinare. In piu' il gate
di fact-check degli articoli esentava esplicitamente quella classe di dati.

Questo modulo chiude il buco: raccoglie in un posto solo gli attributi
VERIFICATI (nazionalita', mano, rovescio, data di nascita, altezza, categoria
per i giocatori; superficie, categoria, citta', paese per i tornei) leggendoli
dai contenuti pubblicati, che sono stati verificati uno per uno su fonti
ufficiali di circuito. Da qui li pescano:

  - generate_profiles.py  per non inventare piu' gli attributi
  - generate_analysis.py  per metterli nel blocco DATI AUTORITATIVI, cosi' che
                          il gate di fact-check possa finalmente controllarli
  - write_article.py      per la superficie del torneo, che prima era
                          un'euristica a parole chiave con default "cemento"

Regola di fondo: se un dato non e' qui, non e' verificato, e allora NON si
scrive. Meglio una scheda senza la mano che una scheda con la mano sbagliata.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR_GIOCATORI = ROOT / 'src' / 'content' / 'giocatori-profilo'
DIR_TORNEI = ROOT / 'src' / 'content' / 'tornei-profilo'

# Campi degli attributi tecnici: questi NON vanno mai inventati.
CAMPI_GIOCATORE = (
    'nome', 'nazionalita', 'data_nascita', 'mano', 'rovescio',
    'altezza', 'categoria', 'superficie_preferita',
)
CAMPI_TORNEO = (
    'nome', 'citta', 'paese', 'categoria', 'superficie', 'anno', 'fondato',
)

_FM = re.compile(r'^---\n(.*?)\n---', re.S)


def _campo(fm: str, chiave: str) -> str | None:
    m = re.search(rf'^{chiave}:\s*"?(.*?)"?\s*$', fm, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    return v or None


def _leggi(path: Path, campi) -> dict | None:
    try:
        testo = path.read_text(encoding='utf-8')
    except OSError:
        return None
    m = _FM.match(testo)
    if not m:
        return None
    fm = m.group(1)
    if (_campo(fm, 'pubblicato') or '').lower() == 'false':
        return None
    return {c: _campo(fm, c) for c in campi}


def norm(s: str | None) -> str:
    """Chiave di confronto: senza accenti, minuscola, senza punteggiatura."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


# ---------------------------------------------------------------- giocatori

@lru_cache(maxsize=1)
def _indice_giocatori() -> dict:
    """slug_profilo -> attributi, piu' alias per nome e cognome."""
    per_slug, alias = {}, {}
    if not DIR_GIOCATORI.exists():
        return {'per_slug': per_slug, 'alias': alias}
    for p in sorted(DIR_GIOCATORI.glob('*.md')):
        d = _leggi(p, CAMPI_GIOCATORE)
        if not d:
            continue
        slug = p.stem
        d['slug'] = slug
        per_slug[slug] = d
        nome = d.get('nome')
        if nome:
            alias.setdefault(norm(nome), slug)
            pezzi = nome.split()
            if len(pezzi) >= 2:
                # cognome (anche composto) come alias secondario
                alias.setdefault(norm(' '.join(pezzi[1:])), slug)
    return {'per_slug': per_slug, 'alias': alias}


def fatti_giocatore(nome_o_slug: str) -> dict | None:
    """Attributi verificati di un giocatore, o None se non ne abbiamo.

    Accetta lo slug del profilo, il nome completo o il cognome. Il nome
    abbreviato dei tabelloni ("W. Falkowska") viene gestito provando il
    cognome, perche' e' quello che l'API fornisce.
    """
    if not nome_o_slug:
        return None
    idx = _indice_giocatori()
    chiave = nome_o_slug.strip()
    if chiave in idx['per_slug']:
        return idx['per_slug'][chiave]
    n = norm(chiave)
    if n in idx['alias']:
        return idx['per_slug'][idx['alias'][n]]
    # "W. Falkowska" -> prova il solo cognome
    pezzi = [x for x in re.split(r'\s+', chiave) if not re.fullmatch(r'[A-Za-z]\.?', x)]
    if pezzi:
        n2 = norm(' '.join(pezzi))
        if n2 in idx['alias']:
            return idx['per_slug'][idx['alias'][n2]]
    return None


def blocco_giocatore(nome_visualizzato: str, nome_api: str = '') -> str:
    """Righe da incollare nel blocco DATI AUTORITATIVI di un articolo.

    Elenca SOLO gli attributi verificati. Per quelli che mancano dice
    esplicitamente che non sono verificati, cosi' il modello sa che non puo'
    scriverli e il gate sa che citarli e' un errore.
    """
    d = fatti_giocatore(nome_visualizzato) or fatti_giocatore(nome_api)
    etichette = [
        ('nazionalita', 'nazionalita'),
        ('mano', 'mano dominante'),
        ('rovescio', 'rovescio'),
        ('data_nascita', 'data di nascita'),
        ('altezza', 'altezza'),
        ('categoria', 'circuito'),
    ]
    if not d:
        return (f'  {nome_visualizzato}: nessun attributo verificato in archivio.\n'
                f'    NON scrivere mano, rovescio, nazionalita, eta o altezza di questo giocatore.')
    righe = [f'  {d.get("nome") or nome_visualizzato}:']
    mancanti = []
    for chiave, etichetta in etichette:
        v = d.get(chiave)
        if v:
            righe.append(f'    {etichetta}: {v}')
        else:
            mancanti.append(etichetta)
    if mancanti:
        righe.append(f'    NON VERIFICATI, da non scrivere: {", ".join(mancanti)}')
    return '\n'.join(righe)


# ------------------------------------------------------------------- tornei

@lru_cache(maxsize=1)
def _indice_tornei() -> dict:
    """chiave citta/nome normalizzata -> attributi del torneo."""
    per_slug, alias = {}, {}
    if not DIR_TORNEI.exists():
        return {'per_slug': per_slug, 'alias': alias}
    for p in sorted(DIR_TORNEI.glob('*.md')):
        d = _leggi(p, CAMPI_TORNEO)
        if not d:
            continue
        slug = p.stem
        d['slug'] = slug
        per_slug[slug] = d
        for v in (d.get('citta'), d.get('nome')):
            if v:
                alias.setdefault(norm(v), slug)
        # lo slug senza anno: "vienna-2026" -> "vienna", "lyon-france-2026" -> "lyon france"
        base = re.sub(r'-(19|20)\d\d$', '', slug).replace('-', ' ')
        alias.setdefault(norm(base), slug)
    return {'per_slug': per_slug, 'alias': alias}


def _pulisci_nome_torneo(raw: str) -> str:
    """Toglie il rumore che arriva grezzo dall'API dei tabelloni."""
    s = re.sub(r'\s*-\s*Qualification\s*$', '', raw or '', flags=re.I)
    return s.strip()


def fatti_torneo(nome_torneo: str, anno: int | None = None) -> dict | None:
    """Attributi verificati di un torneo, o None se non ne abbiamo."""
    if not nome_torneo:
        return None
    idx = _indice_tornei()
    pulito = _pulisci_nome_torneo(nome_torneo)
    candidati = [pulito, re.sub(r'\s*\([^)]*\)\s*$', '', pulito).strip()]
    for c in candidati:
        n = norm(c)
        if not n:
            continue
        if anno:
            slug_atteso = f'{n.replace(" ", "-")}-{anno}'
            if slug_atteso in idx['per_slug']:
                return idx['per_slug'][slug_atteso]
        if n in idx['alias']:
            d = idx['per_slug'][idx['alias'][n]]
            if anno and d.get('anno') and str(d['anno']) != str(anno):
                continue
            return d
    return None


def superficie_torneo(nome_torneo: str, anno: int | None = None) -> str | None:
    """Superficie VERIFICATA del torneo, o None se non la conosciamo.

    Sostituisce l'euristica a parole chiave che assegnava "cemento" per
    default: era cosi' che il Challenger di Cali, che si gioca sulla terra,
    e' stato pubblicato come cemento.
    """
    d = fatti_torneo(nome_torneo, anno)
    return (d or {}).get('superficie')


def blocco_torneo(nome_torneo: str, anno: int | None = None) -> str:
    """Righe da incollare nel blocco DATI AUTORITATIVI di un articolo."""
    d = fatti_torneo(nome_torneo, anno)
    pulito = _pulisci_nome_torneo(nome_torneo)
    if not d:
        return (f'  {pulito}: torneo non presente in archivio verificato.\n'
                f'    NON scrivere superficie, sede, categoria o albo d\'oro di questo torneo.')
    righe = [f'  {d.get("nome") or pulito}:']
    for chiave, etichetta in (('citta', 'citta'), ('paese', 'paese'),
                              ('categoria', 'categoria'), ('superficie', 'superficie'),
                              ('fondato', 'fondato')):
        v = d.get(chiave)
        if v:
            righe.append(f'    {etichetta}: {v}')
    return '\n'.join(righe)


def ricarica():
    """Svuota la cache: serve dopo aver scritto o corretto un profilo."""
    _indice_giocatori.cache_clear()
    _indice_tornei.cache_clear()


if __name__ == '__main__':
    import sys
    g = _indice_giocatori()
    t = _indice_tornei()
    print(f'giocatori verificati in archivio: {len(g["per_slug"])}')
    print(f'tornei verificati in archivio:    {len(t["per_slug"])}')
    con_mano = sum(1 for d in g['per_slug'].values() if d.get('mano'))
    con_rov = sum(1 for d in g['per_slug'].values() if d.get('rovescio'))
    print(f'  con mano verificata:     {con_mano}')
    print(f'  con rovescio verificato: {con_rov}')
    for arg in sys.argv[1:]:
        print(f'\n--- {arg} ---')
        print(blocco_giocatore(arg))
        print(blocco_torneo(arg))
