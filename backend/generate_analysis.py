"""Per un match applica il framework canonico KAKEGURUI FASE 1-2-3-4 + sanity anti-bias
+ FACT-CHECK anti-allucinazione.

Pipeline:
1. Fetch autoritativo API Tennis: H2H completo, ultimi 15 match per giocatore,
   standings, risultati ultimi tornei. Costruisce un data_block FATTUALE.
2. Chiama claude headless con prompt che include i dati autoritativi e vieta
   di citare fatti non presenti nel data_block.
3. Seconda passata claude di FACT-CHECK: riceve articolo + data_block, verifica
   ogni affermazione factuale (date, score, winner, titoli, ranking, finali
   raggiunte). Se trova errori, segnala e la pipeline rigenera.
4. Max 2 tentativi di rigenerazione per articolo. Se persiste errore, skip.
"""
import json
import os
import sys
import subprocess
import shutil
import requests
from pathlib import Path
from datetime import date, timedelta


def _env_api_key():
    k = os.environ.get('API_TENNIS_KEY')
    if k: return k
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith('API_TENNIS_KEY='):
                return line.split('=', 1)[1].strip()
    return None


API_KEY = _env_api_key()
API_BASE = 'https://api.api-tennis.com/tennis/'


def _api(method, **params):
    if not API_KEY:
        return {}
    params.update(method=method, APIkey=API_KEY)
    try:
        r = requests.get(API_BASE, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def fetch_h2h(pk1, pk2):
    """Precedenti diretti autoritativi."""
    d = _api('get_H2H', first_player_key=pk1, second_player_key=pk2)
    h2h = d.get('result', {}).get('H2H', []) or []
    rows = []
    for m in h2h:
        p1 = m.get('event_first_player', '')
        p2 = m.get('event_second_player', '')
        winner_label = m.get('event_winner', '')
        winner_name = p1 if winner_label == 'First Player' else (p2 if winner_label == 'Second Player' else 'N/A')
        rows.append({
            'date': m.get('event_date'),
            'tournament': m.get('tournament_name'),
            'round': m.get('tournament_round'),
            'match': f'{p1} vs {p2}',
            'winner': winner_name,
            'score': m.get('event_final_result'),
        })
    rows.sort(key=lambda r: r.get('date') or '')
    return rows


def fetch_recent_matches(pk, days=120, max_results=15):
    """Ultimi match autoritativi del giocatore."""
    end = date.today()
    start = end - timedelta(days=days)
    d = _api('get_fixtures',
             date_start=start.isoformat(),
             date_stop=end.isoformat(),
             player_key=pk)
    result = d.get('result', []) or []
    rows = []
    for m in result:
        p1 = m.get('event_first_player', '')
        p2 = m.get('event_second_player', '')
        if '/' in p1 or '/' in p2:
            continue  # skip doppi
        if str(m.get('event_status', '')).lower() not in ('finished',):
            continue
        pk_str = str(pk)
        is_p1 = (str(m.get('first_player_key', '')) == pk_str)
        if is_p1:
            opp = p2
            winner_label = m.get('event_winner', '')
            won = winner_label == 'First Player'
        else:
            opp = p1
            winner_label = m.get('event_winner', '')
            won = winner_label == 'Second Player'
        rows.append({
            'date': m.get('event_date'),
            'tournament': m.get('tournament_name'),
            'round': m.get('tournament_round'),
            'opponent': opp,
            'result': 'W' if won else 'L',
            'score': m.get('event_final_result'),
        })
    rows.sort(key=lambda r: r.get('date') or '', reverse=True)
    return rows[:max_results]


def build_data_block(match):
    """Costruisce il blocco di dati autoritativi API Tennis."""
    pk1 = match.get('first_player_key')
    pk2 = match.get('second_player_key')
    p1 = match.get('event_first_player', '')
    p2 = match.get('event_second_player', '')

    h2h = fetch_h2h(pk1, pk2)
    recent1 = fetch_recent_matches(pk1)
    recent2 = fetch_recent_matches(pk2)

    def fmt_h2h():
        if not h2h:
            return '  (nessun precedente registrato in archivio API Tennis)'
        lines = []
        for i, r in enumerate(h2h, 1):
            lines.append(f"  [{i}] {r['date']} - {r['tournament']} ({r['round']})")
            lines.append(f"      Match: {r['match']}")
            lines.append(f"      VINCITORE: {r['winner']} - score {r['score']}")
        return '\n'.join(lines)

    def fmt_recent(name, rows):
        if not rows:
            return f'  (nessun match recente registrato per {name})'
        lines = []
        for r in rows:
            lines.append(f"  {r['date']} {r['result']} vs {r['opponent']} - {r['tournament']} {r['round']} - {r['score']}")
        return '\n'.join(lines)

    stats_p1 = {'W': sum(1 for r in recent1 if r['result'] == 'W'), 'L': sum(1 for r in recent1 if r['result'] == 'L')}
    stats_p2 = {'W': sum(1 for r in recent2 if r['result'] == 'W'), 'L': sum(1 for r in recent2 if r['result'] == 'L')}

    return f"""
================================================================
DATI AUTORITATIVI API TENNIS - FONTE UNICA DELLA VERITA'
Non inventare dati non presenti qui sotto. Non desumere score o
risultati da nomi di tornei. Usa ESCLUSIVAMENTE questi record.
================================================================

PRECEDENTI DIRETTI {p1} vs {p2}:
{fmt_h2h()}

ULTIMI 15 MATCH {p1} (bilancio {stats_p1['W']}V-{stats_p1['L']}L):
{fmt_recent(p1, recent1)}

ULTIMI 15 MATCH {p2} (bilancio {stats_p2['W']}V-{stats_p2['L']}L):
{fmt_recent(p2, recent2)}
================================================================
"""


PROMPT_PIPELINE = """Sei il motore editoriale di AnalisiTennis.it, una testata di analisi tennis in italiano.

Devi analizzare questo match applicando INTEGRALMENTE il framework KAKEGURUI FASE 1-2-3-4
+ integrazioni + sanity-check-anti-bias, cosi' come salvato nella memoria utente
`project_prompt_fasi_canonico.md`. Riapplica OGNI VOCE, usa i prompt-recupero per
verificare che nulla sia saltato, applica il sanity anti-bias finale PRIMA di scrivere l'output.

**MATCH:**
{match_block}

**DATI AUTORITATIVI (FONTE UNICA):**
{data_block}

**REGOLA ANTI-ALLUCINAZIONE (NON NEGOZIABILE)**:
Ogni singolo dato factuale che citi nell'articolo e nel verdetto (score, vincitori di
precedenti, date, torneo, risultato specifico, titoli vinti, finali raggiunte, ranking)
DEVE essere direttamente estratto dal blocco DATI AUTORITATIVI qui sopra.
- Se un precedente dice "VINCITORE: X - score 2-1", NON puoi scrivere che l'altro giocatore
  ha vinto o che il punteggio era diverso.
- Se non c'e' nessun precedente nel blocco, NON inventare un H2H.
- Se un match non e' nei recenti del giocatore, NON citarlo.
- Nei precedenti, LEGGI con attenzione il campo "VINCITORE" ESPLICITO: non desumere il
  vincitore dalla posizione del nome nel campo "Match". Il formato "A vs B - VINCITORE: B"
  significa che B ha vinto, non A.
- Per ogni dato citato, prima di scrivere la frase, verifica mentalmente di averlo visto
  nel blocco. Se non e' li', NON scriverlo.

Fatti ammessi senza fonte diretta (background culturale non controverso):
- Nazionalita' nota del giocatore
- Mano dominante nota (destro/mancino) se e' informazione pubblica consolidata
- Caratteristiche generali della superficie di gioco

Fatti NON ammessi senza dato autoritativo nel blocco:
- Score di precedenti
- Vincitore di H2H
- Titoli stagionali
- Finali raggiunte
- Ranking numerico specifico
- Bilancio stagionale W-L
- Nomi specifici di avversari battuti/persi

**OUTPUT RICHIESTO** (un singolo JSON, nessun testo prima o dopo):

```json
{{
  "titolo": "Titolo giornalistico avvincente, 50-70 caratteri, SEO-friendly (contiene almeno un nome giocatore). NON deve anticipare il verdetto, deve suscitare curiosita' sul match.",
  "sottotitolo": "Sottotitolo che suscita curiosita', 80-130 caratteri. Imparziale, non anticipa il pronostico.",
  "descrizione": "Meta description SEO 150-160 caratteri. Imparziale.",
  "corpo_markdown": "ARTICOLO COMPLETO in prosa giornalistica italiana, 700-1100 parole, paragrafi max 4 righe, parole-chiave principali in **grassetto** senza esagerare (3-6 occorrenze totali). Nessun elenco puntato nel corpo. Nessun riferimento a sistema/FASE/bankroll/quote/bookmaker/stake/EV/pick. Niente abbreviazioni oscure (sempre 'palle break' non 'BP', 'scontri diretti' non 'H2H'). Tecnicismi solo del tennis. Prosa fluida variabile, niente 'in sintesi', 'in conclusione', 'ecco perche'', 'fondamentalmente'. IMPARZIALITA' OBBLIGATORIA: tratta i due giocatori allo stesso modo nel corpo, dati di uno + dati dell'altro, precedenti di uno + contesto dell'altro. Il corpo NON deve far trasparire verso chi pendiamo. Nessun aggettivo sbilanciato, nessuna tesi anticipata nel corpo. Il verdetto arriva solo nel campo 'verdetto'. MINI-TITOLI DI SEZIONE OBBLIGATORI: inserisci mini-titoli markdown H3 (### Titoletto) PRIMA dei paragrafi che aprono un nuovo argomento tematico. Esempi di titoletti: '### Precedenti', '### Forma fisica', '### Stile di gioco', '### Fattore campo', '### Il momento in classifica', '### Il mese di ottobre' (varia in base al match). Target: 3-5 mini-titoli in totale. Il PRIMO paragrafo introduttivo NON porta mini-titolo. L'ULTIMO paragrafo di chiusura prima del verdetto NON porta mini-titolo. Non mettere mini-titoli in ogni paragrafo, solo ai cambi di contesto netti.",
  "verdetto": "Pronostico sportivo editoriale DECISO 2-3 frasi, 180-280 caratteri. SOLO uno di questi tre formati: (a) 'Oggi la puo' spuntare X' (match equilibrato con leggero favore X); (b) 'Oggi nettamente X' (favore netto X); (c) 'Partita equilibrata, ma e' molto probabile che Y prenda almeno un set / lo scenario piu' plausibile e' 2-1' (match stretto scenario tre set). MAI altri mercati: niente ace, over/under games, handicap, tiebreak si/no. Solo chi vince il match o scenario >=1 set / 2-1. Mai quote, mai consigli di scommessa. VERDETTO DECISO, MAI PIEDE IN DUE SCARPE: se dici 'oggi la puo' spuntare X', NON aggiungere subito dopo 'pero' l'altro e' avanti nei precedenti e resta in corsa'. Scegli una strada e motivala, la controlettura sta gia' nel corpo imparziale. Il verdetto e' il momento in cui ci sbilanciamo con convinzione, non in cui ci cautaliamo.",
  "tag": ["5-8 tag di parole-chiave SEO: giocatori, torneo, categoria, superficie, tipo-match"],
  "sanity_check": {{
    "bias_rilevati": ["lista eventuali bias infiltrati e corretti"],
    "voci_fasi_tutte_applicate": true,
    "corpo_imparziale": true,
    "verdetto_solo_match_winner_o_un_set": true,
    "fatti_citati_tutti_verificati_contro_data_block": true,
    "elenco_fatti_citati": [
      "elenca qui ogni affermazione factuale che hai scritto nel corpo e nel verdetto, con il riscontro autoritativo (es. 'H2H 2-0 Moller: confermato da precedenti 2024-11-09 Lima e 2025-10-01 Braga, VINCITORE Moller in entrambi')"
    ]
  }}
}}
```

**REGOLE OUTPUT NON NEGOZIABILI**:
1. Niente riferimenti al sistema, FASE, bankroll, quote, bookmaker, DomusBet, EV, stake, Kelly, overlay
2. Niente abbreviazioni che possano confondere
3. Tecnicismi solo del tennis
4. Prosa fluida NON AI-smell
5. IMPARZIALITA' nel corpo
6. Verdetto SOLO su match-winner o >=1 set / 2-1
7. Culmina con verdetto sportivo editoriale, mai una quota
8. 700-1100 parole, paragrafi max 4 righe
9. Firma implicita: Redazione AnalisiTennis
10. ZERO ALLUCINAZIONI: cita solo fatti presenti nel DATI AUTORITATIVI qui sopra
"""


PROMPT_FACT_CHECK = """Sei un fact-checker rigoroso per AnalisiTennis.it.

Ricevi:
1. Un articolo di analisi tennis gia' scritto (in formato JSON con campi titolo,
   sottotitolo, descrizione, corpo_markdown, verdetto).
2. Il blocco DATI AUTORITATIVI API Tennis che era la fonte di verita' per quell'articolo.

Devi verificare che OGNI affermazione factuale (score, vincitori di H2H, date, risultati
specifici, titoli, finali, ranking, bilanci W-L, nomi di avversari battuti o persi) sia
COERENTE con i dati autoritativi.

Attenzione particolare ai PRECEDENTI DIRETTI: il campo "VINCITORE" indica chi ha vinto
il match. Un record "A vs B, VINCITORE: A" significa che A ha vinto. Non invertire mai.

**ARTICOLO DA VERIFICARE:**
{article_json}

**DATI AUTORITATIVI (fonte di verita'):**
{data_block}

**OUTPUT RICHIESTO** (un singolo JSON, nessun testo prima o dopo):

```json
{{
  "verdict": "PASS" oppure "FAIL",
  "errori": [
    "lista di errori factuali trovati. Vuota se verdict PASS. Esempi: 'L'articolo dice che Rocha ha vinto a Braga 2025 ma i dati autoritativi dicono VINCITORE: Moller.' Ogni errore cita (a) la frase incriminata e (b) la verita' autoritativa."
  ],
  "note": [
    "eventuali note su affermazioni ambigue o non verificabili ma non chiaramente false"
  ]
}}
```

Non essere pedante su particolari stilistici o interpretativi, cerca SOLO errori factuali
verificabili contro il blocco dati. Se un fatto non e' citato nel blocco e nemmeno
nell'articolo, non e' un errore. Se un fatto e' nell'articolo ma contraddice il blocco,
e' un errore. Se un fatto e' nell'articolo e il blocco non lo copre (es. descrizione
generale di superficie), NON e' un errore.
"""


def _claude_call(prompt, timeout=1800):
    claude_bin = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~/.local/node/bin')}:{env.get('PATH','')}"
    result = subprocess.run(
        [claude_bin, '-p', prompt, '--output-format', 'json'],
        capture_output=True, text=True, timeout=timeout, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f'claude CLI fallita: {result.stderr}')
    try:
        wrapper = json.loads(result.stdout)
        content = wrapper.get('result') or wrapper.get('content') or result.stdout
    except json.JSONDecodeError:
        content = result.stdout
    start = content.find('{')
    end = content.rfind('}') + 1
    if start < 0 or end <= start:
        raise RuntimeError(f'JSON non trovato nel content: {content[:300]}')
    return json.loads(content[start:end])


def fact_check(article, data_block):
    """Seconda passata claude: verifica che ogni fatto citato sia nel data_block."""
    article_slim = {
        'titolo': article.get('titolo'),
        'sottotitolo': article.get('sottotitolo'),
        'descrizione': article.get('descrizione'),
        'corpo_markdown': article.get('corpo_markdown'),
        'verdetto': article.get('verdetto'),
    }
    prompt = PROMPT_FACT_CHECK.format(
        article_json=json.dumps(article_slim, ensure_ascii=False, indent=2),
        data_block=data_block
    )
    return _claude_call(prompt, timeout=600)


def genera(match, max_tentativi=2):
    """Genera articolo + fact-check + retry se fallisce."""
    match_block = f"""- Data match: {match.get('event_date')} {match.get('event_time')}
- Giocatore 1: {match.get('event_first_player')} (key API: {match.get('first_player_key')})
- Giocatore 2: {match.get('event_second_player')} (key API: {match.get('second_player_key')})
- Torneo: {match.get('tournament_name')}
- Fase/Round: {match.get('tournament_round')}
- Tipo: {match.get('event_type_type')}
- Stagione: {match.get('tournament_season')}"""

    print(f'  Fetch dati autoritativi API Tennis...', flush=True)
    data_block = build_data_block(match)

    last_err = None
    for tentativo in range(1, max_tentativi + 1):
        print(f'  Tentativo generazione {tentativo}/{max_tentativi}...', flush=True)
        prompt = PROMPT_PIPELINE.format(match_block=match_block, data_block=data_block)
        article = _claude_call(prompt)

        print(f'  Fact-check in corso...', flush=True)
        check = fact_check(article, data_block)
        verdict = check.get('verdict', 'FAIL')
        errors = check.get('errori', []) or []

        if verdict == 'PASS' and not errors:
            print(f'  Fact-check: PASS', flush=True)
            article['fact_check'] = check
            article['data_block_used'] = data_block
            return article

        last_err = errors
        print(f'  Fact-check: FAIL con {len(errors)} errori:', flush=True)
        for e in errors[:5]:
            print(f'    - {e}', flush=True)

    raise RuntimeError(f'Impossibile generare articolo privo di allucinazioni dopo {max_tentativi} tentativi. Ultimi errori: {last_err}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: python generate_analysis.py selected_YYYY-MM-DD.json', file=sys.stderr)
        sys.exit(1)
    selected = json.loads(Path(sys.argv[1]).read_text())
    outdir = Path(sys.argv[1]).parent / 'analyses'
    outdir.mkdir(exist_ok=True)
    for m in selected:
        mid = m.get('event_key')
        print(f'Analizzo match {mid}: {m.get("event_first_player")} vs {m.get("event_second_player")}', flush=True)
        try:
            analysis = genera(m)
            out = outdir / f'analysis_{mid}.json'
            out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
            print(f'  Salvata in {out}', flush=True)
        except Exception as e:
            print(f'  ERRORE: {e}', file=sys.stderr, flush=True)
