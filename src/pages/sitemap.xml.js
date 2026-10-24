import { getCollection } from 'astro:content';
import { collectPlayers, collectTournaments } from '../lib/hubs.js';

export async function GET(context) {
  const articoli = await getCollection('articoli', ({ data }) => data.pubblicato !== false);
  const site = context.site?.toString().replace(/\/$/, '') || 'https://analisitennis.it';
  const today = new Date().toISOString().split('T')[0];

  const statiche = [
    '', '/chi-siamo', '/contatti', '/privacy', '/cookie',
    '/categoria/atp', '/categoria/wta', '/categoria/slam',
    '/categoria/challenger', '/categoria/masters', '/categoria/itf',
    '/giocatori', '/tornei',
  ];

  const giocatori = collectPlayers(articoli);
  const tornei = collectTournaments(articoli);

  const urls = [
    ...statiche.map(p => ({
      loc: `${site}${p}`,
      changefreq: p === '' ? 'daily' : 'weekly',
      priority: p === '' ? '1.0' : '0.6',
      lastmod: today,
    })),
    ...giocatori.map(p => ({
      loc: `${site}/giocatori/${p.slug}`,
      lastmod: new Date(p.articoli[0].data.data).toISOString().split('T')[0],
      changefreq: 'weekly',
      priority: '0.7',
    })),
    ...tornei.map(t => ({
      loc: `${site}/tornei/${t.slug}`,
      lastmod: new Date(t.articoli[0].data.data).toISOString().split('T')[0],
      changefreq: 'weekly',
      priority: '0.7',
    })),
    ...articoli.map(a => ({
      loc: `${site}/articoli/${a.slug}`,
      lastmod: new Date(a.data.data).toISOString().split('T')[0],
      changefreq: 'weekly',
      priority: '0.8',
    })),
  ];

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map(u => `  <url>
    <loc>${u.loc}</loc>
    <lastmod>${u.lastmod}</lastmod>
    <changefreq>${u.changefreq}</changefreq>
    <priority>${u.priority}</priority>
  </url>`).join('\n')}
</urlset>`;

  return new Response(xml, { headers: { 'Content-Type': 'application/xml' } });
}
