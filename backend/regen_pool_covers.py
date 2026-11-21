#!/usr/bin/env python3
"""Rigenera le cover degli articoli con UNICITA' garantita.

Problema: articoli vecchi (soprattutto match ITF senza foto dei giocatori)
hanno cover ripetute o poco pertinenti (stessi stadi vuoti). Questo script
riassegna le cover riusando la stessa catena di write_article
(foto favorito -> foto altro giocatore -> P18 entity -> POOL d'azione ->
venue), ma con un dedup GLOBALE incrementale che accumula man mano: due
articoli non ricevono mai la stessa foto finche' il materiale basta.

Preserva le cover che sono gia' foto di un giocatore reale del match
(quelle vanno bene e sono pertinenti). Rigenera solo quelle generiche
(venue o pool) o duplicate.

Uso:
  python3 regen_pool_covers.py [--date YYYY-MM-DD ...] [--all] [--dry-run]

Senza argomenti: rigenera gli articoli degli ultimi 7 giorni.
"""
from __future__ import annotations
import sys, re, argparse, shutil
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attach_covers import (
    COVERS_DIR, detect_winner, pick_image, pick_venue, download,
    used_covers_for_player, resolve_full, build_credit, entity_photo,
    cover_file_is_player,
)
from pool_cover import pick_from_pool

ROOT = Path(__file__).resolve().parent.parent
ARTS = ROOT / 'src/content/articoli'

import unicodedata


