"""Gate di VERIFICA TURNO: ogni volta che un articolo nomina la fase del
torneo, quella fase dev'essere ESATTAMENTE quella reale.

Perche' serve, oltre a verify_rounds.py: quello verifica UN turno per TORNEO
prima della generazione. Ma in un torneo vero piu' turni convivono nello
stesso giorno (al Masters di Parigi il martedi' si giocano primo E secondo
turno insieme): applicare un turno unico a tutti i match del giorno e' la
causa classica di "esordio" scritto su una partita che esordio non e'.

Questo gate agisce DOPO la scrittura e lavora sul testo pubblicato:
  1. Estrae da titolo/sottotitolo/descrizione/corpo ogni affermazione di
     fase, inclusi i sinonimi che implicano il primo turno ("esordio",
     "debutto", "al via", "apre il torneo").
  2. Verifica via WEB, per ogni torneo della giornata, quali turni si giocano
     quel giorno; se ne convive piu' di uno chiede il turno MATCH PER MATCH.
  3. Confronta affermato vs reale:
       - coincidono            -> ok
       - divergono             -> ERRORE FATTUALE
       - turno non verificato  -> l'articolo non deve nominarlo affatto
  4. Con --fix riscrive le sole parti che sbagliano (titolo, sottotitolo,
     descrizione, corpo), senza toccare il resto dell'analisi.

Uso:
  python3 check_round_claims.py --date=YYYY-MM-DD [--fix]

Robusto: se il web check fallisce il torneo resta "non verificato" e si
segnala soltanto. Non blocca mai la pipeline.
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from generate_analysis import _claude_call

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'
BACKEND = Path(__file__).resolve().parent

# Fase canonica -> come la si scrive in italiano.
CANONICI = {
    'primo turno': 'Primo turno',
    'secondo turno': 'Secondo turno',
    'terzo turno': 'Terzo turno',
    'sedicesimi': 'Sedicesimi di finale',
    'ottavi': 'Ottavi di finale',
    'quarti': 'Quarti di finale',
    'semifinale': 'Semifinale',
    'finale': 'Finale',
}

# Espressioni che AFFERMANO una fase. I sinonimi di apertura implicano il
# primo turno: se il match e' un secondo turno, "esordio" e' un errore.
CLAIM_RX = [
    (r"\besordi\w*\b", 'primo turno'),
    (r"\bdebutt\w+\b", 'primo turno'),
    (r"\bal via\b", 'primo turno'),
    (r"\bapr\w+ il torneo\b", 'primo turno'),
    (r"\bprima uscita\b", 'primo turno'),
    (r"\bprimo turno\b", 'primo turno'),
    (r"\bsecondo turno\b", 'secondo turno'),
    (r"\bterzo turno\b", 'terzo turno'),
    (r"\bsedicesimi\b", 'sedicesimi'),
    (r"\bottavi\b", 'ottavi'),
    (r"\bquarti di finale\b", 'quarti'),
    (r"\bsemifinal\w*\b", 'semifinale'),
    # "finale" solo se NON preceduta da "di" (altrimenti cattura dentro
    # "quarti di finale" / "ottavi di finale" e inventa un claim inesistente).
    (r"(?<!di )\bfinale\b", 'finale'),
]


def _norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _fm_get(testo, campo):
    m = re.search(rf'^{campo}:\s*"?(.*?)"?\s*$', testo, re.M)
    return m.group(1).strip() if m else ''


def _split(testo):
    """Frontmatter e corpo di un articolo."""
    m = re.match(r'^(---\r?\n[\s\S]*?\r?\n---\r?\n)([\s\S]*)$', testo)
    return (m.group(1), m.group(2)) if m else ('', testo)


def _canon_round(raw):
    """Normalizza un'etichetta di round (API o web) in chiave canonica."""
    r = _norm(raw)
    if not r:
        return ''
    if 'qualif' in r:
        return 'qualificazione'
    # Forme inglesi PRIMA di quelle italiane: "quarterfinal"/"semifinal"
    # contengono "final" e verrebbero scambiate per la finale.
    if 'quarterfinal' in r or 'quarter-final' in r or 'quarter final' in r:
        return 'quarti'
    if 'semifinal' in r or 'semi-final' in r or 'semi final' in r:
        return 'semifinale'
    if 'round of 32' in r or 'round of 64' in r:
        return 'primo turno'
    if 'round of 16' in r:
        return 'ottavi'
    if re.search(r'\b(1st|first) round\b', r) or r in ('r1', 'round 1'):
        return 'primo turno'
    if re.search(r'\b(2nd|second) round\b', r) or r in ('r2', 'round 2'):
        return 'secondo turno'
    if re.search(r'\b(3rd|third) round\b', r) or r in ('r3', 'round 3'):
        return 'terzo turno'
    # Forme italiane (piu' specifiche prima: "semifinale" prima di "finale").
    for chiave in ('primo turno', 'secondo turno', 'terzo turno', 'sedicesimi',
                   'ottavi', 'quarti', 'semifinal', 'final'):
        if chiave in r:
            return {'semifinal': 'semifinale', 'final': 'finale'}.get(chiave, chiave)
    return ''


