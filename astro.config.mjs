import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

const site = process.env.PUBLIC_SITE_URL || 'https://dsplayground.com.br';

// Tailwind 4 via plugin Vite (substitui @astrojs/tailwind, deprecated em
// Astro 5+). applyBaseStyles passa a ser papel do @import "tailwindcss"
// no global.css — sem flag aqui.
export default defineConfig({
  site,
  output: 'static',
  trailingSlash: 'never',
  vite: {
    plugins: [tailwindcss()],
  },
  build: {
    inlineStylesheets: 'auto',
  },
});
