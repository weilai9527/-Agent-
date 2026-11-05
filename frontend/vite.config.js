import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

const projectRoot = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root: projectRoot,
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    allowedHosts: ['freckles-flying-patio.ngrok-free.dev'],
    proxy: {
      // 证书服务可返回同源验真链接。开发服务器和 preview 只向公开只读进程转发精确的 GET。
      '^/verify/[0-9a-f]{32}$': {
        target: process.env.VITE_CREDENTIALS_PUBLIC_PROXY_TARGET || 'http://127.0.0.1:8113',
        changeOrigin: true,
        bypass(req) {
          if (req.method !== 'GET' || req.headers['transfer-encoding'] ||
              (req.headers['content-length'] && req.headers['content-length'] !== '0')) return false;
        },
        configure(proxy) {
          proxy.on('proxyReq', (req) => {
            // 验真只依赖链接中的随机序号，登录 cookie、来源页和调用方自报身份都不能发往公开服务。
            for (const name of req.getHeaderNames()) {
              if (!['host', 'accept', 'accept-language', 'accept-encoding'].includes(name)) req.removeHeader(name);
            }
          });
          proxy.on('proxyRes', (res) => { delete res.headers['set-cookie']; });
        },
      },
      '/api': process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:3001',
      '/ws': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:3001',
        ws: true,
      },
    },
  },
});
