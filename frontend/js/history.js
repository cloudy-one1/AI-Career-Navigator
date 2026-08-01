// ===================================================
// history.js — 面试历史记录
// ===================================================

import { $, el, fmtDate, DIM_NAMES } from './utils.js';
import { listSessions, getSession, getGlobalWeaknessProfile } from './api.js';

/** 初始化历史 Tab */
export function initHistory() {
  const panel = $('#history-panel');
  panel.innerHTML = '';

  panel.appendChild(el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '📜 面试历史' }),
    el('div', { id: 'history-list', className: 'history-list' },
      el('div', { className: 'streaming-indicator' },
        el('div', { className: 'streaming-dots' },
          el('div', { className: 'streaming-dot' }),
          el('div', { className: 'streaming-dot' }),
          el('div', { className: 'streaming-dot' }),
        ),
        el('span', { textContent: '加载中...' }),
      ),
    ),
  ));

  panel.appendChild(el('div', { id: 'history-detail' }));

  // v2.7: 全局薄弱点画像
  panel.appendChild(el('div', { id: 'weakness-profile', className: 'card' },
    el('div', { className: 'card-title', textContent: '📊 能力画像（历史累积）' }),
    el('div', { id: 'weakness-profile-content', className: 'weakness-profile-content' },
      el('div', { className: 'streaming-indicator' },
        el('div', { className: 'streaming-dots' },
          el('div', { className: 'streaming-dot' }),
          el('div', { className: 'streaming-dot' }),
          el('div', { className: 'streaming-dot' }),
        ),
        el('span', { textContent: '分析中...' }),
      ),
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
    sessions.forEach(s => {
      listEl.appendChild(el('div', {
        className: 'history-item',
        onClick: () => loadSessionDetail(s.id),
      },
        el('div', {},
          el('div', { className: 'history-date', textContent: fmtDate(s.created_at) }),
          el('div', { className: 'history-meta', textContent: `风格: ${s.style || 'friendly'} | ${s.resume_text ? '有简历' : '无简历'}` }),
        ),
        el('div', { textContent: '查看 →', style: 'color:var(--primary);font-size:.85rem;' }),
      ));
    });
  } catch (e) {
    listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-text">加载失败: ${e.message}</div></div>`;
  }
}

async function loadSessionDetail(sessionId) {
  const detailEl = $('#history-detail');
  detailEl.innerHTML = '<div class="streaming-indicator"><div class="streaming-dots"><div class="streaming-dot"></div><div class="streaming-dot"></div><div class="streaming-dot"></div></div><span>加载详情...</span></div>';

  try {
    const data = await getSession(sessionId);
    const session = data.session;
    const questions = data.questions || [];
    const diagnoses = data.diagnoses || [];
    const roundSummaries = data.round_summaries || [];
    const report = data.report;

    let html = `<div class="card" style="border-left:4px solid var(--primary);">`;
    html += `<div class="card-title">📋 ${fmtDate(session.created_at)}</div>`;
    html += `<div style="font-size:.85rem;color:var(--text-secondary);">Session: ${session.id}</div>`;
    html += `<div style="font-size:.85rem;color:var(--text-secondary);">风格: ${session.style || 'friendly'}</div>`;

    if (report) {
      const r = typeof report === 'string' ? JSON.parse(report) : (report.report_json ? JSON.parse(report.report_json) : report);
      const normalizedReport = r.report_json ? JSON.parse(r.report_json) : r;
      if (normalizedReport.overall_avg != null) {
        html += `<div style="font-size:1.1rem;font-weight:700;color:var(--primary);margin-top:8px;">综合评分: ${normalizedReport.overall_avg.toFixed(1)} / 5</div>`;
      }
    }

    // 轮次汇总
    if (roundSummaries.length > 0) {
      html += '<div style="margin-top:12px;">';
      roundSummaries.forEach(rs => {
        const s = typeof rs.summary_json === 'string' ? JSON.parse(rs.summary_json) : rs;
        html += `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:.85rem;">
          <span>${rs.round_name || s.round_name || `轮次${rs.round_index}`}</span>
          <span style="font-weight:600;color:var(--primary);">${s.avg_score || 0} / 5</span>
        </div>`;
      });
      html += '</div>';
    }

    // 诊断列表
    if (diagnoses.length > 0) {
      html += '<div style="margin-top:12px;font-size:.85rem;color:var(--text-secondary);">';
      html += `共 ${diagnoses.length} 条诊断记录`;
      html += '</div>';
    }

    html += '</div>';
    detailEl.innerHTML = html;
  } catch (e) {
    detailEl.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-text">加载详情失败: ${e.message}</div></div>`;
  }
}
