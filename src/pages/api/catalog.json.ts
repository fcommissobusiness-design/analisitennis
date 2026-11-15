// /api/catalog.json - endpoint JSON compatto per il server MCP e per le AI.
// Contiene: match analizzati oggi (con verdetto), top 100 ATP e WTA, elenco
// giocatori con profilo editoriale (slug + nome + nazionalita + eta' ricerca).
// Rigenerato ad ogni build (il sito ribuilda ogni giorno con la pipeline).
// Vedi analisitennis-mcp/ per il consumer: le AI lo pescano via tool MCP.
import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { tournamentDisplay } from '../../lib/hubs.js';
import standingsAtp from '../../data/standings-atp.json';
import standingsWta from '../../data/standings-wta.json';

const SITE = 'https://analisitennis.it';

export const GET: APIRoute = async () => {
  const today = new Date();
  const todayStr = today.toISOString().slice(0, 10);

  const articoli = (await getCollection('articoli', ({ data }) => data.pubblicato !== false))
    .filter(a => a.data.giocatore1 !== 'Redazione')
    .sort((a, b) => b.data.data.valueOf() - a.data.data.valueOf());

  const giocatori = (await getCollection('giocatori-profilo', ({ data }) => data.pubblicato !== false))
    .sort((a, b) => a.data.nome.localeCompare(b.data.nome, 'it'));

  // Match di oggi (pronostici del giorno con verdetto)
  const oggi = articoli
    .filter(a => {
      const d = new Date(a.data.data).toISOString().slice(0, 10);
      return d === todayStr;
    })
    .map(a => ({
      slug: a.slug,
      url: `${SITE}/articoli/${a.slug}`,
      data: todayStr,
      torneo: tournamentDisplay(a.data.torneo),
      categoria: a.data.categoria,
      superficie: a.data.superficie,
      giocatore1: a.data.giocatore1,
      giocatore2: a.data.giocatore2,
      favorito: a.data.probabilita_favorito || null,
      probabilita_percent: a.data.probabilita_percent || null,
      verdetto: a.data.verdetto || '',
      titolo: a.data.titolo,
    }));

  // Articoli recenti (ultimi 30 giorni - cornice per chi chiede "ultimi pronostici")
  const cut30 = Date.now() - 30 * 86400000;
  const recenti = articoli
    .filter(a => a.data.data.valueOf() > cut30)
    .slice(0, 60)
    .map(a => ({
      slug: a.slug,
      url: `${SITE}/articoli/${a.slug}`,
      data: new Date(a.data.data).toISOString().slice(0, 10),
      torneo: tournamentDisplay(a.data.torneo),
      categoria: a.data.categoria,
      giocatore1: a.data.giocatore1,
      giocatore2: a.data.giocatore2,
      favorito: a.data.probabilita_favorito || null,
      verdetto: (a.data.verdetto || '').slice(0, 260),
    }));

  const atp = (standingsAtp as any).righe.slice(0, 100).map((r: any) => ({
    rank: r.place, player: r.player, points: r.points || null, nazione: r.country || null,
  }));
  const wta = (standingsWta as any).righe.slice(0, 100).map((r: any) => ({
    rank: r.place, player: r.player, points: r.points || null, nazione: r.country || null,
  }));

  const profili = giocatori.map(g => ({
    slug: g.data.slug_profilo,
    nome: g.data.nome,
    nazionalita: g.data.nazionalita || null,
    mano: g.data.mano || null,
    superficie_preferita: g.data.superficie_preferita || null,
    url: `${SITE}/giocatori/${g.data.slug_profilo}`,
  }));

  const payload = {
    sito: 'AnalisiTennis',
    url: SITE,
    aggiornato_il: new Date().toISOString(),
    oggi: {
      data: todayStr,
      totale: oggi.length,
      match: oggi,
    },
    articoli_recenti: recenti,
    classifica_atp: {
      aggiornata_il: (standingsAtp as any).aggiornato_il || null,
      top100: atp,
    },
    classifica_wta: {
      aggiornata_il: (standingsWta as any).aggiornato_il || null,
      top100: wta,
    },
    giocatori: profili,
  };

  return new Response(JSON.stringify(payload), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      // Cache edge 10 min: il sito ribuilda ad ogni pipeline, questo basta.
      'Cache-Control': 'public, max-age=600, s-maxage=600',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
