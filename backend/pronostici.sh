#!/bin/bash
# FASE B v2 - Pronostici del giorno, STREAMING DEPLOY per-match.
#
# Differenza vs v1:
#   - Loop per-match: ogni articolo che passa il gate 3 pilastri + web
#     factcheck va LIVE immediatamente (commit+push+IndexNow singolo).
#     Primo articolo online in ~10 min invece di ~2h.
#   - Gate aggregati (check_round_claims, check_title_bias, audit_covers,
#     vet_covers) girano a fine loop come "safety net" e, se correggono
#     qualcosa, generano UN commit di patch.
#   - Fallimento di un match NON blocca gli altri: il report finale dice
#     cosa e' live e cosa e' saltato (no-data, factcheck fallito, altro).
#   - Health check SEO+GEO finale su un campione degli articoli pushati.

set -uo pipefail

cd "$(dirname "$0")"

OGGI=$(date +%F)
BACKEND="$HOME/analisitennis/backend"
REPO="$HOME/analisitennis"
LOG_DIR="$BACKEND/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/pronostici_${OGGI}.log"
SENTINEL="$LOG_DIR/.ran-pronostici-${OGGI}"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
log_section() { echo "" | tee -a "$LOG"; echo "=== $* ===" | tee -a "$LOG"; }

log_section "AVVIO Fase B v2 pronostici - $(date)"

# Idempotenza
if [ -f "$SENTINEL" ]; then
    log "Fase B gia' completata oggi ($OGGI). Esco con 0."
    exit 0
fi

# Lock
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

# Rete
if ! curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://1.1.1.1/" 2>/dev/null | grep -q "^[23]"; then
    log "ERRORE: nessuna rete. Rilancia quando sei online."
    exit 75
fi

# Nessuna dipendenza esterna oltre Python3: niente jq.

# ============================================================
# SETUP (zero deploy): palinsesto + selezione + verifica round
# ============================================================
log_section "[SETUP 0] Fetch palinsesto (se manca)"
cd "$BACKEND"
if [ ! -f "fixtures_${OGGI}.json" ]; then
    python3 fetch_fixtures.py "$OGGI" 2>&1 | tee -a "$LOG" || {
        log "ERRORE fetch_fixtures"; exit 75
    }
else
    log "Palinsesto gia' presente: fixtures_${OGGI}.json"
fi

log_section "[SETUP 1] Selezione match top"
python3 select_matches.py "fixtures_${OGGI}.json" 2>&1 | tee -a "$LOG"

log_section "[SETUP 2] Verifica round via web"
python3 verify_rounds.py "selected_${OGGI}.json" 2>&1 | tee -a "$LOG" || true

SELECTED="$BACKEND/selected_${OGGI}.json"
if [ ! -f "$SELECTED" ]; then
    log "ERRORE: selected_${OGGI}.json non esiste. Esco."
    exit 75
fi

N_MATCH=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$SELECTED")
log "Match in pipeline: $N_MATCH"

# Contatori riepilogo
PUBBLICATI=()
SKIPPATI_FACTCHECK=()
SKIPPATI_NODATA=()
SKIPPATI_ALTRO=()

# ============================================================
# LOOP PER-MATCH: gate -> scrittura -> sanity -> deploy singolo
# ============================================================
log_section "[LOOP] Pipeline per-match ($N_MATCH match)"

cd "$BACKEND"
mkdir -p analyses

