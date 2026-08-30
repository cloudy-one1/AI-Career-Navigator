// ===================================================
// shareReport.js — v7.0 招聘端只读报告页
//
// 三条设计约束：
// 1. 纯只读：本文件不发起任何写请求（无 POST/PATCH/DELETE），
//    "只读"靠"根本没有写路径"来保证，而不是靠服务端拒绝。
// 2. 免登录：拿链接的是外部 HR，不该被要求注册。
// 3. 脱敏由后端完成，本页只负责如实呈现 —— 不在前端二次脱敏，
//    否则"看到的内容"与"实际发出的内容"可能不一致，反而更难审计。
// ===================================================

import { $, el, fmtDate, skeletonBlock } from './utils.js';

const DIM_LABEL_FALLBACK = {
  star_completeness: 'STAR 完整度',
  quantification: '量化程度',
  logic_coherence: '逻辑连贯性',
  job_relevance: '岗位相关性',
  professional_depth: '专业深度',
};

/** 从 /share/{token} 的 URL 中取令牌 */
function tokenFromPath() {
  const m = location.pathname.match(/\/share\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}

export async function initSharedReport() {
  const token = tokenFromPath();
  const content = $('#share-content');

  if (!token) {
    renderError('链接不完整', '缺少分享令牌，请向分享者索取完整链接。');
    return;
  }

  content.replaceChildren(loadingBlock());

  let data;
  try {
    const res = await fetch(`/api/shared/${encodeURIComponent(token)}`);
    if (!res.ok) {
      // 不区分 404 的具体原因（不存在 / 已撤销 / 已过期）——服务端刻意统一措辞，
      // 前端也如实呈现，不替攻击者做区分。
      renderError('无法查看这份报告',
                  '链接可能已被分享者撤销、已过期，或本来就不存在。请向分享者索取新的链接。');
      return;
    }
    data = await res.json();
  } catch (_) {
    renderError('加载失败', '网络异常，请稍后重试。');
    return;
  }

  renderReport(data);
}

// ===== 渲染 =====

function loadingBlock() {
  return el('div', { className: 'card share-loading' },
    skeletonBlock({ lines: 4 }),
    el('span', { textContent: '正在加载报告…' }),
  );
}

function renderError(title, desc) {
  const content = $('#share-content');
  content.replaceChildren(
    el('div', { className: 'card share-error' },
      el('div', { className: 'share-error-title', textContent: title }),
      el('div', { className: 'share-error-desc', textContent: desc }),
    ),
  );
  $('#share-title').textContent = '无法查看';
  $('#share-subtitle').textContent = '';
}

function renderReport(data) {
  $('#share-title').textContent = `${data.candidate_name || '候选人'}的诊断报告`;
  const parts = [];
  if (data.completed_at) parts.push(`完成于 ${fmtDate(data.completed_at)}`);
  if (data.overall_score) parts.push(`总评 ${Number(data.overall_score).toFixed(1)} / 5.0`);
  $('#share-subtitle').textContent = parts.join(' · ');

  renderReportInto($('#share-content'), data);

  const footer = $('#share-footer');
  footer.classList.remove('hidden');
  const expiry = $('#share-expiry');
  expiry.textContent = data.expires_at
    ? `本链接有效期至 ${fmtDate(data.expires_at)}`
    : '本链接未设置有效期（分享者可随时撤销）';
}

/**
 * v7.0.1: 把报告主体渲染进任意容器（供招聘端收件箱复用）。
 *
 * 与 initSharedReport 的分工：本函数只负责"内容区"（评分/五维/摘要/逐题），
 * 不碰分享页特有的 header/footer DOM——那些元素在主应用里不存在。
 * 调用方需保证容器内有 id="share-radar" 的 canvas（dimensionCard 会创建）。
 */
export function renderReportInto(container, data) {
  if (!container) return;
  container.replaceChildren(
    scoreCard(data),
    dimensionCard(data),
    strengthsCard(data),
    data.include_detail ? qaCard(data) : detailHiddenCard(),
  );
  mountRadar(container, data);
}

function scoreCard(data) {
  const score = Number(data.overall_score || 0);
  return el('section', { className: 'card share-score-card' },
    el('div', { className: 'share-score' },
      el('div', { className: 'share-score-value', textContent: score.toFixed(1) }),
      el('div', { className: 'share-score-label', textContent: '综合评分 / 5.0' }),
    ),
    el('div', { className: 'share-score-side' },
      el('div', { className: 'share-score-verdict', textContent: verdict(score) }),
      el('div', { className: 'share-score-hint', textContent: roundLine(data) }),
    ),
  );
}

function verdict(score) {
  if (score >= 4.2) return '表现优秀：结构完整、证据充分';
  if (score >= 3.5) return '表现良好：个别维度仍有提升空间';
  if (score >= 2.8) return '表现一般：存在明显短板';
  if (score > 0) return '表现偏弱：需要系统性练习';
  return '本次未取得有效评分';
}

function roundLine(data) {
  const rounds = data.rounds || [];
  if (!rounds.length) return '共 0 个面试轮次';
  const avg = rounds.reduce((s, r) => s + Number(r.avg_score || 0), 0) / rounds.length;
  return `共 ${rounds.length} 个轮次，轮次均分 ${avg.toFixed(1)}`;
}

function dimensionCard(data) {
  const dims = data.dimensions || [];
  if (!dims.length) {
    return el('section', { className: 'card' },
      el('div', { className: 'card-title', textContent: '五维表现' }),
      el('div', { className: 'share-empty', textContent: '本次未记录维度评分' }));
  }
  return el('section', { className: 'card' },
    el('div', { className: 'card-title', textContent: '五维表现' }),
    el('div', { className: 'chart-wrapper', style: 'max-width:420px;margin:0 auto;' },
      el('canvas', { id: 'share-radar' })),
    el('div', { className: 'share-dim-list' },
      ...dims.map(d => el('div', { className: 'share-dim-row' },
        el('span', { className: 'share-dim-name',
                     textContent: d.label || DIM_LABEL_FALLBACK[d.key] || d.key }),
        el('span', { className: 'share-dim-bar' },
          el('span', {
            className: 'share-dim-fill',
            style: `width:${Math.min(100, (Number(d.score || 0) / 5) * 100)}%;`,
          })),
        el('span', { className: 'share-dim-score',
                     textContent: Number(d.score || 0).toFixed(1) }),
      )),
    ),
  );
}

function strengthsCard(data) {
  const box = (title, items, cls) => el('div', { className: `share-list-box ${cls}` },
    el('div', { className: 'share-list-title', textContent: title }),
    items && items.length
      ? el('ul', { className: 'share-list' },
          ...items.map(x => el('li', { textContent: x })))
      : el('div', { className: 'share-empty', textContent: '无' }),
  );

  return el('section', { className: 'card' },
    el('div', { className: 'card-title', textContent: '诊断摘要' }),
    el('div', { className: 'share-summary-grid' },
      box('优势', data.strengths, 'ok'),
      box('待改进', data.weaknesses, 'warn'),
    ),
    data.suggestions
      ? el('div', { className: 'share-suggestions', textContent: data.suggestions })
      : null,
  );
}

function qaCard(data) {
  const items = data.qa_details || [];
  return el('section', { className: 'card' },
    el('div', { className: 'card-title', textContent: '逐题明细' }),
    items.length
      ? el('div', { className: 'share-qa-list' },
          ...items.map(q => el('div', { className: 'share-qa-item' },
            el('div', { className: 'share-qa-head' },
              el('span', { className: 'share-qa-index', textContent: `#${q.index ?? '-'}` }),
              el('span', { className: 'share-qa-round', textContent: q.round_name || '' }),
              el('span', { className: 'share-qa-score',
                           textContent: q.score != null ? Number(q.score).toFixed(1) : '—' }),
            ),
            el('div', { className: 'share-qa-question', textContent: q.question }),
            q.overall_comment
              ? el('div', { className: 'share-qa-comment', textContent: q.overall_comment })
              : null,
            q.risk_points && q.risk_points.length
              ? el('div', { className: 'share-qa-risks' },
                  el('span', { className: 'share-qa-risk-label', textContent: '风险点：' }),
                  el('span', { textContent: q.risk_points.join('；') }))
              : null,
            q.assisted
              ? el('div', { className: 'share-qa-assisted',
                            textContent: '本题在提示/引导下完成' })
              : null,
            q.follow_up_skipped
              ? el('div', { className: 'share-qa-assisted',
                            textContent: '本题面试官追问后未补充作答（跳过追问）' })
              : null,
          )))
      : el('div', { className: 'share-empty', textContent: '无逐题明细' }),
  );
}

function detailHiddenCard() {
  return el('section', { className: 'card share-detail-hidden' },
    el('div', { className: 'card-title', textContent: '逐题明细' }),
    el('div', { className: 'share-empty',
      textContent: '分享者未公开逐题问答内容。如需查看，请向其索取包含明细的分享链接。' }),
  );
}

// ===== 雷达图 =====

function mountRadar(scope, data) {
  const canvas = scope.querySelector('#share-radar');
  if (!canvas || !window.Chart) return;
  const dims = data.dimensions || [];
  if (!dims.length) return;

  new window.Chart(canvas, {
    type: 'radar',
    data: {
      labels: dims.map(d => d.label || DIM_LABEL_FALLBACK[d.key] || d.key),
      datasets: [{
        label: '得分',
        data: dims.map(d => Number(d.score || 0)),
        backgroundColor: 'rgba(196, 79, 58, 0.15)',
        borderColor: 'rgba(196, 79, 58, 0.9)',
        pointBackgroundColor: 'rgba(196, 79, 58, 1)',
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        r: {
          min: 0,
          max: 5,
          ticks: { stepSize: 1, backdropColor: 'transparent' },
        },
      },
      plugins: { legend: { display: false } },
    },
  });
}
