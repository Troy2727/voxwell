import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Relative base so the built index.html loads from app://voxwell inside Electron.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: { port: 5173, strictPort: true },
  build: {
    rollupOptions: {
      input: { main: path.resolve(__dirname, 'index.html'), overlay: path.resolve(__dirname, 'overlay.html') },
    },
  },
});
