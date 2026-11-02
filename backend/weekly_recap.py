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


def _slugify(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", '').replace('’', '')
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:80]


def _lookup_profili():
    """Mappe dai profili esistenti: citta/nome torneo -> slug, e set slug
    giocatori. Servono a linkare i risultati solo dove la pagina esiste."""
    g_dir = ROOT / 'src' / 'content' / 'giocatori-profilo'
    t_dir = ROOT / 'src' / 'content' / 'tornei-profilo'
    giocatori = set()
    if g_dir.exists():
        for p in g_dir.glob('*.md'):
            s = _fm(p.read_text(), 'slug_profilo')
            if s:
                giocatori.add(s)
    tornei = {}  # chiave slugificata (citta/nome/slug-senza-anno) -> info
    if t_dir.exists():
        for p in t_dir.glob('*.md'):
            txt = p.read_text()
            slug = _fm(txt, 'slug_profilo')
            if not slug:
                continue
            info = {
                'slug': slug,
                'nome': _fm(txt, 'nome'),
                'citta': _fm(txt, 'citta'),
                'superficie': _fm(txt, 'superficie'),
                'anno': _fm(txt, 'anno'),
            }
            # Indicizza per forme slugificate (accent-insensitive): citta, nome
            # e slug senza anno finale. Cosi' "Queretaro" trova
            # "Santiago de Querétaro" / "queretaro-2026".
            chiavi = {_slugify(info['citta']), _slugify(info['nome']),
                      re.sub(r'-\d{4}$', '', slug)}
            for c in chiavi:
                if c:
                    tornei[c] = info
    return giocatori, tornei


def salva_risultati(verificati, settimana_iso, anno):
    """Persiste i vincitori VERIFICATI (con fonte) in src/data/risultati.json,
    accumulando nel tempo un dataset di risultati reali. Merge idempotente per
    (torneo, anno): la pagina /risultati li rende. Robusta: non blocca mai."""
    import json as _json
    out = ROOT / 'src' / 'data' / 'risultati.json'
    try:
        store = _json.loads(out.read_text()) if out.exists() else {}
    except Exception:
        store = {}
    risultati = store.get('risultati', [])
    giocatori_slugs, tornei_lk = _lookup_profili()

    def slug_se_esiste(nome_giocatore):
        s = _slugify(nome_giocatore)
        return s if s in giocatori_slugs else ''

    aggiunti = 0
    for v in verificati:
        torneo = (v.get('torneo') or '').strip()
        if not torneo or not v.get('vincitore'):
            continue
        # Match per slug (accent-insensitive). Prima esatto, poi sottostringa
        # (es. "queretaro" dentro un indice piu' lungo).
        chiave_t = _slugify(re.sub(r'\s+\d{4}$', '', torneo))
        info = tornei_lk.get(chiave_t)
        if not info and chiave_t:
            for k, v_info in tornei_lk.items():
                if chiave_t in k or k in chiave_t:
                    info = v_info
                    break
        info = info or {}
        entry = {
            'settimana': settimana_iso,
            'torneo': info.get('nome') or torneo,
            'torneo_display': info.get('citta') or re.sub(r'\s+\d{4}$', '', torneo).strip(),
            'slug_torneo': info.get('slug', ''),
            'categoria': v.get('categoria', ''),
            'superficie': info.get('superficie', ''),
            'anno': int(info.get('anno') or anno or 0) or anno,
            'vincitore': v.get('vincitore', ''),
            'vincitore_slug': slug_se_esiste(v.get('vincitore', '')),
            'finalista': v.get('finalista', ''),
            'finalista_slug': slug_se_esiste(v.get('finalista', '')),
            'punteggio': v.get('punteggio', ''),
            'fonte': v.get('fonte', ''),
        }
        chiave = (entry['slug_torneo'] or entry['torneo'].lower(), entry['anno'])
        # Sostituisci se gia' presente (stesso torneo/anno), altrimenti aggiungi.
        risultati = [r for r in risultati
                     if ((r.get('slug_torneo') or (r.get('torneo') or '').lower()), r.get('anno')) != chiave]
        risultati.append(entry)
        aggiunti += 1

    # Ordina: anno desc, settimana desc, categoria asc, torneo asc.
    # Sort stabili dal campo meno significativo al piu' significativo.
    ordine_cat = {'Slam': 0, 'Masters': 1, 'ATP': 2, 'WTA': 3}
    risultati.sort(key=lambda r: r.get('torneo_display', '') or '')
    risultati.sort(key=lambda r: ordine_cat.get(r.get('categoria'), 9))
    risultati.sort(key=lambda r: r.get('settimana', '') or '', reverse=True)
    risultati.sort(key=lambda r: int(r.get('anno') or 0), reverse=True)

    store = {'aggiornato': date.today().isoformat(), 'risultati': risultati}
    out.write_text(_json.dumps(store, ensure_ascii=False, indent=2) + '\n')
    print(f'[risultati] salvati {aggiunti} esiti, totale dataset {len(risultati)} -> {out}', flush=True)
    return out


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


