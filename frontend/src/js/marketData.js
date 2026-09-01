// ===================================================
// marketData.js — 市场数据 Tab（v4.1）
// 还原 job-crawler 采集页 + 岗位列表页设计（纸墨印章风格）。
// v5.0：主题（米色 / 深色）与语义色统一由全局 themeToggle.js 控制，
//       本模块不再维护自己的主题状态；本地 --mkt-* Token 已指向全局 Token。
// 视图：实时采集 / 岗位列表 / 数据分析 / 独立岗位详情（可跳转 51job 原文）
//       注意：本模块的「岗位列表」是**市场采集到的公共缓存**（可再采集），
//       与侧栏「岗位库」（用户私有资产）是两个物理分离的库，不可混称。
// 分析：单选 Gap 分析（/api/gap-analysis）、多选跨岗位对比（/api/cross-job-compare）
// [v8.2] 新增「数据分析」视图：图表卡片 + 每张卡自带 AI 解读（/api/market/insight）
// ===================================================

import { $, el, toast } from './utils.js';
import { cityCoord } from './cityCoords.js';
import {
  startMarketCrawl, getCrawlStatus, getCityMap, getMarketJob,
  getMarketJobs, getMarketStats, runGapAnalysis, crossJobCompare,
  toggleMarketInterest, getMarketCharts, getMarketInsight,
  addMarketJobToPosition, uploadResumeToLibrary, getResume,
} from './api.js';

const PAGE_SIZE = 20;

const state = {
  cityMap: null,          // {province: [[city, code], ...]}
  selectedCities: [],     // 已选城市名数组
  view: 'collect',        // collect | jobs | detail
  filters: { keyword: '', city: '', education: '', salaryMin: '', salaryMax: '' },
  page: 0,
  total: 0,
  items: [],
  selectedRows: [],       // 多选岗位 id（跨岗位对比）
  currentJob: null,       // 详情视图当前岗位
  currentJdText: '',
  crawlTimer: null,
  crawlTaskId: null,
  crawling: false,
  lastKeyword: '',     // 最近一次采集的关键词（用于结果摘要）
  // ── [v8.2] 数据分析视图 ──
  charts: null,        // /api/market/charts 的聚合数据
  chartInstances: {},  // section → Chart 实例（主题切换/重绘时销毁）
  insights: {},        // section → 解读文本（前端缓存，避免切视图重复请求）
};

/**
 * 初始化市场数据 Tab。
 * 首次：构建 DOM 并拉取数据。之后每次切回本 Tab 时（panel.dataset.ready 已置位），
 * 不再重建 DOM（保留筛选/滚动/子视图状态），但**强制从服务端刷新列表与统计**——
 * 「加入岗位库」等操作已持久化入库，切回时必须以服务端为准，否则会看到旧的内存态、
 * 表现为「刚加入的岗位切个界面又变回未加入」。
 */
export function initMarketData() {
  const panel = $('#market-data-panel');
  if (!panel) return;
  if (panel.dataset.ready) {
    refreshJobsAndStats();
    return;
  }
  panel.dataset.ready = '1';

  panel.append(
    buildTopbar(),
    buildCollectView(),
    buildJobsView(),
    buildChartsView(),
    buildDetailView(),
  );

  // [v8.2] 主题切换后图表配色需重绘（Chart.js 的 canvas 不响应 CSS 变量变化）
  window.addEventListener('theme:changed', () => {
    if (state.view === 'charts' && state.charts) drawAllCharts();
  });

  // 数据分析视图：滚动时更新右侧索引导航高亮
  window.addEventListener('scroll', updateTocActive, { passive: true });
  window.addEventListener('resize', updateTocActive, { passive: true });

  // 城市映射 + 岗位列表/统计 并行加载
  getCityMap().then(map => {
    state.cityMap = map;
    renderProvinceSelect();
  }).catch(e => toast(e.message || '城市数据加载失败', 'error'));

  refreshJobsAndStats();
}

/* ─────────────────── 顶部横幅 ─────────────────── */

function buildTopbar() {
  return el('div', { className: 'mkt-topbar' },
    el('div', { className: 'mkt-seal' },
      el('div', { className: 'mkt-seal-mark', textContent: '市' }),
      el('div', {},
        el('div', { className: 'mkt-seal-title', textContent: '市场数据' }),
        el('div', { className: 'mkt-seal-sub', textContent: 'MARKET · ARCHIVE' }),
      ),
    ),
    el('nav', { className: 'mkt-topnav' },
      el('button', { className: 'mkt-topnav-btn active', id: 'mkt-nav-collect', textContent: '实时采集', onClick: () => switchView('collect') }),
      el('button', { className: 'mkt-topnav-btn', id: 'mkt-nav-jobs', textContent: '岗位列表', onClick: () => switchView('jobs') }),
      el('button', { className: 'mkt-topnav-btn', id: 'mkt-nav-charts', textContent: '数据分析', onClick: () => switchView('charts') }),
    ),
  );
}

/* ─────────────────── 视图切换 ─────────────────── */

function switchView(view) {
  state.view = view;
  ['collect', 'jobs', 'charts', 'detail'].forEach(v => {
    $(`#mkt-${v}-view`)?.classList.toggle('active', v === view);
  });
  // 顶栏高亮（详情视图归属岗位列表分支）
  ['collect', 'jobs', 'charts'].forEach(v => {
    const active = v === view || (view === 'detail' && v === 'jobs');
    $(`#mkt-nav-${v}`)?.classList.toggle('active', active);
  });
  if (view === 'jobs') {
    state.page = 0;
    refreshJobsAndStats();
  }
  if (view === 'charts') {
    loadCharts();
    // 切到数据分析视图后，立即计算一次索引高亮
    setTimeout(updateTocActive, 0);
  }
}

/* ─────────────────── 采集视图 ─────────────────── */

function buildCollectView() {
  // Hero（对齐 job-crawler input.html .home-hero）
  const hero = el('div', { className: 'home-hero' },
    el('p', { className: 'eyebrow', textContent: '招聘市场数据分析' }),
    el('h1', { textContent: '招聘信息实时数据分析系统' }),
    el('p', { className: 'subtitle', textContent: '一站式查看岗位分布、薪资水平与技能需求，为你的求职决策提供数据支撑' }),
  );

  // 查询卡片（对齐 job-crawler：card + data-no="查询与采集"）
  const formCard = el('div', { className: 'card home-card fade-up', 'data-no': '查询与采集' },
    el('div', { className: 'form-group' },
      el('label', { textContent: '岗位名称（支持关键词搜索，非精确匹配）' }),
      el('input', { type: 'text', className: 'form-control', id: 'mkt-keyword', placeholder: 'python 开发工程师' }),
    ),

    el('div', { className: 'form-group' },
      el('label', { textContent: '选择城市（可选，不选则全国范围搜索）' }),
      el('div', { className: 'city-row' },
        el('select', { id: 'mkt-province-sel', onChange: onProvinceChange },
          el('option', { value: '', textContent: '← 选择省份' }),
        ),
        el('span', { className: 'city-arrow', textContent: '›' }),
        el('select', { id: 'mkt-city-sel', disabled: true, onChange: syncAddBtn },
          el('option', { value: '', textContent: '先选省份 →' }),
        ),
        el('button', { type: 'button', id: 'mkt-add-city', className: 'add-city-btn', disabled: true, textContent: '＋ 添加城市', onClick: addCity }),
      ),
      el('div', { className: 'selected-cities-wrap', id: 'mkt-selected-wrap' },
        el('div', { className: 'wrap-label', textContent: '已选城市：' }),
        el('div', { className: 'selected-cities', id: 'mkt-selected-cities' }),
      ),
    ),

    el('div', { style: 'display:flex; gap:14px; flex-wrap:wrap;' },
      el('div', { className: 'form-group', style: 'flex:1; min-width:170px;' },
        el('label', { textContent: '排序方式（仅"立即实时采集"生效）' }),
        el('select', { className: 'form-control', id: 'mkt-sort', style: 'font-size:15px;' },
          el('option', { value: '0', textContent: '按相关性排序' }),
          el('option', { value: '1', textContent: '最新发布' }),
        ),
      ),
      el('div', { className: 'form-group', style: 'flex:1; min-width:170px;' },
        el('label', { textContent: '实时采集页数（仅"立即实时采集"生效，1~5）' }),
        el('input', { type: 'number', className: 'form-control', id: 'mkt-pages', value: '2', min: '1', max: '5', style: 'font-size:15px;' }),
      ),
    ),

    el('div', { style: 'display:flex; gap:10px; margin-top:4px;' },
      el('button', { type: 'button', id: 'mkt-query-btn', className: 'btn btn-default', style: 'flex:1; padding:12px; font-size:15px;', textContent: '查询已有数据', onClick: queryExisting }),
      el('button', { type: 'button', id: 'mkt-crawl-btn', className: 'btn btn-info', style: 'flex:1; padding:12px; font-size:15px;', textContent: '立即实时采集', onClick: startCrawl }),
    ),
    el('p', { className: 'form-hint', textContent: '查询已有数据：浏览已收录的岗位信息；实时采集：获取 51job 最新招聘数据（更新前会清空旧记录）。' }),

    // 增强：采集进度轮询条
    el('div', { className: 'mkt-progress', id: 'mkt-progress' },
      el('div', { className: 'mkt-progress-head' },
        el('span', { className: 'mkt-progress-msg', id: 'mkt-progress-msg', textContent: '排队中…' }),
        el('span', { className: 'mkt-progress-stat', id: 'mkt-progress-stat', textContent: '累计 0 条' }),
      ),
      el('div', { className: 'mkt-progress-bar' },
        el('div', { className: 'mkt-progress-bar-fill', id: 'mkt-progress-fill' }),
      ),
      el('div', { className: 'mkt-progress-sub', id: 'mkt-progress-sub', textContent: '正在启动浏览器…' }),
    ),

    // 采集结果提示（对齐 collect.html 的 .alert-info）
    el('div', { className: 'alert alert-info', id: 'mkt-collect-result' }),
    el('div', { className: 'alert alert-danger', id: 'mkt-error' }),
  );

  // 首页功能卡（对齐 input.html 的 .home-feature-grid）
  const featureGrid = el('div', { className: 'home-feature-grid fade-up' },
    featureCard('📊', '岗位档案',
      '城市分布、薪资区间、热门技能……已收录岗位的多维数据一图尽览',
      '查看档案 →', () => switchView('jobs')),
    featureCard('🎯', '职业规划',
      '结合市场真实岗位需求，生成分阶段的能力提升路径',
      '开始规划 →', () => goToTab('career-plan')),
    featureCard('📚', '岗位库',
      '管理收藏的目标岗位与 JD，作为简历优化与 Gap 分析的对照基准',
      '进入岗位库 →', () => goToTab('position-library')),
  );

  return el('div', { className: 'mkt-view active home-wrap fade-up', id: 'mkt-collect-view' },
    hero, formCard, featureGrid);
}

