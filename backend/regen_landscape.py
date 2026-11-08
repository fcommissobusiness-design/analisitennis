#!/usr/bin/env python3
"""Rigenerazione MIRATA delle cover VERTICALI gia' pubblicate.

Problema: le cover scelte prima del fix _rank (08/11/26) possono essere foto
verticali del giocatore. Nell'hero (CoverArticolo.astro, object-position
center ~20-38%) un ritratto in piedi viene tagliato SOPRA la testa.

Questo script, SOLO per le cover che sono gia' foto del giocatore del match
(cover_file_is_player) e sono VERTICALI, prova a ri-pescare per LO STESSO
giocatore una foto piu' orizzontale con il nuovo _rank. Applica la nuova foto
solo se e' davvero piu' landscape della corrente. Non tocca:
 - cover gia' orizzontali/quadrate,
 - venue,
 - giocatori che su Commons hanno solo foto verticali (resta la corrente).

Non declassa mai una foto-giocatore valida a venue: se non c'e' niente di
meglio in orizzontale, lascia la cover com'e'.

Scrive il credit nel formato nuovo (build_credit) e aggiorna cover_file.

Uso:
  python3 regen_landscape.py --from=2026-11-01 --to=2026-11-08 --dry-run
  python3 regen_landscape.py --from=2026-11-01 --to=2026-11-08
"""
from __future__ import annotations
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image
from attach_covers import (
    parse_frontmatter, resolve_full, pick_image, build_credit, download,
    used_covers_for_player, cover_file_is_player, COVERS_DIR,
)

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'

VERT_THRESHOLD = 0.95   # ratio w/h sotto il quale la foto e' "verticale"
MIN_GAIN = 0.12         # la nuova foto deve guadagnare almeno tanto in ratio

# Due nomi propri separati da virgola ("Magda Linette, Donna Vekic") = foto
# con DUE giocatrici: non adatta come cover singola. Richiede Cognome con la
# maiuscola dopo la virgola, cosi' "Casper Ruud, Norwegian professional..."
# (didascalia descrittiva di UN giocatore) non scatta.
_COMMA_TWO = re.compile(
    r'[A-ZÀ-Ý][\wÀ-ÿ\-]+\s+[A-ZÀ-Ý][\wÀ-ÿ\-]+,\s+'
    r'[A-ZÀ-Ý][\wÀ-ÿ\-]+\s+[A-ZÀ-Ý][\wÀ-ÿ\-]+'
)
# Parole che tradiscono grafiche/loghi/premiazioni non filtrate da pick_image
# (incluse varianti non inglesi: 'winnaar' = vincitore in olandese).
_BAD_REGEN = ('signature', 'winnaar', 'winner', 'logo', 'trophy', 'ceremon',
              'award', 'celebrat', 'poster', 'banner', 'draw ')


def _is_bad_pick(title: str) -> bool:
    t = title.lower()
    if _COMMA_TWO.search(re.sub(r'^File:', '', title)):
        return True
    return any(w in t for w in _BAD_REGEN)


def _pick_good(full: str, slug: str, excl: set):
    """pick_image ma scarta foto a due persone / grafiche / premiazioni:
    se il top e' 'cattivo' lo esclude e ri-pesca, fino a 5 tentativi."""
    seen = set()
    for _ in range(5):
        try:
            pick = pick_image(full, slug_hint=slug, exclude=excl)
        except Exception:
            return None
        if not pick or pick['title'] in seen:
            return None
        if not _is_bad_pick(pick['title']):
            return pick
        seen.add(pick['title'])
        excl = set(excl) | {pick['title']}
    return None


def _disk_ratio(cover_rel: str):
    p = ROOT / 'public' / cover_rel.lstrip('/')
    if not p.exists():
        return None, None
    try:
        with Image.open(p) as im:
            w, h = im.size
        return (w / max(h, 1)), p
    except Exception:
        return None, p


def _subject_player(cover_file_title: str, g1: str, g2: str):
    """Quale dei due giocatori e' il soggetto della cover attuale? None se
    la cover non e' (riconoscibilmente) una foto di uno dei due."""
    for g in (g1, g2):
        if g and cover_file_is_player(cover_file_title, g, ''):
            return g
    return None


