// ===================================================
// app.js — 主入口：导航切换 + 模块初始化（v4.0 框架）
// 兼容桌面侧边导航 / 平板图标栏 / 移动端底部导航（统一 .nav-item[data-tab]）
// v7.0: 接入账户面板 + 401 全局处理 + 启动时拉取登录态
// ===================================================

import { $, $$ } from './utils.js';
import { initInterview } from './interview.js';
import { initReport } from './report.js';
import { initHistory } from './history.js';
import { initQuestionBank } from './questionBank.js';
import { initCareerPlan } from './careerPlan.js';
import { initMarketData } from './marketData.js';
import { initMemory } from './memoryGraph.js';   // v6.3 长期记忆
import { initAuth, refreshAuthStatus, updateHeaderUser, isLoggedIn } from './auth.js';  // v7.0 认证
import { initResumeLibrary } from './resumeLibrary.js';       // v7.0 简历库
import { initPositionLibrary } from './positionLibrary.js';   // v7.0 岗位库

function switchTab(tabName) {
  // 更新导航项（侧边栏 + 底部栏共用）
  $$('.nav-item').forEach(btn => {
    const active = btn.dataset.tab === tabName;
    btn.classList.toggle('active', active);
    if (active) btn.setAttribute('aria-current', 'page');
    else btn.removeAttribute('aria-current');
  });

  // v7.2: 面板切换过渡。Chromium 走 View Transitions API（旧页淡出+新页上滑），
  // 其余浏览器降级为 .panel-enter 入场动画（motion.css）+ 子元素 stagger。
  const apply = () => {
    $$('.panel').forEach(p => {
      const activating = p.id === `${tabName}-panel`;
      p.classList.remove('panel-enter');
      p.classList.toggle('active', activating);
      if (activating) {
        p.classList.add('panel-enter');
        // 兜底：动画时钟被冻结时（后台标签页节流/极慢设备），
        // stagger 子元素会停在 opacity:0——超时后摘除类，内容立即落到可见态
        setTimeout(() => p.classList.remove('panel-enter'), 1200);
      }
    });

    // 初始化对应面板
    if (tabName === 'interview') initInterview();
    else if (tabName === 'report') initReport();
    else if (tabName === 'history') initHistory();
    else if (tabName === 'question-bank') initQuestionBank();
    else if (tabName === 'career-plan') initCareerPlan();
    else if (tabName === 'market-data') initMarketData();
    else if (tabName === 'memory') initMemory();
    else if (tabName === 'resume-library') initResumeLibrary();
    else if (tabName === 'position-library') initPositionLibrary();
    else if (tabName === 'account') initAuth();
  };

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (document.startViewTransition && !reducedMotion) {
    document.startViewTransition(apply);
  } else {
    apply();
  }

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

  // v7.0: 顶部账户按钮 → 跳到账户面板
  $('#user-btn')?.addEventListener('click', () => switchTab('account'));

  // v7.0: 登录态变化（登录/退出）后同步顶部显示，并让历史等面板感知归属变化。
  // v7.5: 删除了招聘者身份分流（CHARTER DC-08）——退出后回到求职者默认视图。
  window.addEventListener('auth:changed', (e) => {
    const { justLoggedOut } = e.detail || {};
    updateHeaderUser();
    if (justLoggedOut) switchTab('interview');
  });

  // v7.0: 任意请求被 401（token 过期/被吊销）→ 清登录态并引导到账户页。
  // 只在"原本是登录态"时提示，避免每次匿名访问都弹一个没意义的 toast。
  window.addEventListener('auth:unauthorized', () => {
    const wasLoggedIn = isLoggedIn();
    refreshAuthStatus().then(() => {
      if (wasLoggedIn && !isLoggedIn()) {
        switchTab('account');
      }
    });
  });

  // 默认显示面试 Tab
  switchTab('interview');

  // v7.0: 启动时拉取一次登录态（失败静默降级为未登录，不阻断首屏）
  refreshAuthStatus().catch(() => {});
});
