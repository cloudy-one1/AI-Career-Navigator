// ===================================================
// marketData.js — 市场数据 Tab（v4.1）
// 还原 job-crawler 采集页 + 岗位列表页设计（纸墨印章风格），
// 支持两套 UI 风格自由切换（浅色公文风 / 深色 SaaS 风，localStorage 记忆）。
// 视图：实时采集 / 岗位库 / 独立岗位详情（可跳转 51job 原文）
// 分析：单选 Gap 分析（/api/gap-analysis）、多选跨岗位对比（/api/cross-job-compare）
// ===================================================

import { $, el, toast } from './utils.js';
import {
  startMarketCrawl, getCrawlStatus, getCityMap, getMarketJob,
  getMarketJobs, getMarketStats, runGapAnalysis, crossJobCompare,
} from './api.js';

const THEME_KEY = 'market_theme';
const ACCENT_KEY = 'market_accent';
const PAGE_SIZE = 20;
const ACCENTS = [
  { id: 'cyan', color: '#6EE7E0' },
  { id: 'pink', color: '#F9A8D4' },
  { id: 'gold', color: '#FCD34D' },
  { id: 'purple', color: '#C4B5FD' },
];

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
};

/** 初始化市场数据 Tab（幂等：已渲染则跳过） */
export function initMarketData() {
  const panel = $('#market-data-panel');
  if (!panel || panel.dataset.ready) return;
  panel.dataset.ready = '1';

  applyTheme(readSavedTheme(), true);
  applyAccent(readSavedAccent(), true);

  panel.append(
    buildTopbar(),
    buildCollectView(),
    buildJobsView(),
    buildDetailView(),
  );

  // 城市映射 + 岗位列表/统计 并行加载
  getCityMap().then(map => {
    state.cityMap = map;
    renderProvinceSelect();
  }).catch(e => toast(e.message || '城市数据加载失败', 'error'));

  refreshJobsAndStats();

  // 主题按钮更新（构建后）
  syncThemeUI();
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
      el('button', { className: 'mkt-topnav-btn', id: 'mkt-nav-jobs', textContent: '岗位库', onClick: () => switchView('jobs') }),
    ),
    el('div', { className: 'mkt-theme-zone' },
      buildAccentPicker(),
      el('button', {
        id: 'mkt-theme-btn', className: 'mkt-theme-toggle',
        onClick: toggleTheme,
      }),
    ),
  );
}

function buildAccentPicker() {
  return el('div', { className: 'mkt-accent-picker', id: 'mkt-accent-picker' },
    ...ACCENTS.map(a => el('button', {
      className: 'mkt-accent-dot',
      style: `background:${a.color};`,
      title: `语义强调色：${a.id}`,
      'data-accent': a.id,
      onClick: () => applyAccent(a.id),
    })),
  );
}

/* ─────────────────── 主题 / 语义色 ─────────────────── */

function readSavedTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === 'paper' || saved === 'dark') return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'paper';
}

function readSavedAccent() {
  const saved = localStorage.getItem(ACCENT_KEY);
  return ACCENTS.some(a => a.id === saved) ? saved : 'cyan';
}

function applyTheme(theme, silent = false) {
  const panel = $('#market-data-panel');
  if (!panel) return;
  panel.classList.toggle('market-theme-dark', theme === 'dark');
  localStorage.setItem(THEME_KEY, theme);
  if (!silent) {
    syncThemeUI();
    toast(theme === 'dark' ? '已切换为深色 SaaS 风' : '已切换为浅色公文风', 'success');
  }
}

function toggleTheme() {
  const panel = $('#market-data-panel');
  const isDark = panel.classList.contains('market-theme-dark');
  applyTheme(isDark ? 'paper' : 'dark');
}

function syncThemeUI() {
  const btn = $('#mkt-theme-btn');
  if (!btn) return;
  const isDark = $('#market-data-panel').classList.contains('market-theme-dark');
  btn.textContent = isDark ? '☀ 浅色公文风' : '🌙 深色 SaaS 风';
}

