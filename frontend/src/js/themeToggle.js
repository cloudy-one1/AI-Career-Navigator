/* ===================================================
   themeToggle.js — 双风格切换（对齐 job-crawler theme-toggle.js）
   ---------------------------------------------------
   1) 风格切换：toggle <html class="theme-dark">（免刷新实时生效），
      localStorage 记忆，并派发 theme:changed 事件供图表重绘。
   2) 语义色切换器：仅深色下挂载，在 青/粉/金/紫 间切换
      --accent-from / --accent-to，状态存 sessionStorage。
   纯前端，不依赖后端。
   =================================================== */
(function () {
  'use strict';

  const ACCENTS = {
    cyan:   { from: '#5DE0E6', to: '#B48CFF' },
    pink:   { from: '#FF6EC7', to: '#B48CFF' },
    gold:   { from: '#FFB84D', to: '#FF6EC7' },
    purple: { from: '#B48CFF', to: '#5DE0E6' }
  };

  function isDark() {
    return document.documentElement.classList.contains('theme-dark');
  }

  function updateToggleLabel() {
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = isDark() ? '☀ 浅色风' : '🌙 深色风';
  }

  function setAccent(name) {
    const a = ACCENTS[name] || ACCENTS.cyan;
    const root = document.documentElement.style;
    root.setProperty('--accent-from', a.from);
    root.setProperty('--accent-to', a.to);
    document.querySelectorAll('[data-accent-btn]').forEach((b) => {
      b.classList.toggle('active', b.getAttribute('data-accent-btn') === name);
    });
    try { sessionStorage.setItem('_theme_accent', name); } catch (e) {}
  }

  function mountAccentSwitcher() {
    if (document.getElementById('accent-switcher')) return;
    const bar = document.createElement('div');
    bar.id = 'accent-switcher';
    bar.innerHTML =
      '<span class="lbl">语义色</span>' +
      '<button type="button" data-accent-btn="cyan" style="background:#5DE0E6" title="青"></button>' +
      '<button type="button" data-accent-btn="pink" style="background:#FF6EC7" title="粉"></button>' +
      '<button type="button" data-accent-btn="gold" style="background:#FFB84D" title="金"></button>' +
      '<button type="button" data-accent-btn="purple" style="background:#B48CFF" title="紫"></button>';
    document.body.appendChild(bar);
    bar.addEventListener('click', (e) => {
      const b = e.target.closest('[data-accent-btn]');
      if (b) setAccent(b.getAttribute('data-accent-btn'));
    });
    let saved = null;
    try { saved = sessionStorage.getItem('_theme_accent'); } catch (e) {}
    setAccent(saved || 'cyan');
  }

  function bindToggle() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    updateToggleLabel();
    btn.addEventListener('click', () => {
      const next = isDark() ? 'light' : 'dark';
      try { localStorage.setItem('theme', next); } catch (e) {}
      document.documentElement.classList.toggle('theme-dark');
      updateToggleLabel();
      const nowDark = isDark();
      if (nowDark) {
        mountAccentSwitcher();
      } else {
        const sw = document.getElementById('accent-switcher');
        if (sw) sw.remove();
      }
      window.dispatchEvent(new CustomEvent('theme:changed', { detail: { isDark: nowDark } }));
    });
  }

  function init() {
    bindToggle();
    if (isDark()) mountAccentSwitcher();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
