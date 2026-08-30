// ===================================================
// report.js — 综合报告 + Chart.js 雷达图
// ===================================================

import { $, el, toast, DIM_NAMES, escHtml } from './utils.js';
import { getReport, exportReview, getGapAnalysis, crossJobCompare } from './api.js';

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

  // v3.1: 跨岗位对比卡片
  panel.appendChild(_buildCompareCard());

  // v4.0: 支持从「历史」Tab 跳转并自动加载
  const pending = window._pendingReportSession;
  if (pending) {
    window._pendingReportSession = null;
    const input = $('#report-session-id');
    if (input) input.value = pending;
    loadReport();
  }
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

  // v4.0: 报告 Hero（环形总分 + 元信息）
  const sessionId = report.session_id || '';
  const oAvg = report.overall_avg || 0;
  const ringOffset = (326.7 * (1 - Math.min(oAvg, 5) / 5)).toFixed(1);
  content.appendChild(el('div', { className: 'report-hero card' },
    el('div', {
      className: 'report-hero-ring',
      innerHTML: `
        <svg class="score-ring" viewBox="0 0 120 120" width="110" height="110" role="img" aria-label="综合评分 ${oAvg.toFixed(1)} 分（满分 5 分）">
          <circle class="ring-track" cx="60" cy="60" r="52"></circle>
          <circle class="ring-fill" cx="60" cy="60" r="52" stroke-dasharray="326.7" stroke-dashoffset="${ringOffset}"></circle>
          <text class="ring-text" x="60" y="60" text-anchor="middle" dominant-baseline="central">${oAvg.toFixed(1)}</text>
        </svg>`,
    }),
    el('div', { className: 'report-hero-info' },
      el('div', { className: 'report-hero-label', textContent: report.scoring?.weighted ? '加权综合评分' : '综合评分' }),
      el('div', { className: 'report-hero-sub', textContent: `满分 5 · ${report.interviewer_style || 'friendly'} 风格 · ${report.rounds.length} 轮面试` }),
      sessionId ? el('button', {
        className: 'btn btn-secondary btn-sm',
        style: 'margin-top:12px;width:fit-content;',
        textContent: '📥 导出复盘文件',
        onClick: () => {
          exportReview(sessionId).catch(e => toast(e.message, 'error'));
        },
      }) : '',
      // v6.1: HTML 导出（借鉴 offerMaster 的 MD→HTML 渲染，浏览器打印即得 PDF）
      sessionId ? el('button', {
        className: 'btn btn-secondary btn-sm',
        style: 'margin-top:8px;width:fit-content;',
        textContent: '🖨 打印 / 存为 PDF',
        onClick: () => {
          window.open(`${location.origin}/api/reports/${sessionId}/export.html`, '_blank');
        },
      }) : '',
    ),
  ));

  // v4.0: 关键指标条
  const totalQ = (report.rounds || []).reduce((a, r) => a + (r.questions_count || 0), 0);
  const totalA = (report.rounds || []).reduce((a, r) => a + (r.answers_count || 0), 0);
  content.appendChild(el('div', { className: 'report-metrics' },
    el('div', { className: 'metric-item' },
      el('div', { className: 'metric-value', textContent: String(report.rounds?.length || 0) }),
      el('div', { className: 'metric-label', textContent: '轮面试' }),
    ),
    el('div', { className: 'metric-item' },
      el('div', { className: 'metric-value', textContent: `${totalA}/${totalQ}` }),
      el('div', { className: 'metric-label', textContent: '题已答' }),
    ),
    el('div', { className: 'metric-item' },
      el('div', { className: 'metric-value', textContent: String(report.strengths?.length || 0) }),
      el('div', { className: 'metric-label', textContent: '强项' }),
    ),
    el('div', { className: 'metric-item' },
      el('div', { className: 'metric-value', textContent: String(report.weaknesses?.length || 0) }),
      el('div', { className: 'metric-label', textContent: '待提升' }),
    ),
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

  // v4.0: 雷达图 + 轮次时间线（双栏）
  const grid = el('div', { className: 'report-grid-2' });

  if (report.dimension_trends?.length) {
    const chartDiv = el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '🎯 各维度趋势' }),
      el('div', { className: 'chart-container' },
        el('div', { className: 'chart-wrapper' },
          el('canvas', { id: 'radar-chart' }),
        ),
      ),
    );
    grid.appendChild(chartDiv);
    setTimeout(() => drawRadarChart(report), 100);
  }

  if (report.rounds?.length) {
    grid.appendChild(el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '📋 轮次时间线' }),
      el('div', { className: 'round-timeline' },
        ...report.rounds.map(r => el('div', { className: 'timeline-node' },
          el('div', { className: 'timeline-dot' }),
          el('div', { className: 'timeline-body' },
            el('div', { className: 'timeline-name', textContent: r.round_name }),
            el('div', { className: 'timeline-meta', textContent: `${r.answers_count}/${r.questions_count} 题已答` }),
          ),
          el('div', { className: 'timeline-score', textContent: (r.avg_score || 0).toFixed(1) }),
        )),
      ),
    ));
  }

  content.appendChild(grid);

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

  // v5.0: 薄弱点标签跨轮累计（对标 agent-interview-coach /今日弱点）
  if (report.weakness_tag_summary?.length) {
    content.appendChild(el('div', { className: 'card', style: 'margin-top:12px;' },
      el('div', { className: 'card-title', textContent: '🏷 薄弱点标签（跨轮累计）' }),
      el('div', { className: 'report-tag-cloud', style: 'display:flex;flex-wrap:wrap;gap:8px;' },
        ...report.weakness_tag_summary.map(item => el('span', {
          className: 'report-tag',
          style: 'padding:4px 12px;border-radius:14px;background:#FEF2F2;color:#DC2626;font-size:.8rem;font-weight:500;',
          textContent: `${item.tag} ×${item.count}`,
        })),
      ),
    ));
  }

  // 建议
  if (report.suggestions) {
    content.appendChild(el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '💡 提升建议' }),
      el('div', { className: 'suggestions-block', textContent: report.suggestions }),
    ));
  }

  // v6.2: 简历前置追问点（解析阶段产出，本场面试的提问依据）
  const rp = report.resume_points;
  if (rp && (rp.deep_dive_points?.length || rp.vague_points?.length)) {
    content.appendChild(el('div', { className: 'card', style: 'margin-top:12px;' },
      el('div', { className: 'card-title', textContent: '🔎 简历追问线索（解析阶段提取）' }),
      el('div', { style: 'display:flex;flex-wrap:wrap;gap:16px;' },
        renderPointList('★ 值得深挖的点', rp.deep_dive_points),
        renderPointList('★ 可疑 / 模糊的点', rp.vague_points),
      ),
    ));
  }

  // v6.2: 逐题拆解 —— 真实面试影响 + 思考时长（借鉴 GrillMind 的 qaBreakdown）
  if (report.qa_breakdown?.length) {
    const st = report.thinking_stats || {};
    let statLine = st.tracked_count
      ? `⏱ 平均思考 ${st.avg_seconds}s（最长 ${st.max_seconds}s / 最短 ${st.min_seconds}s），共 ${st.answered_count} 题`
      : `共 ${st.answered_count || 0} 题（未采集到思考时长）`;
    // v7.0.2: 追问回避统计（测评问题 #1 —— 跳过追问不再零痕迹）
    const fuStats = report.follow_up_stats || {};
    if (fuStats.skipped_count) {
      statLine += ` · ⏭️ 跳过追问 ${fuStats.skipped_count} 次`;
    }
    content.appendChild(el('div', { className: 'card', style: 'margin-top:12px;' },
      el('div', { className: 'card-title', textContent: '📊 逐题拆解' }),
      el('div', {
        style: 'font-size:.8rem;color:var(--text-secondary);margin-bottom:8px;',
        textContent: statLine,
      }),
      ...report.qa_breakdown.map(renderQaItem),
    ));
  }

  // v7.0: 分享给招聘者（生成只读链接）
  content.appendChild(renderShareSection(sessionId));

  // v3.1: Gap 分析容器（异步加载）
  const gapContainer = el('div', { id: 'gap-analysis-container' });
  content.appendChild(gapContainer);

  // 自动触发 Gap 分析
  loadGapAnalysis(sessionId);
}