def claims_in(testo):
    """Fasi affermate nel testo, con la stringa che le afferma."""
    t = _norm(testo)
    out = {}
    for rx, fase in CLAIM_RX:
        for m in re.finditer(rx, t):
            out.setdefault(fase, set()).add(m.group(0))
    return out


def carica(data_iso):
    arts = []
    for p in sorted(ARTICOLI.glob(f'{data_iso}-*.md')):
        testo = p.read_text()
        fm, corpo = _split(testo)
        g1, g2 = _fm_get(testo, 'giocatore1'), _fm_get(testo, 'giocatore2')
        if g1 == 'Redazione':
            continue  # editoriale: non e' un match
        arts.append({
            'path': p, 'slug': p.stem, 'fm': fm, 'corpo': corpo,
            'titolo': _fm_get(testo, 'titolo'),
            'sottotitolo': _fm_get(testo, 'sottotitolo'),
            'descrizione': _fm_get(testo, 'descrizione'),
            'torneo': _fm_get(testo, 'torneo'),
            'categoria': _fm_get(testo, 'categoria'),
            'g1': g1, 'g2': g2,
        })
    return arts


def round_api(data_iso):
    f = BACKEND / f'selected_{data_iso}.json'
    mappa = {}
    if f.exists():
        try:
            for m in json.loads(f.read_text()):
                k = (_norm(m.get('event_first_player')), _norm(m.get('event_second_player')))
                mappa[k] = _canon_round(m.get('tournament_round'))
        except Exception:
            pass
    return mappa


PROMPT_TURNI = """Fai una WEB SEARCH e stabilisci con precisione quali TURNI del tabellone
principale di singolare si sono giocati in questa data in questo torneo.

- Torneo: {torneo} ({categoria})
- Data: {data}

Attenzione: in un torneo possono convivere PIU' turni nello stesso giorno
(es. primo e secondo turno insieme). Non dare per scontato che sia uno solo.

Poi, per CIASCUNO di questi match, indica a quale turno appartiene:
{elenco}

Se non trovi una fonte chiara per un match, metti "turno": "" per quel match
(meglio vuoto che sbagliato). Non tirare a indovinare.

Usa esattamente una di queste etichette: "primo turno", "secondo turno",
"terzo turno", "sedicesimi", "ottavi", "quarti", "semifinale", "finale",
"qualificazione", oppure "" se incerto.

**Rispondi SOLO con questo JSON:**
```json
{{
  "turni_del_giorno": ["primo turno"],
  "match": [{{"giocatori": "X vs Y", "turno": "primo turno", "fonte": "url"}}],
  "verificato": true
}}
```
"""