/** 首页功能卡（对齐规格 §4.12 .home-feature-card；用 button 以便执行 JS 跳转） */
function featureCard(icon, title, desc, arrow, onClick) {
  return el('button', { type: 'button', className: 'home-feature-card', onClick },
    el('div', { className: 'fc-icon', textContent: icon }),
    el('div', { className: 'fc-title', textContent: title }),
    el('div', { className: 'fc-desc', textContent: desc }),
    el('span', { className: 'fc-arrow', textContent: arrow }),
  );
}

/** 跨 Tab 跳转：复用全局导航项，避免重复实现路由 */
function goToTab(tabName) {
  document.querySelector(`.nav-item[data-tab="${tabName}"]`)?.click();
}

/* ─────────────────── 城市级联（对齐 input.html） ───────────────────
   省份 select → 城市 select → 「＋ 添加城市」→ 已选 tag-chip */

function onProvinceChange(e) {
  const prov = e.target.value;
  const citySel = $('#mkt-city-sel');
  const addBtn = $('#mkt-add-city');
  citySel.innerHTML = '';
  addBtn.disabled = true;
  if (prov && state.cityMap && state.cityMap[prov]) {
    citySel.appendChild(el('option', { value: '', textContent: '请选择城市' }));
    state.cityMap[prov].forEach(([city, code]) => {
      citySel.appendChild(el('option', { value: code, textContent: city }));
    });
    citySel.disabled = false;
  } else {
    citySel.appendChild(el('option', { value: '', textContent: '先选省份 →' }));
    citySel.disabled = true;
  }
}

/** 城市选中 → 启用「＋ 添加城市」按钮 */
function syncAddBtn() {
  $('#mkt-add-city').disabled = !$('#mkt-city-sel').value;
}

/** 添加城市到已选列表（按城市名去重；value 存的是城市代码） */
function addCity() {
  const citySel = $('#mkt-city-sel');
  const city = citySel.options[citySel.selectedIndex].textContent;
  if (!citySel.value || state.selectedCities.includes(city)) {
    citySel.value = '';
    syncAddBtn();
    return;
  }
  state.selectedCities.push(city);
  renderSelectedCities();
  citySel.value = '';
  syncAddBtn();
}

/** 渲染已选城市 tag-chip（对齐 input.html .tag-chip） */
function renderSelectedCities() {
  const wrap = $('#mkt-selected-wrap');
  const list = $('#mkt-selected-cities');
  list.innerHTML = '';
  wrap.style.display = state.selectedCities.length ? 'block' : 'none';
  state.selectedCities.forEach((city, i) => {
    list.appendChild(el('span', { className: 'tag-chip' },
      city,
      el('span', { className: 'tag-remove', textContent: '×', title: '移除', onClick: () => removeCity(i) }),
    ));
  });
}

function removeCity(idx) {
  state.selectedCities.splice(idx, 1);
  renderSelectedCities();
}

function renderProvinceSelect() {
  const sel = $('#mkt-province-sel');
  if (!sel || !state.cityMap) return;
  sel.innerHTML = '';
  sel.appendChild(el('option', { value: '', textContent: '← 选择省份' }));
  Object.keys(state.cityMap).sort().forEach(p => {
    sel.appendChild(el('option', { value: p, textContent: p }));
  });
}

/* 查询已有数据：切到岗位库并按关键词过滤 */
function queryExisting() {
  const kw = $('#mkt-keyword').value.trim();
  state.filters.keyword = kw;
  state.page = 0;
  switchView('jobs');
}

/* ─────────────────── 采集任务（轮询进度） ─────────────────── */

async function startCrawl() {
  const keyword = $('#mkt-keyword').value.trim();
  if (!keyword) { toast('请先输入关键词', 'warning'); return; }
  if (state.crawling) { toast('已有采集任务进行中', 'warning'); return; }

  const pages = parseInt($('#mkt-pages').value, 10) || 2;
  const sortType = $('#mkt-sort').value;
  // 未选城市 → 全国范围搜索（后端 scrape_jobs 内部 fallback 到 ("全国","000000")）
  if (!state.selectedCities.length) toast('未选城市，将按全国范围采集', 'info');

  const btn = $('#mkt-crawl-btn');
  btn.disabled = true;
  btn.textContent = '采集进行中…';
  state.lastKeyword = keyword;
  hideError();
  hideCollectResult();
  showProgress('排队中…', 0, '正在提交采集任务…');

  try {
    const { task_id } = await startMarketCrawl({ keyword, cities: state.selectedCities, pages, sortType });
    state.crawling = true;
    state.crawlTaskId = task_id;
    pollCrawl(task_id);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = '立即实时采集';
    hideProgress();
    showError(e.message);
  }
}

function pollCrawl(taskId) {
  clearInterval(state.crawlTimer);
  state.crawlTimer = setInterval(async () => {
    try {
      const st = await getCrawlStatus(taskId);
      if (!st) {
        stopPolling();
        return;
      }
      const totalCities = st.cities.length;
      const doneCities = Object.keys(st.pages_collected || {}).length;
      const pct = st.status === 'done' ? 100
        : Math.min(95, Math.round((doneCities / Math.max(totalCities, 1)) * 100));
      showProgress(st.message, pct, `${doneCities}/${totalCities} 城市 · ${st.collected} 条`);

      if (st.status === 'done') {
        stopPolling();
        setCrawlDone(st);
      } else if (st.status === 'failed') {
        stopPolling();
        setCrawlFailed(st.error);
      }
    } catch (e) {
      // 单次轮询失败不中断，继续尝试
    }
  }, 1500);
}

function stopPolling() {
  clearInterval(state.crawlTimer);
  state.crawlTimer = null;
  state.crawling = false;
  const btn = $('#mkt-crawl-btn');
  if (btn) { btn.disabled = false; btn.textContent = '立即实时采集'; }
}

function setCrawlDone(st) {
  const bar = $('#mkt-progress');
  bar.classList.add('done');
  showProgress(st.message, 100, '');
  setTimeout(() => {
    bar.classList.remove('visible', 'done');
    refreshJobsAndStats();
  }, 2200);

  showCollectResult(st);
}

