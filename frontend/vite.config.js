import { defineConfig } from 'vite';

// AI 求职陪跑前端 — Vite 配置（v4.0）
// 开发态：:5173 代理 /api /ws /upload 到 FastAPI（:8000），前后端并行开发
// 生产态：vite build 产出 frontend/dist/，由 FastAPI 静态托管
export default defineConfig({
  root: '.',
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
      '/upload': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    // v7.5: 报告分享与招聘端已删除，回归单入口 index.html（见 CHARTER DC-08）。
  },
});
