# AnalisiTennis

Magazine editoriale di analisi tennis in italiano. Pubblica 2-3 articoli al giorno in modo automatico.

## Architettura

- **Frontend**: Astro + Cloudflare Pages (sito statico, veloce, SEO-first)
- **Backend**: pipeline Python che gira ogni giorno alle 07:00 su macOS (LaunchAgent). Fetch palinsesto da API Tennis, selezione match top, applicazione framework analitico KAKEGURUI FASE 1-4 + sanity anti-bias, riformulazione in prosa giornalistica, commit automatico
- **Newsletter**: integrazione Buttondown per iscrizioni
- **Deploy**: GitHub Actions → Cloudflare Pages su push su `main`

## Setup iniziale (una tantum)

### 1. Dominio e Cloudflare Pages
1. Compra `analisitennis.it` (consigliato Cloudflare Registrar: 11€/anno, DNS integrato)
2. Vai su dash.cloudflare.com → Workers & Pages → Create → Pages → Connect to Git
3. Collega questo repo GitHub, framework preset: Astro, branch main
4. Build command: `npm run build`, Output directory: `dist`
5. Aggiungi custom domain `analisitennis.it`

### 2. Secrets GitHub Actions
Aggiungi in Settings → Secrets:
- `CLOUDFLARE_API_TOKEN` (crea su dash.cloudflare.com/profile/api-tokens, template "Edit Cloudflare Workers")
- `CLOUDFLARE_ACCOUNT_ID` (sidebar dashboard)

### 3. Backend locale
```bash
cd backend
cp .env.esempio .env
# Modifica .env se serve
./install_schedule.sh
```

### 4. Buttondown newsletter
- Crea account su buttondown.email con username `analisitennis`
- (Opzionale) Metti API key in .env se vuoi gestire iscritti da script

### 5. Verifica locale
```bash
npm install
npm run dev
# Apri http://localhost:4321
```

## Esecuzione manuale pipeline
```bash
cd backend
./daily.sh
```

## Stato
- 23/10/2026: scaffold completo, pipeline backend scritta, scheduled task pronto
- Pending azione umana: compra dominio, collega Cloudflare, logo definitivo (Filippo lo fa generare da ChatGPT e lo inoltra)

## File chiave
- `src/layouts/Base.astro` - layout base con head SEO
- `src/pages/articoli/[...slug].astro` - template articolo singolo (schema SportsEvent + NewsArticle)
- `src/content/config.ts` - schema contenuto articoli
- `src/styles/global.css` - brand variables, swappabili quando arriva logo
- `backend/daily.sh` - orchestratore pipeline giornaliera
- `backend/generate_analysis.py` - invoca `claude` CLI con prompt pipeline FASE 1-4
- `backend/com.analisitennis.daily.plist` - LaunchAgent macOS 07:00
