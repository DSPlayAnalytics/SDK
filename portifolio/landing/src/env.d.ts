/// <reference path="../.astro/types.d.ts" />
/// <reference types="astro/client" />

interface ImportMetaEnv {
  readonly PUBLIC_SITE_URL?: string;
  readonly PUBLIC_API_URL?: string;
  readonly PUBLIC_DASHBOARD_URL?: string;
  readonly PUBLIC_POS_LOGIN_URL?: string;
  readonly PUBLIC_PUBLISHABLE_KEY?: string;
  readonly PUBLIC_DEBUG?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
