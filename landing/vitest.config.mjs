// Usa `getViteConfig` do astro pra que vitest entenda imports `.astro`
// (atraves do plugin Astro). Sem isso, qualquer test que importe um
// componente Astro estoura `Failed to parse source for import analysis`.
import { getViteConfig } from 'astro/config';

export default getViteConfig({
  test: {
    environment: 'node',
    globals: true,
    include: ['src/**/*.test.ts'],
  },
});
