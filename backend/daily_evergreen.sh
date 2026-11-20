#!/bin/bash
# FASE A v2 - Evergreen first, STREAMING DEPLOY.
#
# Differenza vs v1 (file originale daily_evergreen.sh):
#   - 4 BLOCCHI, ciascuno con sanity check + commit + push + IndexNow.
#     Appena un blocco finisce, cio' che ha prodotto va live SUBITO.
#   - I lenti (profili) sono spostati in fondo: non rallentano piu' il
#     resto, che intanto e' gia' online.
#   - Fallimento di un blocco NON ferma i successivi: il report finale
#     dice cosa e' live e cosa e' saltato.
#   - Health check finale su homepage + sitemap + robots + llms.txt +
#     catalog.json (SEO+GEO insieme).
#
# Flusso:
#   Blocco 1 - Fondamenta rapide: fixtures + standings + H2H + name-map
#              + audit fatti  -> commit+push (classifiche + H2H live)
#   Blocco 2 - Contenuti editoriali rapidi: weekly recap (solo lun) +
#              newsroom + entity linking Wikidata  -> commit+push
#   Blocco 3 - Lenti in fondo: profili (backfill + italiani + coverage)
#              + guard  -> commit+push
#   Blocco 4 - Chiusura: SEO guard + health check live

set -uo pipefail

cd "$(dirname "$0")"

OGGI=$(date +%F)
BACKEND="$HOME/analisitennis/backend"
REPO="$HOME/analisitennis"
LOG_DIR="$BACKEND/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/evergreen_${OGGI}.log"
SENTINEL="$LOG_DIR/.ran-evergreen-${OGGI}"

# Riepilogo blocchi: popolato dai blocchi, letto nel report finale.
STATO_BLOCCO_1="?"
STATO_BLOCCO_2="?"
STATO_BLOCCO_3="?"
STATO_BLOCCO_4="?"
COMMIT_1=""
COMMIT_2=""
COMMIT_3=""

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
log_section() { echo "" | tee -a "$LOG"; echo "=== $* ===" | tee -a "$LOG"; }

log_section "AVVIO Fase A v2 evergreen - $(date)"

# Idempotenza
if [ -f "$SENTINEL" ]; then
    log "Fase A gia' completata oggi ($OGGI). Esco con 0."
    exit 0
fi

# Lock
LOCK="$LOG_DIR/.lock-evergreen"
if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
        log "Lock evergreen orfano (>6h): rimuovo e procedo."
        rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null
    else
        log "Fase A gia' in corso (lock presente). Esco con 0."
        exit 0
    fi
fi
trap 'rm -rf "$LOCK"' EXIT

# Rete
if ! curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://1.1.1.1/" 2>/dev/null | grep -q "^[23]"; then
    log "ERRORE: nessuna rete. Rilancia quando sei online."
    exit 75
fi

# ---- helper: deploy di un blocco (sanity + commit + push + indexnow) ----
# Argomenti:
#   $1 = label del blocco (es. "Blocco 1 - fondamenta")
#   $2 = scope sanity (es. "standings")  (vuoto = salta sanity)
#   $3 = commit message
#   $4+ = path da git-add (percorsi relativi alla repo)
# Ritorna:
#   0 = deploy fatto (commit+push)
#   1 = niente da pushare (commit vuoto)
#   2 = sanity FAIL -> blocco saltato (nessun commit)
#   3 = push fallito -> blocco saltato
blocco_deploy() {
    local label="$1"; shift
    local scope="$1"; shift
    local msg="$1"; shift
    # restanti = path

    cd "$REPO"

    # 1. Sanity check
    if [ -n "$scope" ]; then
        log "[$label] sanity check (scope=$scope)..."
        python3 "$BACKEND/sanity_check.py" "$scope" 2>&1 | tee -a "$LOG"
        local rc_sanity=${PIPESTATUS[0]}
        if [ "$rc_sanity" = "2" ]; then
            log "[$label] SANITY FAIL -> salto il deploy di questo blocco."
            return 2
        fi
    fi

    # 2. git add dei path specifici (no git add -A)
    for p in "$@"; do
        git add "$p" 2>&1 | tee -a "$LOG" || true
    done

    if git diff --cached --quiet; then
        log "[$label] nessuna novita' da pubblicare."
        return 1
    fi

    # 3. commit
    git commit -m "$msg

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" 2>&1 | tee -a "$LOG"

    # 4. push con retry (fino a 5 tentativi, non blocca la Fase A se fallisce)
    local tries=0
    until git push origin main 2>&1 | tee -a "$LOG"; do
        tries=$(( tries + 1 ))
        if (( tries >= 5 )); then
            log "[$label] push fallito 5 volte. Lascio il commit locale e proseguo."
            return 3
        fi
        log "[$label] push fallito, riprovo tra 30s (tentativo $tries/5)"
        sleep 30
    done
    log "[$label] pubblicato su GitHub."

    # 5. IndexNow (SEO+GEO: avvisa Bing/Yandex/ChatGPT Search)
    python3 "$BACKEND/indexnow_ping.py" "$OGGI" 2>&1 | tee -a "$LOG" || true

    # 6. ricorda SHA per il report
    git log -1 --oneline
    return 0
}


