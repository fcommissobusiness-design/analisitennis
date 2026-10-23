# AnalisiTennis - Backend pipeline

Pipeline che ogni giorno alle 07:00 genera 2-3 articoli di analisi tennis e li pubblica sul sito.

## Flusso
1. `fetch_fixtures.py` - recupera il palinsesto del giorno da API Tennis
2. `select_matches.py` - sceglie i 2-3 match top (ATP/WTA 500+ priorità, nomi noti, orari comodi)
3. `generate_analysis.py` - per ogni match applica FASE 1-2-3-4 KAKEGURUI + sanity anti-bias
4. `write_article.py` - riformula in prosa giornalistica (regole output non negoziabili) e scrive markdown in `src/content/articoli/`
5. `git_publish.sh` - commit + push → GitHub Actions → Cloudflare Pages deploy

## Esecuzione
```bash
cd ~/analisitennis/backend
./daily.sh
```

## Scheduled task
LaunchAgent `com.analisitennis.daily.plist` installato in `~/Library/LaunchAgents/` (vedi `install_schedule.sh`).

## Dipendenze
- Python 3.11+
- `requests`, `python-frontmatter`, `pyyaml`
- `claude` CLI (già installato con il piano Max di Filippo)
- `git`, `gh` CLI configurato

## Env richieste (in `.env`)
- `API_TENNIS_KEY` - già disponibile nel progetto tennis-engine-stage2
- `BUTTONDOWN_API_KEY` - solo per newsletter signup (non per pipeline articoli)
