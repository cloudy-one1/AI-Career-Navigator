// ===================================================
// profileCard.js — 能力档案（v8.0 引入，v8.1 定名）
// ---------------------------------------------------
// 首屏只回答三个问题：**我现在什么水平 / 待提升的是什么 / 下一步该做什么**。
// 三个能力模块在这里降级为"执行入口"——产品主线是档案，不是功能菜单。
//
// 数据来源：GET /api/profile（后端聚合简历/岗位/报告/薄弱点/市场基准 + 建议规则表）。
// 设计纪律：取不到档案就降级渲染，绝不挡住其他功能；空态要给出下一步，
// 而不是一句"暂无数据"。
//
// v8.1 术语：全站统一为专业评测语系，禁用"作战室/弹药/加练"一类游戏化隐喻。
// ===================================================

import { $, el, emptyState, skeletonBlock } from './utils.js';
import { updateJourneyProgress } from './navConfig.js';
import { fetchProfile } from './api.js';

const RADAR_NOW = '#C44F3A';    // 印章红：当前水平
const RADAR_PREV = '#A08945';   // 黄铜：上一场（对比线）

/** 三大能力入口（tab 名与 navConfig 保持一致） */
const CAPABILITIES = [
  { tab: 'market-data', icon: '📊', title: '市场数据',
    desc: '职业定位：看清目标岗位的真实市场基准' },
  { tab: 'interview', icon: '🎙️', title: '模拟面试',
    desc: '面试演练：每完成一场，档案同步更新一次' },
  { tab: 'career-plan', icon: '🧭', title: '职业规划',
    desc: '发展路径：从当前能力水平推演到目标岗位' },
];

let radarChart = null;
let curveChart = null;
let bootstrapped = false;

/** 面板初始化入口（由 app.js 的 tabRegistry 调用，每次切回首屏都会刷新） */
export function initProfile() {
  const panel = $('#home-panel');
  if (!panel) return;
  if (!bootstrapped) {
    panel.appendChild(skeletonBlock({ lines: 4 }));
    bootstrapped = true;
  }
  loadProfile(panel);
}

/** 面板重绘前必须销毁 Chart 实例：canvas 已被 innerHTML 清空，
 *  残留实例持有旧 canvas 引用，既泄漏内存也会让下一次 update() 画到空白上。 */
function resetCharts() {
  if (radarChart) { radarChart.destroy(); radarChart = null; }
  if (curveChart) { curveChart.destroy(); curveChart = null; }
}

async function loadProfile(panel) {
  const profile = await fetchProfile();
  panel.innerHTML = '';
  resetCharts();

  if (!profile) {
    // 档案拿不到时清空完成度标记，避免侧栏停留在上一份的过期状态
    updateJourneyProgress(null);
    panel.appendChild(emptyState({
      icon: '📭', title: '档案暂时打不开',
      desc: '后端档案服务不可用，其余功能不受影响。',
    }));
    panel.appendChild(capabilityRow());   // 入口始终保留：档案挂了也得能干活
    return;
  }

  // v8.1: 档案是五步完成度的唯一来源，侧栏时间线与顶部进度条随它刷新
  updateJourneyProgress(profile.journey);

  panel.appendChild(identityStrip(profile));
  panel.appendChild(nbaCard(profile));
  panel.appendChild(el('div', { className: 'war-grid' },
    radarCard(profile),
    gapsCard(profile),
  ));
  panel.appendChild(capabilityRow());

  const degraded = profile.degraded || [];
  if (degraded.length) panel.appendChild(degradedNote(degraded));
}

/** 跳到指定 tab：复用既有导航项，不另开一套路由逻辑 */
function goTab(tab) {
  if (!tab) return;
  document.querySelector(`.nav-item[data-tab="${tab}"]`)?.click();
}

// ===== 顶部摘要：我是谁 / 我要去哪 / 市场基准 =====

function identityStrip(p) {
  const id = p.identity || {};
  const tg = p.target || {};
  const market = tg.market || {};

  const chips = [
    chip('当前简历', id.has_resume ? (id.title || '简历已上传') : '未上传简历', !id.has_resume),
    chip('目标岗位', tg.has_target ? tg.title : '未选定目标岗位', !tg.has_target),
  ];

  if (market.keyword) {
    const parts = [];
    // avg_salary 有两种口径：数字（旧）或 {avg_k, min_k, max_k}（market.get_stats 现状）
    const salary = market.avg_salary;
    const avgK = typeof salary === 'object' ? salary?.avg_k : salary;
    if (avgK) parts.push(`市场均薪 ${avgK}K`);
    if (market.sample_size) parts.push(`${market.sample_size} 条样本`);
    if (!parts.length && (market.top_skills || []).length) {
      parts.push(`热门技能 ${market.top_skills.slice(0, 3).join('/')}`);
    }
    chips.push(chip('市场基准', parts.join(' · ') || market.keyword, false));
  }

  const skills = id.skills || [];
  if (skills.length) chips.push(chip('核心技能', skills.slice(0, 4).join(' / '), false));

  // v8.1: 技能缺口——目标岗位市场热门、但简历里没体现的。这是"往哪补"的直接答案。
  const missing = (tg.skill_gap || {}).missing || [];
  if (missing.length) chips.push(chip('技能缺口', missing.slice(0, 3).join(' / '), true));

  return el('div', { className: 'profile-strip' }, ...chips);
}

