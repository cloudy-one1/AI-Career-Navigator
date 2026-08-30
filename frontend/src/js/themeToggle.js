/* ===================================================
   themeToggle.js — 双风格切换（v7.2 简化版）
   ---------------------------------------------------
   toggle <html class="theme-dark">（免刷新实时生效），
   localStorage 记忆，并派发 theme:changed 事件供图表重绘。
   v7.2：深色统一为「墨夜纸墨」单一强调色，
        原青/粉/金/紫语义色切换器已移除（审美收敛）。
   纯前端，不依赖后端。
   =================================================== */
(function () {
  'use strict';

  function isDark() {
    return document.documentElement.classList.contains('theme-dark');
  }

  function updateToggleLabel() {
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = isDark() ? '☀ 浅色风' : '🌙 深色风';
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
      window.dispatchEvent(new CustomEvent('theme:changed', { detail: { isDark: isDark() } }));
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindToggle);
  else bindToggle();
})();