/** 采集结果摘要（对齐 collect.html 的 .alert-info） */
function showCollectResult(st) {
  const box = $('#mkt-collect-result');
  if (!box) return;
  const cityText = Array.isArray(st.cities) && st.cities.length
    ? st.cities.map(c => (Array.isArray(c) ? c[0] : c)).join('、')
    : '全国';
  box.innerHTML = '';
  box.appendChild(el('div', {},
    '采集完成：关键词「', el('b', { textContent: state.lastKeyword || '—' }),
    '」· 城市「', el('b', { textContent: cityText }),
    '」，共抓到 ', el('span', { className: 'mono', textContent: String(st.collected ?? 0) }),
    ' 条，已写入数据库（更新为最新数据）。',
  ));
  box.appendChild(el('a', {
    href: '#',
    textContent: '查看刚采集的数据 →',
    onClick: e => { e.preventDefault(); switchView('jobs'); },
  }));
  box.classList.add('visible');
}

function hideCollectResult() {
  $('#mkt-collect-result')?.classList.remove('visible');
}

function setCrawlFailed(error) {
  hideProgress();
  hideCollectResult();
  showError(error || '采集失败');
  refreshJobsAndStats();
}

function showProgress(msg, pct, sub) {
  const bar = $('#mkt-progress');
  bar.classList.add('visible');
  $('#mkt-progress-msg').textContent = msg;
  $('#mkt-progress-stat').textContent = sub || `累计 ${pct}%`;
  $('#mkt-progress-fill').style.width = `${pct}%`;
  $('#mkt-progress-sub').textContent = sub || '';
}

function hideProgress() {
  const bar = $('#mkt-progress');
  bar.classList.remove('visible');
}

function showError(msg) {
  const box = $('#mkt-error');
  box.classList.add('visible');
  box.innerHTML = '';
  box.appendChild(el('div', { textContent: `⚠ ${msg}` }));
  // 提示 playwright 安装（未就绪场景）
  if (/playwright|ModuleNotFound|未就绪/i.test(msg)) {
    box.appendChild(el('div', { style: 'margin-top:6px;font-size:12.5px;' },
      '安装指引：', el('code', { textContent: 'pip install playwright playwright-stealth' }),
      ' ，然后 ', el('code', { textContent: 'playwright install chromium' }),
    ));
  }
}

function hideError() {
  const box = $('#mkt-error');
  box.classList.remove('visible');
}

/* ─────────────────── 岗位列表视图 ─────────────────── */

function buildJobsView() {
  const statsRow = el('div', { className: 'mkt-stats-row', id: 'mkt-stats-row' },
    el('div', { className: 'mkt-stat-card' },
      el('div', { className: 'mkt-stat-label', textContent: '岗位总量' }),
      el('div', { className: 'mkt-stat-value', id: 'mkt-stat-total', textContent: '—' }),
    ),
    el('div', { className: 'mkt-stat-card' },
      el('div', { className: 'mkt-stat-label', textContent: '平均薪资' }),
      el('div', { className: 'mkt-stat-value', id: 'mkt-stat-salary', textContent: '—' }),
    ),
    el('div', { className: 'mkt-stat-card' },
      el('div', { className: 'mkt-stat-label', textContent: '热门关键词' }),
      el('div', { className: 'mkt-skills', id: 'mkt-stat-skills' }),
    ),
    el('div', { className: 'mkt-stat-card' },
      el('div', { className: 'mkt-stat-label', textContent: '样本城市' }),
      el('div', { className: 'mkt-skills', id: 'mkt-stat-cities' }),
    ),
  );

  // 筛选表单：主搜索行（高频）+ 高级筛选行（低频，紧凑排列）
  const filters = el('form', { className: 'mkt-filters', onSubmit: e => e.preventDefault() },
    // ── 主搜索：岗位名称 + 城市 + 搜索按钮 ──
    el('div', { className: 'mkt-filter-row' },
      el('div', { className: 'mkt-filter-group mkt-filter-grow' },
        el('label', { textContent: '岗位名称' }),
        el('input', { type: 'text', className: 'form-control', id: 'mkt-f-keyword', placeholder: '如: python开发工程师', onChange: () => { state.filters.keyword = $('#mkt-f-keyword').value.trim(); reloadList(0); } }),
      ),
      el('div', { className: 'mkt-filter-group mkt-filter-mid' },
        el('label', { textContent: '城市' }),
        el('input', { type: 'text', className: 'form-control', id: 'mkt-f-city', placeholder: '如: 北京,上海', onChange: () => { state.filters.city = $('#mkt-f-city').value.trim(); reloadList(0); } }),
      ),
      el('button', { className: 'btn btn-primary', type: 'button', textContent: '🔍 搜索', onClick: () => reloadList(0) }),
    ),
    // ── 高级筛选：学历 + 薪资区间 + 重置 ──
    el('div', { className: 'mkt-filter-row mkt-filter-advanced' },
      el('div', { className: 'mkt-filter-group mkt-filter-sm' },
        el('label', { textContent: '学历' }),
        el('select', { className: 'form-control', id: 'mkt-f-edu', onChange: () => { state.filters.education = $('#mkt-f-edu').value; reloadList(0); } },
          el('option', { value: '', textContent: '不限' }),
          el('option', { value: '大专', textContent: '大专' }),
          el('option', { value: '本科', textContent: '本科' }),
          el('option', { value: '硕士', textContent: '硕士' }),
          el('option', { value: '博士', textContent: '博士' }),
        ),
      ),
      // 薪资区间：最低 ~ 最高 合并为一个视觉组
      el('div', { className: 'mkt-filter-group mkt-filter-salary' },
        el('label', { textContent: '月薪 (K)' }),
        el('div', { className: 'mkt-salary-range' },
          el('input', { id: 'mkt-f-smin', className: 'form-control mkt-salary-input', type: 'number', min: '0', placeholder: '最低', onChange: () => { state.filters.salaryMin = $('#mkt-f-smin').value; reloadList(0); } }),
          el('span', { className: 'mkt-salary-sep', textContent: '~' }),
          el('input', { id: 'mkt-f-smax', className: 'form-control mkt-salary-input', type: 'number', min: '0', placeholder: '最高', onChange: () => { state.filters.salaryMax = $('#mkt-f-smax').value; reloadList(0); } }),
        ),
      ),
      el('button', { className: 'btn btn-default', type: 'button', textContent: '重置', onClick: resetFilters }),
    ),
  );

  // 记录卡片 + 表格（对齐 data.html：card data-no="共 N 条记录"）
  const tableWrap = el('div', { className: 'card', id: 'mkt-count-card', 'data-no': '共 0 条记录' },
    el('table', { className: 'table' },
      el('thead', {},
        el('tr', {},
          el('th', { className: 'pick-col', textContent: '选择' }),
          el('th', { textContent: '职位' }),
          el('th', { textContent: '公司' }),
          el('th', { textContent: '城市' }),
          el('th', { textContent: '最低薪资(千元)' }),
          el('th', { textContent: '最高薪资(千元)' }),
          el('th', { textContent: '发布时间' }),
          el('th', { textContent: '加入岗位库' }),
        ),
      ),
      el('tbody', { id: 'mkt-tbody' },
        el('tr', {},
          el('td', { colSpan: '8', className: 'empty-row', textContent: '加载岗位数据…' }),
        ),
      ),
    ),
  );

  // 翻页（对齐 data.html：← 上一页 / 第 X / Y 页 / 下一页 →）
  const pagination = el('div', { className: 'pager' },
    el('button', { className: 'btn btn-default', id: 'mkt-page-prev', textContent: '← 上一页', onClick: () => reloadList(state.page - 1), disabled: true }),
    el('span', { className: 'page-info', id: 'mkt-page-info', textContent: '第 1 / 1 页' }),
    el('button', { className: 'btn btn-default', id: 'mkt-page-next', textContent: '下一页 →', onClick: () => reloadList(state.page + 1), disabled: true }),
  );

  const compareBar = el('div', { className: 'mkt-compare-bar', id: 'mkt-compare-bar' },
    el('span', { textContent: '已选 ' }),
    el('span', { className: 'cnt', id: 'mkt-compare-cnt', textContent: '0' }),
    el('span', { textContent: ' 个岗位' }),
    el('button', { className: 'mkt-btn mkt-btn-sm', textContent: '跨岗位对比', onClick: doCrossCompare }),
    el('button', { className: 'mkt-btn mkt-btn-sm mkt-btn-ghost', textContent: '清空选择', onClick: clearSelection }),
  );

  const compareResult = el('div', { className: 'mkt-compare-result', id: 'mkt-compare-result' });

  return el('div', { className: 'mkt-view', id: 'mkt-jobs-view' },
    el('p', { className: 'eyebrow', textContent: '数据展示' }),
    el('h2', { style: 'margin-bottom:18px;', textContent: '招聘数据档案' }),
    statsRow, filters, tableWrap, pagination, compareBar, compareResult,
  );
}

function resetFilters() {
  state.filters = { keyword: '', city: '', education: '', salaryMin: '', salaryMax: '' };
  ['mkt-f-keyword', 'mkt-f-city', 'mkt-f-smin', 'mkt-f-smax'].forEach(id => { $(`#${id}`).value = ''; });
  $('#mkt-f-edu').value = '';
  reloadList(0);
}