PROMPT_REVISIONE = """Sei il caporedattore-revisore di AnalisiTennis.it. Rileggi il pezzo del lunedi'
qui sotto PRIMA della pubblicazione e correggilo. Hai davanti gli stessi dati con
cui e' stato scritto: usali come unica fonte di verita'.

{data_block}

**PEZZO DA RIVEDERE (JSON generato):**
```json
{articolo_json}
```

Controlla ed eventualmente CORREGGI, in ordine:

1. FATTUALE (contro i dati sopra):
   - Un campione si puo' dichiarare SOLO se e' tra i VINCITORI VERIFICATI. Se il
     pezzo assegna un titolo a un torneo non verificato, riscrivi la frase senza
     assegnare il campione.
   - Nessun punteggio, numero, ranking o record inventato. Nessun giocatore o
     match non presente nei dati. Non alterare i numeri.

2. SENSO E COPY (qui si annidano gli errori piu' insidiosi):
   - Nessun residuo di auto-correzione o editing lasciato nel testo (es.
     "pardon", "scusate", "anzi no", "cioe'", un nome subito ritrattato da un
     altro). Se c'e', tieni il nome/termine CORRETTO verificato nei dati ed
     elimina il residuo.
   - Nessuna parola fuori posto o priva di senso nel contesto (es. aggettivi
     palesemente sbagliati), nessun refuso di concordanza (genere/numero),
     nessuna frase contraddittoria, garbugliata o troncata.
   - Nomi di giocatori e tornei scritti in modo coerente in tutto il pezzo.

3. STILE: niente quote/bookmaker/scommesse, niente elenchi puntati, prosa fluida,
   niente "in conclusione"/"in sintesi". Lunghezza del corpo 450-750 parole.

**OUTPUT: un singolo JSON, nessun testo prima o dopo. Riporta SEMPRE tutti i campi
con il testo corretto (se non serviva correggere, riportali identici):**
```json
{{
  "verdict": "PASS se non hai cambiato nulla, FIX se hai corretto",
  "problemi": ["elenco sintetico di cosa hai corretto, vuoto se PASS"],
  "titolo": "...",
  "sottotitolo": "...",
  "descrizione": "...",
  "corpo_markdown": "...",
  "chiusura": "...",
  "tag": ["..."]
}}
```
"""


def rivedi(art, data_block):
    """Seconda passata: rilettura factuale + copy/senso del recap. Ritorna il
    pezzo con i campi corretti. Robusta: su errore o output malformato tiene
    l'originale (il recap non deve mai bloccare la pipeline)."""
    import json as _json
    campi = ['titolo', 'sottotitolo', 'descrizione', 'corpo_markdown', 'chiusura', 'tag']
    try:
        prompt = PROMPT_REVISIONE.format(
            data_block=data_block,
            articolo_json=_json.dumps({k: art.get(k) for k in campi}, ensure_ascii=False, indent=2),
        )
        rev = _claude_call(prompt, timeout=600)
    except Exception as e:
        print(f'  [revisione] errore ({e}): tengo la versione originale', flush=True)
        return art
    verdict = (rev.get('verdict') or '').upper()
    problemi = rev.get('problemi') or []
    # Applica solo i campi testuali validi restituiti dalla revisione.
    corretto = dict(art)
    for k in campi:
        v = rev.get(k)
        if k == 'tag':
            if isinstance(v, list) and v:
                corretto[k] = v
        elif isinstance(v, str) and v.strip():
            corretto[k] = v
    if verdict == 'FIX' and problemi:
        print(f'  [revisione] FIX, {len(problemi)} correzioni:', flush=True)
        for p in problemi[:6]:
            print(f'    - {p}', flush=True)
    else:
        print('  [revisione] PASS, nessuna correzione', flush=True)
    return corretto


def scrivi(giorno: date, gruppi, verificati, inizio, fine):
    today_human, _ = _today_strings()
    data_block = _data_block(gruppi, verificati, inizio, fine)
    prompt = PROMPT_RECAP.format(
        today_human=today_human,
        data_block=data_block,
    )
    art = _claude_call(prompt)

    # Passata di revisione factuale + copy (mancava: qui nascevano i refusi di
    # senso). Mirror leggero del fact-check a 3 pilastri degli articoli-match.
    print('[recap] revisione factuale + copy...', flush=True)
    art = rivedi(art, data_block)

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
    # Persisti gli esiti verificati nel dataset /risultati (cresce ogni lunedi').
    try:
        salva_risultati(verificati, giorno.isoformat(), fine.year)
    except Exception as e:
        print(f'[risultati] errore salvataggio (non blocco): {e}', flush=True)
    out = scrivi(giorno, gruppi, verificati, inizio, fine)
    print(f'[recap] scritto {out}')
