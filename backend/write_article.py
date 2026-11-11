"""Scrive l'articolo markdown finale in src/content/articoli/ con frontmatter corretto."""
import hashlib
import json
import os
import random
import re
import sys
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta

try:
    from attach_covers import (
        NAME_MAP, VENUE_MAP, COVERS_DIR, detect_winner,
        pick_image, pick_venue, download, strip_html, clean_author,
        used_covers_for_player, resolve_full, build_credit, all_used_cover_files,
        entity_photo
    )
    HAS_COVER = True
except Exception:
    HAS_COVER = False

try:
    from generate_profiles import ensure_profiles_for_match
    HAS_PROFILES = True
except Exception:
    HAS_PROFILES = False


def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^\w\s-]', '', s.lower())
    s = re.sub(r'[\s_-]+', '-', s).strip('-')
    return s[:80]


# --- Normalizzazione tipografica (regole di stile della testata) ---
# Il modello, quando lascia cadere l'accento, scrive le troncature accentate
# con un apostrofo ASCII ("piu'", "capacita'", "puo'") e ogni tanto usa il
# trattino lungo (em dash), entrambi vietati dallo stile. Qui si normalizza a
# monte, una volta per tutte, cosi' non vanno piu' corretti a mano a ogni run.
_ACUTE_E = {
    'perche': 'perché', 'poiche': 'poiché', 'finche': 'finché',
    'affinche': 'affinché', 'benche': 'benché', 'nonche': 'nonché',
    'giacche': 'giacché', 'sicche': 'sicché', 'cosicche': 'cosicché',
    'allorche': 'allorché', 'anziche': 'anziché', 'fuorche': 'fuorché',
}
# Troncature che MANTENGONO l'apostrofo (non sono accenti caduti).
_PROTECT_APOS = {"po'", "mo'", "be'", "to'"}
_VOW_GRAVE = {'a': 'à', 'o': 'ò', 'i': 'ì', 'u': 'ù'}


def _accenta_parola(tok):
    """'piu' -> 'più', 'perche' -> 'perché', protegge 'po''."""
    low = tok.lower()
    if low in _PROTECT_APOS:
        return tok
    lastv = tok[-2].lower()
    stem = tok[:-2]
    if lastv == 'e':
        rep = _ACUTE_E.get(low[:-1], stem + 'è')
    elif lastv in _VOW_GRAVE:
        rep = stem + _VOW_GRAVE[lastv]
    else:
        return tok
    if tok[0].isupper():
        rep = rep[0].upper() + rep[1:]
    return rep


def normalizza_tipografia(text):
    """Converte troncature con apostrofo ASCII in accenti veri e i trattini
    lunghi in virgole. Non tocca le elisioni (l', d', un', dell': finiscono in
    consonante) ne' le troncature legittime (po', mo')."""
    if not text:
        return text
    # parola che finisce in vocale + apostrofo ASCII
    text = re.sub(r"[A-Za-zàèéìòùÀÈÉÌÒÙ]*[aeiouAEIOU]'",
                  lambda m: _accenta_parola(m.group(0)), text)
    # trattino lungo (em dash U+2014) -> virgola, preservando la spaziatura
    text = (text.replace(' — ', ', ').replace(' —', ',')
                .replace('— ', ', ').replace('—', ', '))
    text = re.sub(r',\s*,', ',', text)
    return text


def categoria(tipo):
    t = (tipo or '').lower()
    if 'grand slam' in t: return 'Slam'
    if 'masters' in t: return 'Masters'
    # 'wta' PRIMA di 'challenger': i tornei WTA 125 sono femminili (tier
    # "challenger" lato donne) ma vanno etichettati WTA, non Challenger
    # (categoria maschile). Un Challenger maschile non contiene mai 'wta'.
    if 'wta' in t: return 'WTA'
    if 'challenger' in t: return 'Challenger'
    if 'itf' in t: return 'ITF'
    return 'ATP'


