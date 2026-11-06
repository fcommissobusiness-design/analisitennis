// Helper per hub giocatori e tornei: estrae entita' dagli articoli
// e produce slug + nome display + lista articoli associati.
// Lato Astro (SSG), gira a build time: nessun impatto runtime sul sito.

// Mappa autoritativa nomi abbreviati -> nome completo, esportata dal backend
// (attach_covers.NAME_MAP) in src/data/name-map.json da export_name_map.py.
// Importandola qui frontend e backend usano SEMPRE lo stesso slug per lo stesso
// giocatore: niente piu' profili duplicati tipo 'b-shelton' + 'ben-shelton'.
import NAME_MAP_BACKEND from '../data/name-map.json';

// Override/aggiunte locali al volo. Il backend (NAME_MAP_BACKEND) ha la
// precedenza: e' la fonte di verita' allineata alla generazione dei profili.
const FULL_NAMES_LOCAL = {
  'A. Fils': 'Arthur Fils',
  'J-L. Struff': 'Jan-Lennard Struff',
  'A. Molcan': 'Alex Molcan',
  'H. Medjedovic': 'Hamad Medjedovic',
  'A. Zakharova': 'Anastasia Zakharova',
  'R. Zhang': 'Shuai Zhang',
  'C. Moutet': 'Corentin Moutet',
  'T. Machac': 'Tomas Machac',
  'C. Wong Hong Yi': 'Cody Wong',
  'E. Jones': 'Emerson Jones',
  'D. Medvedev': 'Daniil Medvedev',
  'A. Bublik': 'Alexander Bublik',
  'D. Vallejo': 'Daniel Vallejo',
  'L. Sonego': 'Lorenzo Sonego',
  'D. Yastremska': 'Dayana Yastremska',
  'X. You': 'Xiaodi You',
  'E. Rybakina': 'Elena Rybakina',
  'D. Shnaider': 'Diana Shnaider',
  'E. S. Liang': 'En Shuo Liang',
  'T. Valentova': 'Tereza Valentova',
  'F. Cerundolo': 'Francisco Cerundolo',
  'T. Griekspoor': 'Tallon Griekspoor',
  'F. Cobolli': 'Flavio Cobolli',
  'L. Musetti': 'Lorenzo Musetti',
  'F. Marozsan': 'Fabian Marozsan',
  'H. Dart': 'Harriet Dart',
  'Y. Putintseva': 'Yulia Putintseva',
  'J. Fearnley': 'Jacob Fearnley',
  'P. Carreno-Busta': 'Pablo Carreno Busta',
  'K. Boulter': 'Katie Boulter',
  'K. Day': 'Kayla Day',
  'S. Zhang': 'Shuai Zhang',
  'L. Fruhvirtova': 'Linda Fruhvirtova',
  'K. Kawa': 'Katarzyna Kawa',
  'H. Kinoshita': 'Hina Kinoshita',
  'N. Basilashvili': 'Nikoloz Basilashvili',
  'S. Tsitsipas': 'Stefanos Tsitsipas',
  'T. A. Tirante': 'Thiago Agustin Tirante',
  'A. Mannarino': 'Adrian Mannarino',
  'V. Kopriva': 'Vit Kopriva',
  'L. Neumayer': 'Lukas Neumayer',
  'Xin. Wang': 'Xinyu Wang',
  'D. Kasatkina': 'Daria Kasatkina',
  // Allineati con NAME_MAP (giornata 28/10/2026 e big ricorrenti)
  'N. Djokovic': 'Novak Djokovic',
  'A. De Minaur': 'Alex de Minaur',
  'C. Ruud': 'Casper Ruud',
  'F. Tiafoe': 'Frances Tiafoe',
  'D. Shapovalov': 'Denis Shapovalov',
  'B. Nakashima': 'Brandon Nakashima',
  'U. Humbert': 'Ugo Humbert',
  'J. Mensik': 'Jakub Mensik',
  'L. Tien': 'Learner Tien',
  'J. Rodionov': 'Jurij Rodionov',
  'H. Hurkacz': 'Hubert Hurkacz',
  'H. Rune': 'Holger Rune',
  'T. Fritz': 'Taylor Fritz',
  'R. Hijikata': 'Rinky Hijikata',
  'N. Borges': 'Nuno Borges',
  'R. Bertola': 'Remy Bertola',
  'Y. Hanfmann': 'Yannick Hanfmann',
  'A. Eala': 'Alexandra Eala',
  'C. Alcaraz': 'Carlos Alcaraz',
  'A. Zverev': 'Alexander Zverev',
  'K. Khachanov': 'Karen Khachanov',
  'A. Rublev': 'Andrey Rublev',
  'T. Paul': 'Tommy Paul',
  'A. Rinderknech': 'Arthur Rinderknech',
  'A. Tabilo': 'Alejandro Tabilo',
  'A. Michelsen': 'Alex Michelsen',
  'C. Norrie': 'Cameron Norrie',
  'A. Davidovich Fokina': 'Alejandro Davidovich Fokina',
  'Z. Bergs': 'Zizou Bergs',
  'V. Williams': 'Venus Williams',
};