# ============================================================
# BLOCCO 1 - Fondamenta rapide
# ============================================================
log_section "[BLOCCO 1] Fondamenta rapide (fixtures + standings + H2H)"
cd "$BACKEND"

# 1a. fetch palinsesto (asset backend, non pubblica)
python3 fetch_fixtures.py "$OGGI" 2>&1 | tee -a "$LOG" || log "WARN fetch_fixtures"

# 1b. classifiche ATP/WTA
python3 fetch_standings.py 2>&1 | tee -a "$LOG" || log "WARN fetch_standings"

# 1c. H2H scontri diretti
python3 fetch_h2h.py 2>&1 | tee -a "$LOG" || log "WARN fetch_h2h"

# 1d. name-map
python3 export_name_map.py 2>&1 | tee -a "$LOG" || log "WARN export_name_map"

# 1e. audit fatti incrociato (report, non pubblica)
python3 audit_fatti.py 2>&1 | tee -a "$LOG" || true

# 1f. deploy incrementale
# scope sanity "h2h" (standings + h2h) + "entities" (no, non c'e' ancora)
cd "$REPO"
blocco_deploy \
    "BLOCCO 1" \
    "h2h" \
    "Evergreen $OGGI blocco 1 (classifiche + H2H)" \
    "src/data/standings-atp.json" "src/data/standings-wta.json" \
    "src/data/standings-atp-ext.json" "src/data/standings-wta-ext.json" \
    "src/data/h2h.json" "src/data/name-map.json"
RC_B1=$?
case $RC_B1 in
    0) STATO_BLOCCO_1="PUBBLICATO"; COMMIT_1=$(git -C "$REPO" rev-parse --short HEAD) ;;
    1) STATO_BLOCCO_1="NO-OP (nessuna novita')" ;;
    2) STATO_BLOCCO_1="SALTATO (sanity FAIL)" ;;
    3) STATO_BLOCCO_1="LOCALE (push fallito)" ;;
esac


# ============================================================
# BLOCCO 2 - Contenuti editoriali rapidi
# ============================================================
log_section "[BLOCCO 2] Editoriali rapidi (recap + news + entity linking)"
cd "$BACKEND"

# 2a. recap settimanale (solo lun)
if [ "$(date +%u)" = "1" ]; then
    python3 weekly_recap.py "$OGGI" 2>&1 | tee -a "$LOG" || true
fi

# 2b. newsroom
python3 fetch_news.py "$OGGI" 2>&1 | tee -a "$LOG" || true

# 2c. entity linking Wikidata
if [ "${ANALISITENNIS_ENTITIES:-1}" != "0" ]; then
    python3 resolve_entities.py 2>&1 | tee -a "$LOG" || true
fi

# 2d. deploy incrementale
cd "$REPO"
blocco_deploy \
    "BLOCCO 2" \
    "news" \
    "Evergreen $OGGI blocco 2 (news + entities + recap)" \
    "src/content/news" \
    "src/content/articoli" \
    "src/data/player_entities.json"
RC_B2=$?
case $RC_B2 in
    0) STATO_BLOCCO_2="PUBBLICATO"; COMMIT_2=$(git -C "$REPO" rev-parse --short HEAD) ;;
    1) STATO_BLOCCO_2="NO-OP (nessuna novita')" ;;
    2) STATO_BLOCCO_2="SALTATO (sanity FAIL)" ;;
    3) STATO_BLOCCO_2="LOCALE (push fallito)" ;;
