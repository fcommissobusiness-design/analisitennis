#!/usr/bin/env python3
"""Gate di PERTINENZA VISIVO delle cover: guarda davvero la foto (non solo
il titolo del file) e decide se e' adatta come copertina di un articolo di
tennis. Le euristiche title-based di attach_covers/audit_covers non possono
sapere che "Shameen Tennis Ground.jpg" ritrae una strada o che una foto e'
una premiazione juniores: serve un occhio.

Come funziona:
- per ogni articolo (filtrabile per --date) prende la cover,
- chiede a claude CLI (vision) un verdetto SI/NO + motivo breve,
- su NO prova a rigenerare la cover (logica audit_covers) e ri-controlla,
- se resta NO dopo il tentativo, la segnala nel report per revisione manuale
  (non blocca la pipeline: meglio una cover debole che un articolo senza
  immagine).

Output: backend/cover_vet.json. Exit 0 sempre (gate non bloccante).

Uso:
  python3 vet_covers.py --date=2026-10-27     # solo gli articoli del giorno
  python3 vet_covers.py                        # tutti (lento: 1 call/cover)
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from attach_covers import (parse_frontmatter, NAME_MAP, pick_image, S,
                           download, strip_html, update_frontmatter, COVERS_DIR,
                           used_covers_for_player, entity_photo,
                           all_used_cover_files)
from audit_covers import regenerate_cover, ARTICOLI, ROOT
from pool_cover import gender_from_categoria

# L'ultima spiaggia, quando ne' foto giocatore ne' venue passano il vet (il
# caso tipico: un W15 tra due sconosciute, di cui non esiste nessuna foto),
# e' il POOL LOCALE di immagini NEUTRE: public/covers/pool/ + manifest.json,
# scelto da pool_cover.pick_from_pool.
#
# Prima c'era qui una lista CLEAN_COURTS di 9 campi su Commons. Rimossa il
# 27/11/26: guardate una per una erano TUTTE inadatte (panorami, campi
# amatoriali con auto parcheggiate, campi dietro recinzione, tribune vuote,
# un doppio, un backdrop col nome dell'evento). Il pool locale e' vagliato a
# vista immagine per immagine e non dipende dalla rete.


def _apply_pool(stem: str, pick: dict) -> str:
    """Applica una immagine del pool locale: e' gia' scaricata e
    ridimensionata, basta copiarla. Le derivate web dell'articolo vanno pero'
    rifatte, altrimenti il lettore continua a vedere la foto precedente."""
    import shutil
    from cover_image_utils import ensure_web_size, card_path
    dest = COVERS_DIR / f'{stem}.jpg'
    shutil.copyfile(pick['pool_src'], dest)
    for d in (dest.with_suffix('.webp'), card_path(dest)):
        try:
            if d.exists():
                d.unlink()
        except Exception:
            pass
    try:
        ensure_web_size(dest)
    except Exception:
        pass
    update_frontmatter(ARTICOLI / f'{stem}.md', f'/covers/{stem}.jpg',
                       pick.get('credit') or '', cover_file=pick.get('title', ''))
    return pick.get('title', '')


def _pick_neutro(stem: str, gender: str, forbidden) -> dict | None:
    """Immagine neutra dal pool locale, evitando quelle gia' in uso."""
    try:
        from pool_cover import pick_from_pool
        return pick_from_pool(slug_hint=stem, exclude=set(forbidden or ()),
                              gender=gender)
    except Exception:
        return None


def _fetch_commons(title: str):
    r = S.get('https://commons.wikimedia.org/w/api.php', params={
        'action': 'query', 'format': 'json', 'titles': title,
        'prop': 'imageinfo', 'iiprop': 'url|extmetadata'}, timeout=30)
    r.raise_for_status()
    p = list(r.json()['query']['pages'].values())[0]
    info = p['imageinfo'][0]
    em = info.get('extmetadata') or {}
    return {'title': p['title'], 'url': info['url'],
            'author': (em.get('Artist') or {}).get('value', ''),
            'license': (em.get('LicenseShortName') or {}).get('value', '')}


