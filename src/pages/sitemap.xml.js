import { getCollection } from 'astro:content';
import { isNoindexArticle } from '../lib/noindex.js';
import h2hData from '../data/h2h.json';
import profilesEn from '../data/profiles-en.json';

export async function GET(context) {
  // noindex esclusi dalla sitemap: Google non deve ricevere un segnale "indicizza"
  // (sitemap) in contraddizione col meta robots noindex sulla pagina. isNoindexArticle
  // copre sia il noindex di qualita' (frontmatter) sia la regola eta' 30gg (pronostici).
  const articoli = await getCollection('articoli', ({ data }) => data.pubblicato !== false && !isNoindexArticle(data));
  const profiliGiocatori = await getCollection('giocatori-profilo', ({ data }) => data.pubblicato !== false);
  const profiliTornei = await getCollection('tornei-profilo', ({ data }) => data.pubblicato !== false);
  const guide = await getCollection('guide', ({ data }) => data.pubblicato !== false);
  const news = await getCollection('news', ({ data }) => data.pubblicato !== false);

  const site = context.site?.toString().replace(/\/$/, '') || 'https://analisitennis.it';
  const today = new Date().toISOString().split('T')[0];

  const statiche = [
    '', '/oggi', '/pronostici', '/calendario', '/chi-siamo', '/contatti', '/privacy', '/cookie',
    '/categoria/atp', '/categoria/wta', '/categoria/slam',
    '/categoria/challenger', '/categoria/masters', '/categoria/itf',
    '/giocatori', '/italiani', '/news', '/tornei', '/guide', '/tag', '/metodo',
    '/classifica-atp', '/classifica-wta',
  ];

  const urls = [
    ...statiche.map(p => ({
      loc: `${site}${p}`,
      changefreq: p === '' ? 'daily' : 'weekly',
      priority: p === '' ? '1.0' : '0.6',
      lastmod: today,
    })),
    ...guide.map(g => ({
      loc: `${site}/guide/${g.slug}`,
      lastmod: today,
      changefreq: 'monthly',
      priority: '0.6',
    })),
    ...news.map(nw => ({
      loc: `${site}/news/${nw.slug}`,
      lastmod: (nw.data.generato_il?.slice(0, 10)) || today,
      changefreq: 'daily',
      priority: '0.7',
    })),
    ...Object.keys(h2hData).map(coppia => ({
      loc: `${site}/scontri-diretti/${coppia}`,
      lastmod: today,
      changefreq: 'weekly',
      priority: '0.6',
    })),
    {
      loc: `${site}/en`,
      lastmod: today,
      changefreq: 'weekly',
      priority: '0.6',
    },
    ...Object.keys(profilesEn).map(slug => ({
      loc: `${site}/en/players/${slug}`,
      lastmod: today,
      changefreq: 'weekly',
      priority: '0.7',
    })),
    ...profiliGiocatori.map(p => ({
      loc: `${site}/giocatori/${p.data.slug_profilo}`,
      lastmod: (p.data.generato_il?.slice(0, 10)) || today,
      changefreq: 'weekly',
      priority: '0.7',
    })),
    ...profiliTornei.map(t => ({
      loc: `${site}/tornei/${t.data.slug_profilo}`,
      lastmod: (t.data.generato_il?.slice(0, 10)) || today,
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