// ——— v7.0: 分享给招聘者 ———

/**
 * 分享区：生成 / 复制 / 撤销 / 查看访问次数。
 *
 * 默认不勾选"包含逐题问答"是有意的：逐字回答是夹带手机号、薪资、内部项目名
 * 风险最高的部分，而分享报告通常只想证明"水平如何"。
 */
function renderShareSection(sessionId) {
  const listBox = el('div', { id: 'share-list', className: 'share-manage-list' });
  // 本次会话新生成的明文 token（按创建顺序）。列表接口不返回 token，
  // 撤销必须靠这些明文 —— 见 renderShareList 的说明。
  const revocable = [];
  // v7.0.1: 可选——填了招聘者用户名，报告会进入对方登录后的收件箱
  const recruiterInput = el('input', {
    className: 'form-input', id: 'share-recruiter',
    placeholder: '招聘者用户名（选填，填了进对方收件箱）',
    style: 'max-width:260px;',
  });
  const includeDetail = el('input', { type: 'checkbox', id: 'share-include-detail' });
  const expirySel = el('select', { id: 'share-expiry', className: 'form-input', style: 'max-width:150px;' },
    el('option', { value: '7', textContent: '7 天有效' }),
    el('option', { value: '30', textContent: '30 天有效', selected: true }),
    el('option', { value: '0', textContent: '长期有效' }),
  );

  const generateBtn = el('button', {
    className: 'btn btn-primary btn-sm', textContent: '🔗 生成分享链接',
    onClick: async () => {
      generateBtn.disabled = true;
      try {
        const res = await request('POST', `/api/sessions/${sessionId}/share`, {
          include_detail: includeDetail.checked,
          expires_days: parseInt(expirySel.value, 10),
          // v7.0.1: 选填。后端校验存在且 role=recruiter，错误会以 400 返回
          shared_with: recruiterInput.value.trim() || null,
        });
        const url = `${location.origin}${res.url}`;
        revocable.unshift(res.share.token);
        try {
          await navigator.clipboard.writeText(url);
          toast('分享链接已生成并复制到剪贴板', 'success');
        } catch (_) {
          // 剪贴板不可用（非 HTTPS / 无权限）时至少让用户能看到链接
          toast('分享链接已生成（请手动复制下方链接）', 'success');
        }
        renderShareList(sessionId, listBox, revocable);
        listBox.dataset.lastUrl = url;
        renderLastUrl(listBox, url);
      } catch (err) {
        toast(err.message || '生成失败', 'error');
      } finally {
        generateBtn.disabled = false;
      }
    },
  });

  const box = el('div', { className: 'card share-manage' },
    el('div', { className: 'card-title', textContent: '🔗 分享给招聘者' }),
    el('div', { className: 'share-manage-desc' },
      '生成一条只读链接发给招聘方。对方无需注册即可查看，你随时可以撤销。'),
    el('div', { className: 'share-manage-controls' },
      generateBtn,
      expirySel,
      el('label', { className: 'checkbox-label', style: 'margin:0;' },
        includeDetail,
        el('span', { className: 'checkbox-text', textContent: '包含逐题问答内容' }),
      ),
    ),
    el('div', { className: 'share-manage-controls' },
      recruiterInput,
      el('span', { className: 'share-manage-meta', style: 'flex:0 1 auto;min-width:0;',
        textContent: '填了用户名：报告直接出现在对方登录后的收件箱；留空：仅生成链接，对方凭链接查看' }),
    ),
    el('div', { className: 'share-manage-hint' },
      '默认只分享结论（总分 / 五维 / 轮次概况）。勾选后会附上每道题的问答原文——' +
      '后端会自动脱敏手机号、邮箱、身份证，但仍建议确认后再分享。'),
    listBox,
  );

  renderShareList(sessionId, listBox, revocable);
  return box;
}

