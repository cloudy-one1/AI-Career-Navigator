// ===================================================
// main.js — Vite 入口（v4.0）
// 承接 app.js 的初始化职责，并注入全局 Chart（兼容
// report.js / liveRadar.js 对 CDN 全局 Chart 的引用）。
// ===================================================

import Chart from 'chart.js/auto';
window.Chart = Chart;

import './js/themeToggle.js'; // v5.0 双风格切换（米色 / 深色 + 语义色）
import './js/app.js';
