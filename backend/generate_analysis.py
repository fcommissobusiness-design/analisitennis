"""Per un match applica il framework canonico KAKEGURUI FASE 1-2-3-4 + sanity anti-bias.

Invoca `claude` CLI (headless) con un prompt che riferisce la memoria canonica
`project_prompt_fasi_canonico.md`, cosi' la pipeline eredita lo script completo
senza duplicarlo qui. Il claude invocato ricarica il framework dalla memoria
dell'utente al primo giro e lo applica a questo specifico match.

Output: file JSON `analysis_<match_id>.json` con:
- raw_phase1, raw_phase2, raw_phase3, raw_phase4
- integrations
- sanity_check (bias flaggati)
- editorial_draft (prosa giornalistica che rispetta le regole output)
"""
import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime


PROMPT_PIPELINE = """
Sei il motore editoriale di AnalisiTennis.it, una testata di analisi tennis in italiano.

Devi analizzare questo match applicando INTEGRALMENTE il framework KAKEGURUI FASE 1-2-3-4
+ integrazioni + sanity-check-anti-bias, cosi' come salvato nella memoria utente
`project_prompt_fasi_canonico.md`. Riapplica OGNI VOCE, usa i prompt-recupero per
verificare che nulla sia saltato, applica il sanity anti-bias finale PRIMA di scrivere l'output.

**MATCH:**
{match_block}

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
    "verdetto_solo_match_winner_o_un_set": true
  }}
}}
```

**REGOLE OUTPUT NON NEGOZIABILI**:
1. Niente riferimenti al sistema, FASE, bankroll, quote, bookmaker, DomusBet, EV, stake, Kelly, overlay
2. Niente abbreviazioni che possano confondere
3. Tecnicismi solo del tennis
4. Prosa fluida NON AI-smell
5. IMPARZIALITA' nel corpo: dati di entrambi, nessuna tesi anticipata, nessun aggettivo sbilanciato
6. Verdetto SOLO su match-winner o >=1 set / 2-1 (mai ace/games/handicap/altro)
7. Culmina con verdetto sportivo editoriale, mai una quota
8. 700-1100 parole, paragrafi max 4 righe
9. Firma implicita: Redazione AnalisiTennis
"""


def genera(match):
    """Invoca claude CLI headless con prompt pipeline."""
    match_block = f"""
- Data match: {match.get('event_date')} {match.get('event_time')}
- Giocatore 1: {match.get('event_first_player')} (key API: {match.get('first_player_key')})
- Giocatore 2: {match.get('event_second_player')} (key API: {match.get('second_player_key')})
- Torneo: {match.get('tournament_name')}
- Fase/Round: {match.get('tournament_round')}
- Tipo: {match.get('event_type_type')}
- Stagione: {match.get('tournament_season')}
"""
    prompt = PROMPT_PIPELINE.format(match_block=match_block)

    import shutil
    claude_bin = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~/.local/node/bin')}:{env.get('PATH','')}"
    result = subprocess.run(
        [claude_bin, '-p', prompt, '--output-format', 'json'],
        capture_output=True,
        text=True,
        timeout=1800,
        env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f'claude CLI fallita: {result.stderr}')

    # claude --output-format json restituisce un wrapper, estraiamo il content
    try:
        wrapper = json.loads(result.stdout)
        content = wrapper.get('result') or wrapper.get('content') or result.stdout
    except json.JSONDecodeError:
        content = result.stdout

    # Il content dovrebbe contenere il JSON interno dell'articolo
    start = content.find('{')
    end = content.rfind('}') + 1
    if start < 0 or end <= start:
        raise RuntimeError(f'JSON non trovato nel content: {content[:300]}')

    return json.loads(content[start:end])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: python generate_analysis.py selected_YYYY-MM-DD.json', file=sys.stderr)
        sys.exit(1)
    selected = json.loads(Path(sys.argv[1]).read_text())
    outdir = Path(sys.argv[1]).parent / 'analyses'
    outdir.mkdir(exist_ok=True)
    for m in selected:
        mid = m.get('event_key')
        print(f'Analizzo match {mid}: {m.get("event_first_player")} vs {m.get("event_second_player")}')
        try:
            analysis = genera(m)
            out = outdir / f'analysis_{mid}.json'
            out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
            print(f'  Salvata in {out}')
        except Exception as e:
            print(f'  ERRORE: {e}', file=sys.stderr)
