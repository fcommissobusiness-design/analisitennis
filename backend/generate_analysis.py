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


class WebFactCheckFail(RuntimeError):
    """Sollevata quando la verifica fattuale indipendente sul web trova errori
    che la correzione automatica non riesce a sanare. Il match NON si pubblica:
    meglio un buco che un articolo con fatti falsi online."""
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
        # NB: il campo "round" dei match recenti (Final, Semi-finals...) arriva
        # dal fornitore ed e' inaffidabile (duplica e sbaglia i turni, assegnando
        # p.es. "Final" a piu' match dello stesso torneo). E' la fonte delle
        # finali/titoli inventati, quindi NON lo includiamo: data, esito,
        # avversario, torneo e punteggio bastano a descrivere la forma e sono
        # affidabili. I round restano solo nei precedenti diretti (H2H).
        lines = []
        for r in rows:
            lines.append(f"  {r['date']} {r['result']} vs {r['opponent']} - {r['tournament']} - {r['score']}")
        return '\n'.join(lines)

    stats_p1 = {'W': sum(1 for r in recent1 if r['result'] == 'W'), 'L': sum(1 for r in recent1 if r['result'] == 'L')}
    stats_p2 = {'W': sum(1 for r in recent2 if r['result'] == 'W'), 'L': sum(1 for r in recent2 if r['result'] == 'L')}

    # Attributi verificati di giocatori e torneo, dall'archivio redazionale.
    # Senza questo blocco il modello si inventava mano, rovescio, nazionalita'
    # e superficie, ed erano proprio i dati che il gate di fact-check non
    # controllava: e' cosi' che e' uscito il caso Falkowska.
    try:
        from fact_store import blocco_giocatore, blocco_torneo
        anno = None
        try:
            anno = int(str(match.get('event_date'))[:4])
        except (TypeError, ValueError):
            pass
        schede = (
            f"{blocco_giocatore(p1)}\n{blocco_giocatore(p2)}\n"
            f"{blocco_torneo(match.get('tournament_name', ''), anno)}"
        )
    except Exception as e:
        schede = (f'  (archivio attributi non disponibile: {e})\n'
                  f'  NON scrivere mano, rovescio, nazionalita, eta, altezza o superficie.')

    return f"""
================================================================
DATI AUTORITATIVI API TENNIS - FONTE UNICA DELLA VERITA'
Non inventare dati non presenti qui sotto. Non desumere score o
risultati da nomi di tornei. Usa ESCLUSIVAMENTE questi record.

ATTRIBUTI VERIFICATI (archivio redazionale, controllato su fonti
ufficiali di circuito). Mano, rovescio, nazionalita', eta', altezza e
superficie si scrivono SOLO se compaiono qui sotto. Se un attributo e'
elencato come NON VERIFICATO, non va scritto in nessuna forma, nemmeno
allusiva ("le traiettorie del mancino", "il piu' giovane dei due"):
{schede}

REGOLA FASI E QUALIFICAZIONI (OBBLIGATORIA): rispetta ALLA LETTERA il
campo round di ogni match. Un round di qualificazione (etichette tipo
"Qualifying", "Qual.", "Q1"/"Q2"/"Q3", "Qualifying Final", "qualificazioni")
NON e' la finale ne' il titolo del torneo: descrivilo come "qualificazione"
o "ultimo turno di qualificazione", MAI come "finale", "ultimo atto",
"atto conclusivo", "titolo" o "vincitore/vincitrice del torneo". Non
scrivere mai che un giocatore ha "raggiunto la finale" o "vinto il titolo"
di un torneo se il round non e' ESATTAMENTE la finale del tabellone
principale. CONTROLLO DI PLAUSIBILITA': se i dati sembrano attribuire a un
giocatore di bassa classifica una finale o un titolo in un grande torneo
(Slam, Masters 1000, WTA 1000/500), e' quasi certamente una qualificazione
o un evento di categoria inferiore: usa formule prudenti ("ha fatto strada",
"un buon risultato") senza attribuire finali o titoli non reali.
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

**USO DEL DOSSIER ANALITICO**: se nel blocco qui sopra e' presente la sezione DOSSIER
ANALITICO REDAZIONALE, usalo per la PROFONDITA' DI LETTURA, non come fonte di numeri:
contesto e fase del torneo, motivazioni e obiettivi dei due, direzione della fatica, matchup
stilistico e lateralita', peso del primo set, significato dei precedenti, meteo e sessione.
Contesto e motivazioni devono pesare molto sul giudizio (circa un terzo), MAI rompendo
l'imparzialita' del corpo e MAI sconfinando in mercati, quote o scommesse.
REGOLE DURE che il dossier NON allenta MAI:
- FATTI NUMERICI e puntuali (quanti match, bilanci vittorie-sconfitte, punteggi, numeri di
  ranking, titoli, finali) si citano SOLO se presenti testualmente nel blocco. NON dedurre
  conteggi nuovi dal racconto del dossier: se il dossier descrive piu' tornei, NON sommarli
  in una cifra tua. Nel dubbio descrivi a parole, senza numero.
- ATTRIBUTI del giocatore (nazionalita', mano, rovescio, eta', altezza) si scrivono SOLO per
  i giocatori con ATTRIBUTI VERIFICATI nel blocco. Se un giocatore e' marcato "nessun
  attributo verificato", NON scriverne la nazionalita' ne' altro, neppure se il contesto la
  rende ovvia (per esempio non chiamarlo "lo spagnolo"). Il divieto vince sempre sulla
  ricchezza del dossier.
- Un punto segnato "non verificabile" nel dossier non diventa un fatto.
Non incollare il dossier: usalo come ragionamento.

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
- NOMI PROPRI: se nel blocco un giocatore compare con la sola iniziale puntata (es.
  "D. Shnaider", "A. Falei", "J. Kym"), NON inventare il nome di battesimo. Scrivi il
  cognome da solo oppure riporta l'iniziale com'e'. Indovinare il nome ("Daria" per
  "D. Shnaider" che e' Diana, "Jakub" per "J. Kym" che e' Jerome) e' un errore pubblicato.
- ETICHETTE DI TURNO DEI MATCH RECENTI INAFFIDABILI: nell'elenco "ULTIMI 15 MATCH" il
  campo del turno (Final, Semi-finals, 1/8-finals...) proviene da un fornitore che spesso
  SBAGLIA, duplica e assegna "Final" a piu' match dello stesso torneo (a volte con una "W"
  accanto a un punteggio di sconfitta). Percio' NON dedurre da quelle etichette che un
  giocatore "ha raggiunto la finale/semifinale", "ha vinto un titolo" o "si e' spinto fino
  agli ultimi atti". Descrivi la forma recente per vittorie e sconfitte contro avversari
  nominati (quelli si', affidabili), non per i turni raggiunti. Un titolo o una finale si
  afferma solo se e' un fatto notorio e consolidato, mai sulla base del solo campo turno.

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

**REGOLA SULLA RECENCY DELLA FORMA (non negoziabile)**:
"Forma recente" significa le ultime settimane rispetto a OGGI {today_short}, non
il risultato piu' altisonante del blocco. Leggi i match in ordine di data: quelli
piu' vicini a oggi pesano di piu' nel descrivere la condizione attuale. Un
risultato di spicco ma lontano nel tempo (ad esempio una finale o un titolo di
uno o due mesi fa) e' CONTESTO di stagione, non forma del momento. Puoi citarlo
UNA volta come sfondo, ma:
- non presentarlo come forma recente ne' con formule tipo "arriva da" o "reduce
  da" se nel frattempo il giocatore ha disputato altri tornei piu' recenti;
- se i match piu' recenti raccontano un andamento diverso (sconfitte,
  discontinuita'), la fotografia della forma e' quella, e va detta chiaramente;
- non farne il fattore portante del verdetto quando i dati piu' recenti lo
  contraddicono o lo ridimensionano.
Errore tipico da evitare: dare per "in grande forma" o "reduce dalla finale" chi
due mesi fa ha raggiunto una finale importante ma da allora ha perso diversi
match piu' recenti. In quel caso la finale e' sfondo, e la forma vera e' quella
delle ultime settimane.

**OUTPUT RICHIESTO** (un singolo JSON, nessun testo prima o dopo):

```json
{{
  "titolo": "Titolo giornalistico avvincente, 50-70 caratteri, SEO-friendly (contiene almeno un nome giocatore). NON deve anticipare il verdetto, deve suscitare curiosita' sul match. ANTI-FORMULA: ogni articolo della giornata viene scritto in una chiamata separata, quindi rischi di ricadere sulle stesse stampelle che useranno tutti gli altri e la home sembra scritta da un robot. EVITA come impostazione di default 'esordio', 'primo turno', 'debutto', 'al via', 'sfida'/'sfidare', 'da decifrare', 'tutto da ...', 'senza precedenti', 'inedito', 'da seguire', 'chi comanda'. Il turno e' un dato e lo puoi nominare, ma NON puo' essere l'angolo del titolo: l'angolo dev'essere cio' che rende diverso QUESTO match (stile di gioco, superficie, momento di forma, posta in palio, contrasto tra i due, contesto del torneo). Se il titolo che stai per scrivere funzionerebbe identico per un'altra partita qualsiasi dello stesso turno, riscrivilo.",
  "sottotitolo": "Sottotitolo che suscita curiosita', 80-130 caratteri. Imparziale, non anticipa il pronostico.",
  "descrizione": "Meta description SEO 150-160 caratteri. Imparziale.",
  "corpo_markdown": "ARTICOLO COMPLETO in prosa giornalistica italiana, 700-1100 parole, paragrafi max 4 righe, parole-chiave principali in **grassetto** senza esagerare (3-6 occorrenze totali). Nessun elenco puntato nel corpo. Nessun riferimento a sistema/FASE/bankroll/quote/bookmaker/stake/EV/pick. Niente abbreviazioni oscure (sempre 'palle break' non 'BP', 'scontri diretti' non 'H2H'). Tecnicismi solo del tennis. Prosa fluida variabile, niente 'in sintesi', 'in conclusione', 'ecco perche'', 'fondamentalmente'. IMPARZIALITA' OBBLIGATORIA: tratta i due giocatori allo stesso modo nel corpo, dati di uno + dati dell'altro, precedenti di uno + contesto dell'altro. Il corpo NON deve far trasparire verso chi pendiamo. Nessun aggettivo sbilanciato, nessuna tesi anticipata nel corpo. Il verdetto arriva solo nel campo 'verdetto'. MINI-TITOLI DI SEZIONE OBBLIGATORI: inserisci mini-titoli markdown H3 (### Titoletto) PRIMA dei paragrafi che aprono un nuovo argomento tematico. Esempi di titoletti: '### Precedenti', '### Forma fisica', '### Stile di gioco', '### Fattore campo', '### Il momento in classifica', '### Il mese di ottobre' (varia in base al match). Target: 3-5 mini-titoli in totale. Il PRIMO paragrafo introduttivo NON porta mini-titolo. L'ULTIMO paragrafo di chiusura prima del verdetto NON porta mini-titolo. Non mettere mini-titoli in ogni paragrafo, solo ai cambi di contesto netti.",
  "verdetto": "Pronostico sportivo editoriale DECISO 2-3 frasi, 180-280 caratteri. PRIMA di scegliere il formato, classifica il GAP tra i due giocatori leggendo il blocco DATI AUTORITATIVI secondo questa griglia (OBBLIGATORIA):\\n\\nGAP NETTO -> usa formato (b) 'Oggi nettamente X: motivazione'. Serve ALMENO una di queste condizioni documentate: differenza ranking >= 50 posizioni; H2H completo >= 3-0; forma recente molto piu' solida di un intero mese (es. titolo o finale recente dell'uno contro due o piu' sconfitte secche dell'altro); mismatch stilistico forte sulla superficie (es. big server indoor contro ribattitore in difficolta' sul veloce).\\n\\nGAP SOTTILE -> usa formato (a) 'Oggi la puo' spuntare X: motivazione'. Serve che DUE fattori concordanti modesti pendano dalla stessa parte (es. un precedente favorevole + forma leggermente migliore). Un solo fattore marginale NON basta per usare (a).\\n\\nGAP APERTO -> usa formato (c) 'Partita equilibrata, scenario piu' plausibile un 2-1 con Y che prende almeno un set' oppure 'match da terzo set senza un favorito chiaro'. Usa (c) quando: nessun fattore e' nettamente a favore di uno; segnali contrastanti (es. H2H all'uno, forma all'altro); dati scarsi o H2H a zero senza altri appigli; esordienti al matchup senza storia.\\n\\nREGOLA ANTI-BIAS DI LINGUAGGIO: NON usare (a) 'puo' spuntare' come default comodo. Se stai scegliendo (a) solo perche' 'tanto il match e' tirato', la scelta corretta e' quasi sempre (c). Il formato (a) e' per quando il favorito e' identificabile ma di misura, con due fattori concordanti; se ne hai uno solo scivola a (c). Target di distribuzione naturale su 10 pronostici: circa 2-3 (b), 4-5 (a), 2-3 (c). Se nella giornata stai scrivendo tutti (a) stai sbagliando.\\n\\nMAI altri mercati: niente ace, over/under games, handicap, tiebreak si/no. Solo chi vince il match o scenario >=1 set / 2-1. Mai quote, mai consigli di scommessa. VERDETTO DECISO, MAI PIEDE IN DUE SCARPE: scegli la strada e motivala, la controlettura sta gia' nel corpo imparziale.",
  "tag": ["5-8 tag di parole-chiave SEO: giocatori, torneo, categoria, superficie, tipo-match"],
  "probabilita": {{
    "favorito": "cognome del giocatore con piu' probabilita' di vincere (scegline SEMPRE uno dei due, anche in equilibrio)",
    "percent_favorito": "numero INTERO tra 50 e 82 = probabilita' di vittoria del favorito, CALCOLATA sui DATI AUTORITATIVI di questo specifico match (differenza di ranking, bilancio e storia degli scontri diretti, forma delle ultime settimane, resa sulla superficie, fattore campo). DEVE essere un numero PRECISO e specifico, MAI un valore tondo di comodo: usa valori come 57, 63, 71, 66, 54, non solo 50/60/70/80. Due match diversi NON devono avere la stessa percentuale se i dati differiscono. Calibrazione coerente con classificazione_gap: gap NETTO -> 68-81; gap SOTTILE -> 55-65; gap APERTO/equilibrio -> 50-54. Nel tennis l'incertezza resta alta: non superare 82 ne' scendere sotto 50 per il favorito."
  }},
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
- **Bias risultato-vetrina**: un risultato di spicco ma datato (es. una finale o
  un titolo di piu' di un mese fa rispetto a oggi {today_short}) presentato come
  forma attuale ("reduce da", "arriva dalla finale di...", "in grande forma") o
  usato come fattore portante del verdetto, quando nel blocco esistono match piu'
  recenti che danno una fotografia diversa della condizione. La forma del momento
  si misura dai match piu' vicini a oggi; un acuto lontano nel tempo e' solo
  sfondo di stagione. FAIL se la forma recente o il verdetto si reggono su un
  risultato datato scavalcando i match piu' recenti.
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

ATTRIBUTI DEI GIOCATORI E DEL TORNEO: questa e' la regola che in passato ha
lasciato passare un errore grave segnalato poi da un lettore (una giocatrice
destra descritta come mancina in tutto il profilo). Il blocco DATI AUTORITATIVI
contiene ora una sezione ATTRIBUTI VERIFICATI. Quindi:
- mano dominante, rovescio, nazionalita', eta' o data di nascita, altezza,
  categoria del giocatore, superficie e sede del torneo NON sono piu' fatti
  "di contesto": sono fatti verificabili contro il blocco, esattamente come
  gli score.
- Se l'articolo afferma uno di questi attributi e il blocco dice il contrario,
  e' un ERRORE e il verdetto e' FAIL.
- Se l'articolo afferma uno di questi attributi e il blocco lo elenca come NON
  VERIFICATO, oppure non lo contiene affatto, e' un ERRORE: non si pubblica un
  attributo che la redazione non ha verificato.
- Vale anche per le allusioni indirette: "le traiettorie del mancino", "gli
  angoli che apre il braccio sinistro", "il piu' giovane dei due", "il
  rimbalzo alto della terra" quando la superficie e' un'altra. Contano come
  affermazioni dell'attributo a tutti gli effetti.

Restano fatti di contesto ammessi senza riscontro nel blocco solo le
osservazioni generiche che non attribuiscono nulla a nessuno in particolare
(es. "sul veloce gli scambi tendono ad accorciarsi").
"""


