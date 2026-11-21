#!/usr/bin/env python3
"""Costruisce un POOL LOCALE di foto d'azione tennis (giocatori in campo).

Perche': i match ITF minori (W15/W50) hanno giocatrici sconosciute senza
foto libere su Commons. Oggi cadono su 'pick_venue' -> stadi vuoti da un
pool minuscolo che si ripete (il 19/11: 16 articoli, 7 immagini reali).

Soluzione: un pool di ~30 foto d'AZIONE verificate (giocatori anonimi che
giocano), scaricate una volta qui, usate come fallback PRIMA del venue.
Mostrano tennis giocato e variano, invece di stadi vuoti ripetuti.

Riusa l'infrastruttura di attach_covers (sessione HTTP con UA che Commons
accetta, filtri tennis, ensure_web_size). Idempotente: non riscarica un
file gia' presente, aggiorna solo il manifest.

Uso:  python3 build_cover_pool.py [--target 30]
Output: public/covers/pool/action-NN.jpg + public/covers/pool/manifest.json
"""
from __future__ import annotations
import sys, json, argparse, hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attach_covers import (
    commons_search, S, _looks_tennis, _BAD_SCENE_RE, CLOSEUP_WORDS,
    _is_venue_photo, build_credit, commons_fileinfo,
)

ROOT = Path(__file__).resolve().parent.parent
POOL_DIR = ROOT / 'public/covers/pool'
MANIFEST = POOL_DIR / 'manifest.json'

# Query d'AZIONE: cercano giocatori che giocano, non stadi. Molte e variate
# per massimizzare un pool grande ed eterogeneo (serve a non ripetere mai le
# cover nello stesso giorno, anche con 16+ articoli ITF).
QUERIES = [
    'tennis forehand player', 'tennis backhand player', 'tennis serve player',
    'tennis player match play', 'ATP tennis match', 'WTA tennis match',
    'tennis rally player', 'tennis volley player', 'professional tennis player playing',
    'tennis tournament match action', 'tennis player return', 'clay court tennis player',
    'hard court tennis player', 'tennis player forehand action', 'tennis singles match',
    'tennis player backhand action', 'tennis player hitting ball',
    'tennis player open', 'tennis grand slam player', 'tennis player serving match',
    'female tennis player action', 'male tennis player action', 'tennis player running',
    'tennis player smash', 'tennis player slice', 'tennis player two handed backhand',
    'tennis match point player', 'tennis player on court', 'tennis player forehand grip',
    'tennis player stretching ball', 'tennis doubles match action', 'tennis player reaching',
    'tennis player clay slide', 'tennis player net approach', 'tennis player celebration fist',
    'ITF tennis player', 'challenger tennis player', 'tennis player action shot',
]

_CLOSEUP = tuple(w.lower() for w in CLOSEUP_WORDS)

# Soggetti/temi poco rappresentativi del circuito ATP/WTA moderno o non
# pertinenti come cover editoriale: li escludiamo per qualita'.
_OFFTOPIC = ('wheelchair', 'paralymp', 'para tennis', 'juniores', 'junior ',
             'veteran', 'seniors', 'table tennis', 'ping pong', 'real tennis',
             'court tennis', 'padel', 'beach tennis', 'drawing', 'sketch',
             'engraving', 'lithograph', 'painting', 'cartoon', 'statue',
             '1900', '1910', '1920', '1930', '1940', '1950',
             # NON-foto o scene non pertinenti viste nei risultati:
             'page ', 'crop', ' le tennis', 'secretary', 'watches', 'watching',
             'shake hands', 'handshake', 'ceremony', 'trophy', 'award', 'medal',
             'poster', 'book', 'postcard', 'stamp', 'magazine', 'cover of',
             'kerry', 'obama', 'minister', 'president', 'royal', 'queen', 'king ')


def is_action_photo(title: str) -> bool:
    """Tiene solo foto d'azione tennis moderne: tema tennis, non venue vuoto,
    non primo piano, non scena vietata, non temi off-topic/storici."""
    t = title.lower()
    if not _looks_tennis(title):
        return False
    if _BAD_SCENE_RE.search(title):
        return False
    if _is_venue_photo(title):   # stadi/arene vuote: le vogliamo escludere qui
        return False
    if any(w in t for w in _CLOSEUP):
        return False
    if any(w in t for w in _OFFTOPIC):
        return False
    return True


def download_local(url: str, dest: Path) -> bool:
    try:
        r = S.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(1024 * 64):
                f.write(chunk)
        from cover_image_utils import ensure_web_size
        ensure_web_size(dest)
        return True
    except Exception as e:
        print(f'  [warn] download fallito {dest.name}: {e}', flush=True)
        if dest.exists():
            dest.unlink()
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', type=int, default=30, help='Foto da raccogliere')
    args = ap.parse_args()

    POOL_DIR.mkdir(parents=True, exist_ok=True)

    # Raccogli candidati unici (per title) da tutte le query.
    candidati = {}
    for q in QUERIES:
        for r in commons_search(q, limit=15):
            title = r.get('title', '')
            if title in candidati:
                continue
            if is_action_photo(title):
                candidati[title] = r
        if len(candidati) >= args.target * 2:
            break
    print(f'[pool] {len(candidati)} candidati d\'azione trovati', flush=True)

    # Manifest esistente (idempotenza): titoli gia' nel pool.
    esistenti = []
    if MANIFEST.exists():
        try:
            esistenti = json.loads(MANIFEST.read_text(encoding='utf-8'))
        except Exception:
            esistenti = []
    gia_presenti = {e['title'] for e in esistenti}

    manifest = list(esistenti)
    md5_visti = set()
    for e in esistenti:
        p = ROOT / 'public' / e['file'].lstrip('/')
        if p.exists():
            md5_visti.add(hashlib.md5(p.read_bytes()).hexdigest())

    n = len(manifest)
    for title, r in candidati.items():
        if n >= args.target:
            break
        if title in gia_presenti:
            continue
        idx = n + 1
        dest = POOL_DIR / f'action-{idx:02d}.jpg'
        url = r.get('url')
        if not url:
            info = commons_fileinfo(title)
            url = info.get('url') if info else None
        if not url:
            continue
        if not download_local(url, dest):
            continue
        # Dedup per contenuto: scarta se md5 gia' nel pool.
        md5 = hashlib.md5(dest.read_bytes()).hexdigest()
        if md5 in md5_visti:
            dest.unlink()
            continue
        md5_visti.add(md5)
        manifest.append({
            'file': f'/covers/pool/{dest.name}',
            'title': title,
            'credit': build_credit(r),
        })
        n += 1
        print(f'  [{n}/{args.target}] {dest.name}  <-  {title[:60]}', flush=True)

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[pool] manifest scritto: {len(manifest)} foto in {POOL_DIR}', flush=True)
    return 0 if manifest else 1


if __name__ == '__main__':
    sys.exit(main())