def _norm(s: str) -> str:
    """Minuscolo senza accenti, per confronti robusti sui cognomi/titoli."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


# Titoli chiaramente non pertinenti come cover editoriale moderna: foto
# d'archivio storiche (anni 1800-1989), scansioni di libri/illustrazioni,
# tabelloni risultati, archivi nazionali. Applicato agli step che pescano
# LIVE da Commons (non al pool, gia' curato).
_BAD_COVER = re.compile(
    r'\b(18\d\d|19[0-8]\d)\b|hilversum|noordwijk|anefo|nationaal|statelib'
    r'|state lib|results|scoreboard|tabellone|nummer|in actie|spelend'
    r'|madchen|aufschlag|squash|racquets, tennis|drawing|sketch|engrav'
    r'|lithograph|illustrat|postcard|cigarette card|museum|library|archiv',
    re.I)


def _cover_ok(title: str) -> bool:
    return bool(title) and not _BAD_COVER.search(_norm(title))


def parse_fm(txt: str) -> dict:
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', txt, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ':' not in line or line.startswith(' '):
            continue
        k, _, v = line.partition(':')
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def set_fm_field(txt: str, key: str, value: str) -> str:
    """Sostituisce o inserisce un campo nel frontmatter."""
    pat = re.compile(rf'^{re.escape(key)}:.*$', re.M)
    line = f'{key}: "{value}"'
    if pat.search(txt):
        return pat.sub(line, txt, count=1)
    # inserisci prima della chiusura ---
    return re.sub(r'\n---\s*\n', f'\n{line}\n---\n', txt, count=1)


def is_player_cover(fm: dict) -> bool:
    """La cover attuale e' gia' una foto di un giocatore del match?"""
    cf = fm.get('cover_file', '')
    g1, g2 = fm.get('giocatore1', ''), fm.get('giocatore2', '')
    if not cf:
        return False
    try:
        return cover_file_is_player(cf, g1, g2)
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', nargs='*', default=[])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    # Selezione articoli
    if args.all:
        files = sorted(ARTS.glob('*.md'))
    elif args.date:
        files = []
        for d in args.date:
            files += sorted(ARTS.glob(f'{d}-*.md'))
    else:
        # ultimi 7 giorni
        oggi = date.today()
        giorni = {(oggi - timedelta(days=i)).isoformat() for i in range(8)}
        files = sorted(f for f in ARTS.glob('*.md')
                       if any(f.name.startswith(g) for g in giorni))

    # Dedup GLOBALE: parte dalle cover-giocatore gia' valide di TUTTI gli
    # articoli (quelle le teniamo), cosi' il pool non ne duplica nessuna.
    used_global: set[str] = set()
    for f in ARTS.glob('*.md'):
        fm = parse_fm(f.read_text(encoding='utf-8'))
        cf = fm.get('cover_file', '')
        if cf and is_player_cover(fm):
            used_global.add(cf)

    rigenerati, tenuti, falliti = 0, 0, 0
    for f in sorted(files):
        txt = f.read_text(encoding='utf-8')
        fm = parse_fm(txt)
        if fm.get('giocatore1') == 'Redazione':
            continue  # news/recap: niente cover-match
        slug = f.stem

        # Tieni le cover che sono gia' foto di un giocatore del match.
        if is_player_cover(fm):
            cf = fm.get('cover_file', '')
            if cf:
                used_global.add(cf)
            tenuti += 1
            continue

        p1, p2 = fm.get('giocatore1', ''), fm.get('giocatore2', '')
        verdetto = fm.get('verdetto', '')
        torneo = fm.get('torneo', '')
        fav, conf = detect_winner(verdetto, p1, p2)

        pick = None
        from_pool = False
        # 1-2. foto dei giocatori del match.
        # REGOLA ANTI-ROBACCIA: accetta la foto SOLO se il titolo contiene il
        # cognome del giocatore cercato. pick_image, per i match ITF con
        # giocatori senza foto propria, ripiega su risultati generici/storici
        # (es. "Yanina Wickmayer" per un match Abouelsaad/Lukosiute, o foto
        # d'archivio anni 60): quelli NON sono pertinenti e vanno scartati a
        # favore del pool curato.
        for cand in ([fav] if (fav and conf != 'equilibrio') else []) + [p1, p2]:
            if not cand:
                continue
            full = resolve_full(cand)
            if full:
                cognome = _norm(full.split()[-1])
                excl = used_covers_for_player(full.split()[-1], skip_slug=slug) | used_global
                cand_pick = pick_image(full, slug_hint=slug, exclude=excl)
                if cand_pick and cognome and cognome in _norm(cand_pick.get('title', '')):
                    pick = cand_pick
                    break
        # 2-bis. P18 entity (foto ufficiale Wikidata del giocatore): tenuta
        # solo se non e' un titolo storico/non pertinente.
        if not pick:
            for cand in (fav, p1, p2):
                if cand:
                    cand_pick = entity_photo(cand, exclude=used_global)
                    if cand_pick and _cover_ok(cand_pick.get('title', '')):
                        pick = cand_pick
                        break
        # 3. POOL d'azione curato (unicita' garantita dal dedup globale)
        if not pick:
            pick = pick_from_pool(slug_hint=slug, exclude=used_global)
            from_pool = bool(pick)
        # 4. venue (ultima spiaggia), comunque filtrato
        if not pick:
            cand_pick = pick_venue(torneo, slug_hint=slug, exclude=used_global)
            if cand_pick and _cover_ok(cand_pick.get('title', '')):
                pick = cand_pick

        if not pick:
            falliti += 1
            print(f'  [SKIP] {slug}: nessuna cover trovata')
            continue

        title = pick.get('title', '')
        if args.dry_run:
            print(f'  [dry] {slug} <- {title[:55]}')
            used_global.add(title)
            rigenerati += 1
            continue

        dest = COVERS_DIR / f'{slug}.jpg'
        try:
            if from_pool and pick.get('pool_src'):
                shutil.copyfile(pick['pool_src'], dest)
                credit = pick.get('credit', '')
            else:
                download(pick['url'], dest)
                credit = build_credit(pick)
            txt = set_fm_field(txt, 'cover_image', f'/covers/{slug}.jpg')
            txt = set_fm_field(txt, 'cover_credit', credit)
            txt = set_fm_field(txt, 'cover_file', title)
            f.write_text(txt, encoding='utf-8')
            used_global.add(title)
            rigenerati += 1
            print(f'  [OK]  {slug} <- {title[:55]}')
        except Exception as e:
            falliti += 1
            print(f'  [ERR] {slug}: {e}')

    print(f'\n[regen] rigenerati={rigenerati} tenuti(foto-giocatore)={tenuti} falliti={falliti}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