function renderLastUrl(listBox, url) {
  const old = listBox.parentElement?.querySelector('.share-last-url');
  if (old) old.remove();
  listBox.insertAdjacentElement('afterend', el('div', { className: 'share-last-url' },
    el('span', { className: 'share-last-url-label', textContent: '最新链接：' }),
    el('code', { textContent: url }),
  ));
}

async function renderShareList(sessionId, listBox, revocable = []) {
  listBox.replaceChildren(el('div', { className: 'share-empty', textContent: '加载中…' }));
  try {
    const data = await request('GET', `/api/sessions/${sessionId}/shares`);
    const rows = data.shares || [];
    if (!rows.length) {
      listBox.replaceChildren(el('div', { className: 'share-empty', textContent: '还没有分享链接' }));
      return;
    }
    // 列表接口按创建时间倒序返回，与 revocable（本次会话新生成的明文 token）
    // 一一对应。只有本次生成的链接带明文 token，因此也只有它们可撤销 ——
    // 这不是限制，而是凭据该有的样子：库里和列表里都只有摘要，
    // 明文只在签发那一刻出现一次。
    listBox.replaceChildren(...rows.map((r, i) => {
      const token = revocable[i];
      return el('div', { className: 'share-manage-row' },
        el('span', { className: `lib-badge${r.revoked ? '' : ' ok'}`,
                     textContent: r.revoked ? '已撤销' : '生效中' }),
        el('span', { className: 'share-manage-meta',
          textContent: `浏览 ${r.access_count || 0} 次 · ${r.include_detail ? '含逐题' : '仅结论'} · ${r.expires_at ? ('到期 ' + String(r.expires_at).slice(0, 10)) : '长期'}` }),
        (token && !r.revoked) ? el('button', {
          className: 'btn btn-sm btn-danger', textContent: '撤销',
          onClick: async () => {
            try {
              await request('DELETE', `/api/shares/${encodeURIComponent(token)}`);
              toast('已撤销，该链接立即失效', 'success');
              renderShareList(sessionId, listBox, revocable);
            } catch (err) {
              toast(err.message || '撤销失败', 'error');
            }
          },
        }) : null,
      );
    }));
  } catch (err) {
    listBox.replaceChildren(el('div', { className: 'share-empty', textContent: err.message || '加载失败' }));
  }
}

