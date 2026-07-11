import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

function readList(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:3001';
  const allowedHosts = readList(env.VITE_ALLOWED_HOSTS);

  return {
    plugins: [react()],
    server: {
      host: env.VITE_DEV_HOST || '127.0.0.1',
      allowedHosts,
      proxy: {
        '/api': proxyTarget,
        '/ws': {
          target: proxyTarget,
          ws: true,
        },
      },
    },
  };
});
