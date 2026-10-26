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
    # Nomi non mappati (identita' incerta) -> fallback venue
    # 'S. Sorger', 'J. Garland', 'Y. Ma', 'Y. Qu', 'M. Yamaguchi', 'S. Y. Cheuk', 'T. Kostovic', 'X. You'
}

# Mappatura torneo -> query venue su Commons (nome venue + "tennis")
VENUE_MAP = {
    'Vienna': 'Erste Bank Open',
    'Brussels': 'Palais 12 Bruxelles',
    'Tokyo': 'Ariake Tennis',
    'Guangzhou': 'Tianhe tennis Guangzhou',
    'Almaty': 'Almaty Arena',
    'Ningbo': 'Ningbo Tennis Center',
    'Lyon (France) - Qualification': 'Lyon Open Tennis',
    'Lyon': 'Lyon Open Tennis',
    'Basel': 'St. Jakobshalle Basel tennis',
    'Cali': 'Club Campestre Cali tennis',
    'Fort Worth (Usa)': 'Fort Worth tennis',
    'Fort Worth': 'Fort Worth tennis',
    'Florence (Italy) - Qualification': 'Firenze Open ATP tennis',
    'Florence': 'Firenze Open ATP tennis',
    'Firenze': 'Firenze Open ATP tennis',
    'Brest': 'Open de Brest tennis',
}

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
    r = S.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    pages = (data.get('query') or {}).get('pages') or {}
    out = []
    for p in pages.values():
        info = (p.get('imageinfo') or [{}])[0]
        if info.get('mime') not in ('image/jpeg', 'image/png'):
            continue
        title = p.get('title', '').lower()
        if any(w in title for w in BLOCK_WORDS):
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
    # Preferisci landscape (ratio >= 1.3) ma non estremo
    ratio = result['w'] / max(result['h'], 1)
    if 1.3 <= ratio <= 2.4:
        score += 5
    # Preferisci risoluzioni medie (schivi i grandi stock con panoramiche)
    if 900 <= result['w'] <= 3500:
        score += 3
    return score


def pick_image(name_full: str):
    """Cerca su Commons. Ritorna una foto solo se contesto chiaro:
       - cognome + nome entrambi nel titolo, oppure
       - cognome + contesto tennis
       Ranking: foto d'azione pura > generiche, scena allargata depenalizzata.
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
    return pool[0]


def pick_venue(torneo: str):
    q = VENUE_MAP.get(torneo) or torneo
    for query in (q, f'{torneo} tennis', f'{torneo} tennis center', f'{torneo} tennis stadium'):
        results = commons_search(query)
        # filtra: deve essere immagine chiaramente legata al tennis
        results = [r for r in results if _looks_tennis(r['title'])]
        if results:
            return results[0]
    return None


def download(url: str, dest: Path):
    r = S.get(url, timeout=60, stream=True)
    r.raise_for_status()
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(1024 * 64):
            f.write(chunk)


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
    fm_lines.append(f'cover_image: "{cover_rel}"')
    fm_lines.append(f'cover_credit: "{credit}"')
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
            pick = pick_venue(torneo)
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