// Mappa effettiva: backend (fonte di verita') + override locali per nomi non
// ancora nel backend. Stesso input -> stesso slug ovunque nel sito.
export const FULL_NAMES = { ...FULL_NAMES_LOCAL, ...NAME_MAP_BACKEND };

export function slugify(s) {
  return (s || '')
    .toString()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/['’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
}

export function displayPlayerName(raw) {
  if (!raw) return '';
  return FULL_NAMES[raw] || raw;
}

// --- Aggancio nomi giocatore <-> righe classifica (robusto) ---
// L'API Tennis scrive i nomi in modo incoerente rispetto ai profili: ordine
// diverso ("Martin Etcheverry Tomas" vs "Tomas Martin Etcheverry"), cognomi
// multipli ("Carlos Alcaraz" vs "Carlos Alcaraz Garfia"), accenti e trattini
// ("Carreno-Busta" vs "Carreño Busta"). Un match esatto perdeva il ranking di
// giocatori di primo piano (Alcaraz n.3 incluso). Qui si confronta per token.
function nameTokens(s) {
  return new Set(
    (s || '').toString().normalize('NFKD').replace(/[̀-ͯ]/g, '')
      .toLowerCase().split(/[^a-z]+/).filter(t => t.length > 1)
  );
}

// Stesso giocatore se i token del nome piu' corto sono TUTTI contenuti nel piu'
// lungo e ne condividono almeno due (evita falsi positivi fra omonimi parziali
// come "Maria Sakkari" / "Maria Timofeeva").
export function samePlayer(a, b) {
  const ta = nameTokens(a), tb = nameTokens(b);
  if (!ta.size || !tb.size) return false;
  const [small, big] = ta.size <= tb.size ? [ta, tb] : [tb, ta];
  let shared = 0;
  for (const t of small) {
    if (big.has(t)) shared++;
    else return false;
  }
  return shared >= 2;
}

function _nrm(s) {
  return (s || '').toString().normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
}

// Stesso giocatore anche fra forma abbreviata ("J. Fonseca") ed estesa
// ("Joao Fonseca"): se un lato ha un solo cognome utile, basta il cognome in
// comune e l'iniziale del nome presente fra le iniziali dell'altro. Serve a
// collegare gli articoli (nomi abbreviati) ai profili creati da nome completo.
export function samePersonLoose(a, b) {
  const ta = nameTokens(a), tb = nameTokens(b);
  if (!ta.size || !tb.size) return false;
  const shared = [...ta].filter(t => tb.has(t));
  if (!shared.length) return false;
  if (ta.size >= 2 && tb.size >= 2) return samePlayer(a, b);
  const init = (s) => {
    const n = _nrm(s);
    return n ? n[0] : '';
  };
  const abbr = ta.size <= tb.size ? a : b;
  const full = ta.size <= tb.size ? b : a;
  const fullInitials = new Set([...nameTokens(full)].map(t => t[0]));
  return fullInitials.has(init(abbr));
}

// Slug del profilo che rappresenta questo giocatore, fra una lista di profili
// {slug, nome}: prima match esatto sullo slug calcolato, poi match per persona.
// Ritorna null se nessun profilo corrisponde.
export function resolveProfileSlug(rawName, profili) {
  const direct = playerSlug(rawName);
  for (const p of profili) if (p.slug === direct) return direct;
  const display = displayPlayerName(rawName);
  for (const p of profili) if (samePersonLoose(display, p.nome) || samePersonLoose(rawName, p.nome)) return p.slug;
  return null;
}

// Cerca il ranking di un giocatore nelle righe classifica ATP/WTA.
// Prima prova il match esatto sul nome completo, poi quello robusto per token.
export function findRanking(nome, righeAtp = [], righeWta = []) {
  const tutte = [
    ...righeWta.map(r => ({ r, tour: 'WTA' })),
    ...righeAtp.map(r => ({ r, tour: 'ATP' })),
  ];
  const n = _nrm(nome);
  for (const { r, tour } of tutte) {
    if (_nrm(r.player) === n) return { tour, place: r.place, points: r.points, player: r.player };
  }
  for (const { r, tour } of tutte) {
    if (samePlayer(nome, r.player)) return { tour, place: r.place, points: r.points, player: r.player };
  }
  return null;
}

export function playerSlug(raw) {
  return slugify(displayPlayerName(raw));
}

// Nomi italiani delle sedi, per allineare gli articoli ai profili torneo
// (il profilo dice "Basilea", l'articolo diceva "Basel").
const TOURNAMENT_LABELS = {
  'Basel': 'Basilea',
  'Paris': 'Parigi',
  'Brussels': 'Bruxelles',
  'Lisbon': 'Lisbona',
  'Florence': 'Firenze',
  'Lyon': 'Lione',
  'Queretaro': 'Querétaro',
  'Vienna': 'Vienna',
};

// Forma leggibile dal lettore: via il suffisso tecnico "- Qualification" che
// arriva grezzo dall'API, via il paese fra parentesi, poi nome italiano.
// NON usare per costruire slug: cambierebbe le URL gia' pubblicate.
export function tournamentDisplay(raw) {
  const base = tournamentKey(raw).replace(/\s*\([^)]*\)\s*$/, '').trim();
  return TOURNAMENT_LABELS[base] || base;
}

