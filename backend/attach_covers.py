#!/usr/bin/env python3
"""Scarica cover Commons per gli articoli esistenti e aggiorna il frontmatter.

Regole:
- se il verdetto identifica un favorito -> cerca foto giocatore su Commons
- se il verdetto esprime equilibrio      -> cerca foto venue/torneo
- mai primi piani ravvicinati del volto (euristico: evita file "portrait|closeup|headshot|face")
"""
from __future__ import annotations
import os, re, sys, json, hashlib, shutil, time
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'
COVERS_DIR = ROOT / 'public' / 'covers'
COVERS_DIR.mkdir(parents=True, exist_ok=True)

UA = 'AnalisiTennisBot/1.0 (https://analisitennis.it; redazione@analisitennis.it)'
S = requests.Session()
S.headers.update({'User-Agent': UA})

# Mappatura nome abbreviato -> nome completo per Commons (ampliabile)
NAME_MAP = {
    'A. Fils': 'Arthur Fils',
    'J-L. Struff': 'Jan-Lennard Struff',
    'A. Molcan': 'Alex Molcan',
    'H. Medjedovic': 'Hamad Medjedovic',
    'A. Zakharova': 'Anastasia Zakharova',
    'R. Zhang': 'Shuai Zhang',
    'C. Moutet': 'Corentin Moutet',
    'T. Machac': 'Tomas Machac',
    'C. Wong Hong Yi': 'Cody Wong',
    'E. Jones': 'Emerson Jones',
    'D. Medvedev': 'Daniil Medvedev',
    'A. Bublik': 'Alexander Bublik',
    'D. Vallejo': 'Daniel Vallejo',
    'L. Sonego': 'Lorenzo Sonego',
    'D. Yastremska': 'Dayana Yastremska',
    'X. You': 'Xiaodi You',
    'E. Rybakina': 'Elena Rybakina',
    'D. Shnaider': 'Diana Shnaider',
    'E. S. Liang': 'En Shuo Liang',
    'T. Valentova': 'Tereza Valentova',
    'F. Cerundolo': 'Francisco Cerundolo',
    'T. Griekspoor': 'Tallon Griekspoor',
    'F. Cobolli': 'Flavio Cobolli',
    'L. Musetti': 'Lorenzo Musetti',
    'F. Marozsan': 'Fabian Marozsan',
    'H. Dart': 'Harriet Dart',
    'Y. Putintseva': 'Yulia Putintseva',
    'J. Fearnley': 'Jacob Fearnley',
    'P. Carreno-Busta': 'Pablo Carreno Busta',
    'M. Inglis': 'Maddison Inglis',
    'K. Boulter': 'Katie Boulter',
    'S. Ishii': 'Saki Ishii',
    'K. Day': 'Kayla Day',
    'S. Zhang': 'Shuai Zhang',
    'L. Fruhvirtova': 'Linda Fruhvirtova',
    'K. Kawa': 'Katarzyna Kawa',
    'H. Kinoshita': 'Hina Kinoshita',
    'N. Basilashvili': 'Nikoloz Basilashvili',
    'S. Tsitsipas': 'Stefanos Tsitsipas',
    'T. A. Tirante': 'Thiago Agustin Tirante',
    'A. Mannarino': 'Adrian Mannarino',
    'V. Kopriva': 'Vit Kopriva',
    'L. Neumayer': 'Lukas Neumayer',
    'Xin. Wang': 'Xinyu Wang',
    'D. Kasatkina': 'Daria Kasatkina',
    # Aggiunti 26/10/2026
    'M. Berrettini': 'Matteo Berrettini',
    'T. M. Etcheverry': 'Tomas Martin Etcheverry',
    'A. Eala': 'Alexandra Eala',
    'M. Stojsavljevic': 'Mika Stojsavljevic',
    'N. Borges': 'Nuno Borges',
    'V. Vacherot': 'Valentin Vacherot',
    'M. Navone': 'Mariano Navone',
    'H. Rune': 'Holger Rune',
    'Q. Halys': 'Quentin Halys',
    'T. Prozorova': 'Tatiana Prozorova',
    'J. M. Cerundolo': 'Juan Manuel Cerundolo',
    'D. Altmaier': 'Daniel Altmaier',
    'T. Fritz': 'Taylor Fritz',
    'A. De Minaur': 'Alex de Minaur',
    'J. Mensik': 'Jakub Mensik',
    'C. Ruud': 'Casper Ruud',
    'D. Stricker': 'Dominic Stricker',
    'L. Darderi': 'Luciano Darderi',
    'M. Arnaldi': 'Matteo Arnaldi',
    'L. Tien': 'Learner Tien',
    'J. Fearnley': 'Jacob Fearnley',
    'P. Badosa': 'Paula Badosa',
    # Giocatori del 25/10 di cui ho certezza del nome completo
    'T. Droguet': 'Titouan Droguet',
    'R. Hijikata': 'Rinky Hijikata',
    'Y. Hanfmann': 'Yannick Hanfmann',
    'R. Bertola': 'Remy Bertola',
    'G. Mpetshi Perricard': 'Giovanni Mpetshi Perricard',
    'A. Kovacevic': 'Aleksandar Kovacevic',
    'J. Duckworth': 'James Duckworth',
    # Aggiunti 27/10/2026 - top ATP + WTA della giornata
    'A. Davidovich Fokina': 'Alejandro Davidovich Fokina',
    'Z. Bergs': 'Zizou Bergs',
    'H. Hurkacz': 'Hubert Hurkacz',
    'A. Fils': 'Arthur Fils',
    'V. Williams': 'Venus Williams',
    'T. Paul': 'Tommy Paul',
    'A. Rublev': 'Andrey Rublev',
    'A. Rinderknech': 'Arthur Rinderknech',
    'A. Tabilo': 'Alejandro Tabilo',
    'K. Khachanov': 'Karen Khachanov',
    'C. Alcaraz': 'Carlos Alcaraz',
    'A. Michelsen': 'Alex Michelsen',
    'B. Van De Zandschulp': 'Botic van de Zandschulp',
    'C. Norrie': 'Cameron Norrie',
    'A. Zverev': 'Alexander Zverev',
    'M. Landaluce': 'Martin Landaluce',
    # Aggiunti 28/10/2026 - top ATP/WTA della giornata
    'N. Djokovic': 'Novak Djokovic',
    'U. Humbert': 'Ugo Humbert',
    'F. Tiafoe': 'Frances Tiafoe',
    'B. Nakashima': 'Brandon Nakashima',
    'D. Shapovalov': 'Denis Shapovalov',
    'J. Rodionov': 'Jurij Rodionov',
    # Nomi non mappati (identita' incerta) -> fallback venue
    # 'S. Sorger', 'J. Garland', 'Y. Ma', 'Y. Qu', 'M. Yamaguchi', 'S. Y. Cheuk', 'T. Kostovic', 'X. You',
    # 'L. Tagger', 'X. Sun', 'M. Sawangkaew', 'J. Kym', 'R. Jodar', 'I. Buse', 'H. Bernet', 'M. Brunold'
}