def superficie(torneo_name, tipo, anno=None):
    # PRIMA FONTE: l'archivio dei tornei verificati (fact_store). I profili
    # torneo sono stati controllati uno per uno su fonti ufficiali, quindi la
    # superficie che leggiamo li' e' un dato, non una supposizione.
    #
    # Prima qui c'era solo l'euristica a parole chiave qui sotto, con default
    # 'cemento': e' cosi' che il Challenger di Cali, che si gioca sulla terra
    # rossa, e' stato pubblicato per giorni come torneo su cemento, con
    # l'articolo che si contraddiceva da solo (il testo diceva terra).
    try:
        from fact_store import superficie_torneo
        verificata = superficie_torneo(torneo_name, anno)
        if verificata:
            return verificata
    except Exception as e:
        print(f'[superficie] archivio non disponibile ({e}), uso l\'euristica')

    # RIPIEGO: euristica a parole chiave, per i tornei che non hanno ancora un
    # profilo verificato. Resta una supposizione: ogni articolo che finisce
    # qui va considerato da controllare.
    n = (torneo_name or '').lower()
    # Erba
    if 'wimbledon' in n or 'halle' in n or 'queen' in n or 'eastbourne' in n \
       or "'s-hertogenbosch" in n or 'stuttgart' in n and 'wta' in n or 'newport' in n:
        return 'erba'
    # Terra rossa: Slam/Masters/500 europei + swing sudamericano (terra battuta)
    terra_tornei = (
        'roland', 'rome', 'roma', 'madrid', 'barcelon', 'monte', 'monaco',
        'hamburg', 'amburgo', 'munich', 'monaco di baviera', 'estoril', 'gstaad',
        'kitzbuhel', 'umag', 'bastad', 'geneva', 'ginevra', 'lyon', 'parma',
        # Swing sudamericano e altri tornei su terra
        'guayaquil', 'quito', 'lima', 'santa cruz', 'buenos aires', 'rio',
        'santiago', 'cordoba', 'bogota', 'medellin', 'campinas', 'florianopolis',
        'sao paulo', 'san paolo', 'concepcion', 'asuncion', 'montevideo',
        'marrakech', 'marrakesh', 'houston', 'casablanca',
    )
    if any(t in n for t in terra_tornei):
        return 'terra'
    if 'indoor' in n or ('paris' in n and 'bercy' in n):
        return 'indoor'
    return 'cemento'