def verifica_web(torneo, categoria, data_iso, matches):
    """Un web check per torneo, con richiesta esplicita match per match."""
    elenco = '\n'.join(f'  - {m["g1"]} vs {m["g2"]}' for m in matches)
    prompt = PROMPT_TURNI.format(torneo=torneo, categoria=categoria,
                                 data=data_iso, elenco=elenco)
    try:
        r = _claude_call(prompt, timeout=300)
    except Exception as e:
        print(f'  [web check fallito] {torneo}: {e}', flush=True)
        return {}
    if not r.get('verificato'):
        print(f'  [non verificato] {torneo}', flush=True)
        return {}
    out = {}
    for voce in r.get('match', []) or []:
        gio = _norm(voce.get('giocatori', ''))
        turno = _canon_round(voce.get('turno', ''))
        if not turno:
            continue
        for m in matches:
            if _norm(m['g1']) in gio and _norm(m['g2']) in gio:
                out[m['slug']] = turno
    giorno = [_canon_round(x) for x in (r.get('turni_del_giorno') or [])]
    giorno = [g for g in giorno if g]
    print(f'  [{torneo}] turni del giorno: {", ".join(giorno) or "?"}; '
          f'match risolti {len(out)}/{len(matches)}', flush=True)
    return out


PROMPT_ADJUDICA = """Devi stabilire UNA cosa sola, con precisione.

Match di cui parla l'articolo: {g1} contro {g2}, torneo {torneo}.

Testo da esaminare:
\"\"\"{testo}\"\"\"

Domanda: il testo afferma che QUESTA partita ({g1} contro {g2} a {torneo}) si
gioca nella fase "{fase}"?

Attenzione: molto spesso una parola come "finale" o "semifinale" compare
riferita al PASSATO o a un ALTRO torneo (es. "reduce da una finale",
"dalla semifinale di Guangzhou", "un giorno dopo la finale", "vinse la finale
di Basilea"). In quei casi la risposta e' false: non e' un'affermazione sulla
fase di questa partita.

Rispondi true SOLO se il testo dice che questa partita appartiene a quella
fase. **Solo questo JSON:**
```json
{{"afferma": true, "frase": "la frase esatta che lo afferma, o \\"\\" se afferma=false"}}
```
"""


def e_davvero_claim(a, fase, testo):
    """Stage 2: un match regex non basta. "reduce da una finale" non e' una
    dichiarazione sulla fase di oggi. Interroghiamo il modello solo sui
    candidati che divergono, cosi' il gate non riscrive testo corretto."""
    try:
        r = _claude_call(PROMPT_ADJUDICA.format(
            g1=a['g1'], g2=a['g2'], torneo=a['torneo'],
            fase=CANONICI.get(fase, fase), testo=testo[:2000]), timeout=240)
        return bool(r.get('afferma'))
    except Exception as e:
        # In dubbio NON si tocca nulla: meglio un falso negativo che
        # riscrivere un articolo corretto.
        print(f'  [arbitrato fallito] {a["slug"]}: {e} -> considero non-claim')
        return False


PROMPT_FIX = """Sei il revisore di AnalisiTennis.it. In questo articolo la FASE DEL TORNEO e'
dichiarata in modo SBAGLIATO e va corretta.

- Match: {g1} contro {g2}, torneo {torneo}
- FASE REALE VERIFICATA: {reale}
- Fase erroneamente dichiarata nel testo: {sbagliata}

Correggi ESCLUSIVAMENTE le espressioni che dichiarano la fase, in tutti i campi
qui sotto. Non toccare nient'altro: non cambiare analisi, numeri, precedenti,
giudizi o stile. Se un'espressione implica il primo turno ("esordio",
"debutto", "al via", "apre il torneo") ma la fase reale e' un'altra,
riformula la frase in modo che indichi la fase reale.
{vincolo}

**CAMPI ATTUALI (JSON):**
```json
{campi}
```

**OUTPUT: solo questo JSON, con TUTTI i campi (identici dove non serviva correggere):**
```json
{{"titolo": "...", "sottotitolo": "...", "descrizione": "...", "corpo_markdown": "..."}}
```
"""