function applyAccent(accent, silent = false) {
  const panel = $('#market-data-panel');
  if (!panel) return;
  panel.classList.remove(...ACCENTS.map(a => `theme-${a.id}`));
  panel.classList.add(`theme-${accent}`);
  localStorage.setItem(ACCENT_KEY, accent);
  document.querySelectorAll('#mkt-accent-picker .mkt-accent-dot').forEach(dot => {
    dot.classList.toggle('active', dot.dataset.accent === accent);
  });
}

/* ─────────────────── 视图切换 ─────────────────── */

function switchView(view) {
  state.view = view;
  ['collect', 'jobs', 'detail'].forEach(v => {
    $(`#mkt-${v}-view`)?.classList.toggle('active', v === view);
  });
  // 顶栏高亮
  ['collect', 'jobs'].forEach(v => {
    $(`#mkt-nav-${v}`)?.classList.toggle('active', v === view || (view === 'detail' && v === 'jobs'));
  });
  if (view === 'jobs') {
    state.page = 0;
    refreshJobsAndStats();
  }
}

/* ─────────────────── 采集视图 ─────────────────── */

function buildCollectView() {
  const banner = el('div', { className: 'mkt-banner' },
    el('h2', { textContent: '51job 岗位实时采集' }),
    el('p', { textContent: '输入关键词，选择省份与城市，启动 Playwright 后台采集。采完自动写入市场数据库，可立即用于 Gap 分析、跨岗位对比与报告市场基准。' }),
    el('div', { className: 'mkt-count-badge' },
      el('span', { className: 'num', id: 'mkt-total-badge', textContent: '—' }),
      el('span', { className: 'lbl', textContent: '条已收录' }),
    ),
  );

  const formCard = el('div', { className: 'mkt-card mkt-card-pad' },
    el('div', { className: 'mkt-card-title', textContent: '采集设置' }),
    el('p', { className: 'mkt-card-sub', textContent: '支持多城市批量采集；"查询已有数据"在本地岗位库中检索，无需联网。' }),

    el('div', { className: 'mkt-form-grid' },
      el('div', { className: 'mkt-field' },
        el('label', { textContent: '关键词' }),
        el('input', { id: 'mkt-keyword', className: 'mkt-input', placeholder: '如 python / java / 数据分析', maxlength: '50' }),
      ),
      el('div', { className: 'mkt-field' },
        el('label', { textContent: '排序方式' }),
        el('select', { id: 'mkt-sort', className: 'mkt-select' },
          el('option', { value: '0', textContent: '按相关性排序' }),
          el('option', { value: '1', textContent: '最新发布' }),
        ),
      ),
      el('div', { className: 'mkt-field' },
        el('label', { textContent: '采集页数' }),
        el('select', { id: 'mkt-pages', className: 'mkt-select' },
          ...[1, 2, 3, 4, 5].map(p =>
            el('option', { value: String(p), textContent: `${p} 页`, ...(p === 2 ? { selected: '' } : {}) })
          ),
        ),
      ),
      el('div', { className: 'mkt-field' },
        el('label', { textContent: '省份' }),
        el('select', { id: 'mkt-province', className: 'mkt-select', onChange: onProvinceChange },
          el('option', { value: '', textContent: '← 选择省份' }),
        ),
      ),
    ),

    el('div', { className: 'mkt-city-row' },
      el('div', { className: 'mkt-city-chips', id: 'mkt-city-picker' },
        el('span', { className: 'mkt-city-hint', id: 'mkt-city-hint', textContent: '先选省份，再点城市添加（可多选）' }),
      ),
    ),

    el('div', { className: 'mkt-actions' },
      el('button', { id: 'mkt-query-btn', className: 'mkt-btn mkt-btn-ghost', textContent: '查询已有数据', onClick: queryExisting }),
      el('button', { id: 'mkt-crawl-btn', className: 'mkt-btn mkt-btn-primary', textContent: '立即实时采集', onClick: startCrawl }),
    ),

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

    el('div', { className: 'mkt-error', id: 'mkt-error' }),
  );

  return el('div', { className: 'mkt-view active', id: 'mkt-collect-view' }, banner, formCard);
}

