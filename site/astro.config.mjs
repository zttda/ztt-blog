// @ts-check

import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
	site: 'https://www.200302.xyz',
	integrations: [mdx(), sitemap({ filter: (page) => !page.endsWith('/style-lab/') })],
	vite: {
		build: {
			// Keep shared interaction scripts cacheable instead of repeating them in every HTML page.
			assetsInlineLimit: 0,
		},
	},
});
