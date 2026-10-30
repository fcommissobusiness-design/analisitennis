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


def _oggi():
    """Data di riferimento 'oggi' per l'analisi. Override con
    ANALISITENNIS_OGGI=YYYY-MM-DD quando si generano in anticipo gli articoli
    del giorno dopo (es. stasera gli articoli di domani). Senza env resta la
    data di sistema: comportamento invariato per la run schedulata."""
    ov = os.environ.get('ANALISITENNIS_OGGI', '').strip()
    if ov:
        try:
            return date.fromisoformat(ov)
        except Exception:
            pass
    return date.today()


def _dati_fino():
    """Data MASSIMA (inclusa, 'YYYY-MM-DD') dei risultati da usare nei dati
    autoritativi. Con ANALISITENNIS_DATI_FINO si scartano H2H e match recenti
    con data SUCCESSIVA: serve ai run manuali in ritardo, quando alcune partite
    di oggi si sono gia' concluse, per NON far trapelare il risultato nel
    pronostico (l'analisi resta un'anteprima come alle 07:00). Senza env: nessun
    filtro, comportamento invariato per la run schedulata."""
    return os.environ.get('ANALISITENNIS_DATI_FINO', '').strip() or None


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
    cutoff = _dati_fino()
    if cutoff:
        rows = [r for r in rows if (r.get('date') or '') <= cutoff]
    rows.sort(key=lambda r: r.get('date') or '')
    return rows


def fetch_recent_matches(pk, days=120, max_results=15):
    """Ultimi match autoritativi del giocatore."""
    end = _oggi()
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
    cutoff = _dati_fino()
    if cutoff:
        rows = [r for r in rows if (r.get('date') or '') <= cutoff]
    rows.sort(key=lambda r: r.get('date') or '', reverse=True)
    return rows[:max_results]


class ApiTennisNoData(RuntimeError):
    """Sollevata quando API Tennis non torna dati utili per il match.
    L'analisi si interrompe e il match viene segnalato nel log: meglio
    saltare un pronostico che pubblicare un'analisi senza dati autoritativi."""
    pass


def build_data_block(match):
    """Costruisce il blocco di dati autoritativi API Tennis.
    Se API Tennis non risponde o non ha dati sufficienti sui due giocatori,
    solleva ApiTennisNoData: l'analisi non parte, meglio zero articolo che
    uno allucinato su dati vuoti."""
    pk1 = match.get('first_player_key')
    pk2 = match.get('second_player_key')
    p1 = match.get('event_first_player', '')
    p2 = match.get('event_second_player', '')

    if not pk1 or not pk2:
        raise ApiTennisNoData(
            f'player_key mancante per {p1}/{p2}: API Tennis non ha i giocatori registrati'
        )

    h2h = fetch_h2h(pk1, pk2)
    recent1 = fetch_recent_matches(pk1)
    recent2 = fetch_recent_matches(pk2)

    # Gate "dati sufficienti": servono almeno un recente per ciascuno (o almeno
    # un H2H). Se la pipeline non ha niente di autoritativo, l'articolo si
    # ridurrebbe a congetture pure -> abort.
    if not recent1 and not recent2 and not h2h:
        raise ApiTennisNoData(
            f'API Tennis vuota per entrambi i giocatori ({p1} e {p2}): '
            'niente H2H, niente match recenti. Analisi interrotta per '
            'evitare pubblicazione senza fonti.'
        )
    if not recent1 and not h2h:
        raise ApiTennisNoData(
            f'API Tennis senza dati su {p1} (niente recenti, niente H2H). Analisi interrotta.'
        )
    if not recent2 and not h2h:
        raise ApiTennisNoData(
            f'API Tennis senza dati su {p2} (niente recenti, niente H2H). Analisi interrotta.'
        )

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

**OGGI E' {today_human}** (data autoritativa, usala come riferimento per
"freschezza dei dati", "aggiornato al giorno corrente", "ultime settimane",
"questo mese", "stagione in corso").