// ——— v6.2: 逐题拆解渲染 ———

/** 简历追问点列表（深挖点 / 模糊点共用） */
function renderPointList(title, items) {
  if (!items?.length) return '';
  return el('div', { style: 'flex:1;min-width:240px;' },
    el('div', { style: 'font-weight:600;font-size:.85rem;margin-bottom:6px;', textContent: title }),
    el('ul', {
      style: 'margin:0;padding-left:18px;font-size:.82rem;line-height:1.75;color:var(--text-secondary);',
    }, ...items.map(t => el('li', { textContent: t }))),
  );
}

/** 单题拆解卡片：分数 + 薄弱维度 + 思考时长 + 真实面试影响 */
function renderQaItem(qa) {
  const score = Number(qa.overall_score) || 0;
  const scoreColor = score >= 4 ? '#16A34A' : (score >= 3 ? '#F59E0B' : '#DC2626');
  const children = [
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;gap:8px;' },
      el('div', {
        style: 'font-weight:600;font-size:.9rem;flex:1;line-height:1.5;',
        textContent: `Q${qa.index}. ${qa.question}`,
      }),
      el('div', {
        style: `font-weight:700;color:${scoreColor};white-space:nowrap;`,
        textContent: score.toFixed(1),
      }),
    ),
    el('div', {
      style: 'font-size:.78rem;color:var(--text-secondary);margin-top:4px;display:flex;gap:12px;flex-wrap:wrap;',
    },
      qa.round_name ? el('span', { textContent: qa.round_name }) : '',
      qa.weakest_dimension_name ? el('span', { textContent: `最薄弱：${qa.weakest_dimension_name}` }) : '',
      qa.thinking_seconds > 0 ? el('span', { textContent: `⏱ 思考 ${qa.thinking_seconds}s` }) : '',
      qa.has_rewrite ? el('span', { textContent: '✍️ 含改写示范' }) : '',
      qa.assisted ? el('span', { textContent: '🆘 借助引导完成' }) : '',
      // v7.0.2: 追问回避标记 —— 报告如实披露"面试官追问了、候选人没接"
      qa.follow_up_skipped ? el('span', { textContent: '⏭️ 跳过追问' }) : '',
    ),
  ];
  if (qa.real_interview_impact) {
    children.push(el('div', {
      style: 'margin-top:6px;font-size:.84rem;line-height:1.6;padding:8px 10px;background:#FFF7ED;border-radius:8px;',
      textContent: `🎯 对真实面试的影响：${qa.real_interview_impact}`,
    }));
  }
  if (qa.risk_points?.length) {
    children.push(el('div', {
      style: 'margin-top:6px;font-size:.8rem;color:#DC2626;line-height:1.6;',
      textContent: `⚠️ ${qa.risk_points.join('；')}`,
    }));
  }
  return el('div', { style: 'border-top:1px solid var(--border,#eee);padding:10px 0;' }, ...children);
}

