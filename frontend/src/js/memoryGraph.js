// ===================================================
// memoryGraph.js — 长期记忆（2D SVG 薄弱点图谱，v6.3）
// 借鉴 HakiMeet MemoryView 的 2D 图谱；只做 2D 一套，不做 3D 双轨。
// 关键纪律：
//  - 节点布局用 id 哈希做**确定性**伪随机，刷新不跳位；
//  - 平移缩放走 transform 合成层，缩放不重算 SVG 路径；
//  - 每个维度最多渲染 6 个子节点，超出聚合为 "+N"，防 DOM 爆炸；
//  - 样式只写图谱画布自身（memory.css），组件类复用全局层。
// ===================================================

import { $, el, DIM_NAMES, toast, confirm as confirmDialog, emptyState } from './utils.js';
import { getWeaknessPoints, resolveWeakness, deleteWeakness } from './api.js';

// ── 画布几何（viewBox 与 DOM 百分比共用同一坐标系）──
const VB_W = 1000, VB_H = 620;
const CX = VB_W / 2, CY = VB_H / 2;
const DIM_R = 210;          // 维度节点环半径
const SUB_R = 78;           // 子节点散布半径
const MAX_SUBS = 6;         // 每维度最多渲染的子节点数

// ── 视图状态（模块级；面板惰性初始化后常驻）──
const view = {
  ready: false,
  data: [],
  includeResolved: false,
  scale: 1, panX: 0, panY: 0,
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

/** 布局：维度环形分布，子节点在维度周围按 id 哈希散开。 */
function layout(points) {
  const byDim = new Map();
  for (const p of points) {
    const key = p.dimension || 'unknown';
    if (!byDim.has(key)) byDim.set(key, []);
    byDim.get(key).push(p);
  }
  const dims = [...byDim.entries()];
  const n = Math.max(dims.length, 1);
  return dims.map(([name, list], i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    // 未解决比例越高，维度环越向内收（视觉上"短板更贴核心"）
    const openRatio = list.filter(p => Number(p.resolved) !== 1).length / list.length;
    const r = DIM_R * (1 - openRatio * 0.12);
    const dx = CX + r * Math.cos(angle);
    const dy = CY + r * Math.sin(angle);
    // 未解决数排前的子节点优先展示（列表已按严重度排序）
    const subs = list.slice(0, MAX_SUBS).map((p, j) => {
      const h1 = fnv1a(String(p.id));
      const h2 = fnv1a(`sub-${p.id}`);
      const a = angle + (h1 - 0.5) * 2.4 + (j - MAX_SUBS / 2) * 0.14;
      const rr = SUB_R * (0.55 + h2 * 0.45);
      return { point: p, x: dx + rr * Math.cos(a), y: dy + rr * Math.sin(a) };
    });
    return { name, x: dx, y: dy, subs, overflow: Math.max(0, list.length - MAX_SUBS) };
  });
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

  // 页头
  panel.appendChild(el('div', { className: 'memory-header card card-hover' },
    el('div', { className: 'memory-header-main' },
      el('div', { className: 'card-title', textContent: '🧠 长期记忆' }),
      el('div', { id: 'memory-stats', className: 'memory-stats' }),
    ),
    el('div', { className: 'memory-header-actions' },
      el('label', { className: 'memory-toggle' },
        Object.assign(el('input', { type: 'checkbox', id: 'memory-include-resolved' }),
          { checked: false, onchange: () => { view.includeResolved = !view.includeResolved; loadMemory(); } }),
        el('span', { textContent: '显示已解决' }),
      ),
      el('button', { className: 'btn btn-secondary btn-sm btn-press', id: 'memory-refresh',
                     textContent: '刷新', onclick: loadMemory }),
    ),
  ));

  // 主区：图谱 + 明细
  const layoutBox = el('div', { className: 'memory-layout' },
    el('div', { className: 'memory-graph-wrap' },
      el('div', { id: 'memory-viewport', className: 'memory-viewport' },
        el('div', { id: 'memory-canvas', className: 'memory-canvas' },
          el('svg', { viewBox: `0 0 ${VB_W} ${VB_H}`, id: 'memory-svg',
                      preserveAspectRatio: 'xMidYMid meet' }),
          el('div', { id: 'memory-nodes', className: 'memory-nodes' }),
        ),
        el('div', { className: 'memory-legend glass-panel' },
          legendDot('danger', '严重（<2.5）'), legendDot('warn', '待补强（2.5-3.5）'),
          legendDot('info', '尚可（≥3.5）'), legendDot('resolved', '已解决'),
        ),
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
  loadMemory();
}

function legendDot(tier, label) {
  return el('span', { className: 'legend-item' },
    el('span', { className: `legend-dot tier-${tier}` }),
    el('span', { textContent: label }),
  );
}

// ===== 数据加载与渲染 =====

async function loadMemory() {
  const detail = $('#memory-detail');
  const nodes = $('#memory-nodes');
  const svg = $('#memory-svg');
  try {
    const res = await getWeaknessPoints(view.includeResolved);
    view.data = res.points || [];
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

  const dims = layout(view.data);

  // 连线层：中心 → 维度 → 子节点（缩放只动 canvas 的 transform，路径不重算）
  const frag = document.createDocumentFragment();
  for (const d of dims) {
    frag.appendChild(pathEl(linkPath(CX, CY, d.x, d.y), 'mlink-dim', `dim-${slug(d.name)}`));
    for (const s of d.subs) {
      frag.appendChild(pathEl(linkPath(d.x, d.y, s.x, s.y), 'mlink-sub', `pt-${s.point.id}`));
    }
  }
  svg.appendChild(frag);

  // 节点层（DOM，按 viewBox 百分比定位，与 SVG 同步缩放）
  const center = nodeEl('memory-node mnode-center', CX, CY, '0');
  center.appendChild(el('span', { className: 'mnode-label', textContent: '薄弱点图谱' }));
  nodes.appendChild(center);

  for (const d of dims) {
    const dn = nodeEl(`memory-node mnode-dim tier-${dominantTier(d)}`, d.x, d.y, `dim-${slug(d.name)}`);
    dn.appendChild(el('span', { className: 'mnode-label', textContent: dimLabel(d.name) }));
    if (d.overflow > 0) {
      dn.appendChild(el('span', { className: 'mnode-overflow', textContent: `+${d.overflow}` }));
    }
    nodes.appendChild(dn);
    for (const s of d.subs) {
      const p = s.point;
      const n = nodeEl(`memory-node mnode-point tier-${tierOf(p)}`, s.x, s.y, `pt-${p.id}`,
                       `薄弱点 ${p.id}`);
      n.appendChild(el('span', {
        className: 'mnode-label',
        textContent: (p.risk_points && p.risk_points[0]) || `${dimLabel(p.dimension)} 短板`,
        title: p.risk_points ? p.risk_points.join('；') : '',
      }));
      n.addEventListener('click', () => focusDetail(p.id));
      nodes.appendChild(n);
    }
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
  const open = d.subs.filter(s => Number(s.point.resolved) !== 1);
  const pool = open.length ? open : d.subs;
  const min = Math.min(...pool.map(s => Number(s.avg_score) || 5));
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
    canvas.style.transform =
      `translate(${view.panX}px, ${view.panY}px) scale(${view.scale})`;
  };

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
