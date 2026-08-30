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
import { initRecruiterInbox } from './recruiterInbox.js';     // v7.0.1 招聘者收件箱

// v7.0.1: 招聘者登录后可见的面板。统一登录、按身份分流——
// 招聘者的"系统"就是收件箱 + 账户，其余求职者面板全部隐藏。
const RECRUITER_TABS = new Set(['recruiter-inbox', 'account']);

/** 按当前身份过滤导航（登录/退出都会触发）。 */
function applyRoleView(user) {
  const isRecruiter = !!user && user.role === 'recruiter';
  $$('.nav-item').forEach(btn => {
    const audience = btn.dataset.audience;
    if (!audience) return;                       // 无标记 = 双端通用（账户）
    const show = isRecruiter
      ? audience === 'recruiter'                 // 招聘者：只看收件箱
      : audience !== 'recruiter';                // 求职者/匿名：看不到收件箱
    btn.classList.toggle('hidden', !show);
  });

  // 身份切换后当前停留的面板可能已被隐藏——招聘者落到收件箱，
  // 求职者若停在收件箱则回到面试页
  const active = $('.nav-item.active');
  if (active && active.classList.contains('hidden')) {
    switchTab(isRecruiter ? 'recruiter-inbox' : 'interview');
  }
}

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
  else if (tabName === 'resume-library') initResumeLibrary();
  else if (tabName === 'position-library') initPositionLibrary();
  else if (tabName === 'recruiter-inbox') initRecruiterInbox();
  else if (tabName === 'account') initAuth();

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

  // v7.0: 登录态变化（登录/退出）后同步顶部显示，并让历史等面板感知归属变化
  // v7.0.1: 携带身份信息 → 按角色分流导航（统一登录，进入不同的系统）
  window.addEventListener('auth:changed', (e) => {
    const { user, justLoggedIn, justLoggedOut } = e.detail || {};
    updateHeaderUser();
    applyRoleView(user ?? null);
    // 登录成功后按身份进入各自的系统
    if (justLoggedIn && user?.role === 'recruiter') switchTab('recruiter-inbox');
    // 退出后回到求职者默认视图（若停在收件箱会被 applyRoleView 隐藏并自动切走，
    // 这里显式回面试页，行为更可预期）
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
