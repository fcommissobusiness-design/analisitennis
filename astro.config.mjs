import { defineConfig } from 'astro/config';
import rehypeAutolink from './src/lib/rehype-autolink.mjs';

export default defineConfig({
  site: 'https://analisitennis.it',
  trailingSlash: 'never',
  build: {
    format: 'file'
  },
  markdown: {
    shikiConfig: { theme: 'github-light' },
    rehypePlugins: [rehypeAutolink]
  }
});
