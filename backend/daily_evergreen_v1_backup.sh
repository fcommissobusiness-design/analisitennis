#!/bin/bash
# FASE A - Evergreen first.
# Ogni giorno quando vuoi. Nessun pronostico: solo cose che resteranno
# rilevanti per settimane o anni (classifiche, H2H, profili, news,
# recap, entity linking, SEO guard). Esce in 15-30 minuti e pubblica
# live il sito aggiornato prima dei pronostici.
#
# Flusso: fetch palinsesto (serve per le H2H delle coppie di oggi) ->
# classifiche -> H2H -> name-map -> audit fatti -> recap settimanale
# (lunedi') -> newsroom -> entity linking Wikidata -> backfill profili
# (foreground) -> commit+push -> IndexNow -> SEO guard.
#
# I PRONOSTICI del giorno sono in pronostici.sh e si lanciano a parte
# ("lancia pronostici" in chat, oppure bash pronostici.sh).

set -uo pipefail

cd "$(dirname "$0")"

OGGI=$(date +%F)
LOG_DIR="$HOME/analisitennis/backend/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/evergreen_${OGGI}.log"
SENTINEL="$LOG_DIR/.ran-evergreen-${OGGI}"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
log_section() { echo "" | tee -a "$LOG"; echo "=== $* ===" | tee -a "$LOG"; }

log_section "AVVIO Fase A evergreen - $(date)"

# Idempotenza: se oggi la fase A ha gia' completato, esci subito.
if [ -f "$SENTINEL" ]; then
    log "Fase A gia' completata oggi ($OGGI). Esco con 0."
    exit 0
fi

# Lock anti-concorrenza (mkdir atomico). Lock orfano >6h considerato morto.
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

# Rete necessaria. Versione minimale: 1 check iniziale, no attesa 6h
# (chi lancia la fase A manualmente verifica da se' di essere online).
if ! curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://1.1.1.1/" 2>/dev/null | grep -q "^[23]"; then
    log "ERRORE: nessuna rete. Rilancia quando sei online."
    exit 75
fi

# 1. Fetch palinsesto del giorno. Serve alle H2H e all'eventuale Fase B
# successiva (pronostici): la Fase A lo prepara, cosi' la Fase B non
# deve rifetcharlo quando viene lanciata.
log_section "[1] Fetch palinsesto $OGGI"
python3 fetch_fixtures.py "$OGGI" 2>&1 | tee -a "$LOG" || {
    log "ERRORE fetch_fixtures, esco con codice 75"
    exit 75
}

# 2. Classifiche ATP/WTA (pagine /classifica-atp e /classifica-wta).
# Evergreen puro: le pagine sono delle piu' viste del sito (24 clic/3mesi
# /classifica-atp, verificato GSC 18/11/2026).
log_section "[2] Classifiche ATP/WTA"
python3 fetch_standings.py 2>&1 | tee -a "$LOG" || true

# 3. H2H. Alimenta le 92 pagine /scontri-diretti/<coppia>, nuove query
# evergreen "<p1> vs <p2>". Richiede fixtures del giorno.
log_section "[3] Scontri diretti H2H"
python3 fetch_h2h.py 2>&1 | tee -a "$LOG" || true

# 4. Name-map: tiene sincronizzati slug tra frontend e backend
# (evita profili duplicati tipo b-shelton + ben-shelton).
log_section "[4] Export name-map per slug profili"
python3 export_name_map.py 2>&1 | tee -a "$LOG" || true

# 5. Audit fatti (incrociato su tutto l'archivio). Non costa nulla, non
# blocca, segnala contraddizioni tra articoli e profili. Zero API.
log_section "[5] Audit incrociato dei fatti"
python3 audit_fatti.py 2>&1 | tee -a "$LOG" || true

# 6. Recap settimanale (solo lunedi').
if [ "$(date +%u)" = "1" ]; then
    log_section "[6] Recap settimanale (lunedi')"
    python3 weekly_recap.py "$OGGI" 2>&1 | tee -a "$LOG" || true
