// Sitemap immagini: espone le cover (articoli + profili torneo) a Google
// Immagini. Ora che ogni cover ha un alt descrittivo, questo apre un canale
// di traffico aggiuntivo. Formato ufficiale image-sitemap (solo image:loc,
// gli altri tag sono ignorati da Google dal 2022).
import { getCollection } from 'astro:content';

export async function GET(context) {
  const site = context.site?.toString().replace(/\/$/, '') || 'https://analisitennis.it';

  const articoli = await getCollection('articoli', ({ data }) => data.pubblicato !== false && data.noindex !== true);
  const profiliTornei = await getCollection('tornei-profilo', ({ data }) => data.pubblicato !== false);
  const profiliGiocatori = await getCollection('giocatori-profilo', ({ data }) => data.pubblicato !== false);

  const esc = s => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const entries = [];
  for (const a of articoli) {
    if (!a.data.cover_image) continue;
    entries.push({ page: `${site}/articoli/${a.slug}`, img: `${site}${a.data.cover_image}` });
  }
  for (const t of profiliTornei) {
    if (!t.data.cover_image) continue;
    entries.push({ page: `${site}/tornei/${t.data.slug_profilo}`, img: `${site}${t.data.cover_image}` });
  }
  for (const p of profiliGiocatori) {
    if (!p.data.cover_image) continue;
    entries.push({ page: `${site}/giocatori/${p.data.slug_profilo}`, img: `${site}${p.data.cover_image}` });
  }

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
${entries.map(e => `  <url>
    <loc>${esc(e.page)}</loc>
    <image:image>
      <image:loc>${esc(e.img)}</image:loc>
    </image:image>
  </url>`).join('\n')}
</urlset>`;

  return new Response(xml, { headers: { 'Content-Type': 'application/xml' } });
}
