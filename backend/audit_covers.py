#!/usr/bin/env python3
"""Audit delle cover articoli: verifica che la foto sia pertinente, non
sfasata e rispetti le regole della testata.

Regole di controllo:
1. Il file cover esiste e pesa > 15 KB (foto reale, non placeholder).
2. Dimensioni reali >= 600px lato lungo (no micro-icone).
3. Aspect ratio tra 1:2 e 3:1 (no immagini estreme).
4. Il titolo del file Commons NON contiene BLOCK_WORDS (ping pong,
   trofei, cerimonie, ecc.).
5. Se il verdetto identifica un favorito mappato: il cognome del
   favorito deve essere nel titolo del file (match foto giocatore);
   altrimenti si accetta solo venue con contesto tennis.
6. Il campo cover_image nel frontmatter punta al file che esiste.

Output:
- Se tutto ok -> exit 0 senza output.
- Se trova problemi -> stampa report + exit 1.
- Flag --fix per rigenerare automaticamente le cover problematiche.

Integrazione pipeline:
Lanciato da daily.sh dopo [4/5] scrittura articoli con flag --fix,
cosi' ogni problema viene corretto prima del commit.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from attach_covers import (
    NAME_MAP, VENUE_MAP, COVERS_DIR, BLOCK_WORDS, TENNIS_CONTEXT,
    detect_winner, pick_image, pick_venue, download, strip_html,
    parse_frontmatter, update_frontmatter, _looks_tennis,
)

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'


def _last_token(name: str) -> str:
    if not name:
        return ''
    parts = [p.strip('.-\'') for p in name.split() if len(p) > 1]
    return parts[-1].lower() if parts else ''


def audit_one(art: Path) -> dict:
    """Ritorna {'slug', 'ok': bool, 'problems': [...], 'suggested_action': ...}."""
    slug = art.stem
    fm, _ = parse_frontmatter(art)
    result = {'slug': slug, 'ok': True, 'problems': [], 'cover_image': None, 'credit': None}
    if not fm:
        return result

    cover_rel = fm.get('cover_image', '')
    result['cover_image'] = cover_rel
    result['credit'] = fm.get('cover_credit', '')

    g1 = fm.get('giocatore1', '')
    g2 = fm.get('giocatore2', '')
    torneo = fm.get('torneo', '')
    verdetto = fm.get('verdetto', '')

    # 1. File esiste?
    if not cover_rel:
        result['ok'] = False
        result['problems'].append('cover_image mancante nel frontmatter')
        return result

    cover_file = ROOT / 'public' / cover_rel.lstrip('/')
    if not cover_file.exists():
        result['ok'] = False
        result['problems'].append(f'file {cover_file.name} non trovato in public/covers/')
        return result

    size_kb = cover_file.stat().st_size / 1024
    if size_kb < 15:
        result['ok'] = False
        result['problems'].append(f'file troppo piccolo ({size_kb:.1f} KB), possibile placeholder vuoto')

    # 2+3. Dimensioni reali + aspect ratio
    try:
        with Image.open(cover_file) as im:
            w, h = im.size
            if max(w, h) < 600:
                result['ok'] = False
                result['problems'].append(f'risoluzione bassa {w}x{h} (lato < 600px)')
            ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 999
            if ratio > 3:
                result['ok'] = False
                result['problems'].append(f'aspect ratio estremo {ratio:.1f}:1 ({w}x{h})')
    except Exception as e:
        result['ok'] = False
        result['problems'].append(f'immagine corrotta o non leggibile: {e}')

    # 4. Titolo file Commons con BLOCK_WORDS?
    credit = (result['credit'] or '').lower()
    for bw in BLOCK_WORDS:
        if bw in credit:
            result['ok'] = False
            result['problems'].append(f'titolo file contiene "{bw}" (block word)')
            break

    # 5. Verdetto favorito -> cognome nel file?
    fav, conf = detect_winner(verdetto, g1, g2)
    if fav and conf != 'equilibrio':
        full = NAME_MAP.get(fav)
        if full:
            last = _last_token(full)
            if last and last not in credit:
                # Il favorito ha mapping ma il credit non ha il cognome.
                # Verifichiamo se Commons ha davvero una foto propria per il
                # giocatore: se SI, la cover attuale e' da sostituire (KO);
                # se NO, il venue va bene (info).
                try:
                    probe = pick_image(full)
                except Exception:
                    probe = None
                if probe:
                    # Esiste foto propria -> cover attuale e' obsoleta, va rifatta
                    result['ok'] = False
                    result['problems'].append(
                        f'cover obsoleta: foto propria di {full} disponibile su Commons '
                        f'("{probe["title"][:60]}") ma credit attuale e\' "{credit[:60]}"'
                    )
                elif not _looks_tennis(credit):
                    result['ok'] = False
                    result['problems'].append(
                        f'favorito {fav} ({full}): no foto Commons, no venue tennis chiaro '
                        f'("{credit[:60]}")'
                    )
                else:
                    result['problems'].append(
                        f'[info] favorito {fav} senza foto Commons; usato venue "{credit[:50]}"'
                    )
        else:
            # Favorito senza mapping -> venue atteso
            if not _looks_tennis(credit):
                result['ok'] = False
                result['problems'].append(
                    f'favorito {fav} non mappato in NAME_MAP e cover non e\' venue tennis: "{credit[:70]}"'
                )

    return result


def regenerate_cover(art: Path) -> tuple[bool, str]:
    """Rigenera la cover usando la stessa logica di write_article.
    Ritorna (success, message)."""
    fm, _ = parse_frontmatter(art)
    if not fm:
        return False, 'frontmatter non parseabile'
    g1 = fm.get('giocatore1', '')
    g2 = fm.get('giocatore2', '')
    torneo = fm.get('torneo', '')
    verdetto = fm.get('verdetto', '')
    slug = art.stem

    fav, conf = detect_winner(verdetto, g1, g2)
    pick = None
    if fav and conf != 'equilibrio':
        full = NAME_MAP.get(fav)
        if full:
            pick = pick_image(full)
    if not pick:
        pick = pick_venue(torneo)
    if not pick:
        return False, 'nessuna immagine disponibile da Commons'

    dest = COVERS_DIR / f'{slug}.jpg'
    try:
        download(pick['url'], dest)
    except Exception as e:
        return False, f'download fallito: {e}'

    credit = (
        f"{pick['title'].replace('File:', '')} | "
        f"{strip_html(pick.get('author') or 'Autore sconosciuto')} | "
        f"{pick.get('license') or 'Wikimedia Commons'}"
    )
    rel = f'/covers/{slug}.jpg'
    update_frontmatter(art, rel, credit)
    return True, pick['title'][:80]


def main():
    args = sys.argv[1:]
    fix = '--fix' in args
    filter_prefix = None
    for a in args:
        if a.startswith('--date='):
            filter_prefix = a.split('=', 1)[1]

    pattern = f'{filter_prefix}-*.md' if filter_prefix else '*.md'
    articoli = sorted(ARTICOLI.glob(pattern))
    articoli = [a for a in articoli if 'benvenuti' not in a.name]

    results = []
    problems = 0
    for art in articoli:
        r = audit_one(art)
        results.append(r)
        if not r['ok']:
            problems += 1

    # Stampa report
    print(f'=== AUDIT COVER: {len(articoli)} articoli analizzati ===', flush=True)
    for r in results:
        if r['ok']:
            # Mostra solo info rilevanti
            info = [p for p in r['problems'] if p.startswith('[info]')]
            if info:
                print(f'  [OK]   {r["slug"]}')
                for p in info:
                    print(f'           {p}')
        else:
            print(f'  [KO]   {r["slug"]}', flush=True)
            for p in r['problems']:
                print(f'           - {p}', flush=True)
            if fix:
                ok, msg = regenerate_cover(ARTICOLI / f'{r["slug"]}.md')
                tag = 'FIX ok' if ok else 'FIX fail'
                print(f'           [{tag}] {msg}', flush=True)

    print(f'\n=== TOTALE: {problems} articoli con problemi su {len(articoli)} ===', flush=True)

    # Scrivi report JSON per daily.sh
    report = ROOT / 'backend' / f'cover_audit.json'
    report.write_text(json.dumps({
        'total': len(articoli),
        'problems': problems,
        'details': results,
    }, indent=2, ensure_ascii=False))

    sys.exit(0 if problems == 0 else 1)


if __name__ == '__main__':
    main()