async function refreshJobsAndStats() {
  loadStats();
  if (state.view === 'jobs') reloadList(state.page);
}

/**
 * 统计卡刷新。
 *
 * 字段名严格对齐后端 `store.get_stats()` 契约：
 *   total(int) / avg_salary{avg_k,min_k,max_k} / cities[{city,cnt}] / top_skills[{skill,count}]
 * 注意：不要沿用 `market_reference` 的那套扁平命名（total_samples/avg_salary_k/top_cities），
 * 那是 Gap 分析结果的字段，与 /api/market/stats 不同源——此前误用导致 4 张卡恒为「—」。
 */
async function loadStats() {
  try {
    const s = await getMarketStats(state.filters.keyword || undefined);
    $('#mkt-stat-total').textContent = s.total ?? '—';
    const avg = s.avg_salary?.avg_k;
    $('#mkt-stat-salary').innerHTML = avg != null
      ? `${Number(avg).toFixed(1)}<small> K/月</small>` : '<small>—</small>';

    const skills = $('#mkt-stat-skills');
    skills.innerHTML = '';
    const skillList = s.top_skills || [];
    skillList.slice(0, 5).forEach(t => skills.appendChild(el('span', { className: 'mkt-skill-tag', textContent: t.skill })));
    if (!skillList.length) skills.textContent = '—';

    const cities = $('#mkt-stat-cities');
    cities.innerHTML = '';
    const cityList = s.cities || [];
    cityList.slice(0, 5).forEach(c => cities.appendChild(el('span', { className: 'mkt-skill-tag', textContent: c.city })));
    if (!cityList.length) cities.textContent = '—';
  } catch (e) {
    // 统计失败不阻塞列表；但不再静默吞掉，否则这类契约错位会再次无声退化
    console.warn('[market] 统计加载失败:', e);
  }
}

async function reloadList(page) {
  state.page = Math.max(0, page);
  const tbody = $('#mkt-tbody');
  tbody.innerHTML = '';
  tbody.appendChild(el('tr', {},
    el('td', { colSpan: '8', className: 'mkt-empty' },
      el('span', { className: 'mkt-loading' }, el('span', { className: 'mkt-spinner' }), '加载岗位数据…'),
    ),
  ));
  try {
    const data = await getMarketJobs(state.filters, state.page, PAGE_SIZE);
    state.items = data.items || [];
    state.total = data.total || 0;
    renderTable();
    renderPagination();
  } catch (e) {
    tbody.innerHTML = '';
    tbody.appendChild(el('tr', {}, el('td', { colSpan: '8', className: 'mkt-empty', textContent: `加载失败：${e.message}` })));
  }
}

function renderTable() {
  const tbody = $('#mkt-tbody');
  tbody.innerHTML = '';
  if (!state.items.length) {
    tbody.appendChild(el('tr', {}, el('td', { colSpan: '8', className: 'mkt-empty', textContent: '没有匹配的岗位。可到「实时采集」拉取一批新数据。' })));
    return;
  }
  state.items.forEach((job) => {
    const selected = state.selectedRows.includes(job.id);
    const interested = isInterested(job);
    const tr = el('tr', {
      className: `data-row${selected ? ' selected' : ''}`,
      'data-id': String(job.id),
      onClick: () => openDetail(job.id),   // 整行点击跳详情（复刻 job-crawler .data-row）
    },
      // 增强：行首多选框（跨岗位对比），阻止冒泡避免误触跳转
      el('td', { className: 'pick-col', onClick: e => e.stopPropagation() },
        el('input', { type: 'checkbox', className: 'mkt-checkbox', checked: selected, onChange: e => toggleSelect(job, e.target.checked) }),
      ),
      el('td', {},
        el('a', { className: 'job-link', textContent: job.title || '—', onClick: e => { e.stopPropagation(); openDetail(job.id); } }),
      ),
      el('td', { textContent: job.company || '-' }),
      el('td', { textContent: job.city || '—' }),
      el('td', { className: 'mono', textContent: job.salary_min != null ? Number(job.salary_min).toFixed(1) : '-' }),
      el('td', { className: 'mono', textContent: job.salary_max != null ? Number(job.salary_max).toFixed(1) : '-' }),
      el('td', { textContent: formatDate(job.collected_at || job.publish_time || '') }),
      el('td', { onClick: e => e.stopPropagation() },
        el('button', {
          type: 'button',
          className: `mkt-add-btn${job.in_library ? ' added' : ''}`,
          disabled: !!job.in_library,
          onClick: e => addToPositionLibrary(job, e.currentTarget),
        }, job.in_library ? '✓ 已在岗位库' : '＋ 加入'),
      ),
    );
    tbody.appendChild(tr);
  });
}

function formatDate(s) {
  if (!s) return '—';
  // "05-15 发布" 或 "2026-08-27 10:00:00"
  if (/^\d{2}-\d{2}/.test(s)) return s.replace('发布', '').trim();
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[2]}-${m[3]}`;
  return s.slice(0, 10);
}

function renderPagination() {
  const totalPages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  // 对齐 job-crawler：记录卡片角标显示「共 N 条记录」
  const card = $('#mkt-count-card');
  if (card) card.dataset.no = `共 ${state.total} 条记录`;
  $('#mkt-page-info').textContent = `第 ${state.page + 1} / ${totalPages} 页`;
  $('#mkt-page-prev').disabled = state.page <= 0;
  $('#mkt-page-next').disabled = state.page >= totalPages - 1;
}

/* ─────────────────── 感兴趣（后端持久化） ───────────────────
   状态存在 market.db 的 job_postings.is_interested（全局标记，
   与题库 question_bank.is_favorited 同模式）。列表 / 详情接口
   均返回该字段，故直接读 job 对象，无需前端另存一份。 */

function isInterested(job) {
  return !!(job && job.is_interested);
}

async function toggleInterest(id, btn) {
  try {
    const { is_interested: on } = await toggleMarketInterest(id);
    btn.classList.toggle('interested', on);
    const label = btn.querySelector('.interest-label');
    if (label) label.textContent = on ? '已收藏' : '感兴趣';
    // 同步内存态，避免翻页 / 重新渲染后状态回退
    const hit = state.items.find(j => String(j.id) === String(id));
    if (hit) hit.is_interested = on ? 1 : 0;
    if (state.currentJob && String(state.currentJob.id) === String(id)) {
      state.currentJob.is_interested = on ? 1 : 0;
    }
  } catch (e) {
    toast(e.message || '收藏失败', 'error');
  }
}

/**
 * [v8.2] 把当前市场岗位导入岗位库，之后在面试页可直接选用这份 JD。
 *
 * 为什么是"导入"而非让岗位库直接读取市场收藏：两个库物理分离（市场是
 * 可再采集的公共缓存，岗位库是用户私有资产），跨库无法 JOIN；且岗位库
 * 要求 JD 文本始终可用，不能依赖市场库那条记录还在。导入是幂等的——
 * 同一岗位重复点击不会产生第二条，后端会返回 created=false。
 */
async function addToPositionLibrary(job, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = '导入中…';
  try {
    const res = await addMarketJobToPosition(job.id);
    btn.textContent = '✓ 已在岗位库';
    btn.classList.add('added');
    // 同步内存态，避免翻页后状态回退
    if (job) job.in_library = true;
    toast(res.created ? '已加入岗位库，面试时可直接选用' : '该岗位此前已在岗位库中',
          res.created ? 'success' : 'info');
  } catch (e) {
    btn.disabled = false;
    btn.textContent = original;
    toast(e.message || '加入岗位库失败', 'error');
  }
}

/* ─────────────────── 多选 / 跨岗位对比 ─────────────────── */

function toggleSelect(job, checked) {
  const idx = state.selectedRows.indexOf(job.id);
  if (checked && idx < 0) state.selectedRows.push(job.id);
  if (!checked && idx >= 0) state.selectedRows.splice(idx, 1);
  // 行高亮
  document.querySelectorAll(`#mkt-tbody tr[data-id]`).forEach(tr => {
    tr.classList.toggle('selected', state.selectedRows.includes(Number(tr.dataset.id)));
  });
  updateCompareBar();
}

function clearSelection() {
  state.selectedRows = [];
  document.querySelectorAll('#mkt-tbody tr[data-id]').forEach(tr => tr.classList.remove('selected'));
  document.querySelectorAll('#mkt-tbody .mkt-checkbox').forEach(cb => { cb.checked = false; });
  updateCompareBar();
}