function chip(label, value, warn) {
  return el('div', { className: `profile-chip${warn ? ' is-warn' : ''}` },
    el('span', { className: 'chip-label', textContent: label }),
    el('span', { className: 'chip-value', textContent: value }),
  );
}

// ===== 区块一：下一步最佳动作（NBA）=====

function nbaCard(p) {
  const a = p.next_action;
  if (!a) {
    return el('div', { className: 'nba-card urgency-normal' },
      el('div', { className: 'nba-mark', textContent: '建议' }),
      el('div', { className: 'nba-body' },
        el('div', { className: 'nba-action', textContent: '先上传一份简历' }),
        el('div', { className: 'nba-reason', textContent: '档案还没有起点，后续一切都依赖它。' }),
      ),
      el('button', { className: 'btn btn-primary nba-go', textContent: '去执行 →',
        onclick: () => goTab('resume-library') }),
    );
  }

  return el('div', { className: `nba-card urgency-${a.urgency || 'normal'}` },
    el('div', { className: 'nba-mark', textContent: '建议' }),
    el('div', { className: 'nba-body' },
      el('div', { className: 'nba-action', textContent: a.action }),
      el('div', { className: 'nba-reason', textContent: a.reason || '' }),
    ),
    el('button', { className: 'btn btn-primary nba-go', textContent: '去执行 →',
      onclick: () => goTab(a.target_tab) }),
  );
}

// ===== 区块二：能力雷达 =====

function radarCard(p) {
  const level = p.level || {};
  const dims = level.dimensions || [];

  const card = el('div', { className: 'card war-radar' },
    el('div', { className: 'card-title', textContent: '📡 能力画像' }),
  );

  if (!dims.length) {
    card.appendChild(emptyState({
      icon: '📡', title: '还没有能力数据',
      desc: '完成第一场模拟面试后，这里会画出你的五维能力曲线。',
    }));
    return card;
  }

  card.appendChild(el('div', { className: 'war-radar-meta', textContent: radarMeta(level) }));
  card.appendChild(el('div', { className: 'chart-wrapper' },
    el('canvas', { id: 'war-radar-canvas' })));
  card.appendChild(deltaRow(dims));

  // 成长曲线：少于两个点不成"趋势"，给空态引导而不是画一条无意义的直线
  const history = level.history || [];
  card.appendChild(el('div', { className: 'war-curve-head', textContent: '能力趋势' }));
  if (history.length < 2) {
    card.appendChild(el('div', { className: 'war-curve-empty' },
      '完成第二场模拟面试后，这里会显示历次评分的变化轨迹。'));
  } else {
    card.appendChild(el('div', { className: 'war-curve-wrap' },
      el('canvas', { id: 'war-curve-canvas' })));
    card.appendChild(el('div', { className: 'war-curve-foot',
      textContent: curveFoot(history) }));
  }

  // canvas 必须挂载后再建图（Chart 需要已布局的父容器）
  setTimeout(() => {
    renderRadar(dims);
    if (history.length >= 2) renderCurve(history);
  }, 0);
  return card;
}

/** 趋势脚注：首末两场的差值（进步可见的最小表达） */
function curveFoot(history) {
  const first = Number(history[0]?.overall ?? 0);
  const last = Number(history[history.length - 1]?.overall ?? 0);
  const diff = last - first;
  const sign = diff > 0 ? '+' : (diff < 0 ? '−' : '±');
  const word = diff > 0.05 ? '提升' : (diff < -0.05 ? '回落' : '基本持平');
  return `${history.length} 场记录 · 首末${word} ${sign}${Math.abs(diff).toFixed(2)}`;
}

function renderCurve(history) {
  const canvas = $('#war-curve-canvas');
  if (!canvas || typeof window.Chart === 'undefined') return;

  const labels = history.map(h => (h.at || '').slice(5, 10) || '—');
  const data = history.map(h => Number(h.overall || 0));

  if (curveChart) {
    curveChart.data.labels = labels;
    curveChart.data.datasets[0].data = data;
    curveChart.update();
    return;
  }

  curveChart = new window.Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: '综合评分',
        data,
        borderColor: RADAR_NOW,
        backgroundColor: RADAR_NOW + '18',
        borderWidth: 2,
        pointBackgroundColor: RADAR_PREV,
        pointRadius: 3,
        tension: 0.3,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      scales: {
        y: {
          min: 0, max: 5,
          ticks: { stepSize: 1, font: { size: 10 } },
          grid: { color: 'rgba(218, 214, 204, .7)' },
        },
        x: {
          ticks: { font: { size: 10 } },
          grid: { display: false },
        },
      },
      plugins: {
        legend: { display: false },
      },
    },
  });
}

