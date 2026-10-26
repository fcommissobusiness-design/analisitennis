#!/bin/bash
# Pipeline giornaliera AnalisiTennis
# Scheduled: ogni giorno alle 07:00 via LaunchAgent
#
# Resilienza:
# - Se il Mac e' spento/dormiente alle 07:00, launchd rilancia automaticamente
#   al risveglio (comportamento nativo StartCalendarInterval).
# - Se il Mac e' acceso ma OFFLINE alle 07:00, lo script attende la rete
#   fino a 6 ore prima di procedere. Se la rete arriva, parte da quel momento.
# - Se la rete NON arriva entro 6 ore, lo script esce con codice 75
#   (EX_TEMPFAIL) e launchd lo riprova con l'intervallo di throttle del plist.
# - La pipeline e' idempotente: ri-eseguita nello stesso giorno committa
#   solo se ci sono articoli nuovi non ancora pushati.

set -uo pipefail

cd "$(dirname "$0")"

OGGI=$(date +%F)
LOG_DIR="$HOME/analisitennis/backend/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_${OGGI}.log"
SENTINEL="$LOG_DIR/.ran-${OGGI}"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
log_section() { echo "" | tee -a "$LOG"; echo "=== $* ===" | tee -a "$LOG"; }

log_section "AVVIO pipeline AnalisiTennis - $(date)"

# Idempotenza: se oggi la pipeline ha gia' completato, esci subito.
# Questo evita duplicati quando il job parte al login (RunAtLoad) dopo
# essere gia' partito al mattino via StartCalendarInterval.
if [ -f "$SENTINEL" ]; then
    log "Pipeline gia' completata oggi ($OGGI). Esco con 0."
    exit 0
fi

# Aspetta che la rete sia disponibile. Max 6 ore (360 iterazioni da 60s).
# Check robusto: curl su endpoint sempre disponibili (Cloudflare DNS 1.1.1.1 + Google).
# NON usiamo API Tennis base perche' ritorna 403 senza API key.
# NON usiamo ping perche' launchd sandbox puo' bloccarlo.
wait_for_network() {
    local max_tries=360
    local try=0
    while (( try < max_tries )); do
        # Due endpoint pubblici che rispondono sempre 200 se c'e' rete + DNS
        if curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://1.1.1.1/" 2>/dev/null | grep -q "^[23]" \
           || curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://www.google.com/" 2>/dev/null | grep -q "^[23]"; then
            if (( try > 0 )); then
                log "Rete tornata disponibile dopo ${try} minuti di attesa"
            else
                log "Rete gia' disponibile"
            fi
            return 0
        fi
        if (( try == 0 )); then
            log "Nessuna rete: attendo..."
        elif (( try % 10 == 0 )); then
            log "Ancora offline dopo ${try} minuti, continuo ad attendere..."
        fi
        try=$(( try + 1 ))
        sleep 60
    done
    log "ERRORE: rete non disponibile dopo 6 ore di attesa, esco con codice 75"
    return 75
}

if ! wait_for_network; then
    exit 75
fi

# 1. Fetch palinsesto
log_section "[1/5] Fetch palinsesto $OGGI"
python3 fetch_fixtures.py "$OGGI" 2>&1 | tee -a "$LOG" || {
    log "ERRORE fetch_fixtures, esco con codice 75 per retry"
    exit 75
}

# 2. Selezione match
log_section "[2/5] Selezione match top"
python3 select_matches.py "fixtures_${OGGI}.json" 2>&1 | tee -a "$LOG"

# 3. Generazione analisi (framework FASE 1-4 + sanity 3 pilastri)
log_section "[3/5] Generazione analisi (claude CLI, fact-check anti-bias+anti-hallucination)"
python3 generate_analysis.py "selected_${OGGI}.json" 2>&1 | tee -a "$LOG"

# Segnala in modo visibile se ci sono stati match skippati per mancanza dati
# autoritativi API Tennis (gate "no data = abort" dentro generate_analysis.py).
SKIPPED_REPORT="skipped_no_data_${OGGI}.json"
if [ -f "$SKIPPED_REPORT" ]; then
    log_section "[ATTENZIONE] Match SKIPPATI per API Tennis senza dati"
    log "File: $SKIPPED_REPORT"
    cat "$SKIPPED_REPORT" | tee -a "$LOG"
fi

# 4. Scrittura articoli markdown
log_section "[4/5] Scrittura articoli"
python3 write_article.py "selected_${OGGI}.json" "analyses" 2>&1 | tee -a "$LOG"

# 4-bis. Audit cover: ogni articolo deve avere cover corretta, pertinente,
# non sfasata. Lo script corregge in-place le cover problematiche (file
# mancanti, foto non-tennis, favorito con foto Commons disponibile ma
# non usata). Esce con codice >0 se trova problemi, ma non blocca la
# pipeline: il --fix li risolve quasi sempre.
log_section "[4-bis/5] Audit cover articoli (corregge sfasamenti)"
python3 audit_covers.py --fix --date="${OGGI}" 2>&1 | tee -a "$LOG" || true

# 5. Commit + push (triggera Cloudflare Pages deploy)
log_section "[5/5] Commit e push"
cd "$HOME/analisitennis"
git add src/content/articoli/*.md 2>&1 | tee -a "$LOG" || true
if git diff --cached --quiet; then
    log "Nessun nuovo articolo da pubblicare oggi."
else
    git commit -m "Articoli automatici $OGGI

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" 2>&1 | tee -a "$LOG"
    # Il push puo' fallire se offline tra fetch e push: ritenta fino a 10 volte
    push_tries=0
    until git push origin main 2>&1 | tee -a "$LOG"; do
        push_tries=$(( push_tries + 1 ))
        if (( push_tries >= 10 )); then
            log "git push fallito 10 volte, esco con codice 75 per retry launchd"
            exit 75
        fi
        log "git push fallito, riprovo tra 60s (tentativo $push_tries/10)"
        sleep 60
    done
    log "Articoli pubblicati su GitHub."
fi

log_section "COMPLETATA pipeline - $(date)"

# Sentinel: segna che oggi la pipeline e' completata. Impedisce doppie
# esecuzioni se launchd rilancia il job (RunAtLoad al login + 07:00 schedulato).
touch "$SENTINEL"

# [POST] Profili editoriali in background.
# Idempotente: skippa i profili gia' esistenti, crea solo quelli mancanti
# per i giocatori/tornei nuovi incontrati oggi. Non blocca la pubblicazione:
# il sito e' gia' live quando questo gira, i profili arrivano con calma.
log_section "[POST] Profili editoriali (background)"
cd "$HOME/analisitennis/backend"
nohup python3 generate_profiles.py backfill > "$LOG_DIR/profiles_${OGGI}.log" 2>&1 &
log "Lanciato backfill profili in background (pid $!)"