# Mappatura torneo -> query venue su Commons (nome venue + "tennis")
VENUE_MAP = {
    'Vienna': 'Wiener Stadthalle',
    'Brussels': 'Palais 12 Bruxelles',
    'Tokyo': 'Ariake Tennis Center',
    # NB: "Shameen Tennis Ground" su Commons e' in realta' una foto di
    # strada di Shamian Island, non un campo. Usiamo il vero impianto del
    # torneo (Guangzhou International Tennis Center) + fallback generico.
    'Guangzhou': 'Guangzhou International Tennis Center',
    'Almaty': 'Almaty Arena',
    'Ningbo': 'Ningbo Yinzhou Tennis Center',
    'Lyon (France) - Qualification': 'Palais des Sports Lyon tennis',
    'Lyon': 'Palais des Sports Lyon tennis',
    'Basel': 'St. Jakobshalle',
    'Cali': 'Club Campestre Cali tennis',
    'Fort Worth (Usa)': 'Fort Worth tennis',
    'Fort Worth': 'Fort Worth tennis',
    'Florence (Italy) - Qualification': 'Palazzo Wanny Firenze',
    'Florence': 'Palazzo Wanny Firenze',
    'Firenze': 'Palazzo Wanny Firenze',
    'Brest': 'Open de Brest tennis',
    'Lisbon': 'Estoril Open tennis',
    'Lisboa': 'Estoril Open tennis',
    'Cali (Colombia)': 'Nalbandian tennis Colombia',
}

