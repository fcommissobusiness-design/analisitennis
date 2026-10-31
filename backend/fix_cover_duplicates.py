"""Normalizza le COVER generiche (campo/arena di ripiego quando manca la foto
di un giocatore del match) perche' NON si ripetano in modo evidente. Le foto di
un giocatore restano intatte (si ripetono legittimamente nei suoi match).

Pool = SOLO arene che superano il vet visivo (campo in gioco, non esterni/vuoti:
elenco verificato con vet_covers). Ogni articolo "generico" (il cui credit non
contiene il cognome di un suo giocatore) riceve un'arena del pool con:
  - venue pertinente al torneo se disponibile (Ningbo, Chennai),
  - altrimenti la meno usata,
  - mai la stessa arena nello stesso giorno o nello stesso torneo,
  - copie dello stesso campo il piu' lontane possibile nel tempo.
Scarica, ridimensiona, rigenera webp, aggiorna il frontmatter.

Uso:  python3 fix_cover_duplicates.py [--dry-run]
"""
import glob
import re
import sys
import time
import hashlib
from collections import defaultdict
from pathlib import Path

import requests
import attach_covers as ac
import vet_covers as vc
from attach_covers import ARTICOLI, COVERS_DIR, download, update_frontmatter, strip_html, NAME_MAP, pick_image, used_covers_for_player

# Arene VERIFICATE col vet (campo in gioco). Nessun esterno/campo vuoto.
POOL = [
    'File:Sydney International Tennis ATP 250 (46001156835).jpg',
    'File:Olympic Tennis Centre, Rio, Brazil.jpg',
    'File:Anjo Sports Park tennis court ac.jpg',
    'File:Taube Family Tennis Stadium 2015.JPG',
    'File:PP Olympic Stadium - Tennis courts.jpg',
    'File:Pörtschach Johannes-Brahms-Promenade Werzer-Tennis-Arena 27052017 8932.jpg',
    'File:Ningbo Yinzhou Tennis Center, 2025-10-25 04.jpg',
    'File:Nungambakkam SDAT Tennis Stadium floodlit match panorama.jpg',
    'File:RK Khanna Tennis Complex New Delhi - Centre Court at Night.jpg',
]
VENUE_PER_TORNEO = {
    'ningbo': 'File:Ningbo Yinzhou Tennis Center, 2025-10-25 04.jpg',
    'chennai': 'File:Nungambakkam SDAT Tennis Stadium floodlit match panorama.jpg',
}
S = requests.Session()
S.headers['User-Agent'] = 'AnalisiTennisBot/1.0 (cover dedup)'


def fetch(title):
    for _ in range(4):
        try:
            r = S.get('https://commons.wikimedia.org/w/api.php', params={
                'action': 'query', 'format': 'json', 'titles': title,
                'prop': 'imageinfo', 'iiprop': 'url|extmetadata'}, timeout=30)
            p = list(r.json()['query']['pages'].values())[0]
            info = p['imageinfo'][0]
            em = info.get('extmetadata') or {}
            return {'title': p['title'], 'url': info['url'],
                    'author': (em.get('Artist') or {}).get('value', ''),
                    'license': (em.get('LicenseShortName') or {}).get('value', '')}
        except Exception:
            time.sleep(1.2)
    return None


def fm(text, campo):
    m = re.search(rf'^{campo}:\s*"?([^"\n]+)"?\s*$', text, re.M)
    return (m.group(1).strip() if m else '')


def cognomi(nome):
    # token >2 lettere del nome (per riconoscere la foto-giocatore nel credit)
    return [w for w in re.findall(r'[A-Za-zÀ-ÿ]+', nome or '') if len(w) > 2]


