import { defineConfig } from 'vite';
import { resolve } from 'node:path';
export default defineConfig({
  base: '/dashboard-static/',
  optimizeDeps: { exclude: ['maplibre-gl'] },
  server: {
    proxy: {
      '/__demo_page': {
        target: 'http://127.0.0.1:5188',
        rewrite: (path) => path.replace('/__demo_page', '/'),
      },
      '/dashboard-api': 'http://127.0.0.1:5188',
      '/dashboard/demo': 'http://127.0.0.1:5188',
      '/save': 'http://127.0.0.1:5188',
      '/sample.csv': 'http://127.0.0.1:5188',
    },
  },
  build: {
    outDir: resolve(import.meta.dirname, '../ckanext/dashboard_view/public/dashboard'),
    emptyOutDir: true,
    target: 'es2022',
    cssCodeSplit: false,
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      input: resolve(import.meta.dirname, 'src/main.ts'),
      output: {
        entryFileNames: 'dashboard.js',
        chunkFileNames: 'dashboard-[name]-[hash].js',
        assetFileNames: 'dashboard[extname]',
      },
    },
  },
  worker: { format: 'es', rollupOptions: { output: { entryFileNames: 'dashboard-worker.js' } } },
});