# Itero ogni match (idx 0..N-1). Estrazione via python3 inline (no jq).
for i in $(seq 0 $((N_MATCH - 1))); do
    # Un singolo python3 scrive il file single e stampa i campi tab-separated
    LINE=$(python3 - "$SELECTED" "$i" <<'PY'
import json, sys
sel = json.load(open(sys.argv[1]))
i = int(sys.argv[2])
m = sel[i]
mid = str(m.get('event_key', ''))
p1 = str(m.get('event_first_player', ''))
p2 = str(m.get('event_second_player', ''))
tor = str(m.get('tournament_name', ''))
# Scrive il single file accanto a selected
import os
single = os.path.join(os.path.dirname(sys.argv[1]), f'selected_single_{mid}.json')
json.dump([m], open(single, 'w'), ensure_ascii=False)
print(f'{mid}\t{p1}\t{p2}\t{tor}\t{single}')
PY
)
    MID=$(echo "$LINE" | cut -f1)
    P1=$(echo "$LINE" | cut -f2)
    P2=$(echo "$LINE" | cut -f3)
    TORNEO=$(echo "$LINE" | cut -f4)
    SINGLE=$(echo "$LINE" | cut -f5)

    log_section "[$((i+1))/$N_MATCH] $P1 vs $P2 - $TORNEO (match $MID)"

    # 1. Generazione analisi (gate 3 pilastri + web factcheck)
    log "  [1] generate_analysis (gate + web factcheck)..."
    python3 generate_analysis.py "$SINGLE" 2>&1 | tee -a "$LOG" || true

    ANALYSIS_FILE="$BACKEND/analyses/analysis_${MID}.json"
    if [ ! -f "$ANALYSIS_FILE" ]; then
        # L'analisi non esiste = match skippato (no-data o factcheck fail)
        # Capiamo il motivo dai file di report generati da generate_analysis
        # Capisco il motivo del skip leggendo i report via python
        SKIP_REASON=$(python3 - "$BACKEND" "$OGGI" "$MID" <<'PY'
import json, os, sys
bk, oggi, mid = sys.argv[1:4]
for kind, label in (('skipped_no_data', 'NO_DATA'), ('skipped_factcheck', 'FACTCHECK')):
    p = os.path.join(bk, f'{kind}_{oggi}.json')
    if not os.path.exists(p):
        continue
    try:
        data = json.load(open(p))
    except Exception:
        continue
    if any(str(x.get('event_key', '')) == mid for x in data):
        print(label); sys.exit(0)
print('UNKNOWN')
PY
)
        case "$SKIP_REASON" in
            NO_DATA)   log "  SKIP no-data: API Tennis senza dati su $P1 o $P2"; SKIPPATI_NODATA+=("$P1 vs $P2") ;;
            FACTCHECK) log "  SKIP factcheck: web-factcheck fallito";             SKIPPATI_FACTCHECK+=("$P1 vs $P2") ;;
            *)         log "  SKIP motivo sconosciuto";                           SKIPPATI_ALTRO+=("$P1 vs $P2") ;;
        esac
        rm -f "$SINGLE"
        continue
    fi

    # 2. Scrittura articolo markdown + cover.
    #    Catturo lo stdout per leggere il path "Scritto: ..." emesso da write_article.
    log "  [2] write_article..."
    WA_OUT=$(python3 write_article.py "$SINGLE" "$BACKEND/analyses" 2>&1 | tee -a "$LOG")
    MD_FILE=$(echo "$WA_OUT" | grep -oE '/[^ ]*\.md' | tail -1)
    if [ -z "$MD_FILE" ] || [ ! -f "$MD_FILE" ]; then
        log "  ATTENZIONE: MD non trovato dall'output di write_article (sara' ripreso dal batch finale)"
        SKIPPATI_ALTRO+=("$P1 vs $P2 [md not found]")
        rm -f "$SINGLE"
        continue
    fi
    MD_NAME=$(basename "$MD_FILE")
    SLUG=$(basename "$MD_FILE" .md)
    log "  MD creato: $MD_NAME"

    # 4. Sanity check pre-commit sul singolo MD
    log "  [3] sanity check articolo..."
    python3 "$BACKEND/sanity_check.py" articles --files "$MD_FILE" 2>&1 | tee -a "$LOG"
    RC_SANITY=${PIPESTATUS[0]}
    if [ "$RC_SANITY" = "2" ]; then
        log "  SANITY FAIL: articolo NON pushato (resta locale, batch finale potra' correggerlo)"
        SKIPPATI_ALTRO+=("$P1 vs $P2 [sanity FAIL]")
        rm -f "$SINGLE"
        continue
    fi

    # 5. Commit + push singolo articolo (+ eventuali cover associate)
    cd "$REPO"
    git add "src/content/articoli/${MD_NAME}" 2>&1 | tee -a "$LOG" || true
    git add "public/covers/${SLUG}"* 2>&1 | tee -a "$LOG" || true

    if git diff --cached --quiet; then
        log "  nessuna novita' da pushare per questo match"
    else
        git commit -m "Pronostico $OGGI: $P1 vs $P2

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" 2>&1 | tee -a "$LOG"

        push_tries=0
        pushed=0
        until git push origin main 2>&1 | tee -a "$LOG"; do
            push_tries=$(( push_tries + 1 ))
            if (( push_tries >= 5 )); then
                log "  push fallito 5 volte, commit resta locale"
                break
            fi
            log "  push fallito, riprovo tra 30s (tentativo $push_tries/5)"
            sleep 30
        done
        if git log origin/main -1 --format=%H 2>/dev/null | grep -q "$(git rev-parse HEAD)"; then
            pushed=1
            log "  PUBBLICATO: https://analisitennis.it/articoli/$SLUG"
            PUBBLICATI+=("$SLUG")
            # 6. IndexNow ping per questo URL
            python3 "$BACKEND/indexnow_ping.py" "$OGGI" 2>&1 | tee -a "$LOG" || true
        fi
    fi

    cd "$BACKEND"
    rm -f "$SINGLE"
