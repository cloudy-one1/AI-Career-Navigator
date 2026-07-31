// ===================================================
// app.js — 主入口：Tab 切换 + 模块初始化
// ===================================================

import { $, $$ } from './utils.js';
import { initInterview } from './interview.js';
import { initReport } from './report.js';
import { initHistory } from './history.js';
import { initQuestionBank } from './questionBank.js';

function switchTab(tabName) {
  // 更新 Tab 按钮
  $$('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
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
}

// 绑定事件
document.addEventListener('DOMContentLoaded', () => {
  $$('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      if (tab) switchTab(tab);
    });
  });

  // 默认显示面试 Tab
  switchTab('interview');
});