fi

# 7. Newsroom: scopre + verifica + pubblica news del giorno.
log_section "[7] Newsroom (scoperta + verifica + gate)"
python3 fetch_news.py "$OGGI" 2>&1 | tee -a "$LOG" || true

# 8. Entity linking Wikidata (GEO): sameAs per articoli/profili ->
# piu' citabili dalle AI. Incrementale, bounded, non blocca.
if [ "${ANALISITENNIS_ENTITIES:-1}" != "0" ]; then
    log_section "[8] Entity linking (Wikidata sameAs)"
    python3 resolve_entities.py 2>&1 | tee -a "$LOG" || true
fi

# 9. Backfill profili editoriali (FOREGROUND, non in background come
# il vecchio daily.sh). Tre passi: nuovi dal palinsesto, italiani in
# classifica, coverage top-100. Idempotenti e vettati. Vale per Fase A
# perche' le pagine profilo sono il primo motore di traffico organico
# (37 clic/3mesi su /giocatori/j-kym, verificato GSC 18/11/2026).
log_section "[9] Profili editoriali (backfill + italiani + coverage)"
python3 generate_profiles.py backfill 2>&1 | tee -a "$LOG" || true
python3 generate_profiles.py italiani 6 2>&1 | tee -a "$LOG" || true
python3 generate_profiles.py coverage 8 2>&1 | tee -a "$LOG" || true

# 10. Guard profiles: un singolo profilo malformato fa fallire astro
# build e blocca il deploy in silenzio. Ripara o rimuove.
cd "$HOME/analisitennis"
log_section "[10] Guard profiles (ripara/rimuove profili rotti)"
python3 backend/guard_profiles.py 2>&1 | tee -a "$LOG" || true

# 11. Commit + push dei soli asset evergreen: profili, news, classifiche,
# H2H, name-map, entity json. NON tocchiamo src/content/articoli/ qui:
# quella collezione e' di competenza esclusiva della Fase B (pronostici).
log_section "[11] Commit e push Fase A"
git add src/content/giocatori-profilo/*.md \
        src/content/tornei-profilo/*.md \
        src/content/news/*.md \
        src/data/*.json \
        public/covers/tornei/ 2>&1 | tee -a "$LOG" || true
if git diff --cached --quiet; then
    log "Nessuna novita' evergreen da pubblicare oggi."
else
    git commit -m "Evergreen $OGGI (profili, news, classifiche, H2H)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" 2>&1 | tee -a "$LOG"
    push_tries=0
    until git push origin main 2>&1 | tee -a "$LOG"; do
        push_tries=$(( push_tries + 1 ))
        if (( push_tries >= 10 )); then
            log "git push fallito 10 volte, esco con 75 per retry"
            exit 75
        fi
        log "git push fallito, riprovo tra 60s (tentativo $push_tries/10)"
        sleep 60
    done
    log "Evergreen pubblicato su GitHub."

    # IndexNow: notifica a Bing/Yandex/ChatGPT Search dei nuovi URL.
    log_section "[POST] IndexNow ping (Bing/Yandex)"
    cd "$HOME/analisitennis/backend"
    python3 indexnow_ping.py "$OGGI" 2>&1 | tee -a "$LOG" || true
    cd "$HOME/analisitennis"
fi

# SEO guard: fotografa footprint indicizzato, avvisa su scaled-content.
log_section "[POST] SEO guard (footprint indicizzato)"
cd "$HOME/analisitennis/backend"
python3 seo_guard.py 2>&1 | tee -a "$LOG" || true

log_section "COMPLETATA Fase A evergreen - $(date)"
touch "$SENTINEL"

log ""
log "Fase A completata. I pronostici del giorno non sono stati generati."
log "Per lanciarli, da chat: 'lancia pronostici'  oppure"
log "da terminale: bash $HOME/analisitennis/backend/pronostici.sh"
