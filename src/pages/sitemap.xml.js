import { getCollection } from 'astro:content';

export async function GET(context) {
  const articoli = await getCollection('articoli', ({ data }) => data.pubblicato !== false);
  const site = context.site?.toString().replace(/\/$/, '') || 'https://analisitennis.it';

  const statiche = [
    '', '/chi-siamo', '/contatti', '/privacy', '/cookie',
    '/categoria/atp', '/categoria/wta', '/categoria/slam',
    '/categoria/challenger', '/categoria/masters', '/categoria/itf'
  ];

  const urls = [
    ...statiche.map(p => ({
      loc: `${site}${p}`,
      changefreq: p === '' ? 'daily' : 'weekly',
      priority: p === '' ? '1.0' : '0.6'
    })),
    ...articoli.map(a => ({
      loc: `${site}/articoli/${a.slug}`,
      lastmod: new Date(a.data.data).toISOString().split('T')[0],
      changefreq: 'weekly',
      priority: '0.8'
    }))
  ];

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map(u => `  <url>
    <loc>${u.loc}</loc>${u.lastmod ? `
    <lastmod>${u.lastmod}</lastmod>` : ''}
    <changefreq>${u.changefreq}</changefreq>
    <priority>${u.priority}</priority>
  </url>`).join('\n')}
</urlset>`;

  return new Response(xml, { headers: { 'Content-Type': 'application/xml' } });
}
