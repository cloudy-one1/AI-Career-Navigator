// ===================================================
// report.js — 综合报告 + Chart.js 雷达图
// ===================================================

import { $, el, toast, DIM_NAMES } from './utils.js';
import { getReport } from './api.js';

let chartInstance = null;

/** 初始化报告 Tab */
export function initReport() {
  const panel = $('#report-panel');
  panel.innerHTML = '';

  panel.appendChild(el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '📊 综合面试报告' }),
    el('div', { className: 'form-group' },
      el('input', { id: 'report-session-id', className: 'form-input', placeholder: '输入 Session ID 查看历史报告...' }),
    ),
    el('div', { style: 'display:flex;gap:8px;' },
      el('button', { id: 'load-report-btn', className: 'btn btn-primary', textContent: '加载报告', onClick: loadReport }),
      el('button', { id: 'load-latest-btn', className: 'btn btn-secondary', textContent: '加载最新', onClick: loadLatestReport }),
    ),
  ));

  panel.appendChild(el('div', { id: 'report-content' }));
}

async function loadLatestReport() {
  // 尝试从全局获取最新报告
  if (window._latestReport && window._latestSessionId) {
    renderReport(window._latestReport);
    return;
  }
  toast('请先完成一次面试', 'warning');
}

async function loadReport() {
  const sessionId = $('#report-session-id')?.value.trim();
  if (!sessionId) { toast('请输入 Session ID', 'warning'); return; }

  try {
    const data = await getReport(sessionId);
    if (data.report) {
      const report = typeof data.report === 'string'
        ? JSON.parse(data.report)
        : (data.report.report_json ? JSON.parse(data.report.report_json) : data.report);

      // normalize
      const normalizedReport = report.report_json
        ? JSON.parse(report.report_json)
        : report;

      renderReport(normalizedReport);
    } else {
      $('#report-content').innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">该会话暂无报告数据</div></div>';
    }
  } catch (e) {
    toast('加载失败: ' + e.message, 'error');
  }
}

function renderReport(report) {
  const content = $('#report-content');
  content.innerHTML = '';

  if (!report || !report.rounds || report.rounds.length === 0) {
    content.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">暂无报告数据</div></div>';
    return;
  }

  // 报告头部
  content.appendChild(el('div', { className: 'report-header card' },
    el('div', { className: 'report-score', textContent: (report.overall_avg || 0).toFixed(1) }),
    el('div', { className: 'report-label',
      textContent: report.scoring?.weighted ? '加权综合评分 / 5' : '综合评分 / 5' }),
    el('div', { style: 'font-size:.8rem;color:var(--text-muted);margin-top:8px;', textContent: `风格: ${report.interviewer_style || 'friendly'} | ${report.rounds.length} 轮面试` }),
  ));

  // v2.6: 评分权重说明
  if (report.scoring?.weight_desc) {
    const s = report.scoring;
    content.appendChild(el('div', { className: 'card weights-banner' },
      el('div', { className: 'card-title',
        textContent: s.weight_source === 'llm' ? '⚖️ 评分权重（按 JD 动态调整）' : '⚖️ 评分权重（五维等权）' }),
      el('div', { className: 'weights-desc', textContent: s.weight_desc }),
      s.weight_reason ? el('div', {
        style: 'font-size:.8rem;color:var(--text-secondary);margin-top:6px;',
        textContent: `📌 ${s.weight_reason}`,
      }) : '',
    ));
  }

  // 雷达图
  if (report.dimension_trends?.length) {
    const chartDiv = el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '🎯 各维度趋势' }),
      el('div', { className: 'chart-container' },
        el('div', { className: 'chart-wrapper' },
          el('canvas', { id: 'radar-chart' }),
        ),
      ),
    );
    content.appendChild(chartDiv);

    setTimeout(() => drawRadarChart(report), 100);
  }

  // 轮次汇总卡片
  if (report.rounds?.length) {
    content.appendChild(el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '📋 轮次汇总' }),
      el('div', { className: 'round-cards' },
        ...report.rounds.map(r => el('div', { className: 'round-card' },
          el('div', {},
            el('div', { className: 'round-card-name', textContent: r.round_name }),
            el('div', { className: 'round-card-meta', textContent: `${r.answers_count}/${r.questions_count} 题已答` }),
          ),
          el('div', { className: 'round-card-score', textContent: (r.avg_score || 0).toFixed(1) }),
        )),
      ),
    ));
  }

  // 强项 & 弱项
  const hasStrengths = report.strengths?.length;
  const hasWeaknesses = report.weaknesses?.length;
  if (hasStrengths || hasWeaknesses) {
    content.appendChild(el('div', { className: 'summary-grid' },
      hasStrengths ? el('div', { className: 'summary-box strengths' },
        el('h4', { textContent: '✅ 强项' }),
        el('ul', {}, ...report.strengths.map(s => el('li', { textContent: s }))),
      ) : '',
      hasWeaknesses ? el('div', { className: 'summary-box weaknesses' },
        el('h4', { textContent: '⚠️ 待提升' }),
        el('ul', {}, ...report.weaknesses.map(w => el('li', { textContent: w }))),
      ) : '',
    ));
  }

  // 建议
  if (report.suggestions) {
    content.appendChild(el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '💡 提升建议' }),
      el('div', { className: 'suggestions-block', textContent: report.suggestions }),
    ));
  }
}