// ——— v3.1: Gap 分析 ———

async function loadGapAnalysis(sessionId) {
  const container = $('#gap-analysis-container');
  if (!container || !sessionId) return;

  // 加载中占位
  container.innerHTML = '';
  container.appendChild(el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '🔍 简历-岗位匹配度分析' }),
    el('div', { className: 'loading-spinner', textContent: '正在分析你与岗位的匹配度...' }),
  ));

  try {
    const gap = await getGapAnalysis(sessionId);
    renderGapAnalysis(container, gap);
  } catch (e) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '🔍 简历-岗位匹配度分析' }),
      el('div', {
        className: 'empty-state',
        textContent: `Gap 分析暂时不可用：${e.message || '请确认包含简历和岗位描述'}`
      }),
    ));
  }
}

function renderGapAnalysis(container, gap) {
  container.innerHTML = '';
  if (!gap || !gap.dimensions) return;

  const dims = gap.dimensions;
  const overall = gap.overall_score || 0;
  const riskColors = { '低': '#10B981', '中': '#F59E0B', '高': '#EF4444' };
  const riskColor = riskColors[gap.risk_level] || '#6B7280';

  // 总分卡片
  container.appendChild(el('div', { className: 'card' },
    el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;' },
      el('div', {},
        el('div', { className: 'card-title', textContent: '🔍 简历-岗位匹配度分析' }),
        gap.market_source ? el('div', {
          style: 'font-size:.75rem;color:var(--text-muted);',
          textContent: `📊 市场基准：${gap.market_source.keyword} · ${gap.market_source.total} 个真实岗位数据作为参照`,
        }) : '',
      ),
      el('div', { style: 'text-align:center;' },
        el('div', {
          style: `font-size:2.5rem;font-weight:700;color:${overall >= 3 ? '#4F46E5' : '#EF4444'};line-height:1.2;`,
          textContent: overall.toFixed(1),
        }),
        el('div', { style: 'font-size:.75rem;color:var(--text-muted);', textContent: '综合匹配度 / 5' }),
        el('div', {
          style: `display:inline-block;padding:2px 12px;border-radius:12px;font-size:.75rem;font-weight:600;color:white;background:${riskColor};margin-top:4px;`,
          textContent: `风险：${gap.risk_level}`,
        }),
      ),
    ),

    // 六维度横条
    el('div', { style: 'margin-top:16px;' },
      ...dims.map(d => {
        const pct = (d.score / 5) * 100;
        const barColor = d.score >= 4 ? '#10B981' : d.score >= 3 ? '#F59E0B' : '#EF4444';
        return el('div', { style: 'margin-bottom:12px;' },
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;' },
            el('div', { style: 'font-size:.85rem;font-weight:600;' },
              el('span', { textContent: d.name }),
              el('span', { style: 'font-size:.7rem;color:var(--text-muted);margin-left:6px;', textContent: `×${(d.weight*100).toFixed(0)}%` }),
            ),
            el('div', { style: 'font-size:.85rem;font-weight:700;color:' + barColor + ';', textContent: `${d.score}/5` }),
          ),
          el('div', { style: 'height:8px;background:#E5E7EB;border-radius:4px;overflow:hidden;' },
            el('div', { style: `height:100%;width:${pct}%;background:${barColor};border-radius:4px;transition:width .6s ease;` }),
          ),
          d.evidence ? el('div', {
            style: 'font-size:.75rem;color:var(--text-secondary);margin-top:4px;',
            textContent: `📌 ${d.evidence}`,
          }) : '',
          d.suggestion ? el('div', {
            style: 'font-size:.75rem;color:#4F46E5;font-weight:500;margin-top:2px;',
            textContent: `💡 ${d.suggestion}`,
          }) : '',
        );
      }    ),
    ),

    // v3.1: 市场基准参照
    gap.market_reference ? _renderMarketRefBlock(gap.market_reference) : '',

    // 整体评估
    gap.overall_assessment ? el('div', {
      style: 'margin-top:16px;padding:12px;background:#EEF2FF;border-radius:8px;font-size:.9rem;color:#3730A3;line-height:1.6;',
    },
      el('strong', { textContent: '📝 综合评估：' }),
      el('span', { textContent: gap.overall_assessment }),
    ) : '',
  ));
}

