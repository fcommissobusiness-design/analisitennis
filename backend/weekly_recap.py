"""Recap settimanale editoriale: un pezzo del lunedi' che ripercorre la settimana
di tennis attraverso LE NOSTRE ANALISI (i tornei coperti) e, per i tornei del
circuito maggiore, riporta i VINCITORI VERI verificati via web.

Due principi anti-allucinazione:
1. NON si deducono i risultati dal campo 'tournament_round' di API Tennis, che e'
   inaffidabile (segna 'Final' anche le qualificazioni, con entry duplicate).
2. I vincitori si citano SOLO se verificati via web search (claude headless con
   accesso al web): per ogni torneo del circuito maggiore si cerca il campione
   reale; se il torneo non e' concluso o non si trova un esito certo, non si
   dichiara alcun vincitore. I Challenger/ITF non si verificano (troppi, poco
   coperti dalle fonti) e restano trattati senza esiti.

Uso:
  python3 weekly_recap.py [YYYY-MM-DD]   # data = lunedi' di pubblicazione

Senza data usa oggi. Copre i 7 giorni precedenti. Idempotente: se il recap di
quella data esiste gia', non rigenera. Se la settimana e' troppo scarica, salta.
"""
import re
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

from generate_analysis import _claude_call, _today_strings

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'

# Minimo di articoli nella settimana per pubblicare un recap sensato.
MIN_ARTICOLI = 4
# Categorie del circuito maggiore: solo queste si verificano via web.
CAT_MAGGIORE = {'ATP', 'WTA', 'Slam', 'Masters'}


def _fm(testo, campo):
    m = re.search(rf'^{campo}:\s*"?([^"\n]+)"?\s*$', testo, re.M)
    return (m.group(1).strip() if m else '')


def raccogli_settimana(giorno: date):
    """Nostri articoli-match dei 7 giorni prima di `giorno`, per torneo."""
    inizio = giorno - timedelta(days=7)
    fine = giorno - timedelta(days=1)
    tornei = {}
    n_art = 0
    for p in ARTICOLI.glob('*.md'):
        t = p.read_text()
        d = _fm(t, 'data')
        if not d:
            continue
        try:
            dd = datetime.strptime(d[:10], '%Y-%m-%d').date()
        except ValueError:
            continue
        if not (inizio <= dd <= fine):
            continue
        torneo = _fm(t, 'torneo')
        if not torneo or torneo == 'Editoriale':
            continue
        n_art += 1
        g = tornei.setdefault(torneo, {
            'torneo': torneo,
            'categoria': _fm(t, 'categoria'),
            'superficie': _fm(t, 'superficie'),
            'match': [],
        })
        g1, g2 = _fm(t, 'giocatore1'), _fm(t, 'giocatore2')
        if g1 and g2:
            g['match'].append(f'{g1} - {g2}')
    gruppi = sorted(tornei.values(), key=lambda x: -len(x['match']))
    return gruppi, n_art, inizio, fine


def verifica_vincitori(gruppi, anno):
    """Per ogni torneo del circuito maggiore cerca via web il vincitore reale.
    Ritorna solo gli esiti VERIFICATI. Robusto: salta su errore o se incerto."""
    verificati = []
    for g in gruppi:
        if g['categoria'] not in CAT_MAGGIORE:
            continue
        nome = re.sub(r'\s*-\s*Qualification$', '', g['torneo'], flags=re.I).strip()
        circ = 'WTA' if g['categoria'] == 'WTA' else 'ATP'
        prompt = (
            f"Fai una WEB SEARCH e stabilisci chi ha vinto il torneo di tennis "
            f"{circ} {nome} {anno} (singolare). Se il torneo NON e' ancora concluso, "
            f"o non trovi una fonte chiara sul campione, metti \"verificato\": false. "
            f"Non tirare a indovinare. Rispondi SOLO con questo JSON, nient'altro:\n"
            f'{{"torneo": "{nome} {anno}", "vincitore": "Nome Cognome", '
            f'"finalista": "Nome Cognome", "punteggio": "6-3 6-4", '
            f'"verificato": true, "fonte": "url"}}'
        )
        try:
            r = _claude_call(prompt, timeout=240)
        except Exception as e:
            print(f'  [errore verifica] {nome}: {e}', flush=True)
            continue
        if r.get('verificato') and r.get('vincitore'):
            verificati.append({
                'torneo': nome, 'categoria': g['categoria'],
                'vincitore': r.get('vincitore'), 'finalista': r.get('finalista', ''),
                'punteggio': r.get('punteggio', ''), 'fonte': r.get('fonte', ''),
            })
            print(f"  [verificato] {nome}: {r.get('vincitore')} ({r.get('fonte', '')})", flush=True)
        else:
            print(f'  [non verificato] {nome} (torneo in corso o esito incerto)', flush=True)
    return verificati