def _claude_call(prompt, timeout=1800, web=False):
    """Chiama la CLI headless di Claude e ritorna il primo oggetto JSON.

    web=True abilita WebSearch + WebFetch per lo stadio di verifica fattuale
    indipendente: la generazione e il gate interno NON usano il web (restano
    ancorati ai dati), ma il fact-check finale va a controllare i fatti sulle
    fonti reali, dove i dati API possono essere sbagliati.
    """
    claude_bin = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~/.local/node/bin')}:{env.get('PATH','')}"
    cmd = [claude_bin, '-p', prompt, '--output-format', 'json']
    if web:
        cmd += ['--allowedTools', 'WebSearch', 'WebFetch']
    result = subprocess.run(
        cmd,
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


# ---- Stadio DOSSIER ANALITICO (tutte le voci non-monetarie del metodo) --
# La generazione base scrive solo sulla spina fattuale API Tennis (ranking,
# H2H, forma, superficie). Questo stadio esegue, come ricerca web + ragionamento,
# tutte le voci analitiche NON di scommessa del metodo: contesto esteso,
# motivazioni, fatica, matchup stilistico, pattern, peso del primo set, durata
# sportiva, precedenti contestualizzati, meteo/sessione, Elo vs ranking, match
# gemello, fattore campo/pubblico, coach. Niente quote/EV/stake/mercati, niente
# spoiler del risultato di oggi, niente dato inventato. Il dossier viene appeso
# al blocco autoritativo cosi' alimenta sia la scrittura sia i gate esistenti.
# Disattivabile con ANALISITENNIS_DOSSIER=0 (run veloce senza profondita' web).

PROMPT_DOSSIER = """Sei un analista editoriale della testata AnalisiTennis. OGGI e' {today_short}
({today_human}). Prepara il DOSSIER ANALITICO interno del match di OGGI tra {p1} e {p2}
({torneo}): la lettura profonda che la redazione usa per scrivere l'anteprima.

Hai accesso al web (WebSearch/WebFetch): USALO per aggiornare e verificare. Parti dalla
spina fattuale qui sotto e arricchiscila.

MATCH:
{match_block}

SPINA FATTUALE (DATI AUTORITATIVI API TENNIS, gia' verificati):
{data_block}

== REGOLE NON NEGOZIABILI ==
1. ANTI-SPOILER ASSOLUTO: il match e' di OGGI. NON cercare, NON dedurre, NON riportare MAI
   il risultato, il punteggio o il vincitore di oggi. Se un risultato di ricerca lo mostra,
   ignoralo. Verifichi e citi SOLO fatti datati PRIMA di oggi.
2. NIENTE SCOMMESSE: testata editoriale, non tipster. VIETATI quote, valore atteso, stake,
   bankroll, Kelly, overlay e QUALSIASI mercato (ace, over/under games, handicap, tiebreak
   si/no, numero game). Leggi il match sul piano SPORTIVO: chi e' favorito e perche',
   equilibrio, peso del primo set, scenario 2-0 / 2-1. Nessun linguaggio da scommesse.
3. ANTI-ALLUCINAZIONE: meglio un buco che una bugia. Se un dato non e' verificato (web o
   spina fattuale), scrivi "non verificabile" e NON inventarlo. NON inventare MAI numeri:
   niente percentuali di servizio/risposta/ace/palle break/hold se non da fonte certa; in
   quel caso descrivi QUALITATIVAMENTE (es. "buon battitore", "ribattitore solido").
4. OGNI DATO VA CONTESTUALIZZATO: mai un dato asettico. Per ogni risultato o statistica di'
   SEMPRE contro chi, in che torneo, su che superficie, in che sessione/meteo e con quali
   motivazioni/momento di carriera. Un dato senza contesto e' falsato.
5. OMONIMI E IDENTITA': verifica che siano i giocatori giusti (nazionalita', mano, eta).
   Se un nome compare solo con l'iniziale, non inventare il nome di battesimo.
6. Niente trattini lunghi (usa virgole o due punti). Accenti corretti (citta, piu, perche).

== VOCI DA SVOLGERE TUTTE (nessuna saltata) ==
A. CONTESTO TORNEO: categoria e peso; FASE REALE del match aggiornata a OGGI (verificala sul
   web, il round nei dati puo' essere vecchio); orario italiano effettivo e sessione
   (diurna/serale/notturna); superficie e campo (indoor/outdoor); significato del torneo nel
   circuito ora; tabellone: eliminazioni o ritiri eccellenti gia' avvenuti, avversario del
   turno dopo.
B. MOTIVAZIONI PER GIOCATORE (una sezione per ciascuno, tra le piu' importanti): da dove
   arriva; come sta adesso (ranking attuale vs picco, forma); obiettivo stagionale (Finals,
   difesa punti, rientro, soglia ranking); significato di QUESTO torneo per lui; impegni
   futuri immediati nei 7-14 giorni (anche altri tornei gia' a palinsesto) e come
   condizionano l'approccio (preservarsi o spingere); dichiarazioni/interviste pre-match.
C. CHECK FORM-ADJUSTED (solo se uno e' sfavorito di ranking, gap >= 50 posizioni): nelle
   ultime 2-3 settimane ha battuto un top-30? finale/semifinale di rilievo? serie aperta di
   vittorie? ranking live in salita? Di' se e' PEER-LIVELLO del favorito.
D. FORMA E ULTIMI 5 MATCH ESATTI di ciascuno, aggiornati a oggi e contestualizzati (contro
   chi, dove, superficie, esito, come: secco o al terzo). Se i dati sono scarsi, estendi per
   calibro e recenza. Un risultato di spicco ma vecchio e' contesto, non forma.
E. FATICA: carico delle ultime 2-3 settimane dei due, match ravvicinati, riposo; asimmetria
   (chi arriva piu' scarico).
F. MATCHUP STILISTICO E LATERALITA': mano e stile dei due; come rende CIASCUNO contro questo
   tipo specifico di avversario (servizio, risposta, stile), tarato anche sulla fatica
   attuale; chi favorisce il matchup.
G. PATTERN: resa per fase di torneo (primi turni vs fasi avanzate) e contro avversari di alto
   livello (top-10/20/50), dove verificabile; altrimenti ometti.
H. PRIMO SET: in questo matchup il primo set e' determinante? chi ha piu' probabilita' di
   prenderlo e perche'? storicamente come hanno reagito dopo averlo preso o perso, con quali
   presupposti; quei presupposti ci sono oggi?
I. DURATA / DINAMICA (sportiva, NON scommesse): il match tende a lungo o corto, propensione
   al terzo set? Spiega perche' (stili, tenuta), senza linee ne' numeri di game.
J. SCONTRI DIRETTI contestualizzati: ogni precedente con quando, dove, superficie, sessione,
   e il momento di carriera di entrambi allora rispetto a oggi.
K. METEO E SESSIONE: se all'aperto, meteo atteso all'ora del match di oggi (temperatura,
   vento, umidita') e impatto sulla velocita' della palla; se indoor, dillo.
L. VERO LIVELLO vs RANKING: scarto tra ranking e livello reale (Elo/forma), ranking stantio.
M. INTEGRAZIONI: match gemello di ciascuno (un match passato molto simile per tipo di
   avversario, superficie, posta e contesto) e cosa insegna; fattore campo e pubblico (neutro
   o di parte, come reagiscono i due); allenatore attuale se rilevante; come reagisce ciascuno
   a QUESTA combinazione di fatica e matchup.
N. SINTESI: 4-6 righe che chiudono il quadro (equilibrio o favorito e perche'), coerenti con
   tutto sopra, senza scommesse e senza anticipare alcun risultato.

Restituisci SOLO questo JSON, nulla prima e nulla dopo:
```json
{{
  "dossier_markdown": "il dossier completo in markdown, titoletti ## per ogni voce A..N, prosa, dati sempre contestualizzati, niente scommesse, niente spoiler",
  "note_non_verificabili": ["punti che NON hai potuto verificare e hai lasciato aperti"],
  "spoiler_evitato": true
}}
```
"""


def build_dossier(match, data_block):
    """Esegue le voci analitiche NON-monetarie come ricerca web + ragionamento,
    ancorate alla spina fattuale. Ritorna la stringa markdown del dossier (o ''
    se qualcosa va storto: la pipeline procede comunque coi soli dati API)."""
    today_human, today_short = _today_strings()
    match_block = f"""- Data e ora match: {match.get('event_date')} {match.get('event_time')} (orario italiano)
- Giocatore 1: {match.get('event_first_player')}
- Giocatore 2: {match.get('event_second_player')}
- Torneo: {match.get('tournament_name')}
- Fase/Round nei dati (DA VERIFICARE aggiornato a oggi): {match.get('tournament_round')}
- Tipo: {match.get('event_type_type')}
- Stagione: {match.get('tournament_season')}"""
    prompt = PROMPT_DOSSIER.format(
        today_human=today_human,
        today_short=today_short,
        p1=match.get('event_first_player', ''),
        p2=match.get('event_second_player', ''),
        torneo=match.get('tournament_name', ''),
        match_block=match_block,
        data_block=data_block,
    )
    # ricerca web agentica (piu' round): timeout generoso.
    res = _claude_call(prompt, timeout=1500, web=True)
    dossier = (res.get('dossier_markdown') or '').strip()
    # Il blocco passa per str.format() a valle: una graffa nel testo lo
    # farebbe esplodere. In prosa tennistica le graffe non servono mai.
    return dossier.replace('{', '(').replace('}', ')')


# ---- Stadio di verifica fattuale INDIPENDENTE sul web -------------------
# Il gate a 3 pilastri controlla la coerenza con i DATI AUTORITATIVI, ma quei
# dati a volte sono gia' sbagliati (etichette di turno errate, omonimi), e in
# quel caso l'articolo coerente coi dati resta sbagliato nei fatti. Il 05/11/2026
# una verifica indipendente sul web ha trovato 6 articoli su 15 con finali e
# titoli inventati nati proprio da dati API corrotti. Questo stadio replica
# quella verifica dentro la pipeline: va a controllare i fatti sulle fonti reali.

PROMPT_WEB_FACTCHECK = """Sei un fact-checker INDIPENDENTE della testata AnalisiTennis.
OGGI E' {today_short}. L'articolo qui sotto e' l'anteprima di un match che si gioca
OGGI tra {p1} e {p2} ({torneo}).

REGOLA ASSOLUTA ANTI-SPOILER: NON cercare, NON aprire, NON dedurre e NON riportare
MAI il risultato, il punteggio o il vincitore del match in anteprima di oggi. Se un
risultato di ricerca lo mostra, ignoralo. Verifichi SOLO fatti datati PRIMA di oggi.

Il tuo compito: controllare sul web, su FONTI AUTOREVOLI (atptour.com, wtatennis.com,
itftennis.com, Wikipedia EN, database tennistici affidabili), ogni affermazione
fattuale verificabile dell'articolo, e segnalare quelle SBAGLIATE. Controlla in
particolare, perche' sono le piu' soggette a errore:
- nazionalita', mano (destro/mancino), rovescio dei due giocatori;
- NOMI PROPRI: se l'articolo da' il nome di battesimo di un giocatore, verifica che
  sia quello giusto (errore tipico: nome inventato da un'iniziale, es. "Daria"
  Shnaider mentre e' Diana, "Jakub" Kym mentre e' Jerome);
- scontri diretti: numero di precedenti, chi ha vinto, anno, sede, superficie;
- risultati recenti: ATTENZIONE alle FINALI e ai TITOLI attribuiti a un giocatore.
  Verifica che li abbia davvero raggiunti/vinti; un errore tipico e' descrivere come
  "finale" o "titolo" un torneo in cui il giocatore e' in realta' uscito presto;
- dati del torneo: superficie, indoor/outdoor, citta', sede, categoria.
- riferimenti temporali incoerenti con oggi (es. "lo scorso mese"/"reduce da" che
  puntano a un evento molto piu' vecchio).

NON e' un errore cio' che non riesci a verificare: in quel caso lascialo stare. Segnala
solo cio' che le fonti CONTRADDICONO in modo chiaro.

ARTICOLO DA VERIFICARE:
{article_json}

Restituisci SOLO questo JSON, nulla prima e nulla dopo:
```json
{{
  "verdict": "PASS se non hai trovato errori fattuali, FAIL se ne hai trovato almeno uno",
  "errori": ["descrizione sintetica di ogni errore trovato"],
  "correzioni": [
    {{"sbagliato": "cosa dice l'articolo", "corretto": "il fatto giusto verificato", "fonte": "URL"}}
  ]
}}
```
Se e' tutto corretto: verdict "PASS", liste vuote.
"""


PROMPT_WEB_CORREGGI = """Sei il redattore di AnalisiTennis. Un fact-checker indipendente ha
verificato sul web l'articolo qui sotto e ha trovato alcuni errori fattuali. Devi
RISCRIVERE l'articolo correggendo ESATTAMENTE quegli errori e NULLA ALTRO.

Le CORREZIONI qui sotto sono verita' verificata sulle fonti e hanno la PRECEDENZA su
qualunque dato: dove un dato del blocco autoritativo contraddice una correzione, vale la
correzione. Applica ogni correzione nel titolo, sottotitolo, descrizione, corpo, verdetto
e tag ovunque l'errore compaia, e se un errore era portante per il verdetto (es. un
precedente o un titolo rivelatosi falso) RICALIBRA il verdetto di conseguenza.

CORREZIONI VERIFICATE (fonte unica di verita' per questi punti):
{correzioni}

REGOLE: nessun trattino lungo (usa virgole o due punti), lettere accentate corrette (e'
sbagliato scrivere "citta'", si scrive "citta"), tono editoriale non da scommesse, e NON
introdurre fatti nuovi non presenti nell'articolo originale o nelle correzioni. NON
nominare il risultato del match di oggi.

ARTICOLO DA CORREGGERE:
{article_json}

Restituisci SOLO il JSON completo dell'articolo corretto, con gli stessi campi
dell'originale (titolo, sottotitolo, descrizione, corpo_markdown, verdetto, tag,
probabilita_favorito, probabilita_percent, ...), nulla prima e nulla dopo.
"""


def web_fact_check(article, match):
    """Verifica fattuale indipendente sul web. Ritorna {verdict, errori, correzioni}.

    Non riceve il blocco dati API: deve controllare contro il mondo reale, non
    contro la stessa fonte che puo' essere sbagliata.
    """
    _, today_short = _today_strings()
    article_slim = {
        'titolo': article.get('titolo'),
        'sottotitolo': article.get('sottotitolo'),
        'descrizione': article.get('descrizione'),
        'corpo_markdown': article.get('corpo_markdown'),
        'verdetto': article.get('verdetto'),
    }
    prompt = PROMPT_WEB_FACTCHECK.format(
        today_short=today_short,
        p1=match.get('event_first_player', ''),
        p2=match.get('event_second_player', ''),
        torneo=match.get('tournament_name', ''),
        article_json=json.dumps(article_slim, ensure_ascii=False, indent=2),
    )
    # timeout generoso: e' una ricerca web agentica (piu' round).
    return _claude_call(prompt, timeout=1200, web=True)


def _correggi_con_web(article, correzioni):
    """Riscrive l'articolo applicando le correzioni verificate sul web."""
    prompt = PROMPT_WEB_CORREGGI.format(
        correzioni=json.dumps(correzioni, ensure_ascii=False, indent=2),
        article_json=json.dumps(article, ensure_ascii=False, indent=2),
    )
    return _claude_call(prompt, timeout=600)


def _stadio_web(article, match, max_correzioni=2):
    """Stadio 4: verifica web indipendente, con fino a max_correzioni giri.

    - PASS: l'articolo e' confermato dalle fonti, si pubblica.
    - errori con correzioni: si riscrive con la verita' del web e si ri-verifica;
      si ripete fino a max_correzioni volte finche' non torna PASS.
    - errori senza correzioni applicabili, o ancora errori dopo l'ultimo giro:
      si solleva WebFactCheckFail e il match NON si pubblica.
    - errore infrastrutturale (timeout, rete): NON si blocca l'intero palinsesto,
      si pubblica con riserva e lo si annota, cosi' un guasto non svuota la giornata.
    """
    tutte_correzioni = []
    for giro in range(max_correzioni + 1):
        try:
            esito = web_fact_check(article, match)
        except Exception as e:
            print(f'  [web] verifica non eseguita ({e}): pubblico con riserva', flush=True)
            article['web_fact_check'] = {'verdict': 'SKIP_INFRA', 'motivo': str(e)[:300]}
            if tutte_correzioni:
                article['web_corrections_applied'] = tutte_correzioni
            return article

        errori = esito.get('errori') or []
        if esito.get('verdict') == 'PASS' and not errori:
            etichetta = 'PASS' if giro == 0 else f'PASS dopo {giro} correzione/i'
            print(f'  [web] verifica indipendente sul web: {etichetta}', flush=True)
            article['web_fact_check'] = esito
            if tutte_correzioni:
                article['web_corrections_applied'] = tutte_correzioni
            return article

        correzioni = esito.get('correzioni') or []
        print(f'  [web] verifica indipendente (giro {giro + 1}): {len(errori)} errori factuali', flush=True)
        for e in errori[:5]:
            print(f'    - {e}', flush=True)

        if giro == max_correzioni:
            raise WebFactCheckFail(f'ancora errori dopo {max_correzioni} correzioni: {errori[:3]}')
        if not correzioni:
            raise WebFactCheckFail(f'errori senza correzioni applicabili: {errori[:3]}')

        print('  [web] riscrivo con le correzioni verificate e ri-verifico...', flush=True)
        tutte_correzioni.extend(correzioni)
        corrected = _correggi_con_web(article, correzioni)
        corrected['fact_check'] = article.get('fact_check')
        corrected['data_block_used'] = article.get('data_block_used')
        article = corrected

    # Non raggiungibile (il loop ritorna o solleva), ma per sicurezza:
    raise WebFactCheckFail('verifica web non conclusa')


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

    # Stadio DOSSIER ANALITICO: tutte le voci non-monetarie del metodo come
    # ricerca web + ragionamento. Appeso al blocco autoritativo cosi' alimenta
    # scrittura e gate. Degrada: se fallisce, si pubblica coi soli dati API.
    if os.environ.get('ANALISITENNIS_DOSSIER', '1') != '0':
        print('  Dossier analitico (web: contesto, motivazioni, fatica, matchup, meteo, pattern)...', flush=True)
        try:
            dossier = build_dossier(match, data_block)
            if dossier:
                data_block = data_block + (
                    "\n\n================================================================\n"
                    "DOSSIER ANALITICO REDAZIONALE (ricerca web verificata, anti-allucinazione)\n"
                    "Profondita' editoriale aggiuntiva da USARE per contesto e motivazioni.\n"
                    "Vale come fonte autoritativa al pari dei dati API qui sopra. Niente\n"
                    "scommesse, niente spoiler. I punti 'non verificabile' NON sono fatti.\n"
                    "================================================================\n"
                    + dossier
                )
                print('  Dossier analitico: acquisito e integrato', flush=True)
            else:
                print('  Dossier analitico: vuoto, procedo coi soli dati API', flush=True)
        except Exception as e:
            print(f'  Dossier analitico non eseguito ({str(e)[:160]}): procedo coi soli dati API', flush=True)

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
            # Stadio 4: verifica fattuale INDIPENDENTE sul web. Il gate a 3
            # pilastri conferma la coerenza coi dati API, ma se i dati sono
            # sbagliati l'articolo coerente resta falso: qui si controlla contro
            # il mondo reale. Disattivabile con ANALISITENNIS_FACTCHECK_WEB=0.
            if os.environ.get('ANALISITENNIS_FACTCHECK_WEB', '1') != '0':
                print(f'  Verifica indipendente sul web (anti dati-API-sbagliati)...', flush=True)
                article = _stadio_web(article, match)
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
    skipped_factcheck = []
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
        except WebFactCheckFail as e:
            # Skip pulito: l'articolo non ha superato la verifica indipendente
            # sul web e la correzione non e' bastata. NON si pubblica.
            msg = f'[WEB-FACTCHECK] match {mid} {p1} vs {p2}: {e}'
            print(f'  {msg}', file=sys.stderr, flush=True)
            skipped_factcheck.append({
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

    # Report finale skipped-factcheck: match non pubblicati perche' non hanno
    # superato la verifica indipendente sul web nemmeno dopo la correzione.
    if skipped_factcheck:
        report = outdir.parent / f'skipped_factcheck_{Path(sys.argv[1]).stem.split("_")[-1]}.json'
        report.write_text(json.dumps(skipped_factcheck, indent=2, ensure_ascii=False))
        print(f'\n*** {len(skipped_factcheck)} match NON pubblicati per fact-check web fallito ***', flush=True)
        print(f'Report in {report}', flush=True)
        for s in skipped_factcheck:
            print(f'  - {s["player1"]} vs {s["player2"]} @ {s["tournament"]}: {s["motivo"][:80]}', flush=True)