def _set_cover(art: Path, rel: str, credit: str, cover_file_title: str) -> bool:
    """Riscrive cover_image, cover_credit e cover_file nel frontmatter."""
    raw = art.read_text()
    lines = raw.splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip() == '---']
    if len(starts) < 2:
        return False
    fm = lines[starts[0] + 1:starts[1]]
    body = lines[starts[1] + 1:]
    fm = [l for l in fm if not l.startswith(('cover_image:', 'cover_credit:', 'cover_file:'))]
    safe_credit = (credit or '').replace('"', "'")
    safe_rel = (rel or '').replace('"', "'")
    safe_file = (cover_file_title or '').replace('"', "'")
    fm.append(f'cover_image: "{safe_rel}"')
    fm.append(f'cover_credit: "{safe_credit}"')
    if safe_file:
        fm.append(f'cover_file: "{safe_file}"')
    new = ['---'] + fm + ['---'] + body
    art.write_text('\n'.join(new) + ('\n' if raw.endswith('\n') else ''))
    return True


def main():
    args = sys.argv[1:]
    d_from = d_to = None
    dry = False
    for a in args:
        if a.startswith('--from='):
            d_from = a.split('=', 1)[1]
        elif a.startswith('--to='):
            d_to = a.split('=', 1)[1]
        elif a == '--dry-run':
            dry = True

    arts = []
    for art in sorted(ARTICOLI.glob('2026-*.md')):
        if 'benvenuti' in art.name:
            continue
        date = art.name[:10]
        if d_from and date < d_from:
            continue
        if d_to and date > d_to:
            continue
        arts.append(art)

    print(f'Articoli nel range: {len(arts)} ({d_from}..{d_to})\n', flush=True)
    changed = 0
    skipped_novert = skipped_noalt = skipped_novel = 0
    for art in arts:
        fm, _ = parse_frontmatter(art)
        if not fm:
            continue
        g1 = fm.get('giocatore1', '')
        g2 = fm.get('giocatore2', '')
        cover_rel = fm.get('cover_image', '')
        cover_file = fm.get('cover_file', '')
        if not cover_rel:
            continue
        ratio, _p = _disk_ratio(cover_rel)
        if ratio is None:
            print(f'  [?] {art.stem[:46]:46} cover mancante su disco')
            continue
        # Solo cover VERTICALI che sono foto di un giocatore del match.
        if ratio >= VERT_THRESHOLD:
            skipped_novert += 1
            continue
        subj = _subject_player(cover_file, g1, g2)
        if not subj:
            # verticale ma non e' (riconoscibilmente) foto di un giocatore:
            # venue o credit vecchio illeggibile. Non tocco.
            continue
        full = resolve_full(subj) or subj
        surname = full.split()[-1]
        excl = used_covers_for_player(surname, skip_slug=art.stem)
        if cover_file:
            excl.add(cover_file if cover_file.startswith('File:') else 'File:' + cover_file)
        pick = _pick_good(full, art.stem, excl)
        if not pick:
            skipped_noalt += 1
            print(f'  [=] {art.stem[:40]:40} ratio {ratio:.2f} {full:24} nessuna alternativa -> tengo')
            continue
        new_ratio = pick['w'] / max(pick['h'], 1)
        same = pick['title'] == cover_file or pick['title'] == ('File:' + cover_file)
        if same or new_ratio < VERT_THRESHOLD or (new_ratio - ratio) < MIN_GAIN:
            skipped_novel += 1
            print(f'  [=] {art.stem[:40]:40} ratio {ratio:.2f} {full:24} alt ratio {new_ratio:.2f} non migliore -> tengo')
            continue
        # Applica
        print(f'  [+] {art.stem[:40]:40} {ratio:.2f} -> {new_ratio:.2f}  {full:20} {pick["title"][5:55]}')
        if dry:
            changed += 1
            continue
        dest = COVERS_DIR / f'{art.stem}.jpg'
        try:
            download(pick['url'], dest)
        except Exception as e:
            print(f'       download fallito: {e}')
            continue
        credit = build_credit(pick)
        _set_cover(art, f'/covers/{art.stem}.jpg', credit, pick['title'])
        changed += 1

    print(f'\n=== {"DRY-RUN " if dry else ""}rigenerate {changed} cover | '
          f'gia orizzontali {skipped_novert}, senza alternativa landscape '
          f'{skipped_noalt + skipped_novel} ===', flush=True)


if __name__ == '__main__':
    main()