# File specifici di Commons noti come NON pertinenti ma che superano le
# euristiche title-based (es. contengono "tennis ground" ma ritraggono una
# strada). Match su sottostringa del titolo, minuscolo. Ampliabile a mano
# quando l'audit visivo scopre un falso positivo ricorrente.
BAD_FILE_SUBSTR = (
    'shameen tennis ground',   # strada di Shamian Island, non un campo
    'shamian',
    'organisateurs',           # Open Brest 2016: foto dei dirigenti, non match
    'finale moutet',           # Open Brest 2017: cerimonia premiazione juniores
    'tereza valentova fo',     # premiazione juniores, non foto d'azione
    'president marcos',        # cerimonia politica (Eala premiata dal governo)
    'hails alex eala',         # stessa cerimonia politica
    'tianhe stadium',          # stadio di CALCIO di Guangzhou, non tennis
)

BLOCK_WORDS = (
    'portrait', 'closeup', 'close_up', 'close-up', 'headshot', 'face', 'passport',
    # scene allargate dove il giocatore e' un puntino o la foto e' cerimoniale
    'court central', 'aerial', 'trophy', 'podium', 'ceremony', 'medal',
    'press conference', 'awards', 'presentation', 'olympic torch',
    'slazenger balls', 'slazenger ball', 'tennis balls', 'tennis ball',
    'crowd', 'grandstand', 'empty court', 'draw ceremony',
    'olympic rings', 'opening ceremony',
    # Esclusioni per falsi positivi "venue"
    'table tennis', 'ping pong', 'pingpong', 'street tennis',
    'tennis racket icon', 'logo tennis',
    # Traduzioni ping pong / tennis tavolo
    'tennis de table', 'tenis de mesa', 'tenis mesa', 'tavolo da tennis',
    'tennistavolo', 'tischtennis',
    # Conferenze, summit, premi - non sono match
    'web summit', 'conference', 'conférence', 'panel', 'speech',
    'press ceremony', 'red carpet', 'gala', 'festival',
    'school match', 'junior academy', 'tennis school',
)

# Parole che indicano foto d'AZIONE pura (preferite): un giocatore in gioco.
ACTION_WORDS = (
    'forehand', 'backhand', 'serve', 'serving', 'volley', 'return',
    'smash', 'hitting', 'swing', 'practicing', 'warmup', 'warm-up',
)

# Parole che indicano foto di SCENA ALLARGATA (giocatore piccolo, campo intero,
# o posa cerimoniale con sponsor sullo sfondo). Da deprioritizzare.
WIDE_SCENE_WORDS = (
    'ceremony', 'medal', 'podium', 'trophy', 'trophy ceremony',
    'press conference', 'olimpic rings', 'olympic rings',
    'court central', 'stadium wide', 'from stands', 'aerial',
    'awards', 'presentation', 'olympic torch',
)


def parse_frontmatter(path: Path):
    text = path.read_text()
    m = re.match(r'^---\n(.*?)\n---\n(.*)', text, re.S)
    if not m:
        return None, text
    body = m.group(2)
    fm_raw = m.group(1)
    fm = {}
    for line in fm_raw.splitlines():
        mm = re.match(r'^([a-zA-Z_0-9]+):\s*(.*)$', line)
        if mm:
            k, v = mm.group(1), mm.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            fm[k] = v
    return fm, text


