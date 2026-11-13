// Impronta del deploy: espone a /version.txt lo SHA del commit da cui il sito
// e' stato buildato. Serve al controllo automatico post-push (health check su
// GitHub Actions) per verificare che il deploy Cloudflare Workers Builds sia
// andato live. Valore catturato a BUILD TIME.
//
// Cloudflare Workers Builds espone WORKERS_CI_COMMIT_SHA durante `npm run build`.
// Fallback: variabili comuni, poi git locale (build in locale), poi 'unknown'.
import { execSync } from 'node:child_process';

function commitSha() {
  const fromEnv =
    process.env.WORKERS_CI_COMMIT_SHA ||
    process.env.CF_PAGES_COMMIT_SHA ||
    process.env.GITHUB_SHA ||
    process.env.COMMIT_SHA;
  if (fromEnv) return fromEnv.trim();
  try {
    return execSync('git rev-parse HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim();
  } catch {
    return 'unknown';
  }
}

export async function GET() {
  const body = commitSha() + '\n';
  return new Response(body, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'no-store, max-age=0',
    },
  });
}
