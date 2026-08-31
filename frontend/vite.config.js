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
    // v7.0: 多入口——share.html（招聘端只读报告页）与 index.html 并列。
    // 不加这条的话 Vite 只打包 index.html，构建产物里没有 share.html，
    // FastAPI 的 /share/{token} 路由在 dist 托管模式下会 404。
    rollupOptions: {
      input: {
        main: 'index.html',
        share: 'share.html',
      },
    },
  },
});