done


# ============================================================
# BATCH FINALE: safety net gates (round claims, title bias, cover)
# ============================================================
log_section "[BATCH] Safety net: round claims + title bias + cover"

cd "$BACKEND"
python3 check_round_claims.py --date="${OGGI}" --fix 2>&1 | tee -a "$LOG" || true
python3 check_title_bias.py --date="${OGGI}" 2>&1 | tee -a "$LOG" || true
python3 audit_covers.py --fix --date="${OGGI}" 2>&1 | tee -a "$LOG" || true
python3 vet_covers.py --date="${OGGI}" 2>&1 | tee -a "$LOG" || true

# Se i gate batch hanno modificato qualcosa, UN commit di patch
cd "$REPO"
git add src/content/articoli public/covers 2>&1 | tee -a "$LOG" || true
if git diff --cached --quiet; then
    log "Nessuna correzione batch necessaria."
else
    git commit -m "Pronostici $OGGI: correzioni batch (round/title/cover)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" 2>&1 | tee -a "$LOG"
    push_tries=0
    until git push origin main 2>&1 | tee -a "$LOG"; do
        push_tries=$(( push_tries + 1 ))
        if (( push_tries >= 5 )); then
            log "Push correzioni batch fallito, commit resta locale."
            break
        fi
        log "Push fallito, riprovo tra 30s (tentativo $push_tries/5)"
        sleep 30
    done
    python3 "$BACKEND/indexnow_ping.py" "$OGGI" 2>&1 | tee -a "$LOG" || true
fi


# ============================================================
# HEALTH CHECK FINALE (SEO + GEO + raggiungibilita' articoli)
# ============================================================
log_section "[HEALTH] Check live SEO + GEO + sample articoli"

SAMPLE=()
for slug in "${PUBBLICATI[@]:0:3}"; do
    SAMPLE+=("https://analisitennis.it/articoli/$slug")
done

if [ ${#SAMPLE[@]} -gt 0 ]; then
    python3 "$BACKEND/health_check.py" --wait 180 --sample "${SAMPLE[@]}" 2>&1 | tee -a "$LOG" || true
else
    python3 "$BACKEND/health_check.py" --wait 60 2>&1 | tee -a "$LOG" || true
fi


# ============================================================
# REPORT FINALE
# ============================================================
log_section "REPORT Fase B v2 - $(date)"
log "Match in pipeline: $N_MATCH"
log "Pubblicati: ${#PUBBLICATI[@]}"
log "Skippati factcheck: ${#SKIPPATI_FACTCHECK[@]}"
log "Skippati no-data: ${#SKIPPATI_NODATA[@]}"
log "Skippati altro: ${#SKIPPATI_ALTRO[@]}"

if [ ${#PUBBLICATI[@]} -gt 0 ]; then
    log ""
    log "PUBBLICATI:"
    for s in "${PUBBLICATI[@]}"; do log "  - $s"; done
fi
if [ ${#SKIPPATI_FACTCHECK[@]} -gt 0 ]; then
    log ""
    log "SKIPPATI (factcheck fallito):"
    for s in "${SKIPPATI_FACTCHECK[@]}"; do log "  - $s"; done
fi
if [ ${#SKIPPATI_NODATA[@]} -gt 0 ]; then
    log ""
    log "SKIPPATI (no-data API):"
    for s in "${SKIPPATI_NODATA[@]}"; do log "  - $s"; done
fi
if [ ${#SKIPPATI_ALTRO[@]} -gt 0 ]; then
    log ""
    log "SKIPPATI (altro):"
    for s in "${SKIPPATI_ALTRO[@]}"; do log "  - $s"; done
fi

log ""
log "Fase B completata."
# Sentinel SOLO se almeno un articolo e' stato pubblicato. Se 0 pubblicati
# (es. claude CLI non loggata, API giu', tutti i match skippati), NON si
# marca "fatto": cosi' un retry successivo puo' davvero rigenerare, invece
# di uscire subito vedendo il sentinel di un run fallito.
if [ ${#PUBBLICATI[@]} -gt 0 ]; then
    touch "$SENTINEL"
else
    log "Zero articoli pubblicati: sentinel NON creato (il retry potra' rigenerare)."
fi