def write(match, analysis, out_dir):
    titolo = normalizza_tipografia(analysis['titolo'])
    sottotitolo = normalizza_tipografia(analysis['sottotitolo'])
    descrizione = normalizza_tipografia(analysis['descrizione'])
    corpo = normalizza_tipografia(analysis['corpo_markdown'])
    verdetto = normalizza_tipografia(analysis['verdetto'])
    tag = [normalizza_tipografia(t) for t in analysis.get('tag', [])]

    p1 = match.get('event_first_player', '').strip()
    p2 = match.get('event_second_player', '').strip()
    data = match.get('event_date')
    torneo = match.get('tournament_name', '')
    cat = categoria(match.get('event_type_type'))
    anno_match = None
    try:
        anno_match = int(str(data)[:4])
    except (TypeError, ValueError):
        pass
    sup = superficie(torneo, match.get('event_type_type'), anno_match)

    slug_base = slugify(f"{p1}-vs-{p2}-{torneo}-pronostico-analisi")
    slug = f"{data}-{slug_base}"

    cover_image = None
    cover_credit = None
    cover_file = None
    if HAS_COVER:
        try:
            fav, conf = detect_winner(verdetto, p1, p2)
            pick = None
            tried = set()
            # Dedup GLOBALE: nessuna foto gia' usata in un altro articolo.
            used_global = all_used_cover_files(skip_slug=slug)
            # 1. foto del favorito (se il match non e' dato in equilibrio).
            #    exclude = foto gia' usate per lui + dedup globale: variazione.
            if fav and conf != 'equilibrio':
                full = resolve_full(fav)
                if full:
                    tried.add(fav)
                    excl = used_covers_for_player(full.split()[-1], skip_slug=slug) | used_global
                    pick = pick_image(full, slug_hint=slug, exclude=excl)
            # 2. foto dell'altro protagonista del match (o di uno dei due se
            #    equilibrio): un vero giocatore della partita e' sempre piu'
            #    pertinente di un venue generico, ed evita cover duplicate.
            if not pick:
                for cand in (p1, p2):
                    if cand in tried:
                        continue
                    full = resolve_full(cand)
                    if full:
                        excl = used_covers_for_player(full.split()[-1], skip_slug=slug) | used_global
                        pick = pick_image(full, slug_hint=slug, exclude=excl)
                        if pick:
                            break
            # 2-bis. Rete di sicurezza Wikidata: se la ricerca testuale non ha
            #    trovato un vero giocatore (nome non risolto, pochissime foto),
            #    usa la foto canonica P18 di uno dei due PRIMA del venue. Evita
            #    le cover non pertinenti (edifici, omonimi) per i giocatori
            #    agganciati al knowledge graph.
            if not pick:
                for cand in (fav, p1, p2):
                    if not cand:
                        continue
                    pick = entity_photo(cand, exclude=used_global)
                    if pick:
                        break
            # 3. ultima spiaggia: venue del torneo. slug_hint diversifica gli
            #    articoli dello stesso torneo; dedup globale evita venue ripetuti.
            if not pick:
                pick = pick_venue(torneo, slug_hint=slug, exclude=used_global)
            if pick:
                dest = COVERS_DIR / f'{slug}.jpg'
                try:
                    download(pick['url'], dest)
                    cover_image = f'/covers/{slug}.jpg'
                    cover_credit = build_credit(pick)
                    cover_file = pick['title']  # per il dedup globale (non mostrato)
                except Exception as e:
                    print(f'[cover] download fallito per {slug}: {e}')
        except Exception as e:
            print(f'[cover] errore per {slug}: {e}')

    fm = {
        'titolo': titolo,
        'sottotitolo': sottotitolo,
        'data': data,
        'autore': 'Redazione AnalisiTennis',
        'torneo': torneo,
        'categoria': cat,
        'superficie': sup,
        'giocatore1': p1,
        'giocatore2': p2,
        'tag': tag,
        'verdetto': verdetto,
        'descrizione': descrizione,
        'pubblicato': True
    }
    # Probabilita' di vittoria calcolata dal modello sui dati del match: numero
    # preciso e variabile (lo legge la griglia ProbabilitaVittoria in pagina).
    prob = analysis.get('probabilita') or {}
    fav = str(prob.get('favorito', '')).strip()
    try:
        pct = int(round(float(str(prob.get('percent_favorito', '')).strip().rstrip('%'))))
    except (ValueError, TypeError):
        pct = 0
    if fav and 50 <= pct <= 82:
        fm['probabilita_favorito'] = fav
        fm['probabilita_percent'] = pct
    if cover_image:
        fm['cover_image'] = cover_image
        fm['cover_credit'] = cover_credit
        if cover_file:
            fm['cover_file'] = cover_file

    # Timestamp fine analisi (Europe/Rome).
    # Mostrato nell'articolo come "24 ottobre 2026, 07:12".
    # Rappresenta l'istante in cui l'analisi e' stata completata e confezionata.
    try:
        from zoneinfo import ZoneInfo
        ora_it = datetime.now(ZoneInfo('Europe/Rome'))
    except Exception:
        ora_it = datetime.now()

    # EDIZIONE DEL MATTINO (cablato): generato_il e' SEMPRE un orario
    # mattiniero (~07:20), a prescindere da quando gira la pipeline. Ora che
    # il sistema parte a comando a qualsiasi ora, la testata deve comunque
    # uscire come edizione del mattino, senza doverlo correggere a mano ogni
    # volta. ARTICOLO_ORA_OVERRIDE="HH:MM" puo' comunque forzare un altro
    # orario; ARTICOLO_DATA_OVERRIDE="YYYY-MM-DD" forza la DATA (es. stasera
    # gli articoli di domani).
    ora_override = os.environ.get('ARTICOLO_ORA_OVERRIDE', '').strip() or '07:20'
    data_override = os.environ.get('ARTICOLO_DATA_OVERRIDE', '').strip()
    try:
        h, m = (int(x) for x in ora_override.split(':'))
        base = ora_it.replace(hour=h, minute=m, second=0, microsecond=0)
        if data_override:
            try:
                y, mo, d = (int(x) for x in data_override.split('-'))
                base = base.replace(year=y, month=mo, day=d)
            except Exception:
                pass
        # variazione deterministica per slug: -8 .. +37 minuti, cosi' gli
        # articoli non hanno tutti lo stesso minuto esatto (resta nel mattino).
        jitter = int(hashlib.md5(slug.encode()).hexdigest(), 16) % 46 - 8
        pub = base + timedelta(minutes=jitter)
        # isoformat tz-aware (es. "2026-11-09T07:20+01:00"): il browser lo
        # mostra all'ora di Roma corretta su QUALUNQUE macchina di build. Un
        # valore naive veniva invece interpretato come UTC e mostrato +1h.
        fm['generato_il'] = pub.isoformat(timespec='minutes')
    except Exception:
        fm['generato_il'] = ora_it.isoformat(timespec='minutes')

    frontmatter_lines = ['---']
    for k, v in fm.items():
        if isinstance(v, list):
            frontmatter_lines.append(f"{k}:")
            for item in v:
                frontmatter_lines.append(f'  - "{item}"')
        elif isinstance(v, bool):
            frontmatter_lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, int) and not isinstance(v, bool):
            frontmatter_lines.append(f"{k}: {v}")
        else:
            vv = str(v).replace('"', "'")
            frontmatter_lines.append(f'{k}: "{vv}"')
    frontmatter_lines.append('---')
    frontmatter_lines.append('')
    frontmatter_lines.append(corpo)

    out = Path(out_dir) / f'{slug}.md'
    out.write_text('\n'.join(frontmatter_lines))

    # NOTE: la generazione dei profili editoriali per giocatori e torneo non
    # viene fatta qui (bloccherebbe la pipeline). daily.sh la lancia in
    # background dopo [5/5] commit+push, cosi' il sito e' live prima e i
    # profili mancanti si aggiungono con calma nelle ore successive.

    return out


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Uso: python write_article.py selected.json analyses_dir [out_dir]', file=sys.stderr)
        sys.exit(1)
    selected = json.loads(Path(sys.argv[1]).read_text())
    analyses_dir = Path(sys.argv[2])
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).parent.parent / 'src' / 'content' / 'articoli'
    out_dir.mkdir(parents=True, exist_ok=True)
    for m in selected:
        mid = m.get('event_key')
        af = analyses_dir / f'analysis_{mid}.json'
        if not af.exists():
            print(f'Skip {mid}: analisi mancante')
            continue
        analysis = json.loads(af.read_text())
        out = write(m, analysis, out_dir)
        print(f'Scritto: {out}')
