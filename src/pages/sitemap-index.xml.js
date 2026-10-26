// Sitemap-index: aggrega sitemap.xml (contenuti permanenti) e sitemap-news.xml
// (articoli ultime 48h). Google raccomanda un indice quando si hanno piu'
// sitemap, cosi' basta aggiungere una sola URL in Search Console.
export async function GET(context) {
  const site = context.site?.toString().replace(/\/$/, '') || 'https://analisitennis.it';
  const today = new Date().toISOString().split('T')[0];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>${site}/sitemap.xml</loc>
    <lastmod>${today}</lastmod>
  </sitemap>
  <sitemap>
    <loc>${site}/sitemap-news.xml</loc>
    <lastmod>${today}</lastmod>
  </sitemap>
</sitemapindex>`;
  return new Response(xml, { headers: { 'Content-Type': 'application/xml' } });
}