function updateCompareBar() {
  const bar = $('#mkt-compare-bar');
  const cnt = state.selectedRows.length;
  bar.classList.toggle('visible', cnt > 0);
  $('#mkt-compare-cnt').textContent = String(cnt);
  if (cnt > 5) {
    toast('最多对比 5 个岗位，请减少选择', 'warning');
    state.selectedRows = state.selectedRows.slice(0, 5);
    $('#mkt-compare-cnt').textContent = '5';
  }
}

async function doCrossCompare() {
  const ids = state.selectedRows;
  if (ids.length < 2) { toast('请至少选择 2 个岗位', 'warning'); return; }
  if (ids.length > 5) { toast('最多对比 5 个岗位', 'warning'); return; }

  const box = $('#mkt-compare-result');
  if (!box) { console.error('[market] #mkt-compare-result not found'); toast('对比区域加载异常，请刷新页面', 'error'); return; }
  box.innerHTML = '';
  box.appendChild(el('div', { className: 'mkt-card mkt-card-pad' },
    el('div', { className: 'mkt-card-title', textContent: `跨岗位对比（${ids.length} 个岗位）` }),
    el('label', { className: 'mkt-info-label', textContent: '简历内容', style: 'margin-bottom:4px;display:block;' }),
    el('div', { style: 'display:flex; gap:8px; align-items:center; margin-bottom:10px;' },
      el('textarea', { id: 'mkt-compare-resume', className: 'mkt-resume-ta', placeholder: '粘贴简历内容，用于与所选岗位逐一对比…', style: 'flex:1;' }),
    ),
    el('div', { className: 'mkt-analyze-actions' },
      el('button', { className: 'mkt-btn mkt-btn-ghost mkt-btn-sm', textContent: '📋 复用面试 Tab 简历', onClick: () => copyResumeTo('#mkt-compare-resume') }),
      el('button', { className: 'mkt-btn mkt-btn-ghost mkt-btn-sm', textContent: '📁 上传简历文件', onClick: () => $('#mkt-compare-upload')?.click() }),
      el('input', { type: 'file', id: 'mkt-compare-upload', accept: '.pdf,.docx,.txt', style: 'display:none;', onChange: e => handleCompareResumeUpload(e.target) }),
      el('button', { className: 'mkt-btn mkt-btn-primary mkt-btn-sm', textContent: '开始对比', onClick: () => runCompare(ids) }),
      el('button', { className: 'mkt-btn mkt-btn-ghost mkt-btn-sm', textContent: '取消', onClick: () => { box.innerHTML = ''; } }),
    ),
  ));
  // 滚动到对比区域，确保用户能看到表单
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/** 跨岗位对比：上传本地简历文件并解析填充到 textarea */
async function handleCompareResumeUpload(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  input.value = '';   // 允许重复选同一文件
  const SOFT_LIMIT = 10 * 1024 * 1024;
  if (file.size > SOFT_LIMIT) {
    toast(`文件较大（${(file.size / 1024 / 1024).toFixed(1)}MB），上传可能失败`, 'warning');
  }
  toast('正在解析简历…', 'info');
  try {
    const result = await uploadResumeToLibrary(file);
    const id = result?.resume?.id;
    if (!id) throw new Error('入库响应缺少 id');
    // 入库响应剔除了 raw_text（回执不回传全文），需再拉详情取全文
    const detail = await getResume(id);
    const text = detail?.resume?.raw_text || '';
    if (!text.trim()) throw new Error('未能从文件中提取到简历文本');
    const ta = $('#mkt-compare-resume');
    if (ta) ta.value = text;
    toast(`简历已解析（${text.length} 字）`, 'success');
  } catch (err) {
    toast(err.message || '简历上传失败', 'error');
  }
}

async function runCompare(ids) {
  const resumeText = $('#mkt-compare-resume').value.trim();
  if (resumeText.length < 10) { toast('简历内容至少 10 字（可复用面试 Tab 简历）', 'warning'); return; }

  const box = $('#mkt-compare-result');
  box.innerHTML = '';
  box.appendChild(el('div', { className: 'mkt-loading' }, el('span', { className: 'mkt-spinner' }), '正在跨岗位对比…'));

  try {
    const jdList = [];
    for (const id of ids) {
      const { job, jd_text } = await getMarketJob(id);
      jdList.push({ title: `${job.title} · ${job.company}`, text: jd_text });
    }
    const data = await crossJobCompare(resumeText, jdList);
    renderCompareResult(box, data);
  } catch (e) {
    box.innerHTML = '';
    box.appendChild(el('div', { className: 'alert alert-danger visible', textContent: `对比失败：${e.message}` }));
  }
}

function renderCompareResult(box, data) {
  box.innerHTML = '';
  if (!data || !data.results) return;
  const sorted = [...data.results].sort((a, b) => b.overall_score - a.overall_score);
  const riskColors = { '低': 'low', '中': 'mid', '高': 'high' };

  box.appendChild(el('div', { className: 'mkt-card mkt-card-pad' },
    el('div', { className: 'mkt-card-title', textContent: '跨岗位对比结果' }),
    data.recommendation ? el('div', { className: 'mkt-compare-rec', textContent: `📌 综合推荐：${data.recommendation}` }) : null,
    ...sorted.map((r, i) => {
      const riskCls = riskColors[r.risk_level] || 'mid';
      return el('div', { className: 'mkt-rank-card' },
        el('div', { className: `mkt-rank-no ${i === 1 ? 'n2' : i === 2 ? 'n3' : ''}`, textContent: `#${i + 1}` }),
        el('div', { className: 'mkt-rank-body' },
          el('div', { className: 'mkt-rank-title' },
            el('span', { textContent: r.title }),
            el('span', { className: 'mkt-rank-score', textContent: `${Number(r.overall_score).toFixed(1)} 分` }),
            el('span', { className: `mkt-gap-risk ${riskCls}`, textContent: `风险：${r.risk_level}` }),
          ),
          (r.key_strengths || []).length ? el('div', { className: 'mkt-rank-keys' },
            ...r.key_strengths.map(s => el('span', { className: 'mkt-rank-key ok', textContent: `✓ ${s}` })),
          ) : null,
          (r.key_gaps || []).length ? el('div', { className: 'mkt-rank-keys' },
            ...r.key_gaps.map(s => el('span', { className: 'mkt-rank-key gap', textContent: `✗ ${s}` })),
          ) : null,
        ),
      );
    }),
  ));
}

/* ─────────────────── 独立详情视图 ─────────────────── */

function buildDetailView() {
  return el('div', { className: 'mkt-view', id: 'mkt-detail-view' },
    el('p', { className: 'eyebrow', textContent: '岗位详情' }),
    el('h2', { style: 'margin-bottom:18px;', textContent: '职位档案详情' }),
    el('div', { id: 'mkt-detail-body' }),
  );
}

async function openDetail(jobId) {
  switchView('detail');
  const body = $('#mkt-detail-body');
  body.innerHTML = '';
  body.appendChild(el('div', { className: 'mkt-loading' }, el('span', { className: 'mkt-spinner' }), '加载岗位详情…'));

  try {
    const { job, jd_text } = await getMarketJob(jobId);
    state.currentJob = job;
    state.currentJdText = jd_text;
    renderDetail(body, job, jd_text);
  } catch (e) {
    body.innerHTML = '';
    body.appendChild(el('div', { className: 'alert alert-danger visible', textContent: `详情加载失败：${e.message}` }));
  }
}

function renderDetail(body, job, jdText) {
  body.innerHTML = '';
  const no = job.id;

  // 主卡片（对齐 job_detail.html：左侧青绿描边）
  const card = el('div', { className: 'card', style: 'border-left: 4px solid var(--teal);' },
    // 标题行：职位 / 公司·地区 + 操作按钮组
    el('div', { style: 'display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:20px; flex-wrap:wrap; gap:12px;' },
      el('div', { style: 'display:flex; gap:14px; align-items:flex-start;' },
        el('div', { className: 'stamp', textContent: '档案' }),
        el('div', {},
          el('h3', { style: 'margin:0 0 8px 0; color:var(--mkt-ink); font-size:22px;', textContent: job.title || '—' }),
          el('p', { style: 'margin:0; color:var(--mkt-ink-muted); font-size:15px;' },
            el('span', { style: 'margin-right:16px;', textContent: `🏢 ${job.company || '未披露'}` }),
            el('span', { textContent: `📍 ${job.city || job.address || '—'}` }),
          ),
        ),
      ),
      el('div', { className: 'mkt-detail-actions', style: 'display:flex; gap:8px; flex-wrap:wrap; align-items:center;' },
        el('button', { className: 'btn btn-default', style: 'font-size:14px;', textContent: '← 返回列表', onClick: () => switchView('jobs') }),
        el('button', {
          className: `btn btn-primary${job.in_library ? ' added' : ''}`,
          style: 'font-size:14px;',
          disabled: !!job.in_library,
          textContent: job.in_library ? '✓ 已在岗位库' : '＋ 加入岗位库',
          onClick: e => addToPositionLibrary(job, e.currentTarget),
        }),
        job.url ? el('a', {
          className: 'btn btn-info btn-detail', href: job.url, target: '_blank',
          rel: 'noopener noreferrer', style: 'text-decoration:none; font-size:14px;',
          textContent: '🔗 查看详情',
        }) : null,
      ),
    ),

    // 信息网格（对齐 job_detail.html）
    el('div', { style: 'display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:16px; margin-bottom:24px; padding:16px; background:var(--mkt-paper); border-radius:12px;' },
      infoCell('薪资范围', job.salary_raw || (job.salary_min != null ? `${Number(job.salary_min).toFixed(1)}-${job.salary_max != null ? Number(job.salary_max).toFixed(1) : '—'}K` : '面议'), true),
      infoCell('学历要求', job.education || '不限'),
      infoCell('经验要求', formatExp(job.exp_min, job.exp_max)),
      infoCell('发布时间', formatDate(job.collected_at || '')),
    ),

    // 技能标签
    (job.tags || []).length ? el('div', { className: 'mkt-skills', style: 'margin-bottom:12px;' },
      ...job.tags.map(t => el('span', { className: 'mkt-skill-tag', textContent: t })),
    ) : null,

    // 职位描述
    el('div', {},
      el('h4', { style: 'margin:0 0 12px 0; font-size:18px; color:var(--mkt-ink);', textContent: '职位描述' }),
      el('div', {
        style: 'padding:16px; background:var(--mkt-paper); border-radius:12px; line-height:1.8; white-space:pre-wrap; font-size:15px; color:var(--mkt-ink); max-height:400px; overflow-y:auto;',
        textContent: job.description || '该职位暂无详细描述信息',
      }),
    ),
  );

  // 增强：Gap 分析（本项目扩展，job-crawler 无）
  const analyzeCard = el('div', { className: 'mkt-analyze', style: 'margin-top:16px;' },
    el('h3', { textContent: '简历匹配分析' }),
    el('label', { className: 'mkt-info-label', textContent: '简历内容', style: 'margin-bottom:4px;display:block;' }),
    el('textarea', { id: 'mkt-detail-resume', className: 'mkt-resume-ta', placeholder: '粘贴简历内容，至少 10 字…' }),
    el('div', { className: 'mkt-analyze-actions' },
      el('button', { className: 'btn btn-default', textContent: '📋 复用面试 Tab 简历', onClick: () => copyResumeTo('#mkt-detail-resume') }),
      el('button', { className: 'btn btn-info', textContent: '开始 Gap 分析', onClick: () => doGapAnalysis('#mkt-detail-resume', '#mkt-detail-gap', state.currentJdText) }),
    ),
    el('div', { id: 'mkt-detail-gap' }),
  );

  body.append(card, analyzeCard);
}

/** 详情信息格（对齐 job_detail.html；highlight=true 用于薪资：等宽 + 青绿大字） */
function infoCell(label, value, highlight = false) {
  return el('div', {},
    el('div', { style: 'font-size:13px; color:var(--mkt-ink-muted); margin-bottom:4px;', textContent: label }),
    el('div', {
      className: highlight ? 'mono' : '',
      style: highlight
        ? 'font-size:20px; font-weight:700; color:var(--teal);'
        : 'font-size:16px; font-weight:600; color:var(--mkt-ink);',
      textContent: value,
    }),
  );
}

function formatExp(min, max) {
  if (min == null && max == null) return '不限';
  if (min == null) return `${max}年以下`;
  if (max == null) return `${min}年以上`;
  return `${min}-${max}年`;
}

function copyResumeTo(targetSel) {
  const resumeText = $('#resume-text');
  const target = $(targetSel);
  if (!resumeText || !resumeText.value.trim()) {
    toast('面试 Tab 的简历为空，请先粘贴简历', 'warning');
    return;
  }
  target.value = resumeText.value.trim();
  toast('已复用面试简历', 'success');
}

/* ─────────────────── Gap 分析 ─────────────────── */

async function doGapAnalysis(taSel, boxSel, jdText) {
  const resumeText = $(taSel).value.trim();
  if (resumeText.length < 10) { toast('简历内容至少 10 字', 'warning'); return; }
  if (!jdText) { toast('缺少岗位 JD 文本', 'warning'); return; }

  const box = $(boxSel);
  box.innerHTML = '';
  box.appendChild(el('div', { className: 'mkt-loading' }, el('span', { className: 'mkt-spinner' }), '正在分析匹配度…'));

  try {
    const gap = await runGapAnalysis({
      resumeText,
      jdText,
      keyword: (state.currentJob?.title || '').split(/[\s·,，/]/)[0],
    });
    renderGapResult(box, gap);
  } catch (e) {
    box.innerHTML = '';
    box.appendChild(el('div', { className: 'alert alert-danger visible', textContent: `分析失败：${e.message}` }));
  }
}

function renderGapResult(box, gap) {
  box.innerHTML = '';
  if (!gap || !gap.dimensions) { box.appendChild(el('div', { className: 'alert alert-danger visible', textContent: '未返回有效的分析结果' })); return; }

  const overall = gap.overall_score || 0;   // 1-5 分制
  const overallPct = Math.round((overall / 5) * 100);
  const riskCls = gap.risk_level === '低' ? 'low' : gap.risk_level === '中' ? 'mid' : 'high';
  const riskColor = gap.risk_level === '低' ? 'var(--emerald-600)' : gap.risk_level === '中' ? 'var(--warning)' : 'var(--indigo-800)';

  const summary = el('div', { className: 'mkt-gap-summary' },
    el('div', { className: 'mkt-gap-score' },
      el('div', { className: 'mkt-gap-ring', style: `background:conic-gradient(${riskColor} ${(overall / 5) * 360}deg, var(--mkt-line) 0deg);`, textContent: overallPct }),
      el('div', {},
        el('div', { style: 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;' },
          el('span', { style: 'font-family:var(--mkt-serif);font-weight:700;font-size:15px;', textContent: `整体匹配 ${overallPct}/100` }),
          el('span', { className: `mkt-gap-risk ${riskCls}`, textContent: `风险：${gap.risk_level}` }),
        ),
        gap.overall_assessment ? el('div', { style: 'font-size:12.5px;color:var(--mkt-ink-2);margin-top:6px;line-height:1.6;', textContent: gap.overall_assessment }) : null,
      ),
    ),
  );

  const dims = el('div', { className: 'mkt-gap-dims' },
    ...gap.dimensions.map(d => {
      const pct = (d.score / 5) * 100;
      const barCls = d.score >= 4 ? 'high' : d.score >= 3 ? 'mid' : 'low';
      const scoreCls = d.score >= 4 ? 'high' : d.score >= 3 ? 'mid' : 'low';
      return el('div', { className: 'mkt-dim-row' },
        el('div', { className: 'mkt-dim-head' },
          el('span', { className: 'mkt-dim-name', textContent: `${d.name}（权重 ${Math.round((d.weight || 0) * 100)}%）` }),
          el('span', { className: `mkt-dim-score ${scoreCls}`, textContent: `${d.score}/5` }),
        ),
        el('div', { className: 'mkt-dim-bar' },
          el('div', { className: `mkt-dim-bar-fill ${barCls}`, style: `width:${pct}%;` }),
        ),
        d.evidence ? el('div', { className: 'mkt-dim-evidence', textContent: `📋 证据：${d.evidence}` }) : null,
        d.gap ? el('div', { className: 'mkt-dim-evidence', textContent: `🔍 差距：${d.gap}` }) : null,
      );
    }),
  );

  const suggestion = gap.overall_suggestion || gap.dimensions
    .filter(d => d.score < 3)
    .map(d => d.suggestion)
    .filter(Boolean)
    .join('；');

  const sug = suggestion ? el('div', { className: 'mkt-gap-suggestion', textContent: `✍️ 改进建议：${suggestion}` }) : null;

  // 市场基准
  let marketRef = null;
  const mr = gap.market_reference || gap.market_ref;
  if (mr && mr.total_samples) {
    marketRef = el('div', { className: 'mkt-market-ref' },
      el('div', { className: 'title', textContent: `📊 市场基准参考（${mr.keyword || ''} · ${mr.total_samples} 样本）` }),
      mr.avg_salary_k != null ? el('div', { textContent: `平均薪资 ${Number(mr.avg_salary_k).toFixed(1)}K/月 · 常见区间 ${mr.salary_range || '—'}` }) : null,
      (mr.top_cities || []).length ? el('div', { textContent: `热门城市：${mr.top_cities.slice(0, 6).join(' / ')}` }) : null,
      (mr.top_skills || []).length ? el('div', { textContent: `热门技能：${mr.top_skills.slice(0, 8).join(' / ')}` }) : null,
      mr.summary ? el('div', { style: 'margin-top:4px;color:var(--mkt-stamp-deep);', textContent: mr.summary }) : null,
    );
  } else if (gap.market_source && gap.market_source.total) {
    marketRef = el('div', { className: 'mkt-market-ref' },
      el('div', { className: 'title', textContent: `📊 市场参考（${gap.market_source.keyword || ''} · ${gap.market_source.total} 样本）` }),
    );
  }

  box.append(summary, dims, sug, marketRef);
}

/* ═══════════════════════════════════════════════════════════════
   [v8.2] 数据分析视图：图表卡片 + 每张卡自带 AI 解读
   ═══════════════════════════════════════════════════════════════ */

/**
 * 图表卡片注册表。
 *
 * 新增一张卡片 = 在此加一项即可：解读按钮、三态交互、缓存角标、失败降级
 * 全部自动继承，不必改其它任何代码。
 * `section` 必须与后端 insight.SECTIONS 的 key 一一对应。
 *
 * kind: text（无图，仅摘要+解读）| bar | hbar | doughnut | dual（柱+线双轴）| geo（中国地图）
 */
const CHART_CARDS = [
  { section: 'overview', title: '市场总览', hint: '全部样本的整体画像', kind: 'text' },
  { section: 'salary', title: '薪资分布', hint: '月薪分档（千元/月）', kind: 'bar' },
  { section: 'city', title: '城市分布', hint: '岗位数量 Top10', kind: 'hbar' },
  { section: 'skill', title: '热门词汇', hint: '岗位标签词频 Top20', kind: 'hbar' },
  { section: 'education', title: '学历分布', hint: '最低学历要求占比', kind: 'doughnut' },
  { section: 'experience', title: '经验分布', hint: '年资要求分布', kind: 'bar' },
  { section: 'cross_exp', title: '薪资 × 经验', hint: '柱＝岗位数　线＝均薪(K)', kind: 'dual' },
  { section: 'cross_edu', title: '薪资 × 学历', hint: '柱＝岗位数　线＝均薪(K)', kind: 'dual' },
];

/** 纸墨印章配色：印章红 / 青绿 / 黄铜 / 靛蓝…（与 report.js 保持同源） */
const CHART_COLORS = ['#C44F3A', '#3A7A6A', '#A08945', '#4A6B8A',
  '#8A5A7A', '#7A8A4A', '#A06A4A', '#5A7A8A'];

/** 读取当前主题墨色的 rgb 分量，让图表文字/网格随深浅主题自适应 */
function inkRgb() {
  return getComputedStyle(document.documentElement)
    .getPropertyValue('--ink-rgb').trim() || '26,26,26';
}

function buildChartsView() {
  const grid = el('div', { className: 'mkt-chart-grid', id: 'mkt-chart-grid' },
    ...CHART_CARDS.map(buildChartCard));

  const toc = el('nav', { className: 'mkt-chart-toc', id: 'mkt-chart-toc', 'aria-label': '图表索引' },
    el('div', { className: 'mkt-chart-toc-title', textContent: '快速定位' }),
    ...CHART_CARDS.map(({ section, title }) => el('a', {
      className: 'mkt-chart-toc-item',
      href: `#mkt-card-${section}`,
      textContent: title,
      onClick: e => { e.preventDefault(); scrollToCard(section); },
    })));

  return el('div', { className: 'mkt-view mkt-charts-wrap', id: 'mkt-charts-view' },
    el('p', { className: 'eyebrow', textContent: '数据分析' }),
    el('h2', { style: 'margin-bottom:6px;', textContent: '市场数据画像' }),
    el('p', { className: 'mkt-charts-sub', id: 'mkt-charts-sub', textContent: '加载中…' }),
    el('div', { className: 'mkt-charts-body' }, grid, toc),
  );
}

/** 平滑滚动到指定卡片，并高亮对应索引项 */
function scrollToCard(section) {
  const card = $(`#mkt-card-${section}`);
  if (!card) return;
  const headerOffset = 76;
  const top = card.getBoundingClientRect().top + window.scrollY - headerOffset;
  window.scrollTo({ top, behavior: 'smooth' });
}

/** 根据当前视口中心的卡片，高亮右侧索引 */
function updateTocActive() {
  const toc = $('#mkt-chart-toc');
  if (!toc || state.view !== 'charts') return;
  const items = toc.querySelectorAll('.mkt-chart-toc-item');
  const cards = CHART_CARDS.map(({ section }) => $(`#mkt-card-${section}`)).filter(Boolean);
  if (!cards.length) return;

  const center = window.innerHeight / 2;
  let activeSection = cards[0].dataset.section;
  let minDist = Infinity;

  cards.forEach(card => {
    const rect = card.getBoundingClientRect();
    const dist = Math.abs(rect.top + rect.height / 2 - center);
    if (dist < minDist) {
      minDist = dist;
      activeSection = card.dataset.section;
    }
  });

  items.forEach(item => {
    item.classList.toggle('active', item.getAttribute('href') === `#mkt-card-${activeSection}`);
  });
}

/**
 * 通用分析卡片 = 图表 + AI 解读。
 *
 * 固定三段结构：卡头（标题/副标题）→ 图表区 → 解读区（按钮 + 结果）。
 * 按钮三态：✨ AI 解读 → 解读中…（禁用）→ 🔄 重新解读。
 * 解读失败只在卡片内降级展示，绝不影响图表本身。
 */
function buildChartCard({ section, title, hint, kind }) {
  const canvasId = `mkt-chart-${section}`;
  const insightId = `mkt-insight-${section}`;

  const body = el('div', { className: 'mkt-insight-body', id: insightId, style: 'display:none;' });
  const btn = el('button', {
    className: 'mkt-ai-btn', type: 'button', id: `mkt-ai-${section}`,
    textContent: '✨ AI 解读',
    onClick: () => runInsight(section, btn, body),
  });

  const chartArea = kind === 'text'
    ? el('div', { className: 'mkt-chart-text', id: canvasId, textContent: '—' })
    : el('div', { className: 'chart-container' },
      el('div', { className: 'chart-wrapper' },
        el('canvas', { id: canvasId })));

  return el('div', { className: 'card mkt-chart-card', 'data-section': section, id: `mkt-card-${section}` },
    el('div', { className: 'mkt-chart-head' },
      el('div', { className: 'mkt-chart-title', textContent: title }),
      el('div', { className: 'mkt-chart-hint', textContent: hint }),
    ),
    chartArea,
    el('div', { className: 'mkt-insight' }, btn, body),
  );
}

/** 拉取图表数据；样本量变化则作废前端已缓存的解读结论 */
async function loadCharts() {
  const sub = $('#mkt-charts-sub');
  try {
    const data = await getMarketCharts(state.filters.keyword || '');
    const prevTotal = state.charts ? state.charts.total : undefined;
    state.charts = data;

    if (prevTotal !== undefined && prevTotal !== data.total) {
      // 数据变过了：旧解读是对着旧样本说的，必须作废
      state.insights = {};
      resetInsightCards();
    }

    if (sub) {
      sub.textContent = data.total
        ? `共 ${data.total} 条岗位样本${data.keyword ? `（关键词：${data.keyword}）` : ''}`
          + `　·　点击任意卡片上的「AI 解读」可获得针对该维度的分析`
        : '暂无数据，请先采集或导入岗位';
    }
    drawAllCharts();
  } catch (e) {
    if (sub) sub.textContent = `图表数据加载失败：${e.message}`;
  }
}

function resetInsightCards() {
  CHART_CARDS.forEach(({ section }) => {
    const btn = $(`#mkt-ai-${section}`);
    const body = $(`#mkt-insight-${section}`);
    if (btn) btn.textContent = '✨ AI 解读';
    if (body) { body.style.display = 'none'; body.innerHTML = ''; }
  });
}

function drawAllCharts() {
  if (!state.charts) return;
  CHART_CARDS.forEach(({ section, kind }) => {
    if (kind === 'text') renderOverviewText(section);
    else drawChart(section, kind);
  });
}

/** overview 卡无图，用文字摘要承载（样本量 + 各维度第一名的速览） */
function renderOverviewText(section) {
  const host = $(`#mkt-chart-${section}`);
  if (!host) return;
  const d = state.charts;
  host.innerHTML = '';

  if (!d.total) { host.textContent = '暂无数据'; return; }

  const topOf = (arr, key) => (arr || []).filter(x => x.count > 0 || x.cnt > 0)[0]?.[key] || '—';
  const rows = [
    ['样本总量', `${d.total} 条`],
    ['最多岗位城市', topOf(d.city, 'city')],
    ['主力薪资档', topOf(d.salary, 'label')],
    ['主流学历', topOf(d.education, 'label')],
    ['主流年资', topOf(d.experience, 'label')],
    ['最高频词汇', topOf(d.skill, 'skill')],
  ];
  rows.forEach(([k, v]) => host.appendChild(
    el('div', { className: 'mkt-chart-text-row' },
      el('span', { className: 'k', textContent: k }),
      el('span', { className: 'v', textContent: v })),
  ));
}

/**
 * 把后端各维度异构结构统一成 {labels, values}。
 * geo 卡降级为柱状图时复用 city 数据，因此这里做一次到 city 的映射。
 */
function pickSeries(section) {
  const key = section === 'geo' ? 'city' : section;
  const raw = (state.charts || {})[key] || [];
  if (section === 'city') return { labels: raw.map(x => x.city), values: raw.map(x => x.cnt) };
  if (section === 'skill') return { labels: raw.map(x => x.skill), values: raw.map(x => x.count) };
  return { labels: raw.map(x => x.label), values: raw.map(x => x.count) };
}

function drawChart(section, kind) {
  const canvas = $(`#mkt-chart-${section}`);
  if (!canvas || typeof window.Chart === 'undefined') return;

  // 重绘前必须销毁旧实例，否则 Chart.js 会报 "Canvas is already in use"
  if (state.chartInstances[section]) {
    state.chartInstances[section].destroy();
    delete state.chartInstances[section];
  }

  const rgb = inkRgb();
  const gridColor = `rgba(${rgb}, 0.12)`;
  const tickColor = `rgba(${rgb}, 0.65)`;
  const base = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
  };

  let config;

  if (kind === 'dual') {
    const raw = state.charts[section] || {};
    config = {
      data: {
        labels: raw.labels || [],
        datasets: [
          {
            type: 'bar', label: '岗位数', yAxisID: 'y',
            data: raw.counts || [], backgroundColor: `${CHART_COLORS[1]}CC`, borderRadius: 3,
          },
          {
            type: 'line', label: '均薪(K)', yAxisID: 'y1',
            data: raw.avg_salaries || [], borderColor: CHART_COLORS[0],
            backgroundColor: CHART_COLORS[0], tension: 0.3, pointRadius: 3,
          },
        ],
      },
      options: {
        ...base,
        plugins: { legend: { display: true, labels: { color: tickColor, boxWidth: 12, font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: tickColor }, grid: { display: false } },
          y: { position: 'left', ticks: { color: tickColor }, grid: { color: gridColor } },
          y1: { position: 'right', ticks: { color: tickColor }, grid: { display: false } },
        },
      },
    };
  } else if (kind === 'doughnut') {
    const { labels, values } = pickSeries(section);
    config = {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: CHART_COLORS.map(c => `${c}D9`),
          borderColor: 'transparent',
        }],
      },
      options: {
        ...base,
        cutout: '58%',
        plugins: {
          legend: {
            display: true, position: 'right',
            labels: { color: tickColor, boxWidth: 12, font: { size: 11 } },
          },
        },
      },
    };
  } else {
    const { labels, values } = pickSeries(section);
    config = {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: values, backgroundColor: `${CHART_COLORS[0]}D9`, borderRadius: 3,
        }],
      },
      options: {
        ...base,
        indexAxis: kind === 'hbar' ? 'y' : 'x',
        scales: {
          x: { ticks: { color: tickColor }, grid: { display: kind === 'hbar' ? 'default' : false, color: gridColor } },
          y: { ticks: { color: tickColor }, grid: { display: kind === 'hbar' ? false : 'default', color: gridColor } },
        },
      },
    };
  }

  state.chartInstances[section] = new window.Chart(canvas.getContext('2d'), config);
}