function onProvinceChange(e) {
  const prov = e.target.value;
  const picker = $('#mkt-city-picker');
  picker.innerHTML = '';
  if (!prov) {
    picker.appendChild(el('span', { className: 'mkt-city-hint', textContent: '先选省份，再点城市添加（可多选）' }));
    return;
  }
  const cities = state.cityMap[prov] || [];
  const chosen = new Set(state.selectedCities);
  cities.forEach(([city]) => {
    picker.appendChild(el('span', {
      className: 'mkt-chip',
      style: chosen.has(city) ? 'opacity:.55;' : 'cursor:pointer;',
      textContent: city,
      onClick: () => toggleCity(prov, city),
    }));
  });
}

function toggleCity(prov, city) {
  const idx = state.selectedCities.indexOf(city);
  if (idx >= 0) {
    state.selectedCities.splice(idx, 1);
  } else {
    state.selectedCities.push(city);
  }
  // 重绘当前省份城市按钮 + 已选汇总
  const provSel = $('#mkt-province');
  onProvinceChange({ target: provSel });
  renderSelectedSummary();
}

function renderSelectedSummary() {
  const wrap = $('#mkt-city-picker');
  const existing = wrap.querySelector('.mkt-city-summary');
  if (existing) existing.remove();
  if (!state.selectedCities.length) return;
  const summary = el('div', { className: 'mkt-city-summary', style: 'display:contents;' });
  state.selectedCities.forEach(city => {
    summary.appendChild(el('span', { className: 'mkt-chip' },
      city,
      el('button', { textContent: '×', title: '移除', onClick: () => removeCity(city) }),
    ));
  });
  wrap.appendChild(summary);
}

function removeCity(city) {
  const idx = state.selectedCities.indexOf(city);
  if (idx >= 0) state.selectedCities.splice(idx, 1);
  onProvinceChange({ target: $('#mkt-province') });
  renderSelectedSummary();
}

