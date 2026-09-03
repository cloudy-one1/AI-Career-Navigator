// ===================================================
// app.js — 主入口：壳层装配 + tab 注册表 + hash 路由
// v7.6「旅程主线」：导航 DOM 由 navConfig.js 渲染（侧边栏/底部导航
// 单一数据源），面板初始化收敛为 tabRegistry——新增页面注册一行即可。
// hash 路由（#/interview …）：刷新/后退/分享直达对应页。
// 兼容桌面侧边导航 / 平板图标栏 / 移动端底部导航（统一 .nav-item[data-tab]）
// 账户面板与 401 全局处理随认证一并下线
// ===================================================

import { $, $$ } from './utils.js';
import {
  renderSidebar, renderBottomNav, renderJourneyProgress, updateJourneyActive,
} from './navConfig.js';
import { initInterview } from './interview.js';
import { initReport } from './report.js';
import { initHistory } from './history.js';
import { initQuestionBank } from './questionBank.js';
import { initCareerPlan } from './careerPlan.js';
import { initMarketData } from './marketData.js';
import { initMemory } from './memoryGraph.js';   // v6.3 长期记忆
import { initResumeLibrary } from './resumeLibrary.js';       // v7.0 简历库
import { initPositionLibrary } from './positionLibrary.js';   // v7.0 岗位库
import { initProfile } from './profileCard.js';               // v8.0 能力档案

/** tab → 面板 init。新增页面在此注册一行即可，不再需要改 if/else 链。 */
const tabRegistry = {
  'home': initProfile,        // v8.2 默认首屏：能力档案（landing 已独立为单独 HTML）
  'interview': initInterview,
  'report': initReport,
  'history': initHistory,
  'question-bank': initQuestionBank,
  'career-plan': initCareerPlan,
  'market-data': initMarketData,
  'memory': initMemory,
  'resume-library': initResumeLibrary,
  'position-library': initPositionLibrary,
};

let currentTab = null;

function tabFromHash() {
  const m = location.hash.match(/^#\/([\w-]+)$/);
  return (m && tabRegistry[m[1]]) ? m[1] : null;
}

function applyTab(tabName) {
  // 更新导航项（侧边栏 + 底部栏共用）
  $$('.nav-item').forEach(btn => {
    const active = btn.dataset.tab === tabName;
    btn.classList.toggle('active', active);
    if (active) btn.setAttribute('aria-current', 'page');
    else btn.removeAttribute('aria-current');
  });

  // v7.6: 高亮当前 tab 所在旅程步骤（侧栏时间线 + 进度条）
  updateJourneyActive(tabName);

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

    tabRegistry[tabName]?.();
  };

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (document.startViewTransition && !reducedMotion) {
    document.startViewTransition(apply);
  } else {
    apply();
  }

  updateInterviewStatus(tabName);
  currentTab = tabName;
}

/** 切换 tab。hash 与目标不一致时只改 hash（进浏览器历史），
 *  由 hashchange 回环触发真正的 applyTab，保证后退/前进与视图一致。 */
function switchTab(tabName) {
  if (!tabRegistry[tabName]) tabName = 'home';
  if (tabName === currentTab) return;
  const target = `#/${tabName}`;
  if (location.hash !== target) {
    location.hash = target;
    return;
  }
  applyTab(tabName);
}

// v4.0: 面试状态灯 — 有其他模块进行中会话且离开面试页时显示，点击可跳回
function updateInterviewStatus(currentTabName) {
  const light = $('#interview-status');
  if (!light) return;
  const inSession = window._interviewActive === true;
  light.classList.toggle('visible', inSession && currentTabName !== 'interview');
}

// 绑定事件
document.addEventListener('DOMContentLoaded', () => {
  // v7.6: 壳层装配——导航与旅程进度条由单一数据源渲染
  renderSidebar($('#app-nav'));
  renderBottomNav($('#bottom-nav'));
  renderJourneyProgress($('#journey-progress'));

  $$('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      if (tab) switchTab(tab);
    });
  });

  $('#interview-status')?.addEventListener('click', () => switchTab('interview'));

  // v7.6: hash 路由——浏览器后退/前进、手动改 hash 均直达对应页
  window.addEventListener('hashchange', () => {
    switchTab(tabFromHash() || currentTab || 'home');
  });

  // v8.2: 产品主页已独立为 landing.html；SPA 内默认首屏回到能力档案
  // 注意：此处须与 index.html 中带 .active 的静态兜底面板保持一致，否则 JS 执行前会闪错面板。
  const initial = tabFromHash() || 'home';
  // replaceState 同步 URL 但不触发 hashchange（首屏直接 apply，避免空白闪帧）
  if (location.hash !== `#/${initial}`) {
    history.replaceState(null, '', `#/${initial}`);
  }
  applyTab(initial);
});
