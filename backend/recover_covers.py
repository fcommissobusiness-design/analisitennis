#!/usr/bin/env python3
"""Re-copertina gli articoli con foto DUPLICATA, VECCHIA o non pertinente.

Regole (richiesta esplicita dell'utente):
- nessuna foto ripetuta tra articoli diversi (dedup globale)
- niente foto di molti anni fa quando ne esiste una recente del giocatore
- preferire la foto del giocatore al venue (meno "stadi che giocatori")

Elabora gli articoli dal piu' RECENTE: gli articoli visibili e piu' importanti
per la SEO scelgono per primi la foto migliore; i piu' vecchi ripiegano.
Riscrive cover_credit (una riga) e cover_file. Il file cover (/covers/slug.jpg)
viene sovrascritto quando la foto cambia.
"""
import os
import re
import sys
import time
from pathlib import Path

DRY = bool(os.environ.get('DRY'))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attach_covers import (  # noqa: E402
    ARTICOLI, COVERS_DIR, parse_frontmatter, detect_winner,
    pick_image, pick_venue, download, build_credit, resolve_full, _anno_foto,
    _looks_tennis, VENUE_MAP,
)

ANNO_SOGLIA = 2018  # sotto a questo, una foto e' "vecchia" -> si prova a cambiarla


def _norm_surname(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z]', '', s.lower())


def _venue_pertinent(title: str, torneo: str) -> bool:
    """True se la foto-venue e' davvero un impianto da tennis pertinente:
    - contiene 'tennis' nel titolo (quasi tutti gli impianti veri lo hanno), OR
    - condivide un token (>=4 lettere) con l'IMPIANTO NOTO del torneo (VENUE_MAP).
    Non basta il nome-citta': a Sioux Falls un fiume ('Falls Park ... Sioux
    River') o un motel ('Plaza Courts Motel') condividono il token citta' ma
    non sono campi da tennis. Meglio tenere la cover attuale che metterli."""
    t = _norm_surname(title)  # solo lettere, minuscole, senza accenti
    if 'tennis' in t:
        return True
    venue_noto = VENUE_MAP.get(torneo, '') or ''
    tokens = set()
    for w in re.split(r'[^A-Za-z]+', venue_noto):
        wn = _norm_surname(w)
        if len(wn) >= 4 and wn not in ('open', 'tennis', 'club', 'arena',
                                       'center', 'centre', 'court', 'stadium',
                                       'tour', 'qualification', 'italy', 'france'):
            tokens.add(wn)
    return any(tok in t for tok in tokens)


def _title_has_player(title: str, p1: str, p2: str) -> bool:
    t = _norm_surname(title)
    for p in (p1, p2):
        last = _norm_surname(p.split()[-1]) if p else ''
        if len(last) >= 4 and last in t:
            return True
    return False


def _set_cover_fields(path: Path, credit: str, cover_file: str):
    raw = path.read_text()
    m = re.match(r'^---\n(.*?)\n---\n(.*)$', raw, re.S)
    if not m:
        return
    lines = m.group(1).splitlines()
    body = m.group(2)
    q = lambda s: s.replace('"', "'")
    out, seen_file = [], False
    for line in lines:
        if line.startswith('cover_credit:'):
            out.append(f'cover_credit: "{q(credit)}"')
        elif line.startswith('cover_file:'):
            out.append(f'cover_file: "{q(cover_file)}"')
            seen_file = True
        else:
            out.append(line)
    if not seen_file:
        for i, line in enumerate(out):
            if line.startswith('cover_credit:'):
                out.insert(i + 1, f'cover_file: "{q(cover_file)}"')
                break
    path.write_text('---\n' + '\n'.join(out) + '\n---\n' + body)


def main():
    arts = sorted(ARTICOLI.glob('2026-*.md'), reverse=True)  # piu' recenti prima
    used = set()          # File titles gia' assegnati (dedup globale)
    cambiati = 0
    tenuti = 0
    for art in arts:
        slug = art.stem
        fm, _ = parse_frontmatter(art)
        if not fm or not fm.get('cover_image'):
            continue
        g1, g2 = fm.get('giocatore1', ''), fm.get('giocatore2', '')
        if g1 == 'Redazione':
            continue
        torneo = fm.get('torneo', '')
        verdetto = fm.get('verdetto', '')
        cur_file = (fm.get('cover_file') or '').strip()
        if cur_file and not cur_file.startswith('File:'):
            cur_file = 'File:' + cur_file

        anno = _anno_foto(cur_file or '')
        is_dup = cur_file in used
        is_old = anno is not None and anno < ANNO_SOGLIA

        # Triggers CONSERVATIVI: ricopertina solo se la foto e' duplicata o
        # vecchia. Non forziamo venue->player (su nomi oscuri rischia foto
        # sbagliate, es. un monumento con lo stesso cognome).
        if not (is_dup or is_old):
            if cur_file:
                used.add(cur_file)
            tenuti += 1
            continue

        fav, conf = detect_winner(verdetto, g1, g2)
        cand_names = [fav] if (fav and conf != 'equilibrio') else []
        cand_names += [g1, g2]

        # Re-pick: prima un giocatore del match (recente, non gia' usato), ma
        # SOLO se la foto ha contesto tennis esplicito (evita omonimi/monumenti).
        pick = None
        for c in cand_names:
            if not c:
                continue
            full = resolve_full(c)
            if not full:
                continue
            cand = pick_image(full, slug_hint=slug, exclude=used)
            if cand and _looks_tennis(cand['title']):
                pick = cand
                break
        # Venue solo se PERTINENTE al torneo: meglio tenere l'attuale che
        # mettere l'impianto di un'altra citta' o un luogo a caso.
        if not pick:
            vpick = pick_venue(torneo, slug_hint=slug, exclude=used)
            if vpick and _venue_pertinent(vpick['title'], torneo):
                pick = vpick

        if not pick or pick['title'] in used:
            # Nessuna alternativa nuova: teniamo l'attuale (meglio di niente).
            if cur_file:
                used.add(cur_file)
            tenuti += 1
            continue

        motivo = 'dup' if is_dup else 'vecchia'
        if DRY:
            used.add(pick['title'])
            cambiati += 1
            print(f'[DRY] {slug}: {motivo} | {cur_file[5:40]:35s} -> {pick["title"][:60]}', flush=True)
            continue
        dest = COVERS_DIR / f'{slug}.jpg'
        try:
            download(pick['url'], dest)
        except Exception as e:
            print(f'[recover] download fallito {slug}: {e}')
            if cur_file:
                used.add(cur_file)
            continue
        credit = build_credit(pick)
        _set_cover_fields(art, credit, pick['title'])
        used.add(pick['title'])
        cambiati += 1
        print(f'[recover] {slug}: {motivo} -> {pick["title"][:60]}', flush=True)
        time.sleep(0.3)

    print(f'\n=== FATTO. Ricopertinati: {cambiati} | tenuti: {tenuti} ===')


if __name__ == '__main__':
    main()
