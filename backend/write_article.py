"""Scrive l'articolo markdown finale in src/content/articoli/ con frontmatter corretto."""
import json
import re
import sys
import unicodedata
from pathlib import Path
from datetime import datetime

try:
    from attach_covers import (
        NAME_MAP, VENUE_MAP, COVERS_DIR, detect_winner,
        pick_image, pick_venue, download, strip_html
    )
    HAS_COVER = True
except Exception:
    HAS_COVER = False


def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^\w\s-]', '', s.lower())
    s = re.sub(r'[\s_-]+', '-', s).strip('-')
    return s[:80]


def categoria(tipo):
    t = (tipo or '').lower()
    if 'grand slam' in t: return 'Slam'
    if 'masters' in t: return 'Masters'
    if 'challenger' in t: return 'Challenger'
    if 'itf' in t: return 'ITF'
    if 'wta' in t: return 'WTA'
    return 'ATP'


def superficie(torneo_name, tipo):
    # Euristica base, migliorabile con mapping torneo->superficie
    n = (torneo_name or '').lower()
    if 'roland' in n or 'rome' in n or 'madrid' in n or 'barcelon' in n: return 'terra'
    if 'wimbledon' in n: return 'erba'
    if 'indoor' in n or 'paris' in n and 'bercy' in n: return 'indoor'
    return 'cemento'


def write(match, analysis, out_dir):
    titolo = analysis['titolo']
    sottotitolo = analysis['sottotitolo']
    descrizione = analysis['descrizione']
    corpo = analysis['corpo_markdown']
    verdetto = analysis['verdetto']
    tag = analysis.get('tag', [])

    p1 = match.get('event_first_player', '').strip()
    p2 = match.get('event_second_player', '').strip()
    data = match.get('event_date')
    torneo = match.get('tournament_name', '')
    cat = categoria(match.get('event_type_type'))
    sup = superficie(torneo, match.get('event_type_type'))

    slug_base = slugify(f"{p1}-vs-{p2}-{torneo}-pronostico-analisi")
    slug = f"{data}-{slug_base}"

    cover_image = None
    cover_credit = None
    if HAS_COVER:
        try:
            fav, conf = detect_winner(verdetto, p1, p2)
            pick = None
            if fav and conf != 'equilibrio':
                full = NAME_MAP.get(fav)
                if full:
                    pick = pick_image(full)
            if not pick:
                pick = pick_venue(torneo)
            if pick:
                dest = COVERS_DIR / f'{slug}.jpg'
                try:
                    download(pick['url'], dest)
                    cover_image = f'/covers/{slug}.jpg'
                    cover_credit = (
                        f"{pick['title'].replace('File:', '')} | "
                        f"{strip_html(pick.get('author') or 'Autore sconosciuto')} | "
                        f"{pick.get('license') or 'Wikimedia Commons'}"
                    )
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
    if cover_image:
        fm['cover_image'] = cover_image
        fm['cover_credit'] = cover_credit

    # Timestamp fine analisi (Europe/Rome).
    # Mostrato nell'articolo come "24 ottobre 2026, 07:12".
    # Rappresenta l'istante in cui l'analisi e' stata completata e confezionata.
    try:
        from zoneinfo import ZoneInfo
        ora_it = datetime.now(ZoneInfo('Europe/Rome'))
    except Exception:
        ora_it = datetime.now()
    fm['generato_il'] = ora_it.strftime('%Y-%m-%dT%H:%M')

    frontmatter_lines = ['---']
    for k, v in fm.items():
        if isinstance(v, list):
            frontmatter_lines.append(f"{k}:")
            for item in v:
                frontmatter_lines.append(f'  - "{item}"')
        elif isinstance(v, bool):
            frontmatter_lines.append(f"{k}: {str(v).lower()}")
        else:
            vv = str(v).replace('"', "'")
            frontmatter_lines.append(f'{k}: "{vv}"')
    frontmatter_lines.append('---')
    frontmatter_lines.append('')
    frontmatter_lines.append(corpo)

    out = Path(out_dir) / f'{slug}.md'
    out.write_text('\n'.join(frontmatter_lines))
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
