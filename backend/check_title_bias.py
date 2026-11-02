"""Gate ANTI-BIAS sul copy dei TITOLI della giornata.

Problema reale osservato il 02/11/2026: su 17 titoli, "esordio" compariva 8
volte e "primo turno" 5 (13 titoli su 17 con la stessa formula), piu' "sfida"
4 e "decifrare" 3. Ogni articolo e' generato in una chiamata separata, quindi
il modello non sa cosa ha gia' scritto negli altri e ricade sempre sulle
stesse stampelle: la home sembra scritta da un robot.

NON si vietano le parole: il turno e' un FATTO e va poter dire. Si impone
VARIETA': una stessa formula puo' comparire al massimo MAX_USI volte al
giorno; i titoli in eccesso vengono riscritti cambiando angolo (non negando
il fatto). La riscrittura riceve i fatti del match e il turno VERIFICATO, e
non puo' affermare un turno che non sia quello.

Rilevamento su due livelli:
  1. FORMULE note (lista curata): le stampelle gia' viste.
  2. Bigrammi automatici: qualunque coppia di parole che ricorre in >= SOGLIA
     titoli, anche se nuova. Cosi' il modello non puo' semplicemente spostarsi
     su un'altra stampella il giorno dopo.

Uso:
  python3 check_title_bias.py --date=YYYY-MM-DD [--dry-run]

Robusto: su errore di una riscrittura tiene il titolo originale. Non blocca
mai la pipeline.
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from generate_analysis import _claude_call

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'
BACKEND = Path(__file__).resolve().parent

# Quante volte la STESSA formula puo' comparire nei titoli di una giornata.
MAX_USI = 2
# Da quante occorrenze un bigramma non curato diventa "stampella".
SOGLIA_BIGRAMMA = 3

# Stampelle note: regex -> etichetta leggibile. L'ordine conta (piu'
# specifico prima), ma il conteggio e' per etichetta.
FORMULE = [
    (r"\besordi\w*\b", 'esordio'),
    (r"\bprimo turno\b", 'primo turno'),
    (r"\bsecondo turno\b", 'secondo turno'),
    (r"\bdebutt\w+\b", 'debutto'),
    (r"\bal via\b", 'al via'),
    (r"\bsfid\w+\b", 'sfida/sfidare'),
    (r"\bdecifrar\w*\b", 'da decifrare'),
    (r"\bsenza precedenti\b", 'senza precedenti'),
    (r"\bined\w+\b", 'inedito'),
    (r"\bda seguire\b", 'da seguire'),
    (r"\bchi comanda\b", 'chi comanda'),
    (r"\bchi parte meglio\b", 'chi parte meglio'),
    (r"\btutto da \w+", 'tutto da ...'),
    (r"\bincroc\w+\b", 'incrocio'),
    (r"\bapre il torneo\b|\baprono il torneo\b", 'apre il torneo'),
    (r"\brivincita\b", 'rivincita'),
    (r"\bda tre set\b", 'da tre set'),
]

# Parole da ignorare nel calcolo dei bigrammi (funzionali + nomi di torneo
# ricorrenti: non sono stampelle di stile, sono dati).
STOP = {
    'a', 'al', 'alla', 'allo', 'ai', 'agli', 'alle', 'all', 'da', 'dal', 'dalla',
    'di', 'del', 'della', 'dello', 'dei', 'degli', 'delle', 'e', 'ed', 'il', 'lo',
    'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'in', 'nel', 'nella', 'con', 'su',
    'sul', 'sulla', 'per', 'tra', 'fra', 'che', 'chi', 'non', 'si', 'piu', 'come',
    'contro', 'vs', 'il', 'un',
}


def _norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _fm_get(testo, campo):
    m = re.search(rf'^{campo}:\s*"?(.*?)"?\s*$', testo, re.M)
    return m.group(1).strip() if m else ''


def _fm_set_titolo(path: Path, nuovo: str):
    testo = path.read_text()
    sicuro = nuovo.replace('"', "'")
    nuovo_testo, n = re.subn(r'^titolo:\s*".*?"\s*$', f'titolo: "{sicuro}"',
                             testo, count=1, flags=re.M)
    if n:
        path.write_text(nuovo_testo)
    return bool(n)


def carica_articoli(data_iso):
    """Articoli della giornata, con i campi che servono alla riscrittura."""
    out = []
    for p in sorted(ARTICOLI.glob(f'{data_iso}-*.md')):
        t = p.read_text()
        out.append({
            'path': p,
            'slug': p.stem,
            'titolo': _fm_get(t, 'titolo'),
            'sottotitolo': _fm_get(t, 'sottotitolo'),
            'torneo': _fm_get(t, 'torneo'),
            'categoria': _fm_get(t, 'categoria'),
            'superficie': _fm_get(t, 'superficie'),
            'g1': _fm_get(t, 'giocatore1'),
            'g2': _fm_get(t, 'giocatore2'),
            'verdetto': _fm_get(t, 'verdetto'),
        })
    return out


def round_verificati(data_iso):
    """Turno VERIFICATO per match, da selected_<data>.json (prodotto da
    verify_rounds.py). Chiave: (g1, g2) normalizzati."""
    f = BACKEND / f'selected_{data_iso}.json'
    mappa = {}
    if not f.exists():
        return mappa
    try:
        for m in json.loads(f.read_text()):
            k = (_norm(m.get('event_first_player')), _norm(m.get('event_second_player')))
            mappa[k] = m.get('tournament_round') or ''
    except Exception:
        pass
    return mappa


def formule_in(titolo):
    """Etichette delle stampelle presenti in un titolo."""
    t = _norm(titolo)
    trovate = set()
    for rx, etichetta in FORMULE:
        try:
            if re.search(rx, t):
                trovate.add(etichetta)
        except re.error:
            continue
    return trovate


def token_entita(articoli):
    """Token che sono DATI, non stile: nomi di giocatori, tornei, superfici,
    categorie. Vanno esclusi dai bigrammi, altrimenti "hong kong" (nome del
    torneo) verrebbe scambiato per una stampella di copy."""
    tok = set()
    for a in articoli:
        for campo in ('torneo', 'g1', 'g2', 'categoria', 'superficie'):
            for w in re.findall(r"[a-z]+", _norm(a.get(campo, ''))):
                if len(w) > 1:
                    tok.add(w)
    # Esonimi italiani dei tornei piu' frequenti (il titolo usa questi).
    tok |= {'parigi', 'basilea', 'vienna', 'lione', 'londra', 'pechino',
            'shanghai', 'tokyo', 'madrid', 'roma', 'montecarlo', 'anversa',
            'bruxelles', 'stoccarda', 'monaco', 'wta', 'atp', 'slam',
            'challenger', 'masters'}
    return tok


def bigrammi_in(titolo, entita=frozenset()):
    t = _norm(titolo)
    parole = [w for w in re.findall(r"[a-z]+", t) if w not in STOP and len(w) > 2]
    out = set()
    for i in range(len(parole) - 1):
        a, b = parole[i], parole[i + 1]
        if a in entita or b in entita:
            continue  # contiene un dato (nome), non e' una stampella
        out.add(f'{a} {b}')
    return out


def analizza(articoli, entita=frozenset()):
    """Conteggio di formule e bigrammi su tutta la giornata."""
    cf, cb = Counter(), Counter()
    for a in articoli:
        for f in formule_in(a['titolo']):
            cf[f] += 1
        for b in bigrammi_in(a['titolo'], entita):
            cb[b] += 1
    return cf, cb


def sovrausate(cf, cb):
    """Formule oltre MAX_USI + bigrammi oltre SOGLIA."""
    s = {f for f, n in cf.items() if n > MAX_USI}
    s |= {b for b, n in cb.items() if n >= SOGLIA_BIGRAMMA}
    return s


PROMPT_RISCRITTURA = """Sei il caporedattore di AnalisiTennis.it, testata editoriale italiana di tennis.
Riscrivi UN titolo che e' troppo simile ad altri della stessa giornata.

