// ===================================================
// memoryGraph.js — 长期记忆（2D SVG 薄弱点图谱，v6.3）
// 借鉴 HakiMeet MemoryView 的 2D 图谱；只做 2D 一套，不做 3D 双轨。
// 关键纪律：
//  - 布局按固定画布基准算（LAYOUT_BASE_W），画布变窄时整体缩放而非重排——
//    节点尺寸由 CSS 定死，真按窄画布重排只会越挤越压盖；
//  - 平移缩放走 transform 合成层，缩放不重算 SVG 路径；
//  - 每维度子节点数按维度数分级（2~4），超出聚合为 "+N"，防 DOM 爆炸；
//  - 哈希只用于小幅抖动，保证刷新不跳位；重叠由松弛（AABB 分离 + 退火）兜底；
//  - 样式只写图谱画布自身（memory.css），组件类复用全局层。
// ===================================================

import { $, el, DIM_NAMES, toast, confirm as confirmDialog, emptyState } from './utils.js';
import { getWeaknessPoints, resolveWeakness, deleteWeakness, getGlobalWeaknessProfile, listPositions, fetchProfile } from './api.js';

// ── 画布几何（viewBox 与 DOM 百分比共用同一坐标系）──
// 画布放大到 1200×800：节点是 DOM 元素、尺寸由 CSS 定死（px），
// 只有画布坐标系够大，百分比定位下的节点之间才留得出间距。
const VB_W = 1200, VB_H = 800;
const CX = VB_W / 2, CY = VB_H / 2;

// 布局固定按这个画布宽度来算节点占位；实际画布比它窄时不再重排，
// 而是整体等比缩小画布内容（见 renderGraph 里的 fit）。
// 为什么不能直接按真实宽度重排：节点是 DOM 元素、尺寸由 CSS 定死，
// 画布越窄，节点在 viewBox 坐标系里相对越大，重排必然越挤直至压盖。
const LAYOUT_BASE_W = 700;

// ── 松弛参数（布局后处理，用于消除残余重叠）──
const RELAX_ITER = 300;     // 松弛迭代轮数
const ANCHOR_PULL = 0.08;   // 初始的锚点回归力（逐轮退火衰减，见 relax）
const GAP_X = 16;           // 节点间最小水平间隙（CSS px，运行时换算到 viewBox）
const GAP_Y = 12;           // 节点间最小垂直间隙
const EDGE_GAP = 18;        // 距画布边缘留白

// ── 视图状态（模块级；面板惰性初始化后常驻）──
const view = {
  ready: false,
  data: [],
  includeResolved: false,
  scale: 1, panX: 0, panY: 0,
  fit: 1,               // 画布窄于布局基准时的整体缩放（见 LAYOUT_BASE_W）
  applyTransform: null, // bindPanZoom 注入：fit 变化后重新应用 transform
  // v8.4: 岗位隔离——能力画像和薄弱点针对特定岗位
  positionId: null,     // 当前选中的岗位 ID（null = 全部岗位）
  positions: [],         // 岗位库列表（供选择器使用）
};

