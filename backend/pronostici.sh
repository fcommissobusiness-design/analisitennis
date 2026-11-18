#!/bin/bash
# FASE B - Pronostici del giorno.
# Si lancia a comando ("lancia pronostici" in chat o bash pronostici.sh).
# Dipende da fetch palinsesto gia' fatto dalla Fase A (daily_evergreen.sh).
# Se il palinsesto di oggi non c'e', lo rifetcha.
#
# Flusso: selezione match -> verifica round web -> generazione analisi
# -> scrittura articoli -> verifica turni -> anti-bias titoli -> audit
# cover -> vet cover -> commit+push -> IndexNow.
#
# Durata tipica: 2-3 ore (gate fact-check 3 pilastri + fact-check web
# indipendente su ogni articolo). Il resto del sito e' gia' live grazie
# alla Fase A, quindi se la Fase B tarda non c'e' nessun problema di
# visibilita' aggregata.

set -uo pipefail

cd "$(dirname "$0")"

OGGI=$(date +%F)
LOG_DIR="$HOME/analisitennis/backend/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/pronostici_${OGGI}.log"
SENTINEL="$LOG_DIR/.ran-pronostici-${OGGI}"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
log_section() { echo "" | tee -a "$LOG"; echo "=== $* ===" | tee -a "$LOG"; }

log_section "AVVIO Fase B pronostici - $(date)"

if [ -f "$SENTINEL" ]; then
    log "Fase B gia' completata oggi ($OGGI). Esco con 0."
    exit 0
fi

LOCK="$LOG_DIR/.lock-pronostici"
if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
        log "Lock pronostici orfano (>6h): rimuovo e procedo."
        rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null
    else
        log "Fase B gia' in corso (lock presente). Esco con 0."
        exit 0
    fi
fi
trap 'rm -rf "$LOCK"' EXIT

if ! curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://1.1.1.1/" 2>/dev/null | grep -q "^[23]"; then
    log "ERRORE: nessuna rete. Rilancia quando sei online."
    exit 75
fi

# 0. Fetch palinsesto se la Fase A non l'ha fatto ancora oggi.
if [ ! -f "fixtures_${OGGI}.json" ]; then
    log "Palinsesto di oggi mancante: lo fetcho adesso (la Fase A non l'ha fatta)."
    log_section "[0] Fetch palinsesto $OGGI"
    python3 fetch_fixtures.py "$OGGI" 2>&1 | tee -a "$LOG" || {
        log "ERRORE fetch_fixtures, esco con codice 75"
        exit 75
    }
else
    log "Palinsesto di oggi gia' fetchato dalla Fase A: fixtures_${OGGI}.json"
fi

# 1. Selezione match top.
log_section "[1] Selezione match top"
python3 select_matches.py "fixtures_${OGGI}.json" 2>&1 | tee -a "$LOG"

# 1-bis. Verifica ROUND via WEB CHECK: corregge il round di API Tennis.
log_section "[1-bis] Verifica round via web"
python3 verify_rounds.py "selected_${OGGI}.json" 2>&1 | tee -a "$LOG" || true

# 2. Generazione analisi (CORE). Ogni articolo: gate 3 pilastri +
# fact-check web indipendente. Chi non passa non viene pubblicato.
log_section "[2] Generazione analisi (gate 3 pilastri + fact-check web)"
python3 generate_analysis.py "selected_${OGGI}.json" 2>&1 | tee -a "$LOG"

# Segnala match skippati per dati API mancanti.
SKIPPED_REPORT="skipped_no_data_${OGGI}.json"
if [ -f "$SKIPPED_REPORT" ]; then
    log_section "[ATTENZIONE] Match SKIPPATI per API Tennis senza dati"
    cat "$SKIPPED_REPORT" | tee -a "$LOG"
fi

# Segnala match non pubblicati per fact-check web fallito.
FACTCHECK_REPORT="skipped_factcheck_${OGGI}.json"
if [ -f "$FACTCHECK_REPORT" ]; then
    log_section "[ATTENZIONE] Match NON pubblicati per fact-check web fallito"
    cat "$FACTCHECK_REPORT" | tee -a "$LOG"
fi

# 3. Scrittura articoli markdown.
log_section "[3] Scrittura articoli"
python3 write_article.py "selected_${OGGI}.json" "analyses" 2>&1 | tee -a "$LOG"

# 3-TURNI. Gate FASE DEL TORNEO per match: la verifica per torneo (step
# 1-bis) non copre il caso "due turni nello stesso giorno" (Parigi 1T+2T).
log_section "[3-TURNI] Verifica fase del torneo dichiarata negli articoli"
python3 check_round_claims.py --date="${OGGI}" --fix 2>&1 | tee -a "$LOG" || true

# 3-TITOLI. Gate ANTI-BIAS sul copy dei titoli del giorno.
log_section "[3-TITOLI] Gate anti-bias titoli giornata"
python3 check_title_bias.py --date="${OGGI}" 2>&1 | tee -a "$LOG" || true

# 4. Audit cover articoli (corregge sfasamenti).
log_section "[4] Audit cover articoli (--fix)"
python3 audit_covers.py --fix --date="${OGGI}" 2>&1 | tee -a "$LOG" || true

# 4-ter. Gate di pertinenza visivo cover (claude vision).
log_section "[4-ter] Gate pertinenza visivo cover"
python3 vet_covers.py --date="${OGGI}" 2>&1 | tee -a "$LOG" || true

# 5. Commit + push articoli e cover.
cd "$HOME/analisitennis"
log_section "[5] Commit e push pronostici"
git add src/content/articoli/*.md \
        public/covers/ 2>&1 | tee -a "$LOG" || true
if git diff --cached --quiet; then
    log "Nessun nuovo articolo pronostico da pubblicare oggi."
else
    git commit -m "Pronostici $OGGI

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" 2>&1 | tee -a "$LOG"
    push_tries=0
    until git push origin main 2>&1 | tee -a "$LOG"; do
        push_tries=$(( push_tries + 1 ))
        if (( push_tries >= 10 )); then
            log "git push fallito 10 volte, esco con 75"
            exit 75
        fi
        log "git push fallito, riprovo tra 60s (tentativo $push_tries/10)"
        sleep 60
    done
    log "Pronostici pubblicati su GitHub."

    log_section "[POST] IndexNow ping (Bing/Yandex)"
    cd "$HOME/analisitennis/backend"
    python3 indexnow_ping.py "$OGGI" 2>&1 | tee -a "$LOG" || true
fi

log_section "COMPLETATA Fase B pronostici - $(date)"
touch "$SENTINEL"
