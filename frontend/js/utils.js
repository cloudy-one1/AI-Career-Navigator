// ===================================================
// utils.js — 工具函数
// ===================================================

/** 安全获取 DOM 元素 */
export function $(sel, ctx = document) { return ctx.querySelector(sel); }
export function $$(sel, ctx = document) { return [...ctx.querySelectorAll(sel)]; }

/** 创建元素 */
export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'className') e.className = v;
    else if (k === 'textContent') e.textContent = v;
    else if (k === 'innerHTML') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
    else e.setAttribute(k, v);
  }
  children.forEach(c => {
    if (typeof c === 'string') e.appendChild(document.createTextNode(c));
    else if (c instanceof Node) e.appendChild(c);
  });
  return e;
}

/** 格式化日期 */
export function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Toast 通知 */
let _toastTimer = null;
export function toast(msg, type = 'info') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  if (_toastTimer) clearTimeout(_toastTimer);

  const t = el('div', { className: `toast ${type}`, textContent: msg });
  document.body.appendChild(t);
  _toastTimer = setTimeout(() => t.remove(), 3500);
}

/** 分数颜色类 */
export function scoreClass(s) {
  if (s >= 4) return 'high';
  if (s >= 3) return 'mid';
  return 'low';
}

/** 四维度中文名 */
export const DIM_NAMES = {
  star_completeness: 'STAR 完整度',
  quantification: '量化程度',
  logic_coherence: '逻辑连贯性',
  job_relevance: '岗位相关性',
};

/** 深拷贝 */
export function clone(obj) { return JSON.parse(JSON.stringify(obj)); }