def detect_winner(verdetto: str, g1: str, g2: str):
    """Ritorna (nome_abbreviato_favorito, confidence) o (None, 'equilibrio')."""
    if not g1 or not g2 or not verdetto:
        return None, 'equilibrio'
    v = verdetto.lower()
    if 'equilibrat' in v and 'puo spuntare' not in v and 'può spuntare' not in v and 'nettamente' not in v:
        return None, 'equilibrio'
    # pattern "oggi la può spuntare X" / "oggi nettamente X" / "oggi la puo spuntare X"
    for pat in [
        r"oggi (?:la )?(?:può|puo')?\s*(?:spuntare|puo spuntare|puó spuntare)\s+([a-zàèéìòùA-ZÀ-Ÿ.\-' ]{2,40})",
        r"oggi nettamente\s+([a-zàèéìòùA-ZÀ-Ÿ.\-' ]{2,40})",
    ]:
        mm = re.search(pat, verdetto, re.I)
        if mm:
            candidate = mm.group(1).strip().rstrip(':.,;')
            # Taglia dopo prima parola/duo per pulire
            for name in (g1, g2):
                last_token = name.split()[-1].lower().replace('-', '').replace("'", '')
                if last_token in candidate.lower().replace('-', '').replace("'", ''):
                    return name, 'netto' if 'nettamente' in v else 'misura'
    # Fallback: cerca il cognome di uno dei due nel verdetto
    for name in (g1, g2):
        last = name.split()[-1]
        if re.search(r'\b' + re.escape(last) + r'\b', verdetto, re.I):
            return name, 'misura'
    return None, 'equilibrio'


def commons_search(query: str, limit=15):
    url = 'https://commons.wikimedia.org/w/api.php'
    params = {
        'action': 'query', 'format': 'json',
        'generator': 'search', 'gsrsearch': f'{query}',
        'gsrnamespace': '6', 'gsrlimit': str(limit),
        'prop': 'imageinfo', 'iiprop': 'url|size|extmetadata|mime',
    }
    # Retry con backoff: Commons chiude la connessione sotto carico
    # (RemoteDisconnected). Senza retry l'intera audit --fix si schianta
    # alla prima connessione persa.
    import time
    last_err = None
    for attempt in range(4):
        try:
            r = S.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            last_err = None
            break
        except Exception as e:
            last_err = e
            if attempt < 3:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
    if last_err:
        # Dopo 4 tentativi falliti: non blocchiamo tutto, ritorniamo
        # lista vuota cosi' il chiamante prova altre query o fallback.
        print(f'  [warn] commons_search "{query}" fallita dopo 4 tentativi: {last_err}', flush=True)
        return []
    pages = (data.get('query') or {}).get('pages') or {}
    out = []
    for p in pages.values():
        info = (p.get('imageinfo') or [{}])[0]
        if info.get('mime') not in ('image/jpeg', 'image/png'):
            continue
        title = p.get('title', '').lower()
        if any(w in title for w in BLOCK_WORDS):
            continue
        if any(w in title for w in BAD_FILE_SUBSTR):
            continue
        if info.get('width', 0) < 600:
            continue
        em = info.get('extmetadata') or {}
        out.append({
            'title': p.get('title'),
            'url': info.get('url'),
            'w': info.get('width'), 'h': info.get('height'),
            'author': (em.get('Artist') or {}).get('value', ''),
            'license': (em.get('LicenseShortName') or {}).get('value', ''),
            'desc_url': info.get('descriptionurl'),
        })
    # Preferisci landscape, poi orizzontali grandi
    out.sort(key=lambda x: (-(x['w'] / max(x['h'], 1) >= 1.0), -x['w']))
    return out


