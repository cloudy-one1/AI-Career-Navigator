// ===================================================
// recruiterInbox.js — v7.0.1 招聘者「收到的报告」
//
// 求职者分享报告时可指定发给哪位招聘者（按用户名），该报告进入对方
// 收件箱。与免登录的 /share/{token} 链接是两条独立通道——收件箱走
// 登录态 + 归属校验（发件指定的本人才能打开）。
// ===================================================

import { $, el, toast, fmtDate, emptyState, skeletonBlock } from './utils.js';
import { request } from './api.js';
import { renderReportInto } from './shareReport.js';

export function initRecruiterInbox() {
  const panel = $('#recruiter-inbox-panel');
  if (!panel) return;

  panel.innerHTML = '';

  panel.appendChild(el('div', { className: 'card' },
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;' },
      el('div', {},
        el('div', { className: 'card-title', textContent: '📥 收到的报告' }),
        el('div', { className: 'library-subtitle',
          textContent: '求职者主动分享给你的面试诊断报告。内容已脱敏，仅供参考，不构成录用建议' }),
      ),
      el('button', { className: 'btn btn-secondary btn-press', textContent: '🔄 刷新', onClick: loadInbox }),
    ),
  ));

  panel.appendChild(el('div', { id: 'ri-detail' }));
  panel.appendChild(el('div', { id: 'ri-list' }));

  loadInbox();
}

// ===== 收件箱列表 =====

async function loadInbox() {
  const container = $('#ri-list');
  if (!container) return;
  container.replaceChildren(el('div', { className: 'empty-state' },
    el('div', { className: 'empty-text', textContent: '加载中…' })));

  const detail = $('#ri-detail');
  if (detail) detail.replaceChildren();

  let rows = [];
  try {
    const data = await request('GET', '/api/recruiter/inbox');
    rows = data.reports || [];
  } catch (err) {
    container.replaceChildren(emptyState({
      icon: '⚠️', title: '加载失败', desc: err.message || '请稍后重试',
    }));
    return;
  }

  if (!rows.length) {
    container.replaceChildren(emptyState({
      icon: '📥',
      title: '还没有收到报告',
      desc: '求职者在报告页分享时填入你的用户名，报告就会出现在这里。',
    }));
    return;
  }

  const wrap = el('div', { className: 'library-grid' });
  for (const r of rows) wrap.appendChild(inboxCard(r));
  container.replaceChildren(wrap);
}

function inboxCard(r) {
  const score = Number(r.overall_score || 0);
  const scoreColor = score >= 4 ? 'var(--success, #16a34a)'
                   : score >= 3 ? 'var(--warning, #d97706)' : 'var(--danger, #dc2626)';
  return el('div', { className: 'card card-hover library-card' },
    el('div', { className: 'library-card-head' },
      el('div', { className: 'library-card-title', textContent: r.candidate_name || '候选人报告' }),
      el('span', { className: 'share-qa-score', style: `color:${scoreColor};`,
                   textContent: score.toFixed(1) }),
    ),
    el('div', { className: 'library-card-meta' },
      el('span', { textContent: fmtDate(r.completed_at) }),
      el('span', { textContent: `浏览 ${r.access_count || 0} 次` }),
      r.include_detail ? el('span', { textContent: '含逐题' }) : null,
    ),
    el('div', { className: 'library-card-actions' },
      el('button', {
        className: 'btn btn-sm btn-primary', textContent: '查看报告',
        onClick: () => openReport(r.token_hash),
      }),
    ),
  );
}

// ===== 打开报告（内嵌渲染，不跳出主应用）=====

async function openReport(tokenHash) {
  const detail = $('#ri-detail');
  const list = $('#ri-list');
  if (!detail) return;

  // v7.2: 骨架屏替代 spinner（纸纹 shimmer）
  detail.replaceChildren(el('div', { className: 'card share-loading' },
    skeletonBlock({ lines: 4 }),
    el('span', { textContent: '正在加载报告…' })));
  list.classList.add('hidden');

  let data;
  try {
    data = await request('GET', `/api/recruiter/reports/${encodeURIComponent(tokenHash)}`);
  } catch (err) {
    detail.replaceChildren(el('div', { className: 'card share-error' },
      el('div', { className: 'share-error-title', textContent: '无法打开这份报告' }),
      el('div', { className: 'share-error-desc', textContent: err.message || '请稍后重试' }),
      el('button', {
        className: 'btn btn-secondary btn-sm', textContent: '返回列表',
        onClick: () => { detail.replaceChildren(); list.classList.remove('hidden'); },
      }),
    ));
    return;
  }

  const head = el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: `${data.candidate_name || '候选人'}的诊断报告` }),
    el('div', { className: 'library-subtitle',
      textContent: `完成于 ${fmtDate(data.completed_at)} · 本报告由候选人主动分享，内容已脱敏` }),
  );
  const body = el('div', { className: 'share-content' });
  const back = el('div', { style: 'display:flex;justify-content:flex-end;margin-bottom:8px;' },
    el('button', {
      className: 'btn btn-secondary btn-sm', textContent: '← 返回列表',
      onClick: () => { detail.replaceChildren(); list.classList.remove('hidden'); },
    }),
  );

  detail.replaceChildren(back, head, body);
  renderReportInto(body, data);
}