def _apply(stem: str, pick: dict) -> str:
    dest = COVERS_DIR / f'{stem}.jpg'
    download(pick['url'], dest)
    credit = (f"{pick['title'].replace('File:', '')} | "
              f"{strip_html(pick.get('author') or 'Autore sconosciuto')} | "
              f"{pick.get('license') or 'Wikimedia Commons'}")
    update_frontmatter(ARTICOLI / f'{stem}.md', f'/covers/{stem}.jpg', credit)
    return pick['title'][5:55]

CLAUDE_BIN = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')

PROMPT = (
    "Usa lo strumento Read per aprire l'immagine al percorso:\n{path}\n\n"
    "Devi decidere se e' adatta come COPERTINA di un articolo di tennis.\n"
    "Criterio: vogliamo una di queste tre cose.\n"
    "(a) un giocatore/giocatrice di tennis in AZIONE o almeno a mezza figura "
    "(dal busto in su, con la testa INTERA nell'inquadratura e racchetta/campo "
    "visibili);\n"
    "(b) un vero campo/arena da tennis durante il gioco;\n"
    "(c) un'immagine di tennis NEUTRA, cioe' SENZA persone riconoscibili, "
    "ripresa da VICINO e con il soggetto che RIEMPIE l'inquadratura: rete, "
    "linee, superficie di gioco, palline o racchetta sul campo, con buona luce "
    "e messa a fuoco. E' il ripiego per i match tra giocatori di cui non "
    "esistono foto, quindi va accettata quando e' curata e ordinata.\n\n"
    "Considerala ADATTA (SI) SOLO se mostra chiaramente una di queste cose.\n\n"
    "Considerala NON adatta (NO) se si verifica ANCHE SOLO UNA di queste:\n"
    "- Un PRIMO PIANO STRETTISSIMO del solo volto in cui non si capisce "
    "nemmeno che e' tennis (nessuna racchetta, nessun campo, nessun "
    "abbigliamento o contesto sportivo): NO. ATTENZIONE: un ritratto "
    "ravvicinato o un mezzobusto di un tennista, con un minimo di contesto "
    "sportivo (racchetta, campo, divisa, fascia, in campo), e' invece "
    "AMMESSO: fa una copertina pulita e va bene. Non bocciare un mezzobusto "
    "solo perche' e' ravvicinato.\n"
    "- La TESTA del giocatore e' TAGLIATA o fuori dall'inquadratura, o il "
    "soggetto e' tagliato male (si vedono solo gambe/busto senza testa).\n"
    "- Un CONCERTO, uno spettacolo, un palco, luci da evento, una folla a un "
    "evento: NO anche se e' dentro un'arena che a volte ospita il tennis.\n"
    "- Un TABELLONE, il punteggio, uno scoreboard o un display elettronico come "
    "soggetto principale o che OCCUPA gran parte dell'inquadratura: NO anche se "
    "e' un tabellone da tennis e sullo sfondo si intravede il campo.\n"
    "- Una FOLLA, gli spettatori o le TRIBUNE che DOMINANO la foto senza un "
    "giocatore chiaramente riconoscibile e in azione in primo piano: NO.\n"
    "- Una SCRITTA o un backdrop che DOMINA l'inquadratura come SOGGETTO "
    "PRINCIPALE, senza un giocatore o un campo in primo piano (es. un muro di "
    "loghi o un cartellone pubblicitario fotografato da solo): NO. ATTENZIONE: "
    "i normali CARTELLONI SPONSOR e le scritte sullo sfondo DIETRO a un "
    "giocatore in azione sono NORMALI nel tennis professionistico e si "
    "ACCETTANO senza problemi. Rifiuta SOLO se il testo e' cosi' grande e "
    "nitido da diventare esso stesso il soggetto della foto, oppure se nomina "
    "a chiare lettere e in grande un TORNEO o una CITTA' DIVERSI, al punto da "
    "far credere al lettore che l'articolo parli di un altro evento. Nel "
    "dubbio su una scritta sullo sfondo dietro a un giocatore, ACCETTA.\n"
    "- Una strada, un paesaggio urbano, un edificio generico o il suo esterno "
    "notturno, una cerimonia/premiazione, un altro sport, un gruppo di persone "
    "in giacca, un volto buio da conferenza, un logo o un cartellone.\n"
    "- Un PANORAMA o una veduta d'insieme di uno stadio/impianto ripreso da "
    "LONTANO, dall'ALTO o di LATO, con il campo piccolo o distante; un campo "
    "visto DIETRO una RETE, una RECINZIONE o una barriera; campi AMATORIALI o "
    "da circolo; AUTO PARCHEGGIATE, parcheggi, strade, case, idranti o edifici "
    "che occupano una parte non marginale dell'inquadratura; file di "
    "SEGGIOLINI o TRIBUNE VUOTE che dominano la foto: NO. NOTA BENE: un campo o "
    "un'arena da tennis VUOTO e' ammesso SOLO se ripreso da VICINO, ben "
    "illuminato, con rete, linee e superficie NITIDE che RIEMPIONO "
    "l'inquadratura e nessun elemento urbano o recinzione in evidenza; nel "
    "dubbio su un campo vuoto distante, recintato o con elementi urbani, "
    "rispondi NO.\n"
    "- Un match di DOPPIO (QUATTRO giocatori in campo contemporaneamente) come "
    "soggetto chiaro: NO, perche' gli articoli trattano SINGOLARI.\n"
    "- Una POSA STRANA, SCOMPOSTA o AMBIGUA, che possa risultare EQUIVOCA o "
    "SESSUALIZZABILE: gambe molto divaricate verso l'obiettivo, inquadratura "
    "che insiste su glutei, petto o inguine, accosciata o caduta a terra in "
    "posizione scomposta, gonna o abbigliamento sollevato, smorfia contorta o "
    "grottesca. Anche quando e' una normalissima azione di gioco: se "
    "l'immagine si puo' leggere in modo equivoco, o mette il soggetto in una "
    "posizione poco dignitosa, rispondi NO. Vale a maggior ragione per le "
    "GIOCATRICI. Nel dubbio su una posa, rispondi NO.\n"
    "- Qualunque cosa non chiaramente legata al tennis.\n\n"
    "In sintesi: siamo generosi su inquadratura e sfondo (un mezzobusto "
    "ravvicinato di un tennista va bene, i cartelloni sponsor dietro vanno "
    "bene), ma restiamo severi sulle DUE cose che contano: il SOGGETTO deve "
    "essere pertinente al match e la posa non deve essere equivoca o indegna. "
    "Nel dubbio tra una vera foto di gioco e un tabellone/una folla/delle "
    "tribune che dominano, rispondi NO.\n"
    "Rispondi ESATTAMENTE in questo formato su una riga:\n"
    "VERDETTO: SI|NO - MOTIVO: <massimo 10 parole>"
)


