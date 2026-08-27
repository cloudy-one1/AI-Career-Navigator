// ===================================================
// history.js — 面试历史记录（v4.0：列表增强 + 详情抽屉）
// ===================================================

import { $, el, fmtDate, DIM_NAMES, escHtml } from './utils.js';
import { listSessions, getSession, getGlobalWeaknessProfile } from './api.js';

const STYLE_NAMES = { friendly: '友好型', strict: '严格型', pressure: '压力型' };
const STATUS_MAP = { active: '进行中', completed: '已完成', interrupted: '已中断', aborted: '已中止' };

function loadingIndicator(text) {
  return el('div', { className: 'streaming-indicator' },
    el('div', { className: 'streaming-dots' },
      el('div', { className: 'streaming-dot' }),
      el('div', { className: 'streaming-dot' }),
      el('div', { className: 'streaming-dot' }),
    ),
    el('span', { textContent: text || '加载中...' }),
  );
}

/** 初始化历史 Tab */
export function initHistory() {
  const panel = $('#history-panel');
  panel.innerHTML = '';

  panel.appendChild(el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '📜 面试历史' }),
    el('div', { id: 'history-list', className: 'history-list' },
      loadingIndicator('加载中...'),
    ),
  ));

  panel.appendChild(el('div', { id: 'history-detail' }));

  // v2.7: 全局薄弱点画像
  panel.appendChild(el('div', { id: 'weakness-profile', className: 'card' },
    el('div', { className: 'card-title', textContent: '📊 能力画像（历史累积）' }),
    el('div', { id: 'weakness-profile-content', className: 'weakness-profile-content' },
      loadingIndicator('分析中...'),
    ),
  ));

  loadHistory();
  loadWeaknessProfile();
}