/* ─────────────────── 岗位地理分布（中国地图）─────────────────── */

let _geoLoaded = null;   // 懒加载缓存：{ geo }

/**
 * 懒加载地图插件与中国 GeoJSON。
 *
 * 两样资产都不小（插件 ~100KB、GeoJSON 0.55MB），打进主包会拖慢首屏，
 * 因此只在真正需要渲染地图时才拉取；用 Promise 缓存避免重复下载。
 */
async function loadGeoModules() {
  if (_geoLoaded) return _geoLoaded;
  const [mod, geoMod] = await Promise.all([
    import('chartjs-chart-geo'),
    import('../assets/china-geo.json'),
  ]);
  // ESM 构建无副作用，控制器与比例尺必须手动注册
  window.Chart.register(
    mod.BubbleMapController, mod.GeoFeature, mod.SizeScale, mod.ProjectionScale,
  );
  _geoLoaded = { geo: geoMod.default || geoMod };
  return _geoLoaded;
}

/**
 * 岗位地理分布：省级底图 + 城市气泡（气泡大小＝岗位数量）。
 *
 * 依赖插件与 GeoJSON 两份外部资产，任一失败都降级为横向柱状图——
 * 卡片不能因为地图不可用就整块空白：信息量的损失远大于样式的损失。
 */