function renderProvinceSelect() {
  const sel = $('#mkt-province');
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
  if (!state.selectedCities.length) { toast('请至少选择一个城市', 'warning'); return; }
  if (state.crawling) { toast('已有采集任务进行中', 'warning'); return; }

  const pages = parseInt($('#mkt-pages').value, 10) || 2;
  const sortType = $('#mkt-sort').value;

  const btn = $('#mkt-crawl-btn');
  btn.disabled = true;
  btn.textContent = '采集进行中…';
  hideError();
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
        setCrawlDone(st.message);
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

function setCrawlDone(message) {
  const bar = $('#mkt-progress');
  bar.classList.add('done');
  showProgress(message, 100, '');
  setTimeout(() => {
    bar.classList.remove('visible', 'done');
    refreshJobsAndStats();
  }, 2200);
}

function setCrawlFailed(error) {
  hideProgress();
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

/* ─────────────────── 岗位库视图 ─────────────────── */

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
      el('div', { className: 'mkt-stat-label', textContent: '热门技能 TOP5' }),
      el('div', { className: 'mkt-skills', id: 'mkt-stat-skills' }),
    ),
    el('div', { className: 'mkt-stat-card' },
      el('div', { className: 'mkt-stat-label', textContent: '样本城市' }),
      el('div', { className: 'mkt-skills', id: 'mkt-stat-cities' }),
    ),
  );

  const filters = el('div', { className: 'mkt-card mkt-filters' },
    el('div', { className: 'mkt-field' },
      el('label', { textContent: '关键词' }),
      el('input', { id: 'mkt-f-keyword', className: 'mkt-input', placeholder: '职位关键词…', onChange: () => { state.filters.keyword = $('#mkt-f-keyword').value.trim(); reloadList(0); } }),
    ),
    el('div', { className: 'mkt-field' },
      el('label', { textContent: '城市' }),
      el('input', { id: 'mkt-f-city', className: 'mkt-input', placeholder: '如 北京 / 上海…', onChange: () => { state.filters.city = $('#mkt-f-city').value.trim(); reloadList(0); } }),
    ),
    el('div', { className: 'mkt-field' },
      el('label', { textContent: '学历' }),
      el('select', { id: 'mkt-f-edu', className: 'mkt-select', onChange: () => { state.filters.education = $('#mkt-f-edu').value; reloadList(0); } },
        el('option', { value: '', textContent: '不限' }),
        el('option', { value: '大专', textContent: '大专' }),
        el('option', { value: '本科', textContent: '本科' }),
        el('option', { value: '硕士', textContent: '硕士' }),
        el('option', { value: '博士', textContent: '博士' }),
      ),
    ),
    el('div', { className: 'mkt-field' },
      el('label', { textContent: '最低薪资(K)' }),
      el('input', { id: 'mkt-f-smin', className: 'mkt-input', type: 'number', min: '0', placeholder: '≥ 0', onChange: () => { state.filters.salaryMin = $('#mkt-f-smin').value; reloadList(0); } }),
    ),
    el('div', { className: 'mkt-field' },
      el('label', { textContent: '最高薪资(K)' }),
      el('input', { id: 'mkt-f-smax', className: 'mkt-input', type: 'number', min: '0', placeholder: '≤ …', onChange: () => { state.filters.salaryMax = $('#mkt-f-smax').value; reloadList(0); } }),
    ),
    el('button', { className: 'mkt-btn mkt-btn-ghost mkt-btn-sm', textContent: '重置筛选', onClick: resetFilters }),
  );

  const tableWrap = el('div', { className: 'mkt-table-wrap' },
    el('table', { className: 'mkt-table' },
      el('thead', {},
        el('tr', {},
          el('th', { style: 'width:44px;', textContent: '#' }),
          el('th', { textContent: '职位 / 公司' }),
          el('th', { textContent: '城市' }),
          el('th', { textContent: '最低薪资' }),
          el('th', { textContent: '最高薪资' }),
          el('th', { textContent: '发布时间' }),
          el('th', { textContent: '操作' }),
          el('th', { className: 'mkt-row-check', textContent: '对比' }),
        ),
      ),
      el('tbody', { id: 'mkt-tbody' },
        el('tr', {},
          el('td', { colSpan: '8', className: 'mkt-empty' },
            el('span', { className: 'mkt-loading' },
              el('span', { className: 'mkt-spinner' }), '加载岗位数据…'),
          ),
        ),
      ),
    ),
  );

  const pagination = el('div', { className: 'mkt-pagination' },
    el('span', { id: 'mkt-page-info', textContent: '' }),
    el('div', { className: 'mkt-page-btns' },
      el('button', { className: 'mkt-page-btn', id: 'mkt-page-prev', textContent: '‹', onClick: () => reloadList(state.page - 1), disabled: true }),
      el('button', { className: 'mkt-page-btn', id: 'mkt-page-cur', textContent: '1' }),
      el('button', { className: 'mkt-page-btn', id: 'mkt-page-next', textContent: '›', onClick: () => reloadList(state.page + 1), disabled: true }),
    ),
  );

  const compareBar = el('div', { className: 'mkt-compare-bar', id: 'mkt-compare-bar' },
    el('span', { textContent: '已选 ' }),
    el('span', { className: 'cnt', id: 'mkt-compare-cnt', textContent: '0' }),
    el('span', { textContent: ' 个岗位' }),
    el('button', { className: 'mkt-btn mkt-btn-sm', textContent: '跨岗位对比', onClick: doCrossCompare }),
    el('button', { className: 'mkt-btn mkt-btn-sm mkt-btn-ghost', textContent: '清空选择', onClick: clearSelection }),
  );

  const compareResult = el('div', { className: 'mkt-compare-result', id: 'mkt-compare-result' });

  return el('div', { className: 'mkt-view', id: 'mkt-jobs-view' }, statsRow, filters, tableWrap, pagination, compareBar, compareResult);
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

