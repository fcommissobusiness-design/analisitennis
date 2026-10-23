#!/bin/bash
# Pipeline giornaliera AnalisiTennis
# Scheduled: ogni giorno alle 07:00 via LaunchAgent

set -euo pipefail

cd "$(dirname "$0")"

OGGI=$(date +%F)
LOG_DIR="$HOME/analisitennis/backend/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_${OGGI}.log"

echo "=== $(date) - Avvio pipeline AnalisiTennis ===" | tee -a "$LOG"

# 1. Fetch palinsesto
echo "[1/5] Fetch palinsesto $OGGI..." | tee -a "$LOG"
python3 fetch_fixtures.py "$OGGI" 2>&1 | tee -a "$LOG"

# 2. Selezione match
echo "[2/5] Selezione match top..." | tee -a "$LOG"
python3 select_matches.py "fixtures_${OGGI}.json" 2>&1 | tee -a "$LOG"

# 3. Generazione analisi (framework FASE 1-4)
echo "[3/5] Generazione analisi..." | tee -a "$LOG"
python3 generate_analysis.py "selected_${OGGI}.json" 2>&1 | tee -a "$LOG"

# 4. Scrittura articoli markdown
echo "[4/5] Scrittura articoli..." | tee -a "$LOG"
python3 write_article.py "selected_${OGGI}.json" "analyses" 2>&1 | tee -a "$LOG"

# 5. Commit + push (triggera Cloudflare Pages deploy)
echo "[5/5] Commit e push..." | tee -a "$LOG"
cd "$HOME/analisitennis"
git add src/content/articoli/*.md
if git diff --cached --quiet; then
    echo "Nessun nuovo articolo da pubblicare oggi." | tee -a "$LOG"
else
    git commit -m "Articoli automatici $OGGI

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
    git push origin main 2>&1 | tee -a "$LOG"
    echo "Articoli pubblicati su GitHub." | tee -a "$LOG"
fi

echo "=== $(date) - Pipeline completata ===" | tee -a "$LOG"
