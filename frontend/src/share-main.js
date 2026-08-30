// ===================================================
// share-main.js — Vite 入口（v7.0 招聘端分享页）
// 与 main.js 同构：注入全局 Chart + 挂载只读报告渲染。
//
// 为什么单独一个入口而不是复用 main.js：分享页的读者是外部 HR，
// 不该把主应用的 app.js（导航/面试/历史等全部面板初始化）一并打包进去——
// 多入口让分享页只携带它需要的那几个模块。
// ===================================================

import Chart from 'chart.js/auto';
window.Chart = Chart;

import { initSharedReport } from './js/shareReport.js';
initSharedReport();
