# Setup Cloudflare Pages per analisitennis.it

Guida passo-passo per completare il deploy. Questo file va eseguito manualmente da Filippo perche' richiede autenticazione al tuo account Cloudflare.

## 1. Collega il dominio a Cloudflare

Se hai comprato il dominio su registrar diverso da Cloudflare:
1. Vai su [dash.cloudflare.com](https://dash.cloudflare.com) -> Add a site -> inserisci `analisitennis.it`
2. Scegli piano Free -> continua
3. Cloudflare ti dira' quali nameserver impostare (es. `kurt.ns.cloudflare.com`, `jade.ns.cloudflare.com`)
4. Vai dal tuo registrar (dove hai comprato il dominio) -> gestione DNS/nameserver -> sostituisci i nameserver attuali con quelli di Cloudflare
5. Aspetta propagazione DNS (da 10 minuti a qualche ora)

Se hai comprato il dominio su Cloudflare Registrar questo passaggio e' gia' automatico.

## 2. Crea repo GitHub

```bash
cd ~/analisitennis
gh repo create analisitennis --public --source=. --remote=origin --push
```

Se non hai `gh` CLI installato:
1. Vai su [github.com/new](https://github.com/new)
2. Nome repo: `analisitennis`, visibility: Public
3. NON inizializzarlo con README (ce l'abbiamo gia')
4. Dal terminale:
```bash
cd ~/analisitennis
git remote add origin https://github.com/TUO_USERNAME/analisitennis.git
git push -u origin main
```

## 3. Collega Cloudflare Pages al repo

1. Dashboard Cloudflare -> Workers & Pages -> Create -> Pages -> Connect to Git
2. Autorizza l'app GitHub (prima volta)
3. Seleziona repo `analisitennis`
4. Configurazione build:
   - **Framework preset**: Astro
   - **Build command**: `npm run build`
   - **Build output directory**: `dist`
   - **Root directory**: `/` (lascia vuoto)
5. Save and Deploy -> primo build parte, dura 2-3 minuti

## 4. Collega dominio custom

1. In Pages -> `analisitennis` project -> Custom domains -> Set up a custom domain
2. Inserisci `analisitennis.it` -> Continue
3. Cloudflare chiede di aggiungere il dominio al tuo account (se non l'hai gia' fatto allo step 1): segui il wizard
4. Attiva anche `www.analisitennis.it` come redirect
5. Attendi che SSL sia emesso (automatico, 1-5 min)

## 5. API Token per deploy GitHub Actions

Il workflow GitHub Actions che ho scritto ha bisogno di due secrets per deployare in automatico:

1. Cloudflare dashboard -> clic sul tuo profilo in alto a destra -> My Profile -> API Tokens -> Create Token
2. Usa il template **"Edit Cloudflare Workers"** -> Continue to summary -> Create Token
3. Copia il token (lo vedi solo una volta)
4. Prendi l'Account ID: dashboard sidebar sinistra, in basso -> copia l'Account ID

5. Vai su GitHub -> repo `analisitennis` -> Settings -> Secrets and variables -> Actions -> New repository secret
6. Aggiungi:
   - Nome: `CLOUDFLARE_API_TOKEN` -> valore: il token appena creato
   - Nome: `CLOUDFLARE_ACCOUNT_ID` -> valore: l'account ID

## 6. Buttondown (newsletter)

1. Crea account su [buttondown.email](https://buttondown.email)
2. Username suggerito: `analisitennis` (combacia con il form gia' integrato)
3. (Opzionale) Verifica il dominio di invio: analisitennis.it

Se usi un username diverso, aggiorna `src/components/FormEmail.astro` sostituendo `analisitennis` con il tuo username.

## 7. Verifica finale

- Vai su https://analisitennis.it -> deve caricare la homepage
- Vai su https://analisitennis.it/privacy -> privacy policy
- Vai su https://analisitennis.it/sitemap.xml -> sitemap XML
- Vai su https://analisitennis.it/articoli/2026-10-23-benvenuti -> articolo di benvenuto

## 8. Attiva pipeline giornaliera

```bash
cd ~/analisitennis/backend
cp .env.esempio .env
# Nel .env verifica che API_TENNIS_KEY sia corretta

# Installa Claude Code CLI (richiede il piano Max attivo)
~/.local/node/bin/npm install -g @anthropic-ai/claude-code
# Login al tuo account Claude:
~/.local/node/bin/claude login

# Attiva lo scheduler automatico 07:00
./install_schedule.sh
```

Dal giorno successivo, alle 07:00, lo scheduler esegue la pipeline e pubblica 2-3 articoli automatici.

## Troubleshooting

- Build fallisce su Cloudflare -> controlla che il package-lock.json sia committato
- Dominio non risolve -> controlla che i nameserver siano quelli di Cloudflare e aspetta propagazione DNS
- Articoli non si generano -> `~/analisitennis/backend/logs/daily_YYYY-MM-DD.log`

Per dubbi, scrivimi.