/** FNV-1a 字符串哈希 → [0,1)。确定性布局的种子来源。 */
function fnv1a(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

/** 节点严重度分级：分数越低越危险；已解决统一降为灰色。 */
function tierOf(p) {
  if (Number(p.resolved) === 1) return 'resolved';
  const s = Number(p.avg_score) || 0;
  if (s < 2.5) return 'danger';
  if (s < 3.5) return 'warn';
  return 'info';
}

/** 维度显示名（后端存的是维度 key，兼容未知自定义维度） */
function dimLabel(name) {
  return DIM_NAMES[name] || name;
}

/**
 * 估算标签的像素宽度：布局发生在渲染之前，拿不到真实 DOM 尺寸，
 * 只能按字符宽度估算——中文按 1 个字宽，英数按 0.55 个字宽。
 */
function estimateLabelPx(text, fontSize, maxWidth, padX = 24) {
  let w = 0;
  for (const ch of String(text)) {
    w += /[\u3000-\u9fff\uff00-\uffef]/.test(ch) ? fontSize : fontSize * 0.55;
  }
  return Math.min(w + padX, maxWidth);   // padX = 左右内边距 + 左右边框
}

/** 构造参与松弛的矩形盒；hw/hh 是 viewBox 单位下的半宽、半高。 */
function makeBox(x, y, wPx, hPx, k) {
  return {
    x, y,
    ax: x, ay: y,                      // ax/ay：初始锚点，松弛时用来拉回原位
    hw: (wPx / 2) * k,
    hh: (hPx / 2) * k,
  };
}

/**
 * 每维度渲染几个子节点：维度越多，扇区越窄，铺得开的数量越少，
 * 其余聚合为 "+N"（右侧明细栏仍能看到全部）。
 * 布局基准固定，所以这取决于维度数，与画布实际宽度无关。
 */
function maxSubsFor(dimCount) {
  if (dimCount >= 6) return 2;
  if (dimCount >= 4) return 3;
  return 4;
}

/**
 * 布局三步走：维度环布 → 子节点沿切向铺开 → 松弛去重叠。
 *
 * 为什么必须有松弛：子节点是 DOM 标签，宽度随文字长短浮动，
 * 纯几何分布算不出真实占位，光靠调半径挡不住压盖。
 * 松弛用矩形 AABB 分离兜底，再靠锚点回归把结构拉回环形，
 * 兼顾「不重叠」与「仍然像一张以核心为中心的图谱」。
 */
function layout(points) {
  // CSS 像素 → viewBox 单位。节点尺寸用 px 计、位置用 viewBox 计，必须换算。
  const k = VB_W / LAYOUT_BASE_W;

  const byDim = new Map();
  for (const p of points) {
    const key = p.dimension || 'unknown';
    if (!byDim.has(key)) byDim.set(key, []);
    byDim.get(key).push(p);
  }
  const dims = [...byDim.entries()];
  const n = Math.max(dims.length, 1);

  // 维度越多，环铺得越大（保证相邻扇区间距），子节点群相应收紧。
  // 注意 dimR 不能为 0：单维度时若半径取 0，维度节点会与中心节点重叠。
  const dimR = Math.min(290, n <= 1 ? 170 : 120 + n * 28);
  // 相邻维度中心距的一半 = 本扇区的可用半宽。子节点沿切向铺开不能越界，
  // 否则相邻两维的子节点群会互相侵入——这是维度一多就重叠的主因。
  const sectorHalf = n <= 1 ? dimR * 1.8 : dimR * Math.sin(Math.PI / n);
  const subAlong = Math.max(50, Math.min(n <= 3 ? 175 : 150,
                                         sectorHalf - (132 / 2) * k * 0.55));
  const subOut = n <= 3 ? 110 : 95;      // 子节点沿径向的伸展
  const maxSubs = maxSubsFor(n);

  const dimNodes = [], subNodes = [];

  dims.forEach(([name, list], i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    // 未解决比例越高，维度环越向内收（视觉上"短板更贴核心"）
    const openRatio = list.filter(p => Number(p.resolved) !== 1).length / list.length;
    const r = dimR * (1 - openRatio * 0.1);
    const dx = CX + r * Math.cos(angle);
    const dy = CY + r * Math.sin(angle);
    const label = dimLabel(name);

    // padX 28 / 42 分别对应 CSS 里 .mnode-dim（5px 13px）与 .mnode-center（8px 20px）
    const dn = makeBox(dx, dy, estimateLabelPx(label, 12, 170, 28), 28, k);
    dn.name = name; dn.label = label; dn.points = list;
    dn.overflow = Math.max(0, list.length - maxSubs);
    dimNodes.push(dn);

    // 子节点沿「切向」铺开而非绕维度节点转圈：
    // 切向是相邻维度之间的空隙方向，径向（朝画布外）空间最紧张，
    // 所以让子节点横向排队、径向只做奇偶分层，既排得开又不顶到画布边缘。
    const ax = Math.cos(angle), ay = Math.sin(angle);      // 径向单位向量
    const tx = -ay, ty = ax;                               // 切向单位向量
    const subs = list.slice(0, maxSubs);
    subs.forEach((p, j) => {
      const t = subs.length === 1 ? 0 : j / (subs.length - 1) - 0.5;
      // 哈希只做小幅抖动，保证刷新位置稳定（不跳位）
      const along = t * 2 * subAlong + (fnv1a(`sub-${p.id}`) - 0.5) * 18;
      const outward = (j % 2 ? 1 : -0.45) * subOut + (fnv1a(`r-${p.id}`) - 0.5) * 14;
      const text = (p.risk_points && p.risk_points[0]) || `${dimLabel(p.dimension)} 短板`;
      const sn = makeBox(dx + tx * along + ax * outward,
                         dy + ty * along + ay * outward,
                         estimateLabelPx(text, 11, 132), 24, k);
      sn.point = p; sn.text = text; sn.parent = dn;
      subNodes.push(sn);
    });
  });

  const center = makeBox(CX, CY, estimateLabelPx('薄弱点图谱', 13, 210, 42), 36, k);
  relax([...subNodes, ...dimNodes], center, k);

  return { center, dims: dimNodes, subs: subNodes };
}

/**
 * 松弛：两两分离 → 让开中心 → 回归锚点 → 收进画布。
 * 沿重叠较小的那根轴推开，位移最小，不会把节点甩得太远。
 */
function relax(movers, center, k) {
  const padX = GAP_X * k, padY = GAP_Y * k, edge = EDGE_GAP * k;

  for (let it = 0; it < RELAX_ITER; it++) {
    for (let i = 0; i < movers.length; i++) {
      for (let j = i + 1; j < movers.length; j++) {
        separate(movers[i], movers[j], padX, padY, false);
      }
    }
    // 中心节点固定：由 mover 承担全部位移
    for (const m of movers) separate(m, center, padX, padY, true);

    // 退火：回归力逐轮衰减。前期靠它保住环形结构，后期放手让分离力主导——
    // 否则两股力长期互相拉扯，收敛不到「零重叠」。
    const pull = ANCHOR_PULL * (1 - it / RELAX_ITER);
    for (const m of movers) {
      m.x += (m.ax - m.x) * pull;
      m.y += (m.ay - m.y) * pull;
      m.x = Math.min(Math.max(m.x, m.hw + edge), VB_W - m.hw - edge);
      m.y = Math.min(Math.max(m.y, m.hh + edge), VB_H - m.hh - edge);
    }
  }
}

function separate(a, b, padX, padY, bFixed) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const ox = (a.hw + b.hw + padX) - Math.abs(dx);
  const oy = (a.hh + b.hh + padY) - Math.abs(dy);
  if (ox <= 0 || oy <= 0) return;           // 未重叠
  const share = bFixed ? 1 : 0.5;           // 对方固定时，自己全额让位
  if (ox < oy) {
    const s = (dx >= 0 ? 1 : -1) * ox * share;
    a.x -= s;
    if (!bFixed) b.x += s;
  } else {
    const s = (dy >= 0 ? 1 : -1) * oy * share;
    a.y -= s;
    if (!bFixed) b.y += s;
  }
}

