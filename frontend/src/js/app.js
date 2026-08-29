// ===================================================
// app.js — 主入口：导航切换 + 模块初始化（v4.0 框架）
// 兼容桌面侧边导航 / 平板图标栏 / 移动端底部导航（统一 .nav-item[data-tab]）
// ===================================================

import { $, $$ } from './utils.js';
import { initInterview } from './interview.js';
import { initReport } from './report.js';
import { initHistory } from './history.js';
import { initQuestionBank } from './questionBank.js';
import { initCareerPlan } from './careerPlan.js';
import { initMarketData } from './marketData.js';
import { initMemory } from './memoryGraph.js';   // v6.3 长期记忆

function switchTab(tabName) {
  // 更新导航项（侧边栏 + 底部栏共用）
  $$('.nav-item').forEach(btn => {
    const active = btn.dataset.tab === tabName;
    btn.classList.toggle('active', active);
    if (active) btn.setAttribute('aria-current', 'page');
    else btn.removeAttribute('aria-current');
  });

  // 更新面板
  $$('.panel').forEach(p => {
    p.classList.toggle('active', p.id === `${tabName}-panel`);
  });

  // 初始化对应面板
  if (tabName === 'interview') initInterview();
  else if (tabName === 'report') initReport();
  else if (tabName === 'history') initHistory();
  else if (tabName === 'question-bank') initQuestionBank();
  else if (tabName === 'career-plan') initCareerPlan();
  else if (tabName === 'market-data') initMarketData();
  else if (tabName === 'memory') initMemory();

  updateInterviewStatus(tabName);
}

// v4.0: 面试状态灯 — 有其他模块进行中会话且离开面试页时显示，点击可跳回
function updateInterviewStatus(currentTab) {
  const light = $('#interview-status');
  if (!light) return;
  const inSession = window._interviewActive === true;
  light.classList.toggle('visible', inSession && currentTab !== 'interview');
}

// 绑定事件
document.addEventListener('DOMContentLoaded', () => {
  $$('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      if (tab) switchTab(tab);
    });
  });

  $('#interview-status')?.addEventListener('click', () => switchTab('interview'));

  // 默认显示面试 Tab
  switchTab('interview');
});