esac


# ============================================================
# BLOCCO 3 - Lenti in fondo: profili editoriali
# ============================================================
log_section "[BLOCCO 3] Profili editoriali (backfill + italiani + coverage)"
cd "$BACKEND"

python3 generate_profiles.py backfill 2>&1 | tee -a "$LOG" || true
python3 generate_profiles.py italiani 6 2>&1 | tee -a "$LOG" || true
python3 generate_profiles.py coverage 8 2>&1 | tee -a "$LOG" || true

# guard profili (ripara/rimuove rotti)
cd "$REPO"
python3 "$BACKEND/guard_profiles.py" 2>&1 | tee -a "$LOG" || true

# deploy incrementale
blocco_deploy \
    "BLOCCO 3" \
    "profiles" \
    "Evergreen $OGGI blocco 3 (profili + cover tornei)" \
    "src/content/giocatori-profilo" \
    "src/content/tornei-profilo" \
    "public/covers/tornei"
RC_B3=$?
case $RC_B3 in
    0) STATO_BLOCCO_3="PUBBLICATO"; COMMIT_3=$(git -C "$REPO" rev-parse --short HEAD) ;;
    1) STATO_BLOCCO_3="NO-OP (nessuna novita')" ;;
    2) STATO_BLOCCO_3="SALTATO (sanity FAIL)" ;;
    3) STATO_BLOCCO_3="LOCALE (push fallito)" ;;
esac


# ============================================================
# BLOCCO 4 - Chiusura: SEO guard + health check live
# ============================================================
log_section "[BLOCCO 4] SEO guard + health check live"

# SEO guard: footprint indicizzato
cd "$BACKEND"
python3 seo_guard.py 2>&1 | tee -a "$LOG" || true

# Costruisci lista sample URL da verificare (news + profili pushati oggi)
SAMPLE=()
if [ -n "$COMMIT_2" ]; then
    # Prendi max 3 news del giorno
    for n in $(git -C "$REPO" log -1 --name-only --pretty= "$COMMIT_2" 2>/dev/null | grep '^src/content/news/' | head -3); do
        slug=$(basename "$n" .md)
        SAMPLE+=("https://analisitennis.it/news/$slug")
    done
fi
if [ -n "$COMMIT_3" ]; then
    # Prendi max 2 profili
    for n in $(git -C "$REPO" log -1 --name-only --pretty= "$COMMIT_3" 2>/dev/null | grep -E '^src/content/(giocatori|tornei)-profilo/' | head -2); do
        slug=$(basename "$n" .md)
        if [[ "$n" == *giocatori* ]]; then
            SAMPLE+=("https://analisitennis.it/giocatori/$slug")
        else
            SAMPLE+=("https://analisitennis.it/tornei/$slug")
        fi
    done
fi

# Attendi fino a 180s che il deploy piu' recente sia raggiungibile
if [ ${#SAMPLE[@]} -gt 0 ]; then
    python3 "$BACKEND/health_check.py" --wait 180 --sample "${SAMPLE[@]}" 2>&1 | tee -a "$LOG"
else
    python3 "$BACKEND/health_check.py" --wait 90 2>&1 | tee -a "$LOG"
fi
RC_HC=${PIPESTATUS[0]}
case $RC_HC in
    0) STATO_BLOCCO_4="HEALTH PASS" ;;
    1) STATO_BLOCCO_4="HEALTH WARN" ;;
    2) STATO_BLOCCO_4="HEALTH FAIL (sito giu'?)" ;;
    *) STATO_BLOCCO_4="?" ;;
esac


# ============================================================
# REPORT FINALE
# ============================================================
log_section "REPORT Fase A v2 - $(date)"
log "Blocco 1 (classifiche + H2H):           $STATO_BLOCCO_1 ${COMMIT_1}"
log "Blocco 2 (news + entities + recap):     $STATO_BLOCCO_2 ${COMMIT_2}"
log "Blocco 3 (profili):                     $STATO_BLOCCO_3 ${COMMIT_3}"
log "Blocco 4 (health check):                $STATO_BLOCCO_4"
log ""
log "Fase A completata. Pronostici NON generati."
log "Per lanciarli: bash $BACKEND/pronostici.sh  (o in chat: 'lancia pronostici')"

touch "$SENTINEL"