function linkPath(x1, y1, x2, y2) {
  // 二次贝塞尔：控制点取中点垂直偏移，让连线带一点弧度
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  const k = 0.12;
  const cx = mx - (y2 - y1) * k, cy = my + (x2 - x1) * k;
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}

/** 主入口：面板惰性初始化（与 initHistory 同构） */
export function initMemory() {
  const panel = $('#memory-panel');
  if (!panel || view.ready) return;
  view.ready = true;

  // v8.x: 能力画像（历史累积）从历史记录页迁移到长期记忆页
  panel.appendChild(el('div', { id: 'weakness-profile', className: 'card' },
    el('div', { className: 'card-title', textContent: '📊 能力画像（历史累积）' }),
    el('div', { id: 'weakness-profile-content', className: 'weakness-profile-content' },
      el('div', { className: 'skeleton', 'aria-hidden': 'true' },
        el('div', { className: 'skeleton-line title' }),
        el('div', { className: 'skeleton-line w100' }),
        el('div', { className: 'skeleton-line w80' }),
        el('div', { className: 'skeleton-line w60' }),
      ),
    ),
  ));

  // 页头（v8.4: 增加岗位选择器）
  panel.appendChild(el('div', { className: 'memory-header card card-hover' },
    el('div', { className: 'memory-header-main' },
      el('div', { className: 'card-title', textContent: '🧠 长期记忆' }),
      el('div', { id: 'memory-stats', className: 'memory-stats' }),
    ),
    el('div', { className: 'memory-header-actions' },
      // v8.4: 岗位选择器——能力画像和薄弱点针对特定岗位
      el('select', {
        id: 'memory-position-filter',
        className: 'form-select form-select-sm',
        onchange: (e) => { view.positionId = e.target.value || null; loadMemory(); loadWeaknessProfile(); },
      },
        el('option', { value: '', textContent: '全部岗位' }),
      ),
      el('label', { className: 'memory-toggle' },
        Object.assign(el('input', { type: 'checkbox', id: 'memory-include-resolved' }),
          { checked: false, onchange: () => { view.includeResolved = !view.includeResolved; loadMemory(); } }),
        el('span', { textContent: '显示已解决' }),
      ),
      el('button', { className: 'btn btn-secondary btn-sm btn-press', id: 'memory-refresh',
                     textContent: '刷新', onclick: () => { loadMemory(); loadWeaknessProfile(); } }),
    ),
  ));

  // 主区：图谱 + 明细
  const layoutBox = el('div', { className: 'memory-layout' },
    el('div', { className: 'memory-graph-wrap' },
      el('div', { id: 'memory-viewport', className: 'memory-viewport' },
        el('div', { id: 'memory-canvas', className: 'memory-canvas' },
          // preserveAspectRatio 必须是 none：viewBox 坐标线性铺满容器，才能和
          // 用百分比定位的 DOM 节点严格对齐。用 meet 的话，一旦 min-height
          // 打破 3:2 宽高比，SVG 会居中留白缩放，连线就与节点错位了。
          el('svg', { viewBox: `0 0 ${VB_W} ${VB_H}`, id: 'memory-svg',
                      preserveAspectRatio: 'none' }),
          el('div', { id: 'memory-nodes', className: 'memory-nodes' }),
        ),
      ),
      // 图例放在画布外：画布内只留图谱，悬浮图例会压住右下角的节点
      el('div', { className: 'memory-legend' },
        legendDot('danger', '严重（<2.5）'), legendDot('warn', '待补强（2.5-3.5）'),
        legendDot('info', '尚可（≥3.5）'), legendDot('resolved', '已解决'),
      ),
    ),
    el('div', { className: 'memory-detail-wrap' },
      el('div', { className: 'card', id: 'memory-detail-card' },
        el('div', { className: 'card-title', textContent: '📋 薄弱点明细' }),
        el('div', { id: 'memory-detail' }),
      ),
    ),
  );
  panel.appendChild(layoutBox);

  bindPanZoom($('#memory-viewport'), $('#memory-canvas'));

  // 画布宽度会随窗口变化（含 1024px 断点切换单/双栏）。布局按固定基准算，
  // 所以不必重排，只需重算适配缩放；变化很小时跳过，避免抖动。
  window.addEventListener('resize', () => {
    const vp = $('#memory-viewport');
    if (!vp || !view.data.length) return;
    const fit = Math.min(1, vp.clientWidth / LAYOUT_BASE_W);
    if (Math.abs(fit - view.fit) > 0.01) {
      view.fit = fit;
      if (view.applyTransform) view.applyTransform();
    }
  });

  loadMemory();
  loadWeaknessProfile();

  // v8.4: 加载岗位列表 + 从档案获取默认目标岗位
  loadPositionSelector();
}

