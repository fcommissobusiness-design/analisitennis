import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://analisitennis.it',
  trailingSlash: 'never',
  build: {
    format: 'file'
  },
  markdown: {
    shikiConfig: { theme: 'github-light' }
  }
});
