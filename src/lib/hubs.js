// Helper per hub giocatori e tornei: estrae entita' dagli articoli
// e produce slug + nome display + lista articoli associati.
// Lato Astro (SSG), gira a build time: nessun impatto runtime sul sito.

// Mappa nomi abbreviati -> nome completo per display e SEO.
// Allineata (quando possibile) con backend/attach_covers.py:NAME_MAP.
export const FULL_NAMES = {
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
};

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

export function playerSlug(raw) {
  return slugify(displayPlayerName(raw));
}

export function tournamentDisplay(raw) {
  return (raw || '').replace(/\s*-\s*Qualification$/i, '').trim();
}

// slug torneo include l'anno della data per permettere "vienna-2026" vs "vienna-2027"
export function tournamentSlug(raw, year) {
  return `${slugify(tournamentDisplay(raw))}-${year}`;
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
