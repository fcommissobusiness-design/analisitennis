"""Recap settimanale editoriale: un pezzo del lunedi' che ripercorre la settimana
di tennis attraverso LE NOSTRE ANALISI (i tornei coperti e i big match della
settimana), con uno sguardo a quella che inizia.

Scelta di progetto importante: NON ricostruiamo i risultati dei tornei dall'API.
Il campo 'tournament_round' di API Tennis e' inaffidabile (segna come "Final"
anche match di qualificazione), quindi dedurre i vincitori produrrebbe risultati
sbagliati. Dato che il principio del sito e' zero allucinazioni, il recap si basa
solo su dati che controlliamo - i nostri articoli - e resta un pezzo editoriale
sulle storie e sui tornei della settimana, non un bollettino di risultati.

Uso:
  python3 weekly_recap.py [YYYY-MM-DD]   # data = lunedi' di pubblicazione

Senza data usa oggi. Copre i 7 giorni precedenti. Idempotente: se il recap di
quella data esiste gia', non rigenera. Se nella settimana non abbiamo pubblicato
nulla di rilevante, salta.
"""
import re
import sys
import unicodedata
from datetime import date, timedelta, datetime
from pathlib import Path

from generate_analysis import _claude_call, _today_strings

ROOT = Path(__file__).resolve().parent.parent
ARTICOLI = ROOT / 'src' / 'content' / 'articoli'

# Minimo di articoli nella settimana per pubblicare un recap sensato.
MIN_ARTICOLI = 4


def _fm(testo, campo):
    m = re.search(rf'^{campo}:\s*"?([^"\n]+)"?\s*$', testo, re.M)
    return (m.group(1).strip() if m else '')


def raccogli_settimana(giorno: date):
    """Raccoglie i nostri articoli-match dei 7 giorni prima di `giorno`,
    raggruppati per torneo. Niente editoriali (torneo 'Editoriale')."""
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


def _data_block(gruppi, inizio, fine):
    righe = []
    for g in gruppi:
        # Passa fino a 10 accoppiamenti reali per torneo: cosi' il modello ha i
        # dati veri e non deve inventare match o giocatori.
        elenco = '; '.join(g['match'][:10])
        righe.append(
            f"  - {g['torneo']} ({g['categoria']}, {g['superficie']}), "
            f"{len(g['match'])} match analizzati. Accoppiamenti: {elenco}"
        )
    corpo = '\n'.join(righe)
    return f"""
================================================================
LA SETTIMANA NELLE NOSTRE ANALISI {inizio.isoformat()} -> {fine.isoformat()}
FONTE: solo i nostri articoli. NON dichiarare chi ha vinto i match o i tornei
(pubblichiamo anteprime, non risultati). Parla dei tornei, delle superfici,
dei protagonisti e delle storie, non di esiti.
================================================================
{corpo}
================================================================
"""


PROMPT_RECAP = """Sei il caporedattore di AnalisiTennis.it, testata editoriale italiana di tennis.

**OGGI E' {today_human}.** Scrivi il pezzo editoriale del lunedi' che ripercorre
la settimana di tennis appena trascorsa COSI' COME L'ABBIAMO SEGUITA, basandoti
solo sui dati qui sotto, e chiude con uno sguardo alla settimana che inizia.

{data_block}

**REGOLE NON NEGOZIABILI:**
- NON dire chi ha vinto un match o un torneo, non inventare punteggi, risultati,
  numeri o ranking. Noi pubblichiamo anteprime: il pezzo parla di tornei,
  superfici, protagonisti attesi e storie, MAI di esiti.
- Usa solo i tornei e gli accoppiamenti presenti nel blocco. Non nominare
  giocatori o match che non siano elencati. Non alterare i numeri: se citi
  quanti match abbiamo analizzato, usa ESATTAMENTE quelli indicati, altrimenti
  descrivi il peso dei tornei senza cifre.
- Niente quote, bookmaker, scommesse. Prosa giornalistica fluida, niente elenchi
  puntati, niente "in conclusione"/"in sintesi". Tecnicismi solo del tennis.

**OUTPUT: un singolo JSON, nessun testo prima o dopo:**
```json
{{
  "titolo": "Titolo editoriale 45-70 caratteri sulla settimana di tennis",
  "sottotitolo": "Sottotitolo 80-130 caratteri",
  "descrizione": "Meta description SEO 150-160 caratteri",
  "corpo_markdown": "Articolo 450-700 parole in prosa. Apri con il quadro della settimana (i tornei principali, le superfici, dove si e' giocato), racconta le storie e i protagonisti che abbiamo seguito collegando i tornei tra loro, e chiudi guardando alla settimana che inizia. Usa mini-titoli markdown H3 (### ...) ai cambi di tema. Nessun elenco puntato. MAI risultati o vincitori.",
  "chiusura": "Frase editoriale di chiusura, 120-200 caratteri (andra' nel campo verdetto).",
  "tag": ["5-7 tag SEO: settimana, tornei citati, circuito"]
}}
```
"""


def scrivi(giorno: date, gruppi, inizio, fine):
    today_human, _ = _today_strings()
    prompt = PROMPT_RECAP.format(today_human=today_human, data_block=_data_block(gruppi, inizio, fine))
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
    out = scrivi(giorno, gruppi, inizio, fine)
    print(f'[recap] scritto {out}')