async function drawGeoMap(section) {
  const canvas = $(`#mkt-chart-${section}`);
  if (!canvas || typeof window.Chart === 'undefined') return;

  if (state.chartInstances[section]) {
    state.chartInstances[section].destroy();
    delete state.chartInstances[section];
  }

  const cities = state.charts.city || [];
  const points = [];
  const labels = [];
  cities.forEach(c => {
    const coord = cityCoord(c.city);
    if (!coord) return;                     // 坐标表未收录的城市不打点
    points.push({ longitude: coord[0], latitude: coord[1], value: c.cnt });
    labels.push(c.city);
  });

  if (!points.length) {
    renderGeoFallback(section, '无可用城市坐标');
    return;
  }

  const rgb = inkRgb();
  try {
    const { geo } = await loadGeoModules();
    state.chartInstances[section] = new window.Chart(canvas.getContext('2d'), {
      type: 'bubbleMap',
      data: {
        labels,
        datasets: [{
          label: '岗位数',
          outline: geo.features,
          showOutline: true,
          outlineBorderColor: `rgba(${rgb}, 0.35)`,
          outlineBackgroundColor: `rgba(${rgb}, 0.06)`,
          data: points,
          backgroundColor: 'rgba(196,79,58,0.55)',    // 印章红半透明
          borderColor: 'rgba(150,50,35,0.9)',
          borderWidth: 1,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          projection: { projection: 'mercator' },
          size: { range: [4, 26] },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: item => `${labels[item.dataIndex]}：${points[item.dataIndex].value} 个岗位`,
            },
          },
        },
      },
    });
  } catch (e) {
    renderGeoFallback(section, e.message || '地图资源加载失败');
  }
}