def correggi(a, reale, sbagliata):
    vincolo = ('\nLa fase reale NON e\' verificata: elimina ogni riferimento '
               'alla fase del torneo senza sostituirlo con un altro.'
               if not reale else '')
    campi = json.dumps({
        'titolo': a['titolo'], 'sottotitolo': a['sottotitolo'],
        'descrizione': a['descrizione'], 'corpo_markdown': a['corpo'],
    }, ensure_ascii=False, indent=2)
    prompt = PROMPT_FIX.format(
        g1=a['g1'], g2=a['g2'], torneo=a['torneo'],
        reale=CANONICI.get(reale, reale) or 'non verificata',
        sbagliata=CANONICI.get(sbagliata, sbagliata), vincolo=vincolo, campi=campi)
    r = _claude_call(prompt, timeout=600)

    testo = a['path'].read_text()
    fm, _ = _split(testo)
    for campo in ('titolo', 'sottotitolo', 'descrizione'):
        v = r.get(campo)
        if isinstance(v, str) and v.strip():
            fm = re.sub(rf'^{campo}:\s*".*?"\s*$',
                        f'{campo}: "{v.strip().replace(chr(34), chr(39))}"',
                        fm, count=1, flags=re.M)
    corpo = r.get('corpo_markdown')
    if not (isinstance(corpo, str) and corpo.strip()):
        corpo = a['corpo']
    a['path'].write_text(fm + corpo)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True)
    ap.add_argument('--fix', action='store_true')
    args = ap.parse_args()

    arts = carica(args.date)
    if not arts:
        print(f'[turni] nessun articolo-match per {args.date}')
        return 0
    api = round_api(args.date)

    per_torneo = defaultdict(list)
    for a in arts:
        per_torneo[a['torneo']].append(a)

    print(f'[turni] {len(arts)} match in {len(per_torneo)} tornei, verifica web...')
    verificati = {}
    for torneo, lista in per_torneo.items():
        verificati.update(verifica_web(torneo, lista[0]['categoria'], args.date, lista))

    problemi = []
    for a in arts:
        # Solo i punti che descrivono SICURAMENTE questo match: titolo,
        # sottotitolo, descrizione e primo paragrafo. Piu' avanti nel corpo
        # "quarti"/"finale" si riferiscono quasi sempre a tornei passati del
        # giocatore: scansionarli produrrebbe falsi positivi e correzioni
        # sbagliate su testo corretto.
        primo_par = ''
        for blocco in a['corpo'].split('\n\n'):
            b = blocco.strip()
            if b and not b.startswith('#'):
                primo_par = b
                break
        testo_claim = ' '.join([a['titolo'], a['sottotitolo'], a['descrizione'], primo_par])
        dichiarati = claims_in(testo_claim)
        if not dichiarati:
            continue
        reale = verificati.get(a['slug']) or api.get((_norm(a['g1']), _norm(a['g2']))) or ''
        fonte = 'web' if a['slug'] in verificati else ('api' if reale else 'nessuna')
        sbagliate = [f for f in dichiarati if f != reale]
        if not sbagliate:
            continue
        # Stage 2: conferma che sia davvero un'affermazione sulla fase di
        # QUESTO match e non un riferimento a un torneo passato.
        confermate = [f for f in sbagliate if e_davvero_claim(a, f, testo_claim)]
        if not confermate:
            print(f'   [ok] {a["slug"]}: "{sbagliate[0]}" e\' un riferimento '
                  f'al passato, non la fase di oggi')
            continue
        if not reale:
            problemi.append((a, '', confermate[0],
                             'fase dichiarata ma NON verificata'))
        else:
            problemi.append((a, reale, confermate[0],
                             f'dichiara "{confermate[0]}" ma e\' "{reale}" (fonte {fonte})'))

    if not problemi:
        print('[turni] OK: nessuna fase dichiarata in modo errato')
        return 0

    print(f'[turni] {len(problemi)} articoli con fase errata/non verificata:')
    for a, reale, sbagliata, msg in problemi:
        print(f'   - {a["slug"]}: {msg}')

    if not args.fix:
        return 1
    corretti = 0
    for a, reale, sbagliata, _ in problemi:
        try:
            if correggi(a, reale, sbagliata):
                print(f'   corretto {a["slug"]}')
                corretti += 1
        except Exception as e:
            print(f'   [errore] {a["slug"]}: {e}')
    print(f'[turni] corretti {corretti}/{len(problemi)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
