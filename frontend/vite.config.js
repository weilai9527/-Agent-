import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    allowedHosts: ['freckles-flying-patio.ngrok-free.dev'],
    proxy: {
      '/api': process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:3001',
      '/ws': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:3001',
        ws: true,
      },
    },
  },
});