def strip_html(s: str) -> str:
    s = re.sub(r'<[^>]+>', '', s or '')
    return re.sub(r'\s+', ' ', s).strip()


TENNIS_CONTEXT = ('tennis', ' open', 'wimbledon', 'us open', 'french open', 'roland garros',
                  'australian open', 'atp', 'wta', 'itf', 'challenger', 'olympics', 'olimpiadi',
                  'wmq', 'eastbourne', 'practicing', 'match', 'court', 'arena', 'stadium',
                  'nottingham', 'miami open', 'cincinnati', 'indian wells', 'madrid open',
                  'rome open', 'rogers cup', 'queen', 'rolex', 'erste bank', 'swiss indoors')


def _looks_tennis(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in TENNIS_CONTEXT)


def _rank(result):
    """Punteggio: azione pura > tennis context > scena allargata < 0."""
    t = result['title'].lower()
    score = 0
    if any(w in t for w in ACTION_WORDS):
        score += 50
    if _looks_tennis(t):
        score += 15
    if any(w in t for w in WIDE_SCENE_WORDS):
        score -= 25
    # Depenalizza le foto che ritraggono DUE persone (es. "Djokovic vs
    # Alcaraz", "X and Y"): per una cover singola vogliamo il giocatore
    # da solo, non un duello a figura intera che confonde il soggetto.
    if _PERSON_HINTS.search(result['title']):
        score -= 30
    # Preferisci landscape (ratio >= 1.3) ma non estremo
    ratio = result['w'] / max(result['h'], 1)
    if 1.3 <= ratio <= 2.4:
        score += 5
    # Preferisci risoluzioni medie (schivi i grandi stock con panoramiche)
    if 900 <= result['w'] <= 3500:
        score += 3
    return score


def pick_image(name_full: str, slug_hint: str = ''):
    """Cerca su Commons. Ritorna una foto solo se contesto chiaro:
       - cognome + nome entrambi nel titolo, oppure
       - cognome + contesto tennis
       Ranking: foto d'azione pura > generiche, scena allargata depenalizzata.
    slug_hint: quando passato, varia la scelta tra i migliori candidati di
    pari qualita' in modo deterministico, cosi' due articoli sullo stesso
    giocatore (es. due match di Hurkacz nello stesso giorno) non ricevono
    la stessa identica foto.
    """
    parts = name_full.split()
    last = parts[-1].lower()
    first = parts[0].lower() if len(parts) > 1 else ''
    if len(last) < 4:
        return None  # cognome troppo generico
    pool = []
    for q in [f'"{name_full}" tennis', f'{name_full} tennis', name_full]:
        results = commons_search(q)
        for r in results:
            t = r['title'].lower()
            if last not in t:
                continue
            # Scarta foto che ritraggono DUE giocatori ("X vs Y",
            # "X against Y"): nel titolo non sappiamo quale sia il
            # soggetto in primo piano, col rischio di mostrare
            # l'avversario al posto del favorito (es. una foto
            # "De Minaur vs Rublev" che in realta' inquadra Rublev).
            if _PERSON_HINTS.search(r['title']):
                continue
            # Scarta loghi, cerimonie, premiazioni e pose celebrative
            # con trofeo: vogliamo il giocatore in campo, attuale, non
            # un'immagine datata col trofeo o un logo del circuito.
            if any(w in t for w in (
                    'logo', 'trophy', 'trophies', 'ceremony', 'award',
                    'champion', 'winner', 'celebrat', 'press conference',
                    'challenger tour', 'draw ')):
                continue
            # Deve stabilire che e' davvero il giocatore giusto:
            # nome+cognome insieme, oppure cognome+contesto tennis,
            # oppure titolo corto tipo "Cognome AnnoTorneo"
            strong = first and first in t
            weak = _looks_tennis(t)
            short_ok = (
                len(r['title']) < 36
                and not any(w in t for w in
                            ('candidate', 'river', 'park', 'street', 'city',
                             'political', 'church', 'bridge', 'mountain', 'seaplane'))
            )
            if not (strong or weak or short_ok):
                continue
            pool.append(r)
        if pool:
            break
    if not pool:
        return None
    pool.sort(key=_rank, reverse=True)
    # Variazione deterministica tra i top candidati di pari rango, cosi'
    # articoli diversi sullo stesso giocatore prendono foto diverse.
    if slug_hint and len(pool) > 1:
        top_rank = _rank(pool[0])
        tied = [r for r in pool if _rank(r) >= top_rank - 10][:5]
        if len(tied) > 1:
            idx = int(hashlib.md5(slug_hint.encode()).hexdigest(), 16) % len(tied)
            return tied[idx]
    return pool[0]


