import { defineConfig } from 'vite';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// AI 求职领航前端 — Vite 配置（v4.0）
// 开发态：:5173 代理 /api /ws /upload 到 FastAPI（:8000），前后端并行开发
// 生产态：vite build 产出 frontend/dist/，由 FastAPI 静态托管
// v8.2: 多入口——index.html（主功能 SPA）与 landing.html（独立产品主页）
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
    // v8.2: landing 页独立为单独 HTML 入口，与主功能 SPA（index.html）并列构建。
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
        landing: path.resolve(__dirname, 'landing.html'),
      },
    },
    // 报告分享与招聘端已删除，回归单入口 index.html。
    // v8.0: 中国地图 GeoJSON（src/assets/china-geo.json，约 0.55MB）是数据资产而非代码，
    //       已通过动态 import() 拆成独立的懒加载 chunk，不进主包（仅在打开
    //       「数据分析」视图需要渲染地图时才拉取）。这里放宽告警阈值，避免它
    //       掩盖其它真正需要拆分的 chunk——超过 700kB 仍会告警。
    // v8.6: three.js（约 735KB min / 190KB gzip）经 landing.js 动态 import()
    //       拆为独立 async chunk，仅 landing.html 在首屏渲染后按需拉取，
    //       主应用包（385KB）不受影响。告警阈值放宽到 800kB 以容纳它，
    //       其余 chunk 超过 800kB 仍会告警。
    chunkSizeWarningLimit: 800,
  },
});