async function loadWeaknessProfile() {
  const container = $('#weakness-profile-content');
  try {
    const data = await getGlobalWeaknessProfile();
    const profile = data.profile || [];
    if (profile.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><div class="empty-text">完成面试后，这里将展示你的能力画像</div></div>';
      return;
    }
    container.innerHTML = '';
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

// v4.0: 列表项（标题 + 标签徽章 + 操作）
function buildHistoryItem(s) {
  const rawTitle = (s.resume_text || '').trim().replace(/\s+/g, ' ');
  const title = rawTitle.slice(0, 22) || '未填写简历';
  const styleName = STYLE_NAMES[s.style] || s.style || '友好型';
  const status = STATUS_MAP[s.status] || s.status || '进行中';
  const isLive = s.status === 'active';

  return el('div', {
    className: 'history-item',
    onClick: () => loadSessionDetail(s.id),
  },
    el('div', { className: 'history-main' },
      el('div', { className: 'history-title', textContent: `${title}${rawTitle.length > 22 ? '…' : ''}` }),
      el('div', { className: 'history-date', textContent: fmtDate(s.created_at) }),
      el('div', { className: 'history-tags' },
        el('span', { className: `tag tag-style`, textContent: `🎭 ${styleName}` }),
        el('span', { className: `tag ${isLive ? 'tag-live' : ''}`, textContent: status }),
        s.jd_text ? el('span', { className: 'tag tag-jd', textContent: '📄 含 JD' }) : '',
      ),
    ),
    el('div', { className: 'history-actions' },
      el('button', {
        className: 'btn btn-ghost btn-sm',
        textContent: '查看报告',
        onClick: (e) => { e.stopPropagation(); openReport(s.id); },
      }),
      el('div', { className: 'history-arrow', textContent: '详情 →' }),
    ),
  );
}

async function loadHistory() {
  const listEl = $('#history-list');
  try {
    const data = await listSessions();
    const sessions = data.sessions || [];

    if (sessions.length === 0) {
      listEl.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">暂无面试记录</div></div>';
      return;
    }

    listEl.innerHTML = '';
    sessions.forEach(s => listEl.appendChild(buildHistoryItem(s)));
  } catch (e) {
    listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-text">加载失败: ${escHtml(e.message)}</div></div>`;
  }
}

// v4.0: 跳转到「报告」Tab 并自动加载该会话
function openReport(sessionId) {
  window._pendingReportSession = sessionId;
  document.querySelector('[data-tab="report"]')?.click();
}

// ===== 详情抽屉 =====

function openDrawer(title) {
  let overlay = $('#history-drawer-overlay');
  if (!overlay) {
    overlay = el('div', {
      className: 'drawer-overlay', id: 'history-drawer-overlay',
      onClick: closeDrawer,
    });
    const drawer = el('aside', { className: 'drawer', id: 'history-drawer', role: 'dialog', 'aria-label': '面试详情' },
      el('div', { className: 'drawer-header' },
        el('div', { className: 'drawer-title', id: 'drawer-title' }),
        el('button', { className: 'btn btn-ghost btn-sm', textContent: '✕', onClick: closeDrawer }),
      ),
      el('div', { className: 'drawer-body', id: 'drawer-body' }),
    );
    document.body.appendChild(overlay);
    document.body.appendChild(drawer);
  }
  $('#drawer-title').textContent = title;
  overlay.classList.add('show');
  $('#history-drawer').classList.add('show');
  document.body.classList.add('drawer-open');
  return $('#drawer-body');
}

function closeDrawer() {
  $('#history-drawer-overlay')?.classList.remove('show');
  $('#history-drawer')?.classList.remove('show');
  document.body.classList.remove('drawer-open');
}

// 解析报告（兼容 字符串 / 行记录 / 对象 三种形态）
function parseReport(report) {
  if (!report) return null;
  if (typeof report === 'string') {
    try { return JSON.parse(report); } catch { return null; }
  }
  if (report.report_json) {
    try { return JSON.parse(report.report_json); } catch { return null; }
  }
  return report;
}

async function loadSessionDetail(sessionId) {
  const body = openDrawer('面试详情');
  body.innerHTML = '';
  body.appendChild(loadingIndicator('加载详情...'));

  try {
    const data = await getSession(sessionId);
    const session = data.session || {};
    const qas = data.qas || [];
    const report = parseReport(data.report);

    body.innerHTML = '';

    // ── 概览区 ──
    const oAvg = report?.overall_avg;
    body.appendChild(el('div', { className: 'drawer-section' },
      el('div', { className: 'detail-hero' },
        oAvg != null ? el('div', { className: 'detail-score',
          textContent: oAvg.toFixed(1) }) : '',
        el('div', { className: 'detail-meta' },
          el('div', { className: 'detail-meta-row', textContent: `${STYLE_NAMES[session.style] || session.style || '友好型'} 风格 · ${fmtDate(session.created_at)}` }),
          el('div', { className: 'detail-meta-row detail-session-id', textContent: `Session: ${session.id}` }),
        ),
      ),
      (report?.rounds || []).length > 0 ? el('div', { className: 'detail-rounds' },
        ...report.rounds.map(r => el('div', { className: 'detail-round-row' },
          el('span', { className: 'detail-round-name', textContent: r.round_name }),
          el('span', { className: 'detail-round-score', textContent: (r.avg_score || 0).toFixed(1) }),
        )),
      ) : '',
    ));

    // ── 问答记录 ──
    if (qas.length > 0) {
      body.appendChild(el('div', { className: 'drawer-section' },
        el('div', { className: 'drawer-section-title', textContent: `💬 问答记录（${qas.length}）` }),
        el('div', { className: 'detail-qa-list' },
          ...qas.map((qa, i) => {
            let diag = {};
            try { diag = JSON.parse(qa.diagnosis_json || '{}'); } catch { /* ignore */ }
            const score = diag.overall_score;
            const dims = diag.dimensions || {};
            return el('details', { className: 'detail-qa-item' },
              el('summary', { className: 'detail-qa-summary' },
                el('span', { className: 'detail-qa-q', textContent: `${i + 1}. ${qa.question}` }),
                score > 0 ? el('span', { className: `detail-qa-score score-${score >= 4 ? 'good' : score >= 3 ? 'mid' : 'low'}`, textContent: `${score}/5` }) : '',
              ),
              el('div', { className: 'detail-qa-content' },
                qa.answer ? el('div', { className: 'detail-qa-answer',
                  textContent: qa.answer }) : el('div', { className: 'detail-qa-empty', textContent: '（未作答）' }),
                Object.keys(dims).length > 0 ? el('div', { className: 'detail-qa-dims' },
                  ...Object.entries(dims).map(([k, v]) =>
                    el('span', { className: 'detail-dim-chip',
                      textContent: `${DIM_NAMES[k] || k} ${v}/5` })),
                ) : '',
              ),
            );
          }),
        ),
      ));
    } else {
      body.appendChild(el('div', { className: 'drawer-section' },
        el('div', { className: 'empty-state' },
          el('div', { className: 'empty-icon', textContent: '📭' }),
          el('div', { className: 'empty-text', textContent: '该会话暂无问答记录' }),
        ),
      ));
    }

    // 底部操作
    body.appendChild(el('div', { className: 'drawer-footer' },
      el('button', {
        className: 'btn btn-primary',
        textContent: '📊 查看完整报告',
        onClick: () => { closeDrawer(); openReport(sessionId); },
      }),
    ));
  } catch (e) {
    body.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-text">加载详情失败: ${escHtml(e.message)}</div></div>`;
  }
}