# Parole che indicano venue/impianto (preferite dentro pick_venue).
VENUE_WORDS = ('stadium', 'arena', 'centre', 'center', 'court', 'hall',
               'park', 'complex', 'ground', 'club', 'halle', 'stadthalle',
               'palace', 'palais', 'palazzo', 'palasport', 'palasports',
               'convention', 'olimpico', 'olympiahalle', 'o2 arena')

# Pattern che indica che il risultato e' una foto di persona
# ("Ferrer against Troicki", "Nadal vs Djokovic", "Moretton et Noah",
# "Stefanos Tsitsipas, Swiss Indoors..." = inizio con Nome Cognome,).
import re as _re_person
_PERSON_HINTS = _re_person.compile(
    r'(\bagainst\b|\bvs\.?\b|\bv\.\s|\s(et|and)\s[A-Z])',
    _re_person.IGNORECASE,
)
# Match pattern "File:Nome Cognome," o "Nome Cognome," all'inizio del
# titolo: molte foto di tennisti su Commons sono nominate cosi'.
_PERSON_NAME_PREFIX = _re_person.compile(
    r'^(File:)?([A-ZÁÉÍÓÚÀÈÌÒÙÄÖÜÑŠČĆŽ][a-zñáéíóúàèìòùäöüç\-]+)\s'
    r'([A-ZÁÉÍÓÚÀÈÌÒÙÄÖÜÑŠČĆŽ][a-zñáéíóúàèìòùäöüç\-]+),'
)

# Scene da scartare dentro i venue (cronaca, polizia, parate, concerti,
# cerimonie - non la cosa che vogliamo mostrare come cover). Match su
# parola intera per evitare falsi positivi tipo 'fire' dentro 'Firenze'.
BAD_SCENE_WORDS = ('police', 'protest', 'march', 'graffiti', 'incident',
                   'funeral', 'crash', 'accident', 'demolition', 'fire',
                   'construction', 'ruins', 'abandoned',
                   # Eventi non-tennis che possono svolgersi nello stesso venue
                   'eurovision', 'esc', 'song contest', 'concert',
                   'orchestra', 'opera', 'festival', 'rally', 'speech',
                   'presidential', 'inauguration', 'exposition',
                   'exhibition', 'ice hockey', 'basketball', 'handball',
                   'volleyball', 'wrestling', 'hallenmaster', 'fcsg',
                   'football', 'soccer', 'boxing', 'mma', 'gymnastics',
                   'curling', 'skating', 'figure skating',
                   # Loghi, cartelloni, grafiche: non sono foto di luogo
                   'logo', 'challenger tour', 'poster', 'banner',
                   'signage', 'trophy', 'ceremony')
_BAD_SCENE_RE = _re_person.compile(
    r'\b(' + '|'.join(BAD_SCENE_WORDS) + r')\b',
    _re_person.IGNORECASE,
)