def _gender_clause(gender: str) -> str:
    """Clausola di genere appesa al prompt quando il genere del match e' noto.
    Boccia il caso classico (foto di un uomo su un match femminile e viceversa,
    es. un doppio maschile finito su un articolo WTA)."""
    if gender == 'W':
        return ("\n\nCONTESTO MATCH: l'articolo tratta un match FEMMINILE. La cover "
                "deve ritrarre una GIOCATRICE (donna) in azione/mezza figura, "
                "oppure un campo/arena da tennis. Se il soggetto in azione e' "
                "CHIARAMENTE un GIOCATORE UOMO, rispondi NO.")
    if gender == 'M':
        return ("\n\nCONTESTO MATCH: l'articolo tratta un match MASCHILE. La cover "
                "deve ritrarre un GIOCATORE (uomo) in azione/mezza figura, "
                "oppure un campo/arena da tennis. Se il soggetto in azione e' "
                "CHIARAMENTE una GIOCATRICE DONNA, rispondi NO.")
    return ""


def _players_clause(g1: str, g2: str) -> str:
    """Clausola di PERTINENZA DEL SOGGETTO. Una cover non deve mai ritrarre un
    tennista diverso dai due protagonisti: il lettore crederebbe che il soggetto
    sia uno dei due (es. Kerber messa su un articolo Lacinova-Obradovic, 26/11).
    Le immagini senza persone identificabili restano sempre ammesse."""
    names = ' e '.join(n for n in (g1 or '', g2 or '') if n.strip())
    if not names:
        return ""
    return ("\n\nPROTAGONISTI DEL MATCH: " + names + ". La cover NON deve "
            "ritrarre in modo riconoscibile un tennista o una tennista DIVERSO "
            "da loro: sarebbe una foto non pertinente, che fa credere al lettore "
            "che il soggetto sia uno dei due protagonisti. Se nella foto il "
            "volto di chi gioca e' nitido e riconoscibile e NON corrisponde a "
            "nessuno dei due nomi qui sopra, rispondi NO. Le immagini SENZA "
            "persone identificabili (campo, rete, attrezzatura, soggetto di "
            "spalle o troppo lontano per essere riconosciuto) restano ammesse.")


