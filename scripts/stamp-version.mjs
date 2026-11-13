// Prebuild: scrive public/version.txt con lo SHA del commit da cui il sito
// viene buildato. Gira in Node PRIMA di `astro build`, quindi il file finisce
// tra gli asset statici (public/ -> dist/) e NON viene mai impacchettato nel
// Worker Cloudflare: zero problemi col runtime (niente node:child_process nel
// bundle del Worker). Serve al controllo automatico post-push (health check su
// GitHub Actions) per verificare che il deploy sia andato davvero live.
import { execSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = resolve(root, 'public', 'version.txt');

function commitSha() {
  // 1) Variabili d'ambiente note (Cloudflare Workers Builds, GitHub, ecc.)
  const fromEnv =
    process.env.WORKERS_CI_COMMIT_SHA ||
    process.env.CF_PAGES_COMMIT_SHA ||
    process.env.GITHUB_SHA ||
    process.env.COMMIT_SHA;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();
  // 2) git locale (presente anche nel container di build Cloudflare, che clona il repo)
  try {
    return execSync('git rev-parse HEAD', { cwd: root, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim();
  } catch {
    return 'unknown';
  }
}

const sha = commitSha();
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, sha + '\n', 'utf8');
console.log(`[stamp-version] public/version.txt = ${sha}`);