def _is_venue_photo(title: str) -> bool:
    """True se il titolo del file sembra un venue/impianto reale (contiene
    una venue word: arena, hall, stadium, center, court, ...).
    Scarta i falsi positivi tipo 'Stefanos Tsitsipas, Swiss Indoors Basel
    2024.jpg' che _looks_tennis accetterebbe perche' contiene 'swiss
    indoors', ma NON ha venue word.
    Scarta anche 'X against Y' / 'X vs Y' che sono match tra persone."""
    t = title.lower()
    if _PERSON_HINTS.search(title):
        return False
    # Scarta i titoli che iniziano con un pattern Nome Cognome, (molte
    # foto di tennisti sono "Stefanos Tsitsipas, Swiss Indoors..." o
    # "Jacob Fearnley, 2026 US Open" e passerebbero perche' contengono
    # venue word nel resto).
    if _PERSON_NAME_PREFIX.match(title):
        return False
    if _BAD_SCENE_RE.search(title):
        return False
    return any(w in t for w in VENUE_WORDS)


def _venue_rank(result):
    """Score venue: preferiamo foto di court/tennis puro, in landscape,
    risoluzione media."""
    t = result['title'].lower()
    score = 0
    if 'tennis' in t:
        score += 10
    if 'court' in t:
        score += 5
    if 'arena' in t or 'hall' in t or 'stadium' in t:
        score += 3
    # Preferisci landscape
    ratio = result['w'] / max(result['h'], 1)
    if 1.3 <= ratio <= 2.4:
        score += 3
    if 900 <= result['w'] <= 3500:
        score += 2
    return score


def pick_venue(torneo: str, slug_hint: str = ''):
    """Sceglie una foto venue per il torneo.
    slug_hint: slug dell'articolo. Quando passato, varia la scelta tra i
    top candidati venue in modo deterministico, cosi' articoli diversi
    dello stesso torneo prendono foto DIVERSE del venue (evita cover
    identica su piu' articoli)."""
    import hashlib
    q = VENUE_MAP.get(torneo) or torneo
    best_fallback = None
    for query in (q, f'{torneo} tennis', f'{torneo} tennis center', f'{torneo} tennis stadium'):
        results = commons_search(query)
        # Scarta loghi/cartelloni/cerimonie (BAD_SCENE) a monte: non devono
        # finire nemmeno nel best_fallback.
        results = [r for r in results
                   if (_looks_tennis(r['title']) or _is_venue_photo(r['title']))
                   and not _BAD_SCENE_RE.search(r['title'])]
        if not results:
            continue
        venue_only = [r for r in results if _is_venue_photo(r['title'])]
        if venue_only:
            venue_only.sort(key=_venue_rank, reverse=True)
            # Variazione deterministica: con slug_hint scegliamo tra i top
            # 5 candidati di pari qualita' usando l'hash dello slug. Articoli
            # diversi dello stesso torneo → cover venue diverse.
            if slug_hint and len(venue_only) > 1:
                pool = venue_only[:5]
                idx = int(hashlib.md5(slug_hint.encode()).hexdigest(), 16) % len(pool)
                return pool[idx]
            return venue_only[0]
        # Se nessun venue puro ma c'e' qualche risultato tennis chiaro,
        # lo tengo come fallback (meglio di una foto generica)
        if best_fallback is None:
            best_fallback = results[0]
    # Fallback universale: foto generica di campo da tennis professionale
    # per garantire che ogni articolo abbia una cover coerente col tema.
    # Variazione per-slug cosi' piu' articoli dello stesso torneo senza
    # venue proprio su Commons non ricevano la stessa identica foto.
    for query in ('ATP tennis court professional', 'tennis court outdoor professional',
                  'tennis stadium center court'):
        results = commons_search(query)
        results = [r for r in results if _looks_tennis(r['title']) and _is_venue_photo(r['title'])]
        if results:
            if slug_hint and len(results) > 1:
                pool = results[:6]
                idx = int(hashlib.md5(slug_hint.encode()).hexdigest(), 16) % len(pool)
                return pool[idx]
            return results[0]
    return best_fallback