async function loadStats() {
  try {
    const s = await getMarketStats(state.filters.keyword || undefined);
    $('#mkt-stat-total').textContent = s.total_samples ?? '—';
    const avg = s.avg_salary_k;
    $('#mkt-stat-salary').innerHTML = avg != null
      ? `${Number(avg).toFixed(1)}<small> K/月</small>` : '<small>—</small>';
    $('#mkt-total-badge').textContent = s.total_samples ?? '—';
    const skills = $('#mkt-stat-skills');
    skills.innerHTML = '';
    (s.top_skills || []).slice(0, 5).forEach(t => skills.appendChild(el('span', { className: 'mkt-skill-tag', textContent: t })));
    if (!(s.top_skills || []).length) skills.textContent = '—';
    const cities = $('#mkt-stat-cities');
    cities.innerHTML = '';
    (s.top_cities || []).slice(0, 5).forEach(c => cities.appendChild(el('span', { className: 'mkt-skill-tag', textContent: c })));
    if (!(s.top_cities || []).length) cities.textContent = '—';
  } catch (e) {
    // 统计失败不阻塞列表
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
  const startNo = state.page * PAGE_SIZE;
  state.items.forEach((job, i) => {
    const no = startNo + i + 1;
    const selected = state.selectedRows.includes(job.id);
    const tr = el('tr', { className: selected ? 'selected' : '', 'data-id': String(job.id) },
      el('td', { className: 'mkt-cell-no', textContent: String(no).padStart(2, '0') }),
      el('td', { className: 'mkt-cell-title' },
        el('a', { textContent: job.title || '—', title: '查看详情', onClick: () => openDetail(job.id) }),
        el('div', { className: 'mkt-cell-company', style: 'font-size:12px;color:var(--mkt-ink-muted);font-weight:400;', textContent: job.company || '' }),
      ),
      el('td', { className: 'mkt-cell-city', textContent: job.city || '—' }),
      el('td', { className: 'mkt-salary', textContent: job.salary_min != null ? `${Number(job.salary_min).toFixed(0)}K` : '面议' }),
      el('td', { className: 'mkt-salary', textContent: job.salary_max != null ? `${Number(job.salary_max).toFixed(0)}K` : '面议' }),
      el('td', { className: 'mkt-date', textContent: formatDate(job.collected_at || '') }),
      el('td', {}, el('div', { className: 'mkt-row-actions' },
        job.url ? el('a', { className: 'mkt-link-51', href: job.url, target: '_blank', rel: 'noopener noreferrer', textContent: '🔗 查看详情' }) : null,
      )),
      el('td', { className: 'mkt-row-check' },
        el('input', { className: 'mkt-checkbox', type: 'checkbox', checked: selected, onChange: e => toggleSelect(job, e.target.checked) }),
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
  $('#mkt-page-info').textContent = `共 ${state.total} 条 · 第 ${state.page + 1} / ${totalPages} 页`;
  $('#mkt-page-cur').textContent = String(state.page + 1);
  $('#mkt-page-prev').disabled = state.page <= 0;
  $('#mkt-page-next').disabled = state.page >= totalPages - 1;
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
  box.innerHTML = '';
  box.appendChild(el('div', { className: 'mkt-card mkt-card-pad' },
    el('div', { className: 'mkt-card-title', textContent: `跨岗位对比（${ids.length} 个岗位）` }),
    el('label', { className: 'mkt-info-label', textContent: '简历内容', style: 'margin-bottom:4px;display:block;' }),
    el('textarea', { id: 'mkt-compare-resume', className: 'mkt-resume-ta', placeholder: '粘贴简历内容，用于与所选岗位逐一对比…' }),
    el('div', { className: 'mkt-analyze-actions' },
      el('button', { className: 'mkt-btn mkt-btn-ghost mkt-btn-sm', textContent: '📋 复用面试 Tab 简历', onClick: () => copyResumeTo('#mkt-compare-resume') }),
      el('button', { className: 'mkt-btn mkt-btn-primary mkt-btn-sm', textContent: '开始对比', onClick: () => runCompare(ids) }),
      el('button', { className: 'mkt-btn mkt-btn-ghost mkt-btn-sm', textContent: '取消', onClick: () => { box.innerHTML = ''; } }),
    ),
  ));
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
    box.appendChild(el('div', { className: 'mkt-error visible', textContent: `对比失败：${e.message}` }));
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
    el('button', { className: 'mkt-detail-back', textContent: '← 返回岗位库', onClick: () => switchView('jobs') }),
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
    body.appendChild(el('div', { className: 'mkt-error visible', textContent: `详情加载失败：${e.message}` }));
  }
}

function renderDetail(body, job, jdText) {
  body.innerHTML = '';
  const no = job.id;

  // 标题区
  const head = el('div', { className: 'mkt-detail-head' },
    el('div', { className: 'mkt-detail-badge' },
      el('span', { className: 'no', textContent: String(no).padStart(3, '0') }),
      el('span', { className: 'lbl', textContent: 'NO.' }),
    ),
    el('div', { className: 'mkt-detail-company' },
      el('span', { textContent: job.company || '—' }),
      el('span', { className: 'dot' }),
      el('span', { textContent: job.source || '' }),
    ),
    el('h1', { className: 'mkt-detail-title', textContent: job.title || '—' }),
    el('div', { className: 'mkt-detail-actions' },
      job.url ? el('a', { className: 'mkt-btn mkt-btn-primary', href: job.url, target: '_blank', rel: 'noopener noreferrer', textContent: '🔗 查看 51job 原文' }) : null,
      el('button', { className: 'mkt-btn mkt-btn-ghost', textContent: '用此岗位做 Gap 分析', onClick: () => { document.querySelector('#mkt-detail-body .mkt-resume-ta')?.scrollIntoView({ behavior: 'smooth' }); } }),
    ),
  );

  // 信息四栏
  const info = el('div', { className: 'mkt-detail-info' },
    infoCell('薪资待遇', job.salary_raw || (job.salary_min != null ? `${Number(job.salary_min).toFixed(1)}-${job.salary_max != null ? Number(job.salary_max).toFixed(1) : '—'}K/月` : '面议')),
    infoCell('学历要求', job.education || '不限'),
    infoCell('经验要求', formatExp(job.exp_min, job.exp_max)),
    infoCell('发布时间', formatDate(job.collected_at || '')),
  );

  // 左：描述全文；右：分析
  const descCard = el('div', { className: 'mkt-desc' },
    el('h3', { textContent: '职位描述' }),
    (job.tags || []).length ? el('div', { className: 'mkt-skills', style: 'margin-bottom:12px;' },
      ...job.tags.map(t => el('span', { className: 'mkt-skill-tag', textContent: t })),
    ) : null,
    el('div', { className: 'mkt-desc-text', textContent: job.description || '（暂无详细描述）' }),
  );

  const analyzeCard = el('div', { className: 'mkt-analyze' },
    el('h3', { textContent: '简历匹配分析' }),
    el('label', { className: 'mkt-info-label', textContent: '简历内容', style: 'margin-bottom:4px;display:block;' }),
    el('textarea', { id: 'mkt-detail-resume', className: 'mkt-resume-ta', placeholder: '粘贴简历内容，至少 10 字…' }),
    el('div', { className: 'mkt-analyze-actions' },
      el('button', { className: 'mkt-btn mkt-btn-ghost mkt-btn-sm', textContent: '📋 复用面试 Tab 简历', onClick: () => copyResumeTo('#mkt-detail-resume') }),
      el('button', { className: 'mkt-btn mkt-btn-primary mkt-btn-sm', textContent: '开始 Gap 分析', onClick: () => doGapAnalysis('#mkt-detail-resume', '#mkt-detail-gap', state.currentJdText) }),
    ),
    el('div', { id: 'mkt-detail-gap' }),
  );

  body.append(head, info,
    el('div', { className: 'mkt-detail-grid' }, descCard, analyzeCard),
  );
}

function infoCell(label, value) {
  return el('div', { className: 'mkt-info-cell' },
    el('div', { className: 'mkt-info-label', textContent: label }),
    el('div', { className: 'mkt-info-value muted', textContent: value }),
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
    box.appendChild(el('div', { className: 'mkt-error visible', textContent: `分析失败：${e.message}` }));
  }
}

function renderGapResult(box, gap) {
  box.innerHTML = '';
  if (!gap || !gap.dimensions) { box.appendChild(el('div', { className: 'mkt-error visible', textContent: '未返回有效的分析结果' })); return; }

  const overall = gap.overall_score || 0;   // 1-5 分制
  const overallPct = Math.round((overall / 5) * 100);
  const riskCls = gap.risk_level === '低' ? 'low' : gap.risk_level === '中' ? 'mid' : 'high';
  const riskColor = gap.risk_level === '低' ? '#059669' : gap.risk_level === '中' ? '#D97706' : '#DC2626';

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