**MATCH:**
- Giocatori: {g1} contro {g2}
- Torneo: {torneo} ({categoria}), superficie {superficie}
- Turno VERIFICATO: {turno}
- Sottotitolo dell'articolo: {sottotitolo}
- Nostra chiusura/verdetto: {verdetto}

**TITOLO ATTUALE (da sostituire):** {titolo}

**FORMULE GIA' ABUSATE OGGI, da NON usare:** {formule}

**TITOLI GIA' USATI OGGI (non assomigliare a nessuno di questi):**
{altri}

**REGOLE:**
- 45-70 caratteri. Italiano giornalistico, asciutto, concreto.
- Puoi nominare il turno SOLO se e' "{turno}" ed e' un dato reale; se il turno
  qui sopra e' vuoto o "non verificato", NON nominare alcun turno.
- Non inventare numeri, precedenti, ranking, record o fatti non presenti sopra.
- Cambia ANGOLO, non limitarti a sinonimi: punta su cosa rende diverso QUESTO
  match (stile di gioco, superficie, momento di forma, posta in palio,
  contrasto tra i due, contesto del torneo).
- Niente quote, bookmaker, scommesse. Niente due punti se il titolo gia' ne ha
  uno. Niente clickbait vuoto ("ecco perche'", "incredibile").

