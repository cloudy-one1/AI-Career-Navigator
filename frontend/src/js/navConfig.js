// ===================================================
// navConfig.js — 导航单一数据源（v7.6「旅程主线」布局）
// ---------------------------------------------------
// 桌面/平板侧边栏（五步旅程时间线）与移动端底部导航均由本配置渲染；
// 新增/调整导航入口只改这里：index.html 不再写导航标记，
// app.js 不再逐项维护图标与标签。
// ===================================================

function svg(paths) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

/** 勾选标记（已完成步骤的节点内图形） */
const CHECK_PATHS = '<polyline points="20 6 9 17 4 12"/>';

const ICONS = {
  position: svg('<rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>'),
  market: svg('<path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/>'),
  resume: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
  interview: svg('<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>'),
  questionBank: svg('<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>'),
  history: svg('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
  report: svg('<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>'),
  memory: svg('<circle cx="12" cy="12" r="3"/><circle cx="4.5" cy="7" r="2"/><circle cx="19.5" cy="7" r="2"/><circle cx="4.5" cy="17" r="2"/><circle cx="19.5" cy="17" r="2"/><line x1="6.3" y1="8.2" x2="9.6" y2="10.6"/><line x1="17.7" y1="8.2" x2="14.4" y2="10.6"/><line x1="6.3" y1="15.8" x2="9.6" y2="13.4"/><line x1="17.7" y1="15.8" x2="14.4" y2="13.4"/>'),
  career: svg('<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>'),
  account: svg('<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
  overview: svg('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
};

/**
 * 五步主线（对齐 docs/产品定位延伸_全流程求职陪跑.md 的旅程叙事）。
 *
 * v8.1 术语统一：原「定方向 / 备弹药 / 演练 / 诊弱点 / 定规划」带有游戏化与
 * 军事隐喻，与"专业评测工具"的定位不符，统一为职业发展领域的本行术语。
 * 注意：**只改显示名，tab key 一律不动**——哈希路由、跨模块跳转
 * （history.js / marketData.js 的 .nav-item[data-tab=...].click()）都依赖它。
 */
export const JOURNEY_STEPS = [
  { num: '壹', title: '职业定位', children: [
    { tab: 'position-library', label: '岗位库', shortLabel: '岗位', icon: ICONS.position },
    { tab: 'market-data', label: '市场数据', shortLabel: '市场', icon: ICONS.market },
  ] },
  { num: '贰', title: '简历准备', children: [
    { tab: 'resume-library', label: '简历库', shortLabel: '简历', icon: ICONS.resume },
  ] },
  { num: '叁', title: '面试演练', children: [
    { tab: 'interview', label: '模拟面试', shortLabel: '面试', icon: ICONS.interview },
    { tab: 'question-bank', label: '题库', shortLabel: '题库', icon: ICONS.questionBank },
    { tab: 'history', label: '历史记录', shortLabel: '历史', icon: ICONS.history },
  ] },
  { num: '肆', title: '能力诊断', children: [
    { tab: 'report', label: '综合报告', shortLabel: '报告', icon: ICONS.report },
    { tab: 'memory', label: '长期记忆', shortLabel: '记忆', icon: ICONS.memory },
  ] },
  { num: '伍', title: '发展路径', children: [
    { tab: 'career-plan', label: '职业规划', shortLabel: '规划', icon: ICONS.career },
  ] },
];

/** 能力档案（v8.0 引入、v8.1 定名）：默认首屏。它不属于五步主线中的任何一步——
 *  主线是"做的事"，能力档案是"看全局的地方"，因此独立置于时间线之上。 */
export const OVERVIEW_ITEM = { tab: 'home', label: '能力档案', shortLabel: '档案', icon: ICONS.overview };

/** 账户：旅程之外的独立入口（侧栏底部 / 底部导航末位） */
export const ACCOUNT_ITEM = { tab: 'account', label: '账户', shortLabel: '账户', icon: ICONS.account };

/** 旅程平铺（底部导航用：能力档案 + 五步主线顺序 + 账户） */
export const FLAT_ITEMS = [
  OVERVIEW_ITEM,
  ...JOURNEY_STEPS.flatMap((s) => s.children),
  ACCOUNT_ITEM,
];

/** tab → 所在旅程步骤下标 */
const TAB_STEP = new Map();
JOURNEY_STEPS.forEach((s, i) => s.children.forEach((c) => TAB_STEP.set(c.tab, i)));

/** 当前 tab 属于第几步旅程；不在旅程内（如账户）返回 -1 */
export function stepIndexOf(tab) {
  return TAB_STEP.get(tab) ?? -1;
}

// ── 壳层渲染 ───────────────────────────────────────

function navButton(item) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'nav-item';
  b.dataset.tab = item.tab;
  b.innerHTML = `${item.icon}<span class="nav-label">${item.label}</span>`;
  return b;
}

/** 渲染桌面/平板侧边栏：五步旅程时间线 + 账户 */
export function renderSidebar(container) {
  container.innerHTML = '';

  // 能力档案：置于旅程时间线之上（全局视图先于具体步骤）
  const overview = navButton(OVERVIEW_ITEM);
  overview.classList.add('nav-overview');
  container.appendChild(overview);

  JOURNEY_STEPS.forEach((step, idx) => {
    const stepEl = document.createElement('div');
    stepEl.className = 'journey-step';
    stepEl.dataset.step = String(idx);
    stepEl.innerHTML =
      `<div class="journey-head">` +
      `<span class="journey-num" aria-hidden="true">` +
      `<span class="journey-num-text">${step.num}</span>` +
      `<svg class="journey-num-check" viewBox="0 0 24 24" fill="none" stroke="currentColor"` +
      ` stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${CHECK_PATHS}</svg>` +
      `</span>` +
      `<span class="journey-title">${step.title}</span>` +
      `</div>`;
    step.children.forEach((item) => {
      const b = navButton(item);
      b.classList.add('journey-sub');
      stepEl.appendChild(b);
    });
    container.appendChild(stepEl);
  });
  const account = navButton(ACCOUNT_ITEM);
  account.classList.add('nav-account');
  container.appendChild(account);
}

/** 渲染移动端底部导航：旅程平铺 + 账户 */
export function renderBottomNav(container) {
  container.innerHTML = '';
  FLAT_ITEMS.forEach((item) => {
    const b = navButton(item);
    b.innerHTML = `${item.icon}<span>${item.shortLabel}</span>`;
    container.appendChild(b);
  });
}

/** 渲染主区顶部的旅程进度条（壹→伍 + 完成计数） */
export function renderJourneyProgress(container) {
  container.innerHTML = '';
  container.appendChild(el('span', {
    className: 'jp-counter', id: 'journey-counter',
  }, `${JOURNEY_STEPS.length} 步主线`));
  JOURNEY_STEPS.forEach((step, idx) => {
    if (idx > 0) {
      const line = document.createElement('i');
      line.className = 'jp-line';
      container.appendChild(line);
    }
    const s = document.createElement('span');
    s.className = 'jp-step';
    s.dataset.step = String(idx);
    s.innerHTML =
      `<i class="jp-dot" aria-hidden="true">` +
      `<span class="journey-num-text">${step.num}</span>` +
      `<svg class="journey-num-check" viewBox="0 0 24 24" fill="none" stroke="currentColor"` +
      ` stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${CHECK_PATHS}</svg>` +
      `</i>` +
      `<span class="jp-label">${step.title}</span>`;
    container.appendChild(s);
  });
}

/** 高亮当前 tab 所在旅程步骤（侧栏时间线 + 进度条）。
 *  不在旅程内（如账户）则全部摘除高亮并隐藏进度条。 */
export function updateJourneyActive(tab) {
  const stepIdx = stepIndexOf(tab);
  document.querySelectorAll('.journey-step').forEach((el) => {
    el.classList.toggle('current', Number(el.dataset.step) === stepIdx);
  });
  const progress = document.getElementById('journey-progress');
  if (!progress) return;
  progress.hidden = stepIdx < 0;
  progress.querySelectorAll('.jp-step').forEach((el) => {
    el.classList.toggle('current', Number(el.dataset.step) === stepIdx);
  });
}

/**
 * v8.1: 用档案里的五步完成度刷新侧栏时间线与顶部进度条（三态）。
 *
 * 与 updateJourneyActive 的分工：后者管"你正在看哪一步"（瞬时选中态），
 * 本函数管"你走到了哪一步"（持久完成度）。两者可叠加——
 * 正在看第②步时，第②步同时是 current（选中）与 done（已完成）。
 *
 * @param {object|null} journey 档案返回的 journey 段；为空则清空所有状态标记
 */
export function updateJourneyProgress(journey) {
  const states = (journey && journey.steps) || [];
  const byIndex = new Map(states.map((s, i) => [i, s.state]));

  document.querySelectorAll('.journey-step').forEach((el) => {
    const state = byIndex.get(Number(el.dataset.step));
    el.classList.toggle('is-done', state === 'done');
    el.classList.toggle('is-current', state === 'current');
    el.classList.toggle('is-todo', state === 'todo' || !state);
  });

  const progress = document.getElementById('journey-progress');
  if (!progress) return;
  progress.querySelectorAll('.jp-step').forEach((el) => {
    const state = byIndex.get(Number(el.dataset.step));
    el.classList.toggle('is-done', state === 'done');
    el.classList.toggle('is-current', state === 'current');
    el.classList.toggle('is-todo', state === 'todo' || !state);
  });

  // 已完成计数：给进度条一个可读的"走到第几步"
  const counter = document.getElementById('journey-counter');
  if (counter && journey) {
    counter.textContent = `${journey.completed || 0} / ${journey.total || JOURNEY_STEPS.length} 步已完成`;
  }
}