function drawRadarChart(report) {
  const canvas = $('#radar-chart');
  if (!canvas) return;

  // 销毁旧图表
  if (chartInstance) chartInstance.destroy();

  const ctx = canvas.getContext('2d');

  const dimNames = report.dimension_trends.map(d => DIM_NAMES[d.dimension] || d.dimension);
  const datasets = [];

  report.dimension_trends.forEach((d, idx) => {
    const scores = d.scores || [];
    if (scores.length === 0) return;

    const colors = ['#4F46E5', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'];
    const color = colors[idx] || '#4F46E5';

    // 取最近一轮各维度分数
    const latestScore = scores[scores.length - 1] || scores[0] || 0;

    datasets.push({
      label: DIM_NAMES[d.dimension] || d.dimension,
      data: [latestScore],
      borderColor: color,
      backgroundColor: color + '20',
      borderWidth: 2,
      pointBackgroundColor: color,
      pointRadius: 5,
    });
  });

  // 使用简单雷达图 - 实际需要所有维度在一张图上
  // 重新组织数据：每个轮次一个 dataset
  const roundCount = report.rounds?.length || 1;
  const dimDataset = report.dimension_trends;

  const roundColors = ['#4F46E5', '#10B981', '#F59E0B'];
  const roundDatasets = [];

  for (let r = 0; r < roundCount; r++) {
    const data = dimDataset.map(d => (d.scores && d.scores[r]) ? d.scores[r] : 0);
    if (data.every(v => v === 0)) continue;
    roundDatasets.push({
      label: report.rounds?.[r]?.round_name || `第${r+1}轮`,
      data,
      borderColor: roundColors[r] || '#4F46E5',
      backgroundColor: (roundColors[r] || '#4F46E5') + '15',
      borderWidth: 2,
      pointBackgroundColor: roundColors[r] || '#4F46E5',
      pointRadius: 4,
    });
  }

  if (roundDatasets.length === 0) return;

  chartInstance = new Chart(ctx, {
    type: 'radar',
    data: {
      labels: dimDataset.map(d => DIM_NAMES[d.dimension] || d.dimension),
      datasets: roundDatasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      scales: {
        r: {
          min: 0,
          max: 5,
          ticks: { stepSize: 1, backdropColor: 'transparent', font: { size: 10 } },
          pointLabels: { font: { size: 12, weight: '500' } },
          grid: { color: '#E2E8F0' },
          angleLines: { color: '#E2E8F0' },
        },
      },
      plugins: {
        legend: { position: 'bottom', labels: { padding: 16, font: { size: 12 } } },
      },
    },
  });
}
