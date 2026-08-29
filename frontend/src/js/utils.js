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

/** 五维度中文名 */
export const DIM_NAMES = {
  star_completeness: 'STAR 完整度',
  quantification: '量化程度',
  logic_coherence: '逻辑连贯性',
  job_relevance: '岗位相关性',
  professional_depth: '专业深度',
};

/** 深拷贝 */
export function clone(obj) { return JSON.parse(JSON.stringify(obj)); }

/** HTML 转义（防 XSS） */
export function escHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ===== v6.3 onboarding 工具（借鉴 HakiMeet 的空状态三件套与全局确认弹窗）=====

/** Promise 化确认弹窗（替代原生 window.confirm，样式与交互全局统一）。
 *  danger=true 时确认按钮为红色，用于删除等不可逆操作。
 *  Esc / 点击遮罩 = 取消。 */
export function confirm(message, { title = '请确认', okText = '确定',
                                   cancelText = '取消', danger = false } = {}) {
  return new Promise(resolve => {
    const mask = el('div', { className: 'confirm-mask' });
    const done = val => {
      mask.remove();
      document.removeEventListener('keydown', onKey);
      resolve(val);
    };
    const onKey = e => { if (e.key === 'Escape') done(false); };

    mask.appendChild(el('div', { className: `confirm-box card${danger ? ' confirm-danger' : ''}` },
      el('div', { className: 'confirm-title', textContent: title }),
      el('div', { className: 'confirm-message', textContent: message }),
      el('div', { className: 'confirm-actions' },
        el('button', {
          className: 'btn btn-secondary btn-press', textContent: cancelText,
          onclick: () => done(false),
        }),
        el('button', {
          className: `btn ${danger ? 'btn-danger' : 'btn-primary'} btn-press`,
          textContent: okText, onclick: () => done(true),
        }),
      ),
    ));
    mask.addEventListener('click', e => { if (e.target === mask) done(false); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(mask);
  });
}

/** 空状态三件套（图标 + 标题 + 说明），渲染进容器或独立返回。 */
export function emptyState({ icon = '📭', title = '暂无数据', desc = '' } = {}) {
  const wrap = el('div', { className: 'empty-state' },
    el('div', { className: 'empty-icon', textContent: icon }),
    el('div', { className: 'empty-title', textContent: title }),
  );
  if (desc) wrap.appendChild(el('div', { className: 'empty-desc', textContent: desc }));
  return wrap;
}