function legendDot(tier, label) {
  return el('span', { className: 'legend-item' },
    el('span', { className: `legend-dot tier-${tier}` }),
    el('span', { textContent: label }),
  );
}

async function loadWeaknessProfile() {
  const container = $('#weakness-profile-content');
  if (!container) return;
  try {
    let data = await getGlobalWeaknessProfile(view.positionId);
    let profile = data.profile || [];
    let fallback = false;
    // v8.x: 若当前岗位筛选无数据，但全局有数据，自动 fallback 到全部岗位，
    // 避免"面过试但长期记忆为空"的误解（粘贴 JD 面试时 position_id 为 None）。
    if (profile.length === 0 && view.positionId) {
      const globalData = await getGlobalWeaknessProfile(null);
      const globalProfile = globalData.profile || [];
      if (globalProfile.length > 0) {
        profile = globalProfile;
        fallback = true;
        view.positionId = null;
        const sel = $('#memory-position-filter');
        if (sel) sel.value = '';
      }
    }
    if (profile.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><div class="empty-text">完成面试后，这里将展示你的能力画像</div></div>';
      return;
    }
    container.innerHTML = '';
    if (fallback) {
      container.appendChild(el('div', {
        style: 'font-size:.78rem;color:var(--text-secondary);margin-bottom:10px;',
        textContent: '当前岗位暂无历史画像，已自动展示全部岗位数据',
      }));
    }
    profile.forEach(p => {
      const dimName = DIM_NAMES[p.dimension] || p.dimension;
      const score = p.historical_avg;
      const color = score >= 4 ? 'var(--success)' : (score >= 3 ? 'var(--warning)' : 'var(--danger)');
      container.appendChild(el('div', { className: 'weakness-profile-item' },
        el('div', { className: 'weakness-dim-name', textContent: dimName }),
        el('div', { className: 'weakness-dim-bar' },
          el('div', { className: 'weakness-dim-fill', style: `width:${score * 20}%;background:${color};` }),
        ),
        el('div', { className: 'weakness-dim-score', textContent: score.toFixed(1) }),
        el('div', { className: 'weakness-dim-meta', textContent: `${p.session_count} 次面试 · 权重 ${(p.avg_weight * 100).toFixed(0)}%` }),
      ));
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-text">加载画像失败</div></div>`;
  }
}

// ===== v8.4: 岗位选择器 =====

async function loadPositionSelector() {
  const sel = $('#memory-position-filter');
  if (!sel) return;

  // 并行加载：岗位列表 + 档案（取默认目标岗位）
  const [posData, profile] = await Promise.allSettled([
    listPositions(100),
    fetchProfile(),
  ]);

  // 填充岗位选项
  const positions = (posData.status === 'fulfilled' && posData.value)
    ? (posData.value.positions || []) : [];
  view.positions = positions;
  positions.forEach(p => {
    sel.appendChild(el('option', { value: p.id, textContent: p.title || p.id }));
  });

  // 设置默认选中：档案的目标岗位
  const targetId = (profile.status === 'fulfilled' && profile.value)
    ? (profile.value.target_position_id || null) : null;
  if (targetId) {
    view.positionId = targetId;
    sel.value = targetId;
    // 默认选中后刷新数据
    loadMemory();
    loadWeaknessProfile();
  }
}

// ===== 数据加载与渲染 =====

async function loadMemory() {
  const detail = $('#memory-detail');
  const nodes = $('#memory-nodes');
  const svg = $('#memory-svg');
  try {
    let res = await getWeaknessPoints(view.includeResolved, 200, view.positionId);
    let points = res.points || [];
    let fallback = false;
    // v8.x: 当前岗位筛选无数据时自动 fallback 到全部岗位（与 loadWeaknessProfile 一致）
    if (points.length === 0 && view.positionId) {
      const globalRes = await getWeaknessPoints(view.includeResolved, 200, null);
      const globalPoints = globalRes.points || [];
      if (globalPoints.length > 0) {
        points = globalPoints;
        fallback = true;
        view.positionId = null;
        const sel = $('#memory-position-filter');
        if (sel) sel.value = '';
      }
    }
    view.data = points;
    view._fallback = fallback;
    renderStats();
    renderGraph(svg, nodes);
    renderDetail(detail);
  } catch (e) {
    if (detail) { detail.innerHTML = ''; detail.appendChild(emptyState({
      icon: '⚠️', title: '加载失败', desc: String(e.message || e) })); }
  }
}

function renderStats() {
  const box = $('#memory-stats');
  if (!box) return;
  const total = view.data.length;
  const open = view.data.filter(p => Number(p.resolved) !== 1).length;
  const dims = new Set(view.data.map(p => p.dimension)).size;
  box.innerHTML = '';
  box.append(
    statChip('未解决', open, open > 0 ? 'hot' : ''),
    statChip('已解决', total - open),
    statChip('覆盖维度', dims),
  );
}

function statChip(label, value, extra = '') {
  const chip = el('span', { className: `stat-chip ${extra}` });
  chip.append(el('b', { textContent: String(value) }), el('span', { textContent: label }));
  return chip;
}

function renderGraph(svg, nodes) {
  svg.innerHTML = '';
  nodes.innerHTML = '';
  if (!view.data.length) return;

  // 布局按固定基准算，与实际宽度无关；画布比基准窄时整体缩小画布内容，
  // 窄到什么程度都不会把节点挤到压盖（详见 LAYOUT_BASE_W 的注释）。
  const vp = $('#memory-viewport');
  const vw = vp ? vp.clientWidth : LAYOUT_BASE_W;
  view.fit = Math.min(1, vw / LAYOUT_BASE_W);
  const g = layout(view.data);
  if (view.applyTransform) view.applyTransform();

  // 连线层：中心 → 维度 → 子节点（缩放只动 canvas 的 transform，路径不重算）
  const frag = document.createDocumentFragment();
  for (const d of g.dims) {
    frag.appendChild(pathEl(linkPath(CX, CY, d.x, d.y), 'mlink-dim', `dim-${slug(d.name)}`));
  }
  for (const s of g.subs) {
    frag.appendChild(pathEl(linkPath(s.parent.x, s.parent.y, s.x, s.y),
                            'mlink-sub', `pt-${s.point.id}`));
  }
  svg.appendChild(frag);

  // 节点层（DOM，按 viewBox 百分比定位，与 SVG 同步缩放）
  const center = nodeEl('memory-node mnode-center', g.center.x, g.center.y, '0');
  center.appendChild(el('span', { className: 'mnode-label', textContent: '薄弱点图谱' }));
  nodes.appendChild(center);

  for (const d of g.dims) {
    const dn = nodeEl(`memory-node mnode-dim tier-${dominantTier(d)}`, d.x, d.y, `dim-${slug(d.name)}`);
    dn.appendChild(el('span', { className: 'mnode-label', textContent: d.label }));
    if (d.overflow > 0) {
      dn.appendChild(el('span', { className: 'mnode-overflow', textContent: `+${d.overflow}` }));
    }
    nodes.appendChild(dn);
  }

  for (const s of g.subs) {
    const p = s.point;
    const n = nodeEl(`memory-node mnode-point tier-${tierOf(p)}`, s.x, s.y, `pt-${p.id}`,
                     `薄弱点 ${p.id}`);
    n.appendChild(el('span', {
      className: 'mnode-label',
      textContent: s.text,
      title: p.risk_points ? p.risk_points.join('；') : '',
    }));
    n.addEventListener('click', () => focusDetail(p.id));
    nodes.appendChild(n);
  }
}

function pathEl(d, cls, linkKey) {
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', d);
  p.setAttribute('class', cls);
  p.dataset.link = linkKey;
  return p;
}

function nodeEl(cls, x, y, key, ariaLabel) {
  const n = el('div', { className: cls });
  if (ariaLabel) n.setAttribute('role', 'button');
  n.style.left = `${(x / VB_W) * 100}%`;
  n.style.top = `${(y / VB_H) * 100}%`;
  n.dataset.node = key;
  n.dataset.pid = key.startsWith('pt-') ? key.slice(3) : '';
  n.addEventListener('mouseenter', () => setLinkHot(key, true));
  n.addEventListener('mouseleave', () => setLinkHot(key, false));
  return n;
}

function setLinkHot(key, on) {
  const svg = $('#memory-svg');
  if (!svg) return;
  const path = svg.querySelector(`path[data-link="${CSS.escape(key)}"]`);
  if (path) path.classList.toggle('hot', on);
}

function slug(name) {
  return String(name).replace(/[^a-zA-Z0-9_\u4e00-\u9fa5-]/g, '') || 'dim';
}

function dominantTier(d) {
  const open = d.points.filter(p => Number(p.resolved) !== 1);
  const pool = open.length ? open : d.points;
  const min = Math.min(...pool.map(p => Number(p.avg_score) || 5));
  return min < 2.5 ? 'danger' : min < 3.5 ? 'warn' : 'info';
}

// ===== 明细栏（与图谱双向联动）=====

function renderDetail(container) {
  if (!container) return;
  container.innerHTML = '';
  if (!view.data.length) {
    container.appendChild(emptyState({
      icon: '🌱',
      title: '还没有长期记忆',
      desc: '完成几场模拟面试后，反复失分的维度会自动沉淀到这里；' +
            '下一场面试将优先考察这些短板，补掉一个就标记一个。',
    }));
    return;
  }

  if (view._fallback) {
    container.appendChild(el('div', {
      style: 'font-size:.78rem;color:var(--text-secondary);margin-bottom:10px;',
      textContent: '当前岗位暂无长期记忆，已自动展示全部岗位数据',
    }));
  }

  const byDim = new Map();
  for (const p of view.data) {
    const key = p.dimension || 'unknown';
    if (!byDim.has(key)) byDim.set(key, []);
    byDim.get(key).push(p);
  }

  for (const [dim, list] of byDim) {
    const group = el('div', { className: 'memory-group' },
      el('div', { className: 'memory-group-title' },
        el('span', { textContent: dimLabel(dim) }),
        el('span', { className: 'stat-chip' },
          el('b', { textContent: String(list.filter(p => Number(p.resolved) !== 1).length) }),
          el('span', { textContent: '未解决' })),
      ),
    );
    for (const p of list) group.appendChild(detailItem(p));
    container.appendChild(group);
  }
}

function detailItem(p) {
  const resolved = Number(p.resolved) === 1;
  const risks = (p.risk_points || []).slice(0, 2);
  const item = el('div', { className: `memory-item card-hover tier-${tierOf(p)}${resolved ? ' is-resolved' : ''}` },
    el('div', { className: 'memory-item-head' },
      el('span', { className: 'memory-item-score', textContent: `均分 ${Number(p.avg_score).toFixed(1)}` }),
      el('span', { className: 'memory-item-dim', textContent: dimLabel(p.dimension) }),
      resolved ? el('span', { className: 'memory-resolved-tag', textContent: '已解决' }) : null,
    ),
    risks.length ? el('ul', { className: 'memory-item-risks' },
      ...risks.map(r => el('li', { textContent: r }))) : null,
    el('div', { className: 'memory-item-actions' },
      el('button', {
        className: 'btn btn-sm btn-secondary btn-press',
        textContent: resolved ? '恢复未解决' : '标记已解决',
        onclick: async () => {
          try {
            await resolveWeakness(p.id, !resolved);
            toast(resolved ? '已恢复为未解决' : '太棒了，又补掉一块短板！', 'success');
            loadMemory();
          } catch (e) { toast(`操作失败：${e.message || e}`, 'error'); }
        },
      }),
      el('button', {
        className: 'btn btn-sm btn-danger btn-press', textContent: '删除',
        onclick: async () => {
          const ok = await confirmDialog('删除后不可恢复，确定删除这条薄弱点记录吗？',
            { title: '删除薄弱点', okText: '删除', danger: true });
          if (!ok) return;
          try {
            await deleteWeakness(p.id);
            toast('已删除', 'success');
            loadMemory();
          } catch (e) { toast(`删除失败：${e.message || e}`, 'error'); }
        },
      }),
    ),
  );
  item.dataset.pid = String(p.id);
  item.addEventListener('mouseenter', () => setLinkHot(`pt-${p.id}`, true));
  item.addEventListener('mouseleave', () => setLinkHot(`pt-${p.id}`, false));
  return item;
}

/** 点击图谱节点 → 明细栏滚动定位 + 短暂高亮 */
function focusDetail(pid) {
  const item = document.querySelector(`.memory-item[data-pid="${CSS.escape(pid)}"]`);
  if (!item) return;
  item.scrollIntoView({ behavior: 'smooth', block: 'center' });
  item.classList.add('flash');
  setTimeout(() => item.classList.remove('flash'), 1200);
}

// ===== 平移缩放（transform 合成层；小屏禁滚轮缩放防页面滚动冲突）=====

function bindPanZoom(viewport, canvas) {
  if (!viewport || !canvas) return;
  const apply = () => {
    // fit = 适配画布的整体缩放（布局基准换算），scale = 用户滚轮缩放，两者叠加
    canvas.style.transform =
      `translate(${view.panX}px, ${view.panY}px) scale(${view.scale * (view.fit || 1)})`;
  };
  view.applyTransform = apply;   // 供 renderGraph 在 fit 变化后重放

  let startX = 0, startY = 0, baseX = 0, baseY = 0, moved = false;

  viewport.addEventListener('pointerdown', e => {
    view.dragging = true; moved = false;
    startX = e.clientX; startY = e.clientY;
    baseX = view.panX; baseY = view.panY;
    viewport.classList.add('dragging');
    viewport.setPointerCapture(e.pointerId);
  });
  viewport.addEventListener('pointermove', e => {
    if (!view.dragging) return;
    const dx = e.clientX - startX, dy = e.clientY - startY;
    if (Math.abs(dx) + Math.abs(dy) > 5) moved = true;
    view.panX = baseX + dx; view.panY = baseY + dy;
    apply();
  });
  const end = () => {
    view.dragging = false;
    viewport.classList.remove('dragging');
  };
  viewport.addEventListener('pointerup', end);
  viewport.addEventListener('pointercancel', end);

  // 小屏（<768px）不绑滚轮缩放：滚轮留给页面滚动，双击画布复位
  if (window.innerWidth >= 768) {
    viewport.addEventListener('wheel', e => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      view.scale = Math.min(2, Math.max(0.5, view.scale * factor));
      apply();
    }, { passive: false });
  } else {
    viewport.addEventListener('dblclick', () => {
      view.scale = 1; view.panX = 0; view.panY = 0; apply();
    });
  }
}
