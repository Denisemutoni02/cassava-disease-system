import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

// Online-only PWA: the service worker caches ONLY the app shell.
// All diagnosis, advice and map data are fetched live over the network.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/apple-touch-icon.png', 'icons/*.png'],
      manifest: {
        name: 'CassavaGuard — Leaf Disease Detection',
        short_name: 'CassavaGuard',
        description:
          'Detect cassava mosaic (CMD) and brown streak (CBSD) disease from a leaf photo. Requires internet.',
        theme_color: '#1b5e20',
        background_color: '#f5f5f0',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      workbox: {
        // App shell only — never cache API responses (online-only system)
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest}'],
        navigateFallback: '/index.html',
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    port: 5173,
    strictPort: true, // fail loudly if 5173 is taken instead of silently moving
    host: true,
  },
});