def main():
    dry = '--dry-run' in sys.argv

    arts = {}
    for f in sorted(glob.glob(str(ARTICOLI / '*.md'))):
        stem = Path(f).stem
        if not (COVERS_DIR / f'{stem}.jpg').exists():
            continue
        t = Path(f).read_text()
        g1, g2 = fm(t, 'giocatore1'), fm(t, 'giocatore2')
        cred = fm(t, 'cover_credit')
        toks = cognomi(g1) + cognomi(g2)
        is_player_photo = any(tok.lower() in cred.lower() for tok in toks)
        arts[stem] = {
            'data': fm(t, 'data')[:10], 'torneo': fm(t, 'torneo'),
            'cred': cred, 'generica': not is_player_photo and bool(cred),
        }

    # Rileggi g1/g2 per il tentativo foto-giocatore.
    for stem in arts:
        t = (ARTICOLI / f'{stem}.md').read_text()
        arts[stem]['g1'] = fm(t, 'giocatore1')
        arts[stem]['g2'] = fm(t, 'giocatore2')

    da_fix = sorted([s for s, a in arts.items() if a['generica']],
                    key=lambda s: (arts[s]['data'], s))
    print(f'Articoli con cover generica: {len(da_fix)}')

    # FASE A: prova la foto di un giocatore del match (solo se risolvibile dal
    # NAME_MAP), vettala, e se valida usala. Toglie l'articolo dal carico venue.
    risolti_foto = set()
    if not dry:
        for stem in list(da_fix):
            a = arts[stem]
            for g in (a['g1'], a['g2']):
                full = NAME_MAP.get(g)
                if not full:
                    continue
                try:
                    excl = used_covers_for_player(full.split()[-1], skip_slug=stem)
                    pk = pick_image(full, slug_hint=stem, exclude=excl)
                except Exception:
                    pk = None
                if not pk:
                    continue
                dest = COVERS_DIR / f'{stem}.jpg'
                try:
                    download(pk['url'], dest)
                except Exception:
                    continue
                ok, _ = vc.vet_image(dest)
                if ok:
                    credit = (f"{pk['title'].replace('File:', '')} | "
                              f"{strip_html(pk.get('author') or 'Autore sconosciuto')} | "
                              f"{pk.get('license') or 'Wikimedia Commons'}")
                    update_frontmatter(ARTICOLI / f'{stem}.md', f'/covers/{stem}.jpg', credit)
                    risolti_foto.add(stem)
                    print(f'  [foto] {stem[:46]} -> {full}', flush=True)
                    break
        da_fix = [s for s in da_fix if s not in risolti_foto]
        print(f'Risolti con foto giocatore: {len(risolti_foto)}. Restano per venue: {len(da_fix)}')

    # Prefetch pool venue.
    names = {t: t.replace('File:', '') for t in POOL}
    picks = {t: fetch(t) for t in POOL}
    for t in POOL:
        time.sleep(0.3)
    pool = [t for t in POOL if picks.get(t)]
    print(f'Pool venue valido: {len(pool)}')

    # Stato d'uso: per non superare max e rispettare i vincoli.
    usi = defaultdict(int)
    per_giorno = defaultdict(set)
    per_torneo = defaultdict(set)
    ultimo_uso = {}  # nome -> ultima data usata (per distanziare le copie)

    assign = {}
    for stem in da_fix:
        a = arts[stem]
        giorno, tor = a['data'], a['torneo']
        pref = VENUE_PER_TORNEO.get(tor.lower())
        def ammessa(t):
            nm = names[t]
            return nm not in per_giorno[giorno] and nm not in per_torneo[tor]
        cand = [t for t in pool if ammessa(t)]
        if pref and picks.get(pref) and ammessa(pref):
            scelta = pref
        elif cand:
            # meno usata; a parita', quella usata piu' indietro nel tempo
            scelta = min(cand, key=lambda t: (usi[names[t]], ultimo_uso.get(names[t], '0000')))
        else:
            scelta = min(pool, key=lambda t: usi[names[t]])
        nm = names[scelta]
        usi[nm] += 1
        per_giorno[giorno].add(nm)
        per_torneo[tor].add(nm)
        ultimo_uso[nm] = giorno
        assign[stem] = scelta

    print('\n=== ASSEGNAZIONI ===')
    for stem, title in assign.items():
        print(f'  {stem[:46]:46s} [{arts[stem]["torneo"][:9]:9s}] -> {names[title][:30]}')
        if dry:
            continue
        pick = picks[title]
        try:
            download(pick['url'], COVERS_DIR / f'{stem}.jpg')
            credit = (f"{names[title]} | {strip_html(pick.get('author') or 'Autore sconosciuto')} | "
                      f"{pick.get('license') or 'Wikimedia Commons'}")
            update_frontmatter(ARTICOLI / f'{stem}.md', f'/covers/{stem}.jpg', credit)
            time.sleep(0.2)
        except Exception as e:
            print(f'    [ERRORE] {stem}: {e}')

    print('\n=== USI PER ARENA ===')
    for t in sorted(pool, key=lambda x: -usi[names[x]]):
        if usi[names[t]]:
            print(f'  {usi[names[t]]}x  {names[t][:46]}')


if __name__ == '__main__':
    main()