**OUTPUT: solo questo JSON, nient'altro:**
```json
{{"titolo": "..."}}
```
"""


def riscrivi(a, turno, formule_vietate, altri_titoli):
    prompt = PROMPT_RISCRITTURA.format(
        g1=a['g1'], g2=a['g2'], torneo=a['torneo'], categoria=a['categoria'],
        superficie=a['superficie'], turno=turno or 'non verificato',
        sottotitolo=a['sottotitolo'], verdetto=a['verdetto'], titolo=a['titolo'],
        formule=', '.join(sorted(formule_vietate)) or '(nessuna)',
        altri='\n'.join(f'  - {t}' for t in altri_titoli) or '  (nessuno)',
    )
    r = _claude_call(prompt, timeout=300)
    nuovo = (r.get('titolo') or '').strip().strip('"')
    return nuovo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    articoli = carica_articoli(args.date)
    if not articoli:
        print(f'[titoli] nessun articolo per {args.date}')
        return 0

    entita = token_entita(articoli)
    cf, cb = analizza(articoli, entita)
    print(f'[titoli] {len(articoli)} titoli del {args.date}')
    for f, n in cf.most_common():
        if n > 1:
            print(f'   formula "{f}": {n}x' + ('  <-- OLTRE SOGLIA' if n > MAX_USI else ''))
    for b, n in cb.most_common(8):
        if n >= SOGLIA_BIGRAMMA:
            print(f'   bigramma "{b}": {n}x  <-- OLTRE SOGLIA')

    abusate = sovrausate(cf, cb)
    if not abusate:
        print('[titoli] nessun bias: varieta\' ok')
        return 0
    print(f'[titoli] formule abusate: {", ".join(sorted(abusate))}')

    # Chi riscrivere: per ogni formula abusata tengo le prime MAX_USI
    # occorrenze (in ordine di slug, stabile) e riscrivo le successive.
    tenuti = Counter()
    da_riscrivere = []
    for a in articoli:
        colpevoli = formule_in(a['titolo']) & abusate
        colpevoli |= (bigrammi_in(a['titolo'], entita) & abusate)
        if not colpevoli:
            continue
        eccede = False
        for c in colpevoli:
            tenuti[c] += 1
            if tenuti[c] > MAX_USI:
                eccede = True
        if eccede:
            da_riscrivere.append(a)

    print(f'[titoli] da riscrivere: {len(da_riscrivere)}')
    if args.dry_run:
        for a in da_riscrivere:
            print(f'   - {a["titolo"]}')
        return 0

    turni = round_verificati(args.date)
    titoli_correnti = [a['titolo'] for a in articoli]
    riscritti = 0
    for a in da_riscrivere:
        turno = turni.get((_norm(a['g1']), _norm(a['g2'])), '')
        altri = [t for t in titoli_correnti if t != a['titolo']]
        try:
            nuovo = riscrivi(a, turno, abusate, altri)
        except Exception as e:
            print(f'   [errore] {a["slug"]}: {e} -> tengo originale')
            continue
        if not nuovo or len(nuovo) < 25 or len(nuovo) > 95:
            print(f'   [scartato] titolo non valido per {a["slug"]}: {nuovo!r}')
            continue
        if nuovo in titoli_correnti:
            print(f'   [scartato] duplicato per {a["slug"]}')
            continue
        # Il nuovo titolo non deve reintrodurre una formula gia' abusata.
        if (formule_in(nuovo) | bigrammi_in(nuovo, entita)) & abusate:
            print(f'   [scartato] riusa una formula abusata: {nuovo!r}')
            continue
        if _fm_set_titolo(a['path'], nuovo):
            titoli_correnti = [nuovo if t == a['titolo'] else t for t in titoli_correnti]
            print(f'   OK  {a["slug"]}')
            print(f'       prima: {a["titolo"]}')
            print(f'       dopo : {nuovo}')
            a['titolo'] = nuovo
            riscritti += 1

    cf2, cb2 = analizza(articoli, entita)
    resid = sovrausate(cf2, cb2)
    print(f'[titoli] riscritti {riscritti}/{len(da_riscrivere)}')
    print(f'[titoli] formule ancora sopra soglia: {", ".join(sorted(resid)) or "nessuna"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