def download(url: str, dest: Path):
    r = S.get(url, timeout=60, stream=True)
    r.raise_for_status()
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(1024 * 64):
            f.write(chunk)
    # Ridimensiona SUBITO a misura web: Commons serve file originali da
    # 9000+ px e 10-18 MB. Senza questo la cover sembra "rotta" (si scarica
    # in secondi e intanto la card mostra l'alt-text). Fonte unica della
    # regola: cover_image_utils.ensure_web_size.
    try:
        from cover_image_utils import ensure_web_size
        ensure_web_size(dest)
    except Exception as e:
        print(f'  [warn] resize cover fallito {dest.name}: {e}', flush=True)


def slug_of(path: Path) -> str:
    return path.stem


def update_frontmatter(path: Path, cover_rel: str, credit: str):
    fm, text = parse_frontmatter(path)
    if fm is None:
        return False
    # ricrea frontmatter preservando le righe originali
    raw = path.read_text()
    lines = raw.splitlines()
    # trova inizio/fine ---
    starts = [i for i, l in enumerate(lines) if l.strip() == '---']
    if len(starts) < 2:
        return False
    fm_lines = lines[starts[0] + 1:starts[1]]
    body = lines[starts[1] + 1:]
    # rimuovi vecchi cover_image / cover_credit se presenti
    fm_lines = [l for l in fm_lines if not l.startswith('cover_image:') and not l.startswith('cover_credit:')]
    # Sanifica: alcuni titoli Commons contengono virgolette doppie (es.
    # Ice Palace "Almaty Arena".jpg) che romperebbero la stringa YAML.
    safe_credit = (credit or '').replace('"', "'")
    safe_rel = (cover_rel or '').replace('"', "'")
    fm_lines.append(f'cover_image: "{safe_rel}"')
    fm_lines.append(f'cover_credit: "{safe_credit}"')
    new = ['---'] + fm_lines + ['---'] + body
    path.write_text('\n'.join(new) + ('\n' if raw.endswith('\n') else ''))
    return True


def main():
    report = []
    for art in sorted(ARTICOLI.glob('2026-10-24-*.md')):
        slug = slug_of(art)
        fm, _ = parse_frontmatter(art)
        if not fm:
            print(f'skip {slug}: no frontmatter'); continue
        g1, g2 = fm.get('giocatore1', ''), fm.get('giocatore2', '')
        torneo = fm.get('torneo', '')
        verdetto = fm.get('verdetto', '')
        fav, conf = detect_winner(verdetto, g1, g2)
        reason = ''
        pick = None
        if fav and conf != 'equilibrio':
            full = NAME_MAP.get(fav)
            if full:
                print(f'{slug}: favorito -> {fav} ({full})')
                pick = pick_image(full)
                reason = f'favorito {fav} ({conf})'
            else:
                print(f'{slug}: favorito {fav} senza mappatura -> fallback venue')
                reason = f'favorito {fav} non mappato'
        if not pick:
            print(f'{slug}: fallback venue -> {torneo}')
            pick = pick_venue(torneo, slug_hint=slug)
            reason = f'equilibrio -> venue {torneo}' if not fav else f'{reason}; fallback venue {torneo}'
        if not pick:
            print(f'{slug}: NO IMAGE'); continue
        dest = COVERS_DIR / f'{slug}.jpg'
        try:
            download(pick['url'], dest)
        except Exception as e:
            print(f'{slug}: download fallito {e}'); continue
        credit = f"{pick['title'].replace('File:','')} | {strip_html(pick.get('author') or 'Autore sconosciuto')} | {pick.get('license') or 'Wikimedia Commons'}"
        rel = f"/covers/{slug}.jpg"
        update_frontmatter(art, rel, credit)
        report.append({'slug': slug, 'reason': reason, 'file': pick['title'], 'url': pick['desc_url']})
        time.sleep(0.4)
    print('\n=== REPORT ===')
    for r in report:
        print(f"- {r['slug']}: {r['reason']} -> {r['file']}")
    (ROOT / 'backend' / 'covers_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
