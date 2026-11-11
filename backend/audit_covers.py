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
    parse_frontmatter, update_frontmatter, _looks_tennis, _is_venue_photo,
    used_covers_for_player, cover_file_is_player, entity_photo,
)
from cover_image_utils import ensure_web_size, needs_resize
import hashlib
from collections import defaultdict

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
    # Titolo Commons della foto (campo frontmatter `cover_file`). NB: piu' sotto
    # la variabile `cover_file` viene riusata per il PATH del file immagine in
    # public/, quindi qui teniamo un nome distinto (il path contiene lo slug,
    # che include i cognomi dei giocatori: userebbe un falso match).
    cover_file_title = fm.get('cover_file', '')

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

    # 5. Verdetto favorito -> la cover e' coerente col match?
    #
    # IMPORTANTE: "cosa ritrae la foto" (giocatore / venue / contesto tennis)
    # va deciso sul TITOLO COMMONS del file, non sul credit. Dal passaggio al
    # credit breve ("Autore / Licenza / Wikimedia Commons") il campo
    # cover_credit non contiene piu' il nome del file, quindi un controllo
    # basato sul credit scambiava a torto per "non giocatore / non venue" sia
    # le foto corrette dei giocatori (es. "Carlos Alcaraz (2026 US Open).jpg")
    # sia i venue legittimi (es. "Nungambakkam SDAT Tennis Stadium.jpg"), e li
    # faceva sostituire: da li' partiva la catena che finiva su un campo
    # generico ripetuto su piu' articoli. Il titolo vero e' in cover_file;
    # per gli articoli vecchi (credit lungo "Titolo | Autore | Licenza")
    # ripieghiamo sul primo segmento del credit.
    fav, conf = detect_winner(verdetto, g1, g2)
    if fav and conf != 'equilibrio':
        full = NAME_MAP.get(fav)
        detect_title = (cover_file_title or (result['credit'] or '').split('|')[0]).strip()

        is_player = cover_file_is_player(detect_title, g1, g2)
        is_venue = bool(detect_title) and _is_venue_photo(detect_title)
        looks_t = _looks_tennis(detect_title)

        if is_player:
            # La cover e' gia' una foto di uno dei due giocatori del match
            # (puo' essere l'altro, usato quando il favorito ha solo primi
            # piani bocciati dal vet): valida, non e' ne' obsoleta ne' venue.
            result['problems'].append('[info] cover = foto giocatore del match')
        elif is_venue or looks_t:
            # Venue vero o titolo con contesto tennis: scelta valida (spesso il
            # favorito ha solo primi piani bocciati dal vet e si usa il venue).
            result['problems'].append(
                f'[info] favorito {fav}: venue/contesto tennis "{detect_title[:50]}"'
            )
        elif full:
            # Favorito mappato, ma la cover non e' ne' lui ne' venue ne' tennis:
            # se esiste una foto propria del favorito, la cover va rifatta.
            try:
                probe = pick_image(full)
            except Exception:
                probe = None
            result['ok'] = False
            if probe:
                result['problems'].append(
                    f'cover obsoleta: foto propria di {full} disponibile su Commons '
                    f'("{probe["title"][:60]}") ma cover attuale e\' "{detect_title[:60]}"'
                )
            else:
                result['problems'].append(
                    f'favorito {fav} ({full}): no foto Commons e cover non e\' '
                    f'venue tennis chiaro ("{detect_title[:60]}")'
                )
        else:
            # Favorito non mappato e cover ne' giocatore ne' venue ne' tennis.
            result['ok'] = False
            result['problems'].append(
                f'favorito {fav} non mappato in NAME_MAP e cover non e\' '
                f'ne\' foto di un giocatore del match ne\' venue tennis: "{detect_title[:70]}"'
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
    tried = set()
    # 1. foto del favorito (se il match non e' dato in equilibrio).
    #    exclude = foto gia' usate per lui altrove: variazione tra articoli.
    if fav and conf != 'equilibrio':
        full = NAME_MAP.get(fav)
        if full:
            tried.add(fav)
            excl = used_covers_for_player(full.split()[-1], skip_slug=slug)
            pick = pick_image(full, slug_hint=slug, exclude=excl)
    # 2. foto dell'altro protagonista del match (o di uno dei due se
    #    equilibrio): un vero giocatore della partita e' sempre piu'
    #    pertinente di un venue generico, ed evita cover duplicate.
    if not pick:
        for cand in (g1, g2):
            if cand in tried:
                continue
            full = NAME_MAP.get(cand)
            if full:
                excl = used_covers_for_player(full.split()[-1], skip_slug=slug)
                pick = pick_image(full, slug_hint=slug, exclude=excl)
                if pick:
                    break
    # 2-bis. Rete di sicurezza Wikidata: foto canonica P18 di uno dei due
    #    giocatori PRIMA del venue (qui NAME_MAP e' parziale, quindi entity_photo
    #    - che risolve anche dai profili - recupera molti casi che finivano su un
    #    venue sbagliato/estero o su un omonimo non-tennista).
    if not pick:
        for cand in (fav, g1, g2):
            if not cand:
                continue
            pick = entity_photo(cand)
            if pick:
                break
    # 3. ultima spiaggia: venue del torneo. slug_hint diversifica
    #    articoli diversi dello stesso torneo (anti-duplicato).
    if not pick:
        pick = pick_venue(torneo, slug_hint=slug)
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


def _audit_duplicates(articoli: list[Path]) -> dict[str, str]:
    """Cerca cover duplicate su piu' articoli con favoriti DIVERSI.
    Se la stessa foto appare su match con favoriti incompatibili, almeno
    una delle due e' sbagliata. Scansiona SEMPRE l'intera cartella articoli
    (anche se il run e' filtrato per data) perche' il duplicato puo'
    coinvolgere articoli di giorni diversi.

    Ritorna {slug_articolo: motivo_duplicato} per gli articoli di oggi che
    condividono cover con un articolo di un altro match con favorito
    diverso.
    """
    # Scan completo per hash
    all_articoli = sorted(ARTICOLI.glob('2026-*.md'))
    hash_to_arts = defaultdict(list)
    for art in all_articoli:
        fm, _ = parse_frontmatter(art)
        if not fm:
            continue
        cover_rel = fm.get('cover_image', '').lstrip('/')
        if not cover_rel:
            continue
        cover_file = ROOT / 'public' / cover_rel
        if not cover_file.exists() or not cover_file.is_file():
            continue
        h = hashlib.md5(cover_file.read_bytes()).hexdigest()[:12]
        fav, _conf = detect_winner(fm.get('verdetto', ''), fm.get('giocatore1', ''), fm.get('giocatore2', ''))
        credit = fm.get('cover_credit', '')
        torneo = fm.get('torneo', '')
        hash_to_arts[h].append((art.stem, fav or '', credit, torneo))

    flagged = {}
    for h, lst in hash_to_arts.items():
        if len(lst) < 2:
            continue
        favoriti = {f for _, f, _, _ in lst if f}
        tornei = {t for _, _, _, t in lst if t}
        credit0 = lst[0][2] or ''
        cred_title0 = credit0.split('|')[0] if credit0 else ''
        is_shared_venue = (
            len(tornei) == 1
            and cred_title0
            and _is_venue_photo(cred_title0)
        )
        # Cover venue identica su stesso torneo = tecnicamente non "sbagliata"
        # ma visivamente povera: 3-4 articoli uguali nella homepage. Forziamo
        # variazione passando lo slug_hint a pick_venue nel --fix.
        if is_shared_venue:
            motivo = (f'cover venue identica su {len(lst)} articoli dello stesso torneo '
                      f'({next(iter(tornei))}); varia con slug_hint per diversificare')
            # Flag TUTTI tranne il primo (il primo tiene la foto, gli altri cambiano)
            for stem, _f, _c, _t in lst[1:]:
                flagged[stem] = motivo
            continue
        if len(favoriti) >= 2 or (len(favoriti) == 0 and len(lst) >= 2):
            motivo = (f'cover duplicata su {len(lst)} articoli con favoriti diversi '
                      f'({", ".join(sorted(f for f in favoriti if f)) or "nessuno chiaro"}); '
                      f'molto probabilmente la foto non c\'entra con il match')
            for stem, _f, _c, _t in lst:
                flagged[stem] = motivo
    return flagged


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

    # Scan duplicati su TUTTI gli articoli (indipendentemente dal filtro date)
    dup_flags = _audit_duplicates(articoli)

    # Gate PESO: normalizza ogni cover a misura web PRIMA dell'audit. E'
    # idempotente (no-op se gia' sotto 1600px e 400KB), quindi gira sempre,
    # anche senza --fix: una cover pertinente ma da 15 MB non deve mai
    # arrivare online. Le cover appena scaricate da download() sono gia'
    # ridotte; questo cattura i file storici o quelli reintrodotti a mano.
    for art in articoli:
        fm, _ = parse_frontmatter(art)
        if not fm:
            continue
        cover_rel = (fm.get('cover_image') or '').lstrip('/')
        if not cover_rel:
            continue
        cf = ROOT / 'public' / cover_rel
        if cf.exists() and needs_resize(cf):
            res = ensure_web_size(cf)
            if res.get('ok'):
                print(f'  [RESIZE] {cf.name}: {res.get("before")} -> {res.get("after")}', flush=True)

    results = []
    problems = 0
    for art in articoli:
        r = audit_one(art)
        # Overlay flag duplicati
        if r['slug'] in dup_flags:
            r['ok'] = False
            r['problems'].append(dup_flags[r['slug']])
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