def _data_block(gruppi, verificati, inizio, fine):
    righe = []
    for g in gruppi:
        elenco = '; '.join(g['match'][:10])
        righe.append(
            f"  - {g['torneo']} ({g['categoria']}, {g['superficie']}), "
            f"{len(g['match'])} match analizzati. Accoppiamenti: {elenco}"
        )
    coperti = '\n'.join(righe)

    if verificati:
        vr = '\n'.join(
            f"  - {v['torneo']} ({v['categoria']}): ha VINTO {v['vincitore']}"
            + (f", in finale contro {v['finalista']}" if v['finalista'] else '')
            + (f" con il punteggio {v['punteggio']}" if v['punteggio'] else '')
            for v in verificati
        )
    else:
        vr = '  (nessun vincitore verificato: tornei in corso o non confermati)'

    return f"""
================================================================
TORNEI CHE ABBIAMO COPERTO {inizio.isoformat()} -> {fine.isoformat()}
Parla di questi tornei, superfici, protagonisti. Nomina solo accoppiamenti
elencati; non alterare i numeri.
================================================================
{coperti}

================================================================
VINCITORI VERIFICATI VIA WEB (fonte unica per gli esiti)
Puoi dichiarare un campione SOLO se e' in questo elenco. Per i tornei non
presenti qui NON dire chi ha vinto (sono in corso o non confermati).
================================================================
{vr}
================================================================
"""


PROMPT_RECAP = """Sei il caporedattore di AnalisiTennis.it, testata editoriale italiana di tennis.

**OGGI E' {today_human}.** Scrivi il pezzo editoriale del lunedi' che ripercorre
la settimana di tennis appena trascorsa e chiude con uno sguardo a quella che
inizia, basandoti SOLO sui dati qui sotto.

{data_block}

**REGOLE NON NEGOZIABILI:**
- I VINCITORI: puoi dichiarare chi ha vinto un torneo SOLO se compare
  nell'elenco "VINCITORI VERIFICATI". Per gli altri tornei NON dire chi ha
  vinto (sono in corso o non confermati): parlane senza assegnare un campione.
- Non inventare punteggi, risultati, numeri, ranking o record non presenti nei
  dati. Non nominare giocatori o match non elencati. Non alterare i numeri.
- Niente quote, bookmaker, scommesse. Prosa giornalistica fluida, niente elenchi
  puntati, niente "in conclusione"/"in sintesi". Tecnicismi solo del tennis.

**OUTPUT: un singolo JSON, nessun testo prima o dopo:**
```json
{{
  "titolo": "Titolo editoriale 45-70 caratteri sulla settimana di tennis",
  "sottotitolo": "Sottotitolo 80-130 caratteri",
  "descrizione": "Meta description SEO 150-160 caratteri",
  "corpo_markdown": "Articolo 450-750 parole in prosa. Apri con il quadro della settimana (tornei, superfici, dove si e' giocato), racconta i tornei principali citando i VINCITORI VERIFICATI dove disponibili e le storie dei tornei ancora in corso senza assegnare campioni, poi chiudi guardando alla settimana che inizia. Mini-titoli markdown H3 (### ...) ai cambi di tema. Nessun elenco puntato.",
  "chiusura": "Frase editoriale di chiusura, 120-200 caratteri (andra' nel campo verdetto).",
  "tag": ["5-7 tag SEO: settimana, tornei citati, circuito"]
}}
```
"""


def scrivi(giorno: date, gruppi, verificati, inizio, fine):
    today_human, _ = _today_strings()
    prompt = PROMPT_RECAP.format(
        today_human=today_human,
        data_block=_data_block(gruppi, verificati, inizio, fine),
    )
    art = _claude_call(prompt)

    slug = f'{giorno.isoformat()}-la-settimana-nel-tennis'
    fm = {
        'titolo': art['titolo'],
        'sottotitolo': art['sottotitolo'],
        'data': giorno.isoformat(),
        'autore': 'Redazione AnalisiTennis',
        'torneo': 'Editoriale',
        'categoria': 'ATP',
        'superficie': 'cemento',
        'giocatore1': 'Redazione',
        'giocatore2': 'Lettori',
        'tag': art.get('tag', []),
        'verdetto': art.get('chiusura', 'La settimana di tennis raccontata dalla Redazione.'),
        'descrizione': art['descrizione'],
        'pubblicato': True,
    }
    lines = ['---']
    for k, val in fm.items():
        if isinstance(val, list):
            lines.append(f'{k}:')
            for it in val:
                lines.append(f'  - "{it}"')
        elif isinstance(val, bool):
            lines.append(f'{k}: {str(val).lower()}')
        else:
            lines.append(f'{k}: "{str(val).replace(chr(34), chr(39))}"')
    lines.append('---')
    lines.append('')
    lines.append(art['corpo_markdown'])
    out = ARTICOLI / f'{slug}.md'
    out.write_text('\n'.join(lines))
    return out


if __name__ == '__main__':
    giorno = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    slug = f'{giorno.isoformat()}-la-settimana-nel-tennis'
    if (ARTICOLI / f'{slug}.md').exists():
        print(f'[recap] gia esistente per {giorno}, skip')
        sys.exit(0)
    gruppi, n_art, inizio, fine = raccogli_settimana(giorno)
    print(f'[recap] settimana {inizio} -> {fine}: {n_art} articoli, {len(gruppi)} tornei')
    for g in gruppi:
        print(f"  {g['torneo']} ({g['categoria']}): {len(g['match'])} match")
    if n_art < MIN_ARTICOLI:
        print(f'[recap] pochi articoli ({n_art} < {MIN_ARTICOLI}): niente recap. Skip.')
        sys.exit(0)
    print('[recap] verifica vincitori via web...')
    verificati = verifica_vincitori(gruppi, fine.year)
    print(f'[recap] {len(verificati)} vincitori verificati')
    out = scrivi(giorno, gruppi, verificati, inizio, fine)
    print(f'[recap] scritto {out}')