/** 地图不可用时降级为横向柱状图（城市 Top10），保住卡片的信息量 */
function renderGeoFallback(section, reason) {
  drawChart(section, 'hbar');
  const hint = $(`.mkt-chart-card[data-section="${section}"] .mkt-chart-hint`);
  if (hint) hint.textContent = `气泡大小＝岗位数量　·　⚠️ 地图不可用，已降级为柱状图（${reason}）`;
}

/**
 * 触发单张卡片的 AI 解读。
 * 前端按 section 缓存文本，避免切换视图后重复消耗配额（后端另有 5 分钟 TTL）。
 */
async function runInsight(section, btn, body) {
  const fresh = Boolean(state.insights[section]);   // 已有解读 → 这次是"重新解读"
  btn.disabled = true;
  btn.textContent = '解读中…';
  body.style.display = '';
  body.innerHTML = '';
  body.appendChild(el('span', { className: 'mkt-loading' },
    el('span', { className: 'mkt-spinner' }), 'AI 正在分析…'));

  try {
    const res = await getMarketInsight({
      section, keyword: state.filters.keyword || '', fresh,
    });
    if (res && res.error) {
      state.insights[section] = null;
      renderInsightError(body, res.error);
      btn.textContent = '✨ 重试解读';
    } else {
      state.insights[section] = res;
      renderInsight(body, res);
      btn.textContent = '🔄 重新解读';
    }
  } catch (e) {
    state.insights[section] = null;
    renderInsightError(body, e.message || '解读失败');
    btn.textContent = '✨ 重试解读';
  } finally {
    btn.disabled = false;
  }
}

function renderInsight(body, res) {
  body.innerHTML = '';
  const meta = [];
  if (res.cached) meta.push('服务端缓存');
  if (res.model) meta.push(res.model);
  if (meta.length) {
    body.appendChild(el('div', { className: 'mkt-insight-meta', textContent: meta.join(' · ') }));
  }
  // 后端已约束不输出 Markdown，这里用 textContent 渲染（保留换行 + 防 XSS）
  body.appendChild(el('div', { className: 'mkt-insight-text', textContent: res.text || '' }));
}

function renderInsightError(body, message) {
  body.innerHTML = '';
  body.appendChild(el('div', { className: 'mkt-insight-error', textContent: `⚠️ ${message}` }));
}