/* v3.1: 市场基准参照渲染 */
function _renderMarketRefBlock(ref) {
	if (!ref || !ref.keyword) return '';
	const cities = (ref.top_cities || []).join(' · ');
	const eduRows = (ref.education_distribution || [])
		.map(e => `<span class="mr-educell"><b>${escHtml(e.education)}</b> ${escHtml(String(e.count))}条</span>`)
		.join('');
	const skills = (ref.top_skills || [])
		.map(s => `<span class="mr-tag">${escHtml(s)}</span>`)
		.join(' ');

	return `
	<div class="market-ref-card">
		<div class="mr-header">📊 市场基准参照</div>
		<div class="mr-summary">${escHtml(ref.summary)}</div>
		${skills ? `<div class="mr-row"><span class="mr-label">🔥 热门技能</span><div class="mr-tags">${skills}</div></div>` : ''}
		${cities ? `<div class="mr-row"><span class="mr-label">🏙 热门城市</span><span>${cities}</span></div>` : ''}
		${eduRows ? `<div class="mr-row"><span class="mr-label">🎓 学历分布</span><div>${eduRows}</div></div>` : ''}
		${ref.salary_range ? `<div class="mr-row"><span class="mr-label">💰 薪资范围</span><span>${escHtml(ref.salary_range)}</span></div>` : ''}
	</div>`;
}