Devi analizzare questo match applicando INTEGRALMENTE il framework KAKEGURUI FASE 1-2-3-4
+ integrazioni + sanity-check-anti-bias, cosi' come salvato nella memoria utente
`project_prompt_fasi_canonico.md`. Riapplica OGNI VOCE, usa i prompt-recupero per
verificare che nulla sia saltato, applica il sanity anti-bias finale PRIMA di scrivere l'output.

**PROTOCOLLO ESECUZIONE OBBLIGATORIO (regola madre 23/10/2026 serale)**:
Per ogni singola voce di ogni fase:
1. Esegui la voce.
2. Esegui subito un prompt-controllo mentale per quella voce: "ho fatto tutto?
   ho integrato ogni sotto-elemento? i dati sono completi, precisi, aggiornati
   a OGGI {today_short}? manca qualcosa?". Se SI a "manca qualcosa", INTEGRA
   prima di passare oltre.
3. A fine fase, esegui il prompt-recupero di fase: "ho fatto tutte le voci?
   mancano voci saltate? integrale ora".
4. A fine di tutte le fasi, esegui il SANITY CHECK FINALE a tre pilastri
   (completezza+aggiornamento, anti-allucinazione, anti-bias strutturale).
   Se un pilastro fallisce, rigenera.

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
  "verdetto": "Pronostico sportivo editoriale DECISO 2-3 frasi, 180-280 caratteri. PRIMA di scegliere il formato, classifica il GAP tra i due giocatori leggendo il blocco DATI AUTORITATIVI secondo questa griglia (OBBLIGATORIA):\\n\\nGAP NETTO -> usa formato (b) 'Oggi nettamente X: motivazione'. Serve ALMENO una di queste condizioni documentate: differenza ranking >= 50 posizioni; H2H completo >= 3-0; forma recente molto piu' solida di un intero mese (es. titolo o finale recente dell'uno contro due o piu' sconfitte secche dell'altro); mismatch stilistico forte sulla superficie (es. big server indoor contro ribattitore in difficolta' sul veloce).\\n\\nGAP SOTTILE -> usa formato (a) 'Oggi la puo' spuntare X: motivazione'. Serve che DUE fattori concordanti modesti pendano dalla stessa parte (es. un precedente favorevole + forma leggermente migliore). Un solo fattore marginale NON basta per usare (a).\\n\\nGAP APERTO -> usa formato (c) 'Partita equilibrata, scenario piu' plausibile un 2-1 con Y che prende almeno un set' oppure 'match da terzo set senza un favorito chiaro'. Usa (c) quando: nessun fattore e' nettamente a favore di uno; segnali contrastanti (es. H2H all'uno, forma all'altro); dati scarsi o H2H a zero senza altri appigli; esordienti al matchup senza storia.\\n\\nREGOLA ANTI-BIAS DI LINGUAGGIO: NON usare (a) 'puo' spuntare' come default comodo. Se stai scegliendo (a) solo perche' 'tanto il match e' tirato', la scelta corretta e' quasi sempre (c). Il formato (a) e' per quando il favorito e' identificabile ma di misura, con due fattori concordanti; se ne hai uno solo scivola a (c). Target di distribuzione naturale su 10 pronostici: circa 2-3 (b), 4-5 (a), 2-3 (c). Se nella giornata stai scrivendo tutti (a) stai sbagliando.\\n\\nMAI altri mercati: niente ace, over/under games, handicap, tiebreak si/no. Solo chi vince il match o scenario >=1 set / 2-1. Mai quote, mai consigli di scommessa. VERDETTO DECISO, MAI PIEDE IN DUE SCARPE: scegli la strada e motivala, la controlettura sta gia' nel corpo imparziale.",
  "tag": ["5-8 tag di parole-chiave SEO: giocatori, torneo, categoria, superficie, tipo-match"],
  "sanity_check": {{
    "pilastro_1_completezza_aggiornamento": {{
      "dati_completi": "true/false + nota",
      "dati_precisi": "true/false + nota",
      "dati_aggiornati_a_oggi_{today_short}": "true/false + nota",
      "nessun_dato_stimato_spacciato_per_verificato": "true/false"
    }},
    "pilastro_2_anti_allucinazione": {{
      "fatti_citati_tutti_verificati_contro_data_block": true,
      "campo_vincitore_H2H_letto_esplicitamente": true,
      "elenco_fatti_citati": [
        "ogni affermazione factuale + riscontro autoritativo (es. 'H2H 2-0 Moller: confermato precedenti 2024-11-09 Lima VINCITORE Moller 2-0 e 2025-10-01 Braga VINCITORE Moller 1-2')"
      ]
    }},
    "pilastro_3_anti_bias_strutturale": {{
      "bias_pro_underdog_assente": "true/false + nota (non ho scritto 'contro ogni pronostico', 'si prende lo scalpo', 'stravince nonostante tutti lo diano battuto')",
      "bias_pro_favorito_assente": "true/false + nota (non ho scritto 'la classifica parla chiaro', 'non c'e' storia', 'deve vincere per forza')",
      "bias_nome_forte_assente": "true/false",
      "bias_recency_assente": "true/false (non ho dato peso solo agli ultimi 2-3 match)",
      "bias_home_crowd_assente": "true/false (non ho assunto che il pubblico aiuti senza verificare pattern storico home)",
      "bias_confirmation_assente": "true/false (ho cercato dati che contraddicevano la tesi iniziale, non solo che la confermavano)"
    }},
    "bias_rilevati_e_corretti": ["lista bias infiltrati durante la generazione e come li ho corretti"],
    "voci_fasi_tutte_applicate": true,
    "corpo_imparziale": true,
    "verdetto_solo_match_winner_o_un_set": true,
    "classificazione_gap": {{
      "scelta": "netto|sottile|aperto",
      "formato_verdetto_usato": "a|b|c",
      "fattori_a_favore_del_prescelto": ["elenco concreto dei fattori documentati nei DATI AUTORITATIVI che hanno portato alla scelta: ranking X vs Y, H2H N-M, titoli recenti, forma delle ultime N partite, stile/superficie"],
      "scelta_coerente_con_griglia": "true/false + nota (se scelta=netto DEVE essere formato=b; se scelta=sottile con 2 fattori concordanti formato=a; altrimenti formato=c)",
      "non_default_puo_spuntare": "true/false (confermo che non ho scelto (a) solo per inerzia, ho i due fattori concordanti richiesti)"
    }}
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


PROMPT_FACT_CHECK = """Sei un fact-checker rigoroso + bias-checker per AnalisiTennis.it.

Oggi e' {today_human}. Devi considerare questa data come riferimento di
"aggiornato al giorno corrente".

Ricevi:
1. Un articolo di analisi tennis gia' scritto (in formato JSON con campi titolo,
   sottotitolo, descrizione, corpo_markdown, verdetto).
2. Il blocco DATI AUTORITATIVI API Tennis che era la fonte di verita' per quell'articolo.

Devi eseguire TRE verifiche in ordine. Se UNA SOLA fallisce, verdict e' FAIL.

### PILASTRO 1 — COMPLETEZZA E AGGIORNAMENTO DATI
- Ogni dato citato nell'articolo e' completo (nessun "N/A" o campo vuoto)?
- Ogni dato citato e' preciso (confrontato puntualmente col blocco DATI AUTORITATIVI)?
- Ogni dato citato fa riferimento a eventi coerenti con oggi {today_short}
  (es. "il titolo di Porto" ha senso solo se la data del titolo nei dati e'
  antecedente a oggi; "la stagione in corso" deve essere l'anno di oggi)?

### PILASTRO 2 — ANTI-ALLUCINAZIONE
Verifica che OGNI affermazione factuale (score, vincitori H2H, date, risultati
specifici, titoli, finali, ranking, bilanci W-L, nomi di avversari battuti o persi)
sia COERENTE con i dati autoritativi.
Attenzione particolare ai PRECEDENTI DIRETTI: il campo "VINCITORE" indica chi ha
vinto il match. Un record "A vs B, VINCITORE: A" significa che A ha vinto. Non
invertire mai la lettura.

### PILASTRO 3 — ANTI-BIAS STRUTTURALE
Verifica che la narrativa NON sia infettata da uno di questi bias:
- **Bias pro-underdog**: espressioni come "contro ogni pronostico", "si prende lo
  scalpo del favorito", "stravince nonostante tutti lo diano battuto", "sorpresa
  della giornata", "upset annunciato". Verdetto che sceglie l'underdog ranking
  SENZA una motivazione forte e verificata nei dati.
- **Bias pro-favorito**: espressioni come "la classifica parla chiaro", "non c'e'
  storia", "deve vincere per forza", "sulla carta e' un match a senso unico",
  "formalita'". Verdetto che sceglie il favorito ranking SENZA considerare dati
  che contraddicono (es. H2H sfavorevole, forma recente negativa).
- **Bias nome-forte**: narrativa che pende verso il nome con carriera piu'
  importante ignorando i dati recenti.
- **Bias recency**: narrativa che pesa solo gli ultimi 2-3 match ignorando il
  campione piu' ampio dei recenti.
- **Bias home-crowd**: assunzione che il pubblico aiuti senza verificare pattern
  storico home del giocatore.

**ARTICOLO DA VERIFICARE:**
{article_json}

**DATI AUTORITATIVI (fonte di verita'):**
{data_block}

**OUTPUT RICHIESTO** (un singolo JSON, nessun testo prima o dopo):

```json
{{
  "verdict": "PASS" oppure "FAIL",
  "pilastro_1_completezza_aggiornamento": {{
    "ok": true/false,
    "problemi": ["lista problemi completezza/precisione/aggiornamento, vuota se ok"]
  }},
  "pilastro_2_anti_allucinazione": {{
    "ok": true/false,
    "errori": ["lista errori factuali, vuota se ok. Ogni errore cita la frase incriminata e la verita' autoritativa"]
  }},
  "pilastro_3_anti_bias": {{
    "ok": true/false,
    "bias_rilevati": ["lista bias rilevati con l'espressione incriminata e il tipo di bias"]
  }},
  "errori": ["lista aggregata di errori che hanno portato a FAIL"],
  "note": ["eventuali note su affermazioni ambigue ma non chiaramente false"]
}}
```

Non essere pedante su particolari stilistici. Cerca SOLO:
(a) errori di completezza/precisione/aggiornamento verificabili col blocco dati;
(b) errori factuali di allucinazione verificabili col blocco dati;
(c) espressioni-killer di bias elencate sopra con riscontro nel testo.

Se un fatto non e' citato nel blocco e nemmeno nell'articolo, non e' un errore.
Se un fatto e' nell'articolo ma contraddice il blocco, e' un errore.
Se un fatto e' nell'articolo e il blocco non lo copre (es. descrizione generale
di superficie, nazionalita' nota, mano dominante nota), NON e' un errore.
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


def _today_strings():
    today = _oggi()
    italian_months = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                      'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']
    today_human = f'{today.day} {italian_months[today.month - 1]} {today.year}'
    today_short = today.strftime('%d/%m/%Y')
    return today_human, today_short


def fact_check(article, data_block):
    """Seconda passata claude: verifica anti-allucinazione + anti-bias + aggiornamento."""
    article_slim = {
        'titolo': article.get('titolo'),
        'sottotitolo': article.get('sottotitolo'),
        'descrizione': article.get('descrizione'),
        'corpo_markdown': article.get('corpo_markdown'),
        'verdetto': article.get('verdetto'),
    }
    today_human, today_short = _today_strings()
    prompt = PROMPT_FACT_CHECK.format(
        today_human=today_human,
        today_short=today_short,
        article_json=json.dumps(article_slim, ensure_ascii=False, indent=2),
        data_block=data_block
    )
    return _claude_call(prompt, timeout=600)


def genera(match, max_tentativi=2):
    """Genera articolo + fact-check + retry se fallisce."""
    today_human, today_short = _today_strings()
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
        prompt = PROMPT_PIPELINE.format(
            today_human=today_human,
            today_short=today_short,
            match_block=match_block,
            data_block=data_block,
        )
        article = _claude_call(prompt)

        print(f'  Fact-check (3 pilastri: completezza/anti-allucinazione/anti-bias)...', flush=True)
        check = fact_check(article, data_block)
        verdict = check.get('verdict', 'FAIL')
        errors = check.get('errori', []) or []

        if verdict == 'PASS' and not errors:
            print(f'  Fact-check: PASS su tutti e 3 i pilastri', flush=True)
            article['fact_check'] = check
            article['data_block_used'] = data_block
            return article

        last_err = {
            'pilastro_1': check.get('pilastro_1_completezza_aggiornamento', {}),
            'pilastro_2': check.get('pilastro_2_anti_allucinazione', {}),
            'pilastro_3': check.get('pilastro_3_anti_bias', {}),
            'errori': errors,
        }
        print(f'  Fact-check: FAIL con {len(errors)} problemi:', flush=True)
        for e in errors[:5]:
            print(f'    - {e}', flush=True)

    raise RuntimeError(f'Impossibile generare articolo privo di problemi dopo {max_tentativi} tentativi. Ultimi errori: {last_err}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: python generate_analysis.py selected_YYYY-MM-DD.json', file=sys.stderr)
        sys.exit(1)
    selected = json.loads(Path(sys.argv[1]).read_text())
    outdir = Path(sys.argv[1]).parent / 'analyses'
    outdir.mkdir(exist_ok=True)
    skipped_no_data = []
    for m in selected:
        mid = m.get('event_key')
        p1, p2 = m.get('event_first_player'), m.get('event_second_player')
        out = outdir / f'analysis_{mid}.json'
        if out.exists():
            # Resume idempotente: se un run precedente ha gia' salvato
            # l'analisi, la riusiamo invece di rigenerarla. Serve quando
            # la pipeline viene interrotta a meta' (es. kill, perdita rete)
            # e rilanciata nello stesso giorno.
            print(f'Match {mid}: analisi gia\' presente, skip rigenerazione', flush=True)
            continue
        print(f'Analizzo match {mid}: {p1} vs {p2}', flush=True)
        try:
            analysis = genera(m)
            out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
            print(f'  Salvata in {out}', flush=True)
        except ApiTennisNoData as e:
            # Skip pulito: NON pubblichiamo analisi su un match senza dati
            # autoritativi. Lo segnaliamo nel log e in un file di report
            # cosi' la pipeline (daily.sh / cron) lo vede.
            msg = f'[NO-DATA] match {mid} {p1} vs {p2}: {e}'
            print(f'  {msg}', file=sys.stderr, flush=True)
            skipped_no_data.append({
                'event_key': mid,
                'player1': p1, 'player2': p2,
                'tournament': m.get('tournament_name'),
                'motivo': str(e),
            })
        except Exception as e:
            print(f'  ERRORE: {e}', file=sys.stderr, flush=True)

    # Report finale skipped-no-data: se la lista non e' vuota il daily.sh
    # vede il file e lo logga in modo visibile.
    if skipped_no_data:
        report = outdir.parent / f'skipped_no_data_{Path(sys.argv[1]).stem.split("_")[-1]}.json'
        report.write_text(json.dumps(skipped_no_data, indent=2, ensure_ascii=False))
        print(f'\n*** {len(skipped_no_data)} match SKIPPATI per mancanza dati API Tennis ***', flush=True)
        print(f'Report in {report}', flush=True)
        for s in skipped_no_data:
            print(f'  - {s["player1"]} vs {s["player2"]} @ {s["tournament"]}: {s["motivo"][:80]}', flush=True)