function radarMeta(level) {
  const parts = [];
  if (typeof level.overall === 'number') parts.push(`加权综合 ${level.overall.toFixed(2)} / 5`);
  if (level.report_count) parts.push(`基于最近 ${level.report_count} 份报告`);
  else if (level.session_count) parts.push(`已开 ${level.session_count} 场（尚无报告）`);
  return parts.join(' · ') || '暂无数据';
}

function deltaRow(dims) {
  const items = dims.filter(d => typeof d.delta === 'number' && Math.abs(d.delta) >= 0.05);
  if (!items.length) return el('div', { className: 'war-delta-empty', textContent: '暂无上一场数据可比' });

  return el('div', { className: 'war-delta-row' },
    ...items.map(d => {
      const up = d.delta > 0;
      return el('span', { className: `war-delta ${up ? 'is-up' : 'is-down'}` },
        el('span', { className: 'war-delta-name', textContent: d.name }),
        el('span', { className: 'war-delta-val', textContent: `${up ? '↑' : '↓'} ${Math.abs(d.delta).toFixed(2)}` }),
      );
    }),
  );
}

function renderRadar(dims) {
  const canvas = $('#war-radar-canvas');
  if (!canvas || typeof window.Chart === 'undefined') return;

  const labels = dims.map(d => d.name);
  const now = dims.map(d => Number(d.score || 0));
  // 上一场 = 当前 - 环比 delta；无 delta 时该点留空（断点如实呈现，不编造）
  const prev = dims.map(d => (typeof d.delta === 'number' ? Number((d.score - d.delta).toFixed(2)) : null));

  if (radarChart) {
    radarChart.data.labels = labels;
    radarChart.data.datasets[0].data = now;
    radarChart.data.datasets[1].data = prev;
    radarChart.update();
    return;
  }

  radarChart = new window.Chart(canvas.getContext('2d'), {
    type: 'radar',
    data: {
      labels,
      datasets: [
        {
          label: '当前水平', data: now,
          borderColor: RADAR_NOW, backgroundColor: RADAR_NOW + '22',
          borderWidth: 2, pointBackgroundColor: RADAR_NOW, pointRadius: 4,
        },
        {
          label: '上一场', data: prev,
          borderColor: RADAR_PREV, backgroundColor: RADAR_PREV + '18',
          borderWidth: 2, borderDash: [5, 4],
          pointBackgroundColor: RADAR_PREV, pointRadius: 3, spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      animation: { duration: 400 },
      scales: {
        r: {
          min: 0, max: 5,
          ticks: { stepSize: 1, backdropColor: 'transparent', font: { size: 10 } },
          pointLabels: { font: { size: 12, weight: '500' } },
          grid: { color: 'rgba(218, 214, 204, .8)' },
          angleLines: { color: 'rgba(218, 214, 204, .8)' },
        },
      },
      plugins: {
        legend: { position: 'bottom', labels: { padding: 12, font: { size: 11 } } },
      },
    },
  });
}

// ===== 区块三：待提升项 =====

function gapsCard(p) {
  const gaps = (p.gaps || []).slice(0, 3);
  const card = el('div', { className: 'card war-gaps' },
    el('div', { className: 'card-title', textContent: '🎯 待提升项' }));

  if (!gaps.length) {
    card.appendChild(emptyState({
      icon: '✅', title: '暂无突出短板',
      desc: '当前各维度均已达标，保持复测即可。',
    }));
    return card;
  }

  gaps.forEach((g, i) => {
    card.appendChild(el('div', { className: 'gap-item', onclick: () => goTab(g.action_tab) },
      el('span', { className: 'gap-no', textContent: String(i + 1) }),
      el('div', { className: 'gap-main' },
        el('div', { className: 'gap-title', textContent: g.name }),
        el('div', { className: 'gap-desc', textContent: gapDesc(g) }),
      ),
      el('span', { className: 'gap-sev', textContent: `薄弱度 ${g.severity}` }),
    ));
  });
  return card;
}

function gapDesc(g) {
  const parts = [];
  if (typeof g.current === 'number') parts.push(`当前 ${g.current} → 目标 ${g.target}`);
  if (g.occurrence > 1) parts.push(`连续 ${g.occurrence} 次失分`);
  if ((g.evidence || []).length) parts.push(g.evidence.join('；'));
  return parts.join(' · ');
}

// ===== 区块四：三大能力入口 =====

function capabilityRow() {
  return el('div', { className: 'war-caps' },
    ...CAPABILITIES.map(c => el('div', {
      className: 'card card-hover war-cap', onclick: () => goTab(c.tab),
    },
      el('div', { className: 'war-cap-icon', textContent: c.icon }),
      el('div', { className: 'war-cap-title', textContent: c.title }),
      el('div', { className: 'war-cap-desc', textContent: c.desc }),
    )),
  );
}

// ===== 降级提示（诚实呈现，不假装数据完整）=====

const DEGRADED_LABELS = {
  identity: '简历画像', target: '目标岗位', level: '能力数据', gaps: '薄弱点',
};

function degradedNote(degraded) {
  const names = degraded.map(d => DEGRADED_LABELS[d] || d).join('、');
  return el('div', { className: 'war-degraded' },
    `⚠️ 以下档案数据暂不可用：${names}。其余功能不受影响。`);
}