def _gender_for(fm: dict) -> str:
    """Genere atteso: prima dalla categoria (WTA/ATP/Challenger), poi dal CODICE
    del torneo negli ITF (W50/W15 = femminile, M25/M15 = maschile), infine dai
    tag se presenti. NB: parse_frontmatter non legge le liste YAML, quindi 'tag'
    e' spesso stringa vuota: il codice torneo e' il segnale affidabile per gli ITF."""
    g = gender_from_categoria(fm.get('categoria', ''))
    if g:
        return g
    torneo = (fm.get('torneo') or '')
    m = re.match(r'\s*([WM])\s*\d', torneo, re.I)
    if m:
        return 'W' if m.group(1).upper() == 'W' else 'M'
    blob = (str(fm.get('tag') or '') + ' ' + torneo).lower()
    if 'femminile' in blob or 'wta' in blob:
        return 'W'
    if 'maschile' in blob or 'atp' in blob or 'challenger' in blob:
        return 'M'
    return ''


def vet_image(path: Path, gender: str = '', timeout=120, players=('', '')) -> tuple[bool, str]:
    """Ritorna (pertinente, motivo). In caso di errore CLI -> (True, 'skip')
    per non bloccare: non vogliamo perdere una cover buona per un glitch.
    `players` = (giocatore1, giocatore2) per il gate di pertinenza del soggetto."""
    try:
        prompt = (PROMPT.format(path=path) + _gender_clause(gender)
                  + _players_clause(players[0] if players else '',
                                    players[1] if len(players) > 1 else ''))
        r = subprocess.run(
            [CLAUDE_BIN, '-p', prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (r.stdout or '').strip()
        m = re.search(r'VERDETTO:\s*(SI|NO)\s*-\s*MOTIVO:\s*(.*)', out, re.I)
        if not m:
            # Fallback: cerca un SI/NO secco
            if re.search(r'\bNO\b', out) and not re.search(r'\bSI\b', out):
                return False, out[:80]
            return True, 'parse incerto, tenuta'
        return (m.group(1).upper() == 'SI'), m.group(2).strip()[:80]
    except Exception as e:
        return True, f'vet skip ({type(e).__name__})'


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _source_title(fm: dict) -> str:
    """Titolo Commons attualmente assegnato alla cover, in forma 'File:...'.
    Prima da cover_file, poi dal primo token di cover_credit."""
    cf = (fm.get('cover_file') or '').strip()
    if cf:
        return cf if cf.startswith('File:') else 'File:' + cf
    cred = (fm.get('cover_credit') or '').split('|')[0].strip()
    return ('File:' + cred) if cred else ''


def _reresolve_distinct(art: Path, forbidden: set) -> str:
    """Assegna all'articolo una cover DIVERSA da tutte quelle in `forbidden`,
    ri-controllata dal vet. Ordine: foto giocatore mappato -> P18 Wikidata ->
    campo pulito non ancora usato. Ritorna il titolo 'File:...' scelto, o ''."""
    stem = art.stem
    fm, _ = parse_frontmatter(art)
    gender = _gender_for(fm)
    cover = ROOT / 'public' / (fm.get('cover_image') or '').lstrip('/')
    g1, g2 = fm.get('giocatore1', ''), fm.get('giocatore2', '')

    def _try(pick) -> str:
        if not pick or not pick.get('title') or pick['title'] in forbidden:
            return ''
        _apply(stem, pick)
        ok, _m = vet_image(cover, gender, players=(g1, g2))
        return pick['title'] if ok else ''

    for g in (g1, g2):
        full = NAME_MAP.get(g)
        if not full:
            continue
        excl = used_covers_for_player(full.split()[-1], skip_slug=stem) | set(forbidden)
        try:
            pick = pick_image(full, slug_hint=stem, exclude=excl)
        except Exception:
            pick = None
        r = _try(pick)
        if r:
            return r
    for g in (g1, g2):
        full = NAME_MAP.get(g)
        if not full:
            continue
        excl = used_covers_for_player(full.split()[-1], skip_slug=stem) | set(forbidden)
        try:
            ph = entity_photo(full, exclude=excl)
        except Exception:
            ph = None
        r = _try(ph)
        if r:
            return r
    # Ultima spiaggia: il pool locale di immagini NEUTRE. E' una raccolta
    # curata, vagliata a vista una per una, quindi non la si ri-sottopone al
    # gate: costerebbe una chiamata di visione per articolo senza dire niente
    # di nuovo. Chi tocca il pool deve vagliare prima.
    pick = _pick_neutro(stem, gender, forbidden)
    if pick and pick.get('pool_src'):
        return _apply_pool(stem, pick)
    return ''


def dedup_run(articoli) -> list:
    """Sweep anti-doppione di fine run: se due o piu' articoli condividono la
    STESSA immagine di cover (md5 identico), tiene il primo e ri-risolve gli
    altri con una cover DIVERSA, escludendo ogni sorgente gia' in uso nel run.
    Cosi' due match dello stesso giorno non ricevono mai la stessa copertina
    (es. il caso Trevisan/Allen = stesso panorama Rio del 26/11)."""
    by_hash: dict = {}
    used_titles: set = set()
    for art in articoli:
        fm, _ = parse_frontmatter(art)
        if not fm:
            continue
        rel = (fm.get('cover_image') or '').lstrip('/')
        if not rel:
            continue
        p = ROOT / 'public' / rel
        if not p.exists():
            continue
        by_hash.setdefault(_md5(p), []).append(art)
        t = _source_title(fm)
        if t:
            used_titles.add(t)
    fixed = []
    for arts in by_hash.values():
        if len(arts) < 2:
            continue
        for art in arts[1:]:
            newt = _reresolve_distinct(art, used_titles)
            if newt:
                used_titles.add(newt)
                fixed.append(art.stem)
                print(f'  [DEDUP] {art.stem[:50]} -> {newt[5:50]}', flush=True)
            else:
                print(f'  [DEDUP] {art.stem[:50]} -> nessuna alternativa trovata', flush=True)
    return fixed


def main():
    args = sys.argv[1:]
    date = None
    only = None
    for a in args:
        if a.startswith('--date='):
            date = a.split('=', 1)[1]
        elif a.startswith('--only='):
            only = a.split('=', 1)[1].lower()
    pattern = f'{date}-*.md' if date else '2026-*.md'
    articoli = [a for a in sorted(ARTICOLI.glob(pattern)) if 'benvenuti' not in a.name]
    if only:
        articoli = [a for a in articoli if only in a.stem.lower()]

    report = []
    ko = 0
    for art in articoli:
        fm, _ = parse_frontmatter(art)
        if not fm:
            continue
        cover_rel = (fm.get('cover_image') or '').lstrip('/')
        if not cover_rel:
            continue
        cover = ROOT / 'public' / cover_rel
        if not cover.exists():
            continue
        gender = _gender_for(fm)
        players = (fm.get('giocatore1', ''), fm.get('giocatore2', ''))
        ok, motivo = vet_image(cover, gender, players=players)
        entry = {'slug': art.stem, 'ok': ok, 'motivo': motivo}
        if ok:
            print(f'  [SI] {art.stem[:50]}', flush=True)
            report.append(entry)
            continue

        print(f'  [NO] {art.stem[:50]} - {motivo}', flush=True)
        stem = art.stem
        fm2, _ = parse_frontmatter(art)
        g1, g2 = fm2.get('giocatore1', ''), fm2.get('giocatore2', '')

        # Escalation di auto-correzione, ogni passo ri-controllato dal vet:
        # 1) rigenera con la logica standard (favorito/venue),
        # 2) forza una foto del giocatore mappato (g1 poi g2),
        # 3) ultima spiaggia: un campo da tennis pulito e inequivocabile.
        attempts = []

        gen_ok, gen_msg = regenerate_cover(art)
        if gen_ok:
            ok2, m2 = vet_image(cover, gender, players=players)
            attempts.append(('rigenera', gen_msg[:40], ok2, m2))
            if ok2:
                entry.update({'ok': True, 'risolta_con': 'rigenera'})
                print(f'         -> rigenerata: risolta', flush=True)
                report.append(entry); continue

        cur_title = (fm2.get('cover_credit') or '').split('|')[0].strip()
        for g in (g1, g2):
            full = NAME_MAP.get(g)
            if not full:
                continue
            # Escludi la foto appena bocciata e quelle gia' usate per lui.
            excl = used_covers_for_player(full.split()[-1], skip_slug=stem)
            if cur_title:
                excl.add('File:' + cur_title)
            try:
                pick = pick_image(full, slug_hint=stem, exclude=excl)
            except Exception:
                pick = None
            if not pick:
                continue
            t = _apply(stem, pick)
            ok3, m3 = vet_image(cover, gender, players=players)
            attempts.append(('giocatore:' + full, t, ok3, m3))
            if ok3:
                entry.update({'ok': True, 'risolta_con': 'giocatore ' + full})
                print(f'         -> foto {full}: risolta', flush=True)
                break
        if entry['ok']:
            report.append(entry); continue

        # Step P18: foto canonica Wikidata del giocatore (persona verificata),
        # provata PRIMA del campo di ripiego. Una cover bocciata da scoreboard/
        # folla ha comunque il giocatore giusto: meglio la sua foto ufficiale
        # che un campo neutro. Si prova g1 poi g2.
        for g in (g1, g2):
            full = NAME_MAP.get(g)
            if not full:
                continue
            excl = used_covers_for_player(full.split()[-1], skip_slug=stem)
            if cur_title:
                excl.add('File:' + cur_title)
            try:
                ph = entity_photo(full, exclude=excl)
            except Exception:
                ph = None
            if not ph or not ph.get('url'):
                continue
            t = _apply(stem, ph)
            okP, mP = vet_image(cover, gender, players=players)
            attempts.append(('p18:' + full, t, okP, mP))
            if okP:
                entry.update({'ok': True, 'risolta_con': 'P18 ' + full})
                print(f'         -> P18 {full}: risolta', flush=True)
                break
        if entry['ok']:
            report.append(entry); continue

        # Ultima spiaggia: immagine NEUTRA dal pool locale, variata per slug
        # cosi' articoli diversi non ricevono la stessa. E' gia' vagliata a
        # vista, quindi non si ripassa dal gate.
        try:
            used = all_used_cover_files(skip_slug=stem)
            pick = _pick_neutro(stem, gender, used)
            if pick and pick.get('pool_src'):
                t = _apply_pool(stem, pick)
                attempts.append(('neutra', t, True, 'pool neutro'))
                entry['ok'] = True
                entry['risolta_con'] = 'immagine neutra'
                print('         -> immagine neutra: risolta', flush=True)
            else:
                attempts.append(('neutra', '', False, 'pool neutro vuoto'))
        except Exception as e:
            attempts.append(('neutra', f'errore {e}', False, ''))

        entry['attempts'] = [{'via': a, 'file': f, 'ok': o, 'motivo': m} for a, f, o, m in attempts]
        if not entry['ok']:
            ko += 1
            print(f'         -> ANCORA NO dopo {len(attempts)} tentativi (revisione manuale)', flush=True)
        report.append(entry)

    # Sweep anti-doppione: nessun articolo dello stesso giorno deve avere la
    # stessa identica cover di un altro.
    deduped = dedup_run(articoli)

    (ROOT / 'backend' / 'cover_vet.json').write_text(
        json.dumps({'date': date, 'total': len(report), 'da_rivedere': ko,
                    'deduplicati': deduped, 'details': report}, indent=2,
                   ensure_ascii=False))
    print(f'\n=== VET: {len(report)} cover controllate, {ko} da rivedere a mano, '
          f'{len(deduped)} doppioni risolti ===', flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
