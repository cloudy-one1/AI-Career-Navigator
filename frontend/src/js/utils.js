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
    else if (['disabled', 'checked', 'selected', 'readonly', 'required', 'multiple', 'autofocus'].includes(k)) {
      // 布尔属性：false 时必须移除属性，否则 setAttribute('disabled', 'false') 仍会禁用元素
      e[k] = !!v;
      if (v) e.setAttribute(k, '');
      else e.removeAttribute(k);
    }
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

// ===== v7.2 动效工具（样式统一在 motion.css，全站共享）=====

/** 骨架屏占位块（纸纹 shimmer 扫光），替代 spinner 的加载表达。
 *  lines: 行数；widths: 每行宽度类（'w60' | 'w80' | 'w100'），默认末行短。 */
export function skeletonBlock({ lines = 3, widths = ['w100', 'w80', 'w60'] } = {}) {
  const wrap = el('div', { className: 'skeleton', 'aria-hidden': 'true' });
  for (let i = 0; i < lines; i++) {
    wrap.appendChild(el('div', { className: `skeleton-line ${widths[i % widths.length]}` }));
  }
  return wrap;
}

/** 数字滚动（评分环 / 统计卡揭晓）。easeOutCubic，尊重减弱动效偏好。 */
export function countUp(target, to, { duration = 800, decimals = 1 } = {}) {
  if (!target) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced || !Number.isFinite(to)) {
    target.textContent = to.toFixed(decimals);
    return;
  }
  const start = performance.now();
  const tick = now => {
    const p = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    target.textContent = (to * eased).toFixed(decimals);
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** 印章「盖章」仪式感：给元素挂 .stamp-in 并同步一圈墨晕。 */
export function stampIn(target) {
  if (!target) return;
  target.classList.remove('stamp-in');
  void target.offsetWidth;   // 重置动画
  target.classList.add('stamp-in');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduced) {
    const ripple = el('span', { className: 'stamp-ripple', 'aria-hidden': 'true' });
    target.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
  }
}

/** 表单校验失败的水平 shake 反馈。 */
export function shake(target) {
  if (!target) return;
  target.classList.remove('shake');
  void target.offsetWidth;
  target.classList.add('shake');
  setTimeout(() => target.classList.remove('shake'), 500);
}

/**
 * v7.3: 评分揭晓的径向粒子爆发（motion.css particle-fly 驱动）。
 * tier 决定色板：good=墨青/黄铜/朱砂，mid=黄铜/朱砂，poor=深红/黄铜。
 * JS 驱动的动效必须显式读 prefers-reduced-motion（动效纪律第 2 条）。
 * anchor 需为定位上下文（调用方给 position:relative）。
 */
export function burstParticles(anchor, tier = 'good', { count = 16 } = {}) {
  if (!anchor) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const palette = {
    good: ['var(--teal)', 'var(--brass)', 'var(--stamp)'],
    mid: ['var(--brass)', 'var(--stamp)'],
    poor: ['var(--indigo-800)', 'var(--brass)'],
  }[tier] || ['var(--stamp)'];
  const layer = el('div', { className: 'particle-layer', 'aria-hidden': 'true' });
  for (let i = 0; i < count; i++) {
    const p = el('span', { className: 'particle' });
    p.style.setProperty('--ang', `${Math.round(Math.random() * 360)}deg`);
    p.style.setProperty('--dist', `${44 + Math.round(Math.random() * 52)}px`);
    p.style.setProperty('--pd', `${Math.round(Math.random() * 160)}ms`);
    p.style.setProperty('--pc', palette[i % palette.length]);
    if (i % 3 === 0) { p.style.width = '4px'; p.style.height = '4px'; }
    layer.appendChild(p);
  }
  anchor.appendChild(layer);
  setTimeout(() => layer.remove(), 1400);
}
