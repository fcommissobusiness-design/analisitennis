"""Costruisce i dati Head-to-Head (scontri diretti) per le coppie di giocatori
che abbiamo analizzato, usando l'endpoint get_H2H di API Tennis.

- mappa nome completo -> player_key dalle classifiche ATP+WTA complete,
- raccoglie le coppie dai nostri articoli,
- per ogni coppia con entrambe le chiavi scarica i precedenti reali,
- salva src/data/h2h.json (solo coppie con almeno 1 precedente).

Alimenta le pagine /scontri-diretti/[coppia]. Lanciato dalla pipeline."""
import json
import re
import sys
import unicodedata
from pathlib import Path

from fetch_fixtures import fetch
from attach_covers import NAME_MAP, ARTICOLI, parse_frontmatter

OUT = Path(__file__).resolve().parent.parent / 'src' / 'data' / 'h2h.json'


def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).strip().lower()


def slugify(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    s = re.sub(r'[^\w\s-]', '', s.lower())
    return re.sub(r'[\s_-]+', '-', s).strip('-')


def build_key_map():
    """nome_completo_normalizzato -> player_key, da ATP+WTA (classifiche intere)."""
    m = {}
    for et in ('ATP', 'WTA'):
        try:
            res = fetch('get_standings', event_type=et).get('result', []) or []
        except Exception as e:
            print(f'[h2h] standings {et} errore: {e}', file=sys.stderr)
            continue
        for r in res:
            name = (r.get('player') or '').strip()
            key = r.get('player_key')
            if name and key:
                m.setdefault(norm(name), key)
    return m


def full_name(raw):
    """Da 'N. Djokovic' -> 'Novak Djokovic' (via NAME_MAP) o il raw stesso."""
    return NAME_MAP.get(raw, raw)


def parse_precedenti(h2h_list):
    """Normalizza i match H2H: data, torneo, risultato, vincitore (first/second)."""
    out = []
    for m in h2h_list or []:
        res = (m.get('event_final_result') or '').strip()
        if not res or res in ('-', '0 - 0'):
            continue  # match senza risultato (futuro/annullato)
        out.append({
            'data': m.get('event_date') or '',
            'torneo': (m.get('tournament_name') or '').strip(),
            'g1': m.get('event_first_player') or '',
            'g2': m.get('event_second_player') or '',
            'risultato': res,
            'winner': m.get('event_winner') or '',  # 'First Player'|'Second Player'
        })
    # piu' recenti in alto
    out.sort(key=lambda x: x['data'], reverse=True)
    return out


def main():
    keymap = build_key_map()
    print(f'[h2h] mappa chiavi: {len(keymap)} giocatori')

    # Coppie uniche dagli articoli (nome completo + chiave).
    coppie = {}
    for art in sorted(ARTICOLI.glob('2026-*.md')):
        fm, _ = parse_frontmatter(art)
        if not fm:
            continue
        g1, g2 = fm.get('giocatore1', ''), fm.get('giocatore2', '')
        if g1 in ('Redazione', 'Lettori') or not g1 or not g2:
            continue
        f1, f2 = full_name(g1), full_name(g2)
        k1, k2 = keymap.get(norm(f1)), keymap.get(norm(f2))
        if not k1 or not k2 or k1 == k2:
            continue
        # chiave coppia canonica (ordine alfabetico sui nomi completi)
        a, b = sorted([(f1, k1), (f2, k2)], key=lambda x: norm(x[0]))
        slug = f'{slugify(a[0])}-vs-{slugify(b[0])}'
        coppie[slug] = {'p1': a[0], 'k1': a[1], 'p2': b[0], 'k2': b[1]}

    print(f'[h2h] coppie dagli articoli: {len(coppie)}')
    data = {}
    for slug, c in coppie.items():
        try:
            r = fetch('get_H2H', first_player_key=c['k1'], second_player_key=c['k2'])
            prec = parse_precedenti((r.get('result') or {}).get('H2H', []))
        except Exception as e:
            print(f'[h2h] {slug} errore: {e}', file=sys.stderr)
            continue
        if not prec:
            continue  # niente precedenti reali: pagina sarebbe vuota
        # bilancio: quante vittorie per p1 (nome completo) vs p2
        last1 = norm(c['p1']).split()[-1]
        win1 = win2 = 0
        for m in prec:
            w = m['g1'] if m['winner'] == 'First Player' else (m['g2'] if m['winner'] == 'Second Player' else '')
            if not w:
                continue
            if last1 in norm(w):
                win1 += 1
            else:
                win2 += 1
        data[slug] = {
            'p1': c['p1'], 'p2': c['p2'],
            'slug_p1': slugify(c['p1']), 'slug_p2': slugify(c['p2']),
            'bilancio': {'p1': win1, 'p2': win2},
            'precedenti': prec,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f'[h2h] salvate {len(data)} coppie con precedenti in {OUT.name}')


if __name__ == '__main__':
    main()
