// Rehype plugin: linka automaticamente la PRIMA menzione nel corpo di un
// articolo ai relativi hub. Giocatori (nome completo) -> /giocatori/<slug>,
// tornei (citta' italiana) -> /tornei/<slug>. Gira solo a build time e SOLO
// sui file in src/content/articoli/ (profili e guide restano intatti).
//
// Scopo SEO: distribuire link-equity interna verso le pagine profilo, che
// sono il motore delle impression. Linka la PRIMA occorrenza di ogni entita'
// (una sola volta per articolo) per non appesantire ne' diluire.
//
// Nessuna dipendenza esterna: cammino manuale sull'albero HAST.
import fs from 'node:fs';
import path from 'node:path';

const SKIP_TAGS = new Set(['a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'code', 'pre']);

function parseFrontmatter(txt) {
  const m = txt.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  return m ? m[1] : '';
}
function field(fm, name) {
  const m = fm.match(new RegExp(`^${name}:\\s*["']?(.+?)["']?\\s*$`, 'm'));
  return m ? m[1].trim() : '';
}

// Carica le entita' linkabili dai profili esistenti (= link che risolvono,
// niente 404). Cache globale per l'intera build.
function loadEntities() {
  const root = path.resolve('src/content');
  const entries = [];

  const pdir = path.join(root, 'giocatori-profilo');
  if (fs.existsSync(pdir)) {
    for (const f of fs.readdirSync(pdir)) {
      if (!f.endsWith('.md')) continue;
      const fm = parseFrontmatter(fs.readFileSync(path.join(pdir, f), 'utf8'));
      if (/^pubblicato:\s*false/m.test(fm)) continue;
      const nome = field(fm, 'nome');
      const slug = field(fm, 'slug_profilo');
      // Richiede nome completo (con spazio): evita match su parola singola.
      if (nome && slug && nome.includes(' ')) {
        entries.push({ text: nome, url: `/giocatori/${slug}` });
      }
    }
  }

  const tdir = path.join(root, 'tornei-profilo');
  const cityBest = new Map(); // citta' -> {anno, slug}: tiene l'anno piu' recente
  if (fs.existsSync(tdir)) {
    for (const f of fs.readdirSync(tdir)) {
      if (!f.endsWith('.md')) continue;
      const fm = parseFrontmatter(fs.readFileSync(path.join(tdir, f), 'utf8'));
      if (/^pubblicato:\s*false/m.test(fm)) continue;
      const citta = field(fm, 'citta');
      const slug = field(fm, 'slug_profilo');
      const anno = parseInt(field(fm, 'anno') || '0', 10);
      if (citta && slug) {
        const prev = cityBest.get(citta);
        if (!prev || anno > prev.anno) cityBest.set(citta, { anno, slug });
      }
    }
  }
  for (const [citta, v] of cityBest) entries.push({ text: citta, url: `/tornei/${v.slug}` });

  // Match piu' lunghi prima: "Linda Fruhvirtova" prima di qualunque sottostringa.
  entries.sort((a, b) => b.text.length - a.text.length);
  return entries;
}

let ENTITIES = null;
let NOME_TO_SLUG = null; // nome completo giocatore -> slug_profilo reale
let NAME_MAP = null;     // nome abbreviato API -> nome completo

function loadNameToSlug() {
  const root = path.resolve('src/content');
  const map = new Map();
  const pdir = path.join(root, 'giocatori-profilo');
  if (fs.existsSync(pdir)) {
    for (const f of fs.readdirSync(pdir)) {
      if (!f.endsWith('.md')) continue;
      const fm = parseFrontmatter(fs.readFileSync(path.join(pdir, f), 'utf8'));
      if (/^pubblicato:\s*false/m.test(fm)) continue;
      const nome = field(fm, 'nome');
      const slug = field(fm, 'slug_profilo');
      if (nome && slug) map.set(nome, slug);
    }
  }
  return map;
}
function loadNameMap() {
  try { return JSON.parse(fs.readFileSync(path.resolve('src/data/name-map.json'), 'utf8')); }
  catch { return {}; }
}

// Target extra per QUESTO articolo: i due protagonisti linkati per cognome,
// risolti dal frontmatter. Zero ambiguita' (sappiamo di chi parla il pezzo),
// quindi e' sicuro linkare anche cognomi che altrove sarebbero parole comuni.
function perFileTargets(srcPath) {
  const fm = parseFrontmatter(fs.readFileSync(srcPath, 'utf8'));
  const out = [];
  for (const key of ['giocatore1', 'giocatore2']) {
    const raw = field(fm, key);
    if (!raw || raw === 'Redazione' || raw === 'Lettori') continue;
    const display = NAME_MAP[raw] || raw;
    const slug = NOME_TO_SLUG.get(display);
    if (!slug) continue;
    const parts = display.split(/\s+/);
    if (parts.length >= 2) {
      out.push({ text: parts.slice(1).join(' '), url: `/giocatori/${slug}` });
    }
  }
  return out;
}

export default function rehypeAutolink() {
  return (tree, file) => {
    const p = ((file && (file.path || (file.history && file.history[0]))) || '').replace(/\\/g, '/');
    // Solo articoli: profili e guide non devono auto-linkare (eviti self-link).
    if (!p.includes('/content/articoli/')) return;

    if (!ENTITIES) ENTITIES = loadEntities();
    if (!NOME_TO_SLUG) NOME_TO_SLUG = loadNameToSlug();
    if (!NAME_MAP) NAME_MAP = loadNameMap();
    if (!ENTITIES.length) return;

    // Lista di questo articolo: entita' globali + cognomi dei 2 protagonisti.
    // Match piu' lunghi prima (full name batte cognome).
    const perFile = perFileTargets(p);
    const targets = [...ENTITIES, ...perFile].sort((a, b) => b.text.length - a.text.length);

    const used = new Set(); // una sola occorrenza per URL, per articolo
    const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    function linkText(value) {
      // Trova il match piu' a sinistra tra tutte le entita' non ancora usate.
      let best = null;
      for (const ent of targets) {
        if (used.has(ent.url)) continue;
        const re = new RegExp(`(^|[^\\p{L}\\p{N}])(${esc(ent.text)})(?![\\p{L}\\p{N}])`, 'u');
        const m = re.exec(value);
        if (m) {
          const at = m.index + m[1].length;
          if (!best || at < best.at) best = { at, len: ent.text.length, url: ent.url };
        }
      }
      if (!best) return null;
      used.add(best.url);
      const before = value.slice(0, best.at);
      const matched = value.slice(best.at, best.at + best.len);
      const after = value.slice(best.at + best.len);
      const nodes = [];
      if (before) nodes.push({ type: 'text', value: before });
      nodes.push({
        type: 'element',
        tagName: 'a',
        properties: { href: best.url, class: 'auto-link' },
        children: [{ type: 'text', value: matched }],
      });
      const rest = linkText(after);
      if (rest) nodes.push(...rest);
      else if (after) nodes.push({ type: 'text', value: after });
      return nodes;
    }

    function walk(node, insideSkip) {
      if (!node.children) return;
      for (let i = 0; i < node.children.length; i++) {
        const child = node.children[i];
        if (child.type === 'element') {
          walk(child, insideSkip || SKIP_TAGS.has(child.tagName));
        } else if (child.type === 'text' && !insideSkip) {
          const replaced = linkText(child.value);
          if (replaced) {
            node.children.splice(i, 1, ...replaced);
            i += replaced.length - 1;
          }
        }
      }
    }

    walk(tree, false);
  };
}