function drawRadarChart(report) {
  const canvas = $('#radar-chart');
  if (!canvas) return;

  // 销毁旧图表
  if (chartInstance) chartInstance.destroy();

  const ctx = canvas.getContext('2d');

  // 每个轮次一个 dataset，展示各维度在不同轮次中的表现
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

// ===== v3.1: 跨岗位对比 =====

function _buildCompareCard() {
	const container = el('div', { id: 'compare-card', className: 'card', style: 'margin-top:16px;' });

	container.appendChild(el('div', { className: 'card-title', textContent: '🔄 跨岗位对比' }));
	container.appendChild(el('p', { style: 'font-size:.85rem;color:var(--text-secondary);margin-bottom:12px;',
		textContent: '一份简历 vs 多个岗位并行评估，告诉你更适合投哪个方向。' }));

	// 简历文本
	container.appendChild(el('label', { className: 'form-label', textContent: '简历文本', for: 'compare-resume' }));
	container.appendChild(el('textarea', { id: 'compare-resume', className: 'form-input', rows: 4,
		placeholder: '粘贴简历内容...' }));

	// JD 列表容器
	container.appendChild(el('label', { className: 'form-label', textContent: '岗位描述（至少2个）', style: 'margin-top:12px;' }));
	const jdContainer = el('div', { id: 'compare-jd-list' });
	_addCompareJD(jdContainer, '岗位A');
	_addCompareJD(jdContainer, '岗位B');
	container.appendChild(jdContainer);

	// 添加岗位按钮
	container.appendChild(el('button', { className: 'btn btn-secondary', style: 'margin-top:8px;font-size:.8rem;',
		textContent: '+ 添加岗位', onClick: () => _addCompareJD(jdContainer) }));

	// 对比按钮
	container.appendChild(el('button', {
		className: 'btn btn-primary', textContent: '开始对比分析', style: 'margin-top:12px;width:100%;',
		onClick: _handleCrossCompare,
	}));

	// 结果容器
	container.appendChild(el('div', { id: 'compare-result' }));
	container.appendChild(el('div', { id: 'compare-loading', style: 'display:none;text-align:center;padding:20px;color:var(--text-muted);',
		textContent: '⏳ 正在分析各岗位匹配度...' }));

	return container;
}

function _addCompareJD(container, defaultTitle = '') {
	const idx = (container.children.length || 0);
	const row = el('div', { className: 'compare-jd-row', style: 'margin-top:8px;border:1px solid var(--border);border-radius:8px;padding:10px;background:#F8FAFC;' });

	const titleInput = el('input', {
		className: 'form-input', placeholder: `岗位${idx+1}名称`, value: defaultTitle,
		style: 'margin-bottom:6px;',
	});

	const textInput = el('textarea', {
		className: 'form-input', rows: 2,
		placeholder: '粘贴岗位描述（JD）...',
	});

	const removeBtn = el('button', {
		className: 'btn btn-sm', textContent: '✕ 删除',
		style: 'margin-top:4px;font-size:.75rem;color:#EF4444;',
		onClick: () => row.remove(),
	});

	row.appendChild(titleInput);
	row.appendChild(textInput);
	row.appendChild(removeBtn);
	container.appendChild(row);

	// 至少保留2个
	updateCompareRemoveButtons(container);
}

function updateCompareRemoveButtons(container) {
	const rows = container.querySelectorAll('.compare-jd-row');
	rows.forEach(r => {
		const btn = r.querySelector('button');
		if (btn) btn.style.display = rows.length <= 2 ? 'none' : '';
	});
}

// 监听动态删除
document.addEventListener('click', () => {
	const jdList = $('#compare-jd-list');
	if (jdList) updateCompareRemoveButtons(jdList);
});

async function _handleCrossCompare() {
	const resumeEl = $('#compare-resume');
	const jdListEl = $('#compare-jd-list');
	const resultEl = $('#compare-result');
	const loadingEl = $('#compare-loading');

	const resumeText = resumeEl?.value?.trim();
	if (!resumeText || resumeText.length < 10) {
		toast('请先粘贴简历内容（至少10字）');
		return;
	}

	const jdRows = jdListEl?.querySelectorAll('.compare-jd-row') || [];
	const jdList = [];
	jdRows.forEach(row => {
		const inputs = row.querySelectorAll('input, textarea');
		const title = inputs[0]?.value?.trim();
		const text = inputs[1]?.value?.trim();
		if (title && text) jdList.push({ title, text });
	});

	if (jdList.length < 2) {
		toast('至少需要2个有内容的岗位');
		return;
	}

	resultEl.innerHTML = '';
	if (loadingEl) loadingEl.style.display = '';

	try {
		const result = await crossJobCompare(resumeText, jdList);
		_renderCompareResults(resultEl, result);
	} catch (e) {
		resultEl.innerHTML = `<div class="form-error" style="margin-top:12px;">${escHtml(e.message)}</div>`;
	} finally {
		if (loadingEl) loadingEl.style.display = 'none';
	}
}

function _renderCompareResults(container, result) {
	if (!result.results || result.results.length === 0) {
		container.innerHTML = '<p style="color:var(--text-muted);margin-top:12px;">无对比结果</p>';
		return;
	}

	const fragments = [];

	// 推荐语
	fragments.push(el('div', {
		style: 'margin-top:16px;padding:14px;background:linear-gradient(135deg,#EEF2FF,#F0FDF4);border-radius:10px;border:1px solid #C7D2FE;',
	}, el('div', { style: 'font-weight:700;color:var(--primary-dark);margin-bottom:6px;', textContent: '🏆 综合推荐' }),
	   el('div', { style: 'font-size:.9rem;color:var(--text);line-height:1.6;', textContent: result.recommendation })));

	// 排名柱状图
	fragments.push(el('div', { style: 'margin-top:16px;font-weight:600;font-size:.9rem;', textContent: '📊 匹配度排名' }));
	result.results.forEach((item, idx) => {
		const barColor = idx === 0 ? '#10B981' : idx === result.results.length - 1 ? '#EF4444' : '#4F46E5';
		const pct = (item.overall_score / 5) * 100;
		fragments.push(el('div', { style: 'margin-top:10px;' },
			el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;' },
				el('span', { style: 'font-weight:600;font-size:.85rem;', textContent: `${idx+1}. ${item.title}` }),
				el('span', { style: `font-weight:700;color:${barColor};font-size:.85rem;`, textContent: `${item.overall_score}/5` }),
			),
			el('div', { style: 'height:8px;background:#E5E7EB;border-radius:4px;overflow:hidden;' },
				el('div', { style: `height:100%;width:${pct}%;background:${barColor};border-radius:4px;` }),
			),
			// 风险等级
			el('div', { style: 'font-size:.75rem;color:var(--text-muted);margin-top:4px;', textContent: `风险: ${item.risk_level}` }),
			// 强项
			item.key_strengths?.length ? el('div', { style: 'font-size:.75rem;color:#059669;margin-top:2px;', textContent: `✅ ${item.key_strengths.join(' · ')}` }) : '',
			// 短板
			item.key_gaps?.length ? el('div', { style: 'font-size:.75rem;color:#DC2626;margin-top:2px;', textContent: `⚠ ${item.key_gaps.join(' · ')}` }) : '',
		));
	});

	container.innerHTML = '';
	fragments.forEach(f => container.appendChild(f));
}