// Forma tecnica stabile usata per gli slug: toglie solo "- Qualification",
// esattamente come prima, cosi' "lyon-france-2026" resta "lyon-france-2026".
export function tournamentKey(raw) {
  return (raw || '').replace(/\s*-\s*Qualification$/i, '').trim();
}

// slug torneo include l'anno della data per permettere "vienna-2026" vs "vienna-2027"
export function tournamentSlug(raw, year) {
  return `${slugify(tournamentKey(raw))}-${year}`;
}

// Raccoglie i giocatori con conteggio e lista articoli.
export function collectPlayers(articoli) {
  const map = new Map();
  for (const art of articoli) {
    const names = [art.data.giocatore1, art.data.giocatore2].filter(Boolean);
    for (const raw of names) {
      if (raw === 'Redazione' || raw === 'Lettori') continue;
      const slug = playerSlug(raw);
      if (!slug) continue;
      if (!map.has(slug)) {
        map.set(slug, {
          slug,
          raw,
          display: displayPlayerName(raw),
          articoli: [],
        });
      }
      map.get(slug).articoli.push(art);
    }
  }
  for (const player of map.values()) {
    player.articoli.sort((a, b) => b.data.data.valueOf() - a.data.data.valueOf());
  }
  return [...map.values()].sort((a, b) =>
    b.articoli.length - a.articoli.length || a.display.localeCompare(b.display, 'it')
  );
}

// Raccoglie tornei (per anno) con lista articoli.
export function collectTournaments(articoli) {
  const map = new Map();
  for (const art of articoli) {
    const raw = art.data.torneo;
    if (!raw || raw === 'Editoriale') continue;
    const year = new Date(art.data.data).getFullYear();
    const slug = tournamentSlug(raw, year);
    const display = tournamentDisplay(raw);
    if (!map.has(slug)) {
      map.set(slug, {
        slug,
        raw,
        display,
        anno: year,
        articoli: [],
      });
    }
    map.get(slug).articoli.push(art);
  }
  for (const t of map.values()) {
    t.articoli.sort((a, b) => b.data.data.valueOf() - a.data.data.valueOf());
  }
  return [...map.values()].sort((a, b) =>
    b.anno - a.anno
    || b.articoli.length - a.articoli.length
    || a.display.localeCompare(b.display, 'it')
  );
}

export function playerBio(player) {
  if (!player || !player.articoli.length) return '';
  const tornei = [...new Set(player.articoli.map(a => tournamentDisplay(a.data.torneo)))].slice(0, 4);
  const cat = player.articoli[0].data.categoria;
  const n = player.articoli.length;
  return `Qui raccogliamo tutte le ${n === 1 ? 'nostre letture' : `${n} letture`} dedicate a ${player.display}, giocatore ${cat}, con uno sguardo a scontri diretti, forma recente e appuntamenti dei tornei principali${tornei.length ? ' (' + tornei.join(', ') + ')' : ''}.`;
}

export function tournamentBio(tournament) {
  if (!tournament || !tournament.articoli.length) return '';
  const n = tournament.articoli.length;
  const sup = tournament.articoli[0].data.superficie;
  const cat = tournament.articoli[0].data.categoria;
  return `Qui raccogliamo tutte le ${n === 1 ? 'nostre analisi' : `${n} analisi`} del torneo ${tournament.display} ${tournament.anno}, categoria ${cat} su ${sup}: pronostici, tabellone, forma dei protagonisti.`;
}
