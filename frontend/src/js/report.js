// ===================================================
// report.js — 综合报告 + Chart.js 雷达图
// ===================================================

import { $, el, toast, DIM_NAMES, countUp, skeletonBlock, burstParticles, scoreClass } from './utils.js';
import { getReport, exportReview, getGapAnalysis } from './api.js';

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

  // v4.0: 支持从「历史」Tab 跳转并自动加载
  const pending = window._pendingReportSession;
  if (pending) {
    window._pendingReportSession = null;
    const input = $('#report-session-id');
    if (input) input.value = pending;
    loadReport();
  }

  // v8.x: 面试刚结束自动加载本场报告（由 interview.js 的 finishInterview 置位）
  if (window._pendingLatestReport) {
    window._pendingLatestReport = false;
    loadLatestReport();
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

  // v7.2: 加载期间用骨架屏占位（纸纹 shimmer），替代空白等待
  const loading = $('#report-content');
  if (loading) loading.replaceChildren(skeletonBlock({ lines: 4 }));

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
      style: 'position:relative;',   // v7.3: 粒子层定位上下文
      innerHTML: `
        <svg class="score-ring ring-draw" viewBox="0 0 120 120" width="110" height="110" role="img" aria-label="综合评分 ${oAvg.toFixed(1)} 分（满分 5 分）">
          <circle class="ring-track" cx="60" cy="60" r="52"></circle>
          <circle class="ring-fill" cx="60" cy="60" r="52" stroke-dasharray="326.7" stroke-dashoffset="${ringOffset}"></circle>
          <text class="ring-text" x="60" y="60" text-anchor="middle" dominant-baseline="central">0.0</text>
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
      // v8.3: 导出端点不再需要登录态，query token 兜底随之删除
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

  // v7.2: 评分揭晓仪式感——环形描边绘制 + 分数滚动（motion.css ring-draw）
  countUp(content.querySelector('.report-hero-ring .ring-text'), oAvg, { decimals: 1, duration: 900 });

  // v7.3: 数字落定瞬间，径向粒子爆发（颜色随分数分级，动效纪律：揭示时刻专属）
  const tier = oAvg >= 4 ? 'good' : oAvg >= 3 ? 'mid' : 'poor';
  setTimeout(() => burstParticles(content.querySelector('.report-hero-ring'), tier), 950);

  // v7.3: 五维总览——逐卡弹入
  const dimAvgs = report.dimension_averages || {};
  const dimEntries = Object.entries(DIM_NAMES)
    .filter(([key]) => dimAvgs[key] != null)
    .map(([key, name]) => [key, name, Number(dimAvgs[key])]);
  if (dimEntries.length) {
    content.appendChild(el('div', { className: 'report-dims' },
      ...dimEntries.map(([key, name, avg], i) => el('div', {
        className: 'report-dim-card card-hover pop-in',
        style: `--popd:${110 * i}ms;`,
      },
        el('div', { className: 'report-dim-name', textContent: name }),
        el('div', { className: 'report-dim-score', textContent: avg.toFixed(1) }),
        el('div', { className: 'report-dim-bar' },
          el('div', {
            className: `report-dim-bar-fill ${scoreClass(avg)}`,
            style: `width:${Math.min(100, avg * 20)}%;`,
          })),
      )),
    ));
  }

  // v4.0: 关键指标条
  // v8.x: questions_count 已改为主问题实际出题数（不再用轮次规划上限作分母），
  // 另单独披露追问数，避免"题已答 X/12"低估实际答题量。
  const totalQ = (report.rounds || []).reduce((a, r) => a + (r.questions_count || 0), 0);
  const totalA = (report.rounds || []).reduce((a, r) => a + (r.answers_count || 0), 0);
  const fuAnswered = (report.follow_up_stats || {}).answered_count
                  || (report.rounds || []).reduce((a, r) => a + (r.follow_up_count || 0), 0);
  const fuSkipped = (report.follow_up_stats || {}).skipped_count || 0;
  content.appendChild(el('div', { className: 'report-metrics' },
    el('div', { className: 'metric-item' },
      el('div', { className: 'metric-value', textContent: String(report.rounds?.length || 0) }),
      el('div', { className: 'metric-label', textContent: '轮面试' }),
    ),
    el('div', { className: 'metric-item' },
      el('div', { className: 'metric-value', textContent: `${totalA}/${totalQ}` }),
      el('div', { className: 'metric-label', textContent: '主问题' }),
    ),
    el('div', { className: 'metric-item' },
      el('div', { className: 'metric-value', textContent: String(fuAnswered + fuSkipped) }),
      el('div', { className: 'metric-label', textContent: `追问(${fuSkipped ? '含跳过' + fuSkipped : '全答'})` }),
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
            el('div', { className: 'timeline-meta', textContent:
            `${r.answers_count} 主问题` + (r.follow_up_count ? ` · ${r.follow_up_count} 追问` : '') }),
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
          style: 'padding:4px 12px;border-radius:14px;background:var(--red-50);color:var(--indigo-800);font-size:.8rem;font-weight:500;',
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
    const fuStat = report.follow_up_stats || {};
    const fuTotal = (fuStat.answered_count || 0) + (fuStat.skipped_count || 0);
    let statLine = st.tracked_count
      ? `⏱ 平均思考 ${st.avg_seconds}s（最长 ${st.max_seconds}s / 最短 ${st.min_seconds}s），共 ${st.answered_count} 题`
      : `共 ${st.answered_count || 0} 题（未采集到思考时长）`;
    if (fuTotal) {
      statLine += ` · 💬 追问 ${fuTotal} 次` + (fuStat.skipped_count ? `（跳过 ${fuStat.skipped_count}）` : '');
    }
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

  // v3.1: Gap 分析容器（异步加载）
  const gapContainer = el('div', { id: 'gap-analysis-container' });
  content.appendChild(gapContainer);

  // 自动触发 Gap 分析
  loadGapAnalysis(sessionId);
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
  const scoreColor = score >= 4 ? '#16A34A' : (score >= 3 ? 'var(--warning)' : 'var(--indigo-800)');
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
      style: 'margin-top:6px;font-size:.84rem;line-height:1.6;padding:8px 10px;background:var(--amber-50);border-radius:8px;',
      textContent: `🎯 对真实面试的影响：${qa.real_interview_impact}`,
    }));
  }
  if (qa.risk_points?.length) {
    children.push(el('div', {
      style: 'margin-top:6px;font-size:.8rem;color:var(--indigo-800);line-height:1.6;',
      textContent: `⚠️ ${qa.risk_points.join('；')}`,
    }));
  }
  // v8.x: 本题下的追问（面试官追问 + 候选人补充回答），还原真实面试的追问环节
  const followUps = qa.follow_ups || [];
  if (followUps.length) {
    const fuNodes = followUps.map((fu, i) => {
      const parts = [];
      if (fu.question) {
        parts.push(el('div', {
          style: 'font-weight:600;font-size:.8rem;color:var(--ink-soft);margin-top:6px;',
          textContent: `↳ 追问${i + 1}：${fu.question}`,
        }));
      }
      if (fu.answer) {
        parts.push(el('div', {
          style: 'font-size:.82rem;line-height:1.6;padding:4px 0 4px 14px;color:var(--text-secondary);',
          textContent: `你的补充：${fu.answer}`,
        }));
      }
      return parts;
    }).flat();
    children.push(el('div', {
      style: 'margin-top:6px;padding:6px 10px;background:var(--slate-50,#f8fafc);border-radius:8px;border-left:3px solid var(--indigo-600,#4f46e5);',
    }, el('div', {
      style: 'font-size:.74rem;font-weight:600;color:var(--indigo-700,#4338ca);',
      textContent: `💬 追问环节（${followUps.length}）`,
    }), ...fuNodes));
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
  const riskColors = { '低': 'var(--success)', '中': 'var(--warning)', '高': 'var(--danger)' };
  const riskColor = riskColors[gap.risk_level] || 'var(--ink-soft)';

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
          style: `font-size:2.5rem;font-weight:700;color:${overall >= 3 ? 'var(--primary)' : 'var(--danger)'};line-height:1.2;`,
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
        const barColor = d.score >= 4 ? 'var(--success)' : d.score >= 3 ? 'var(--warning)' : 'var(--danger)';
        return el('div', { style: 'margin-bottom:12px;' },
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;' },
            el('div', { style: 'font-size:.85rem;font-weight:600;' },
              el('span', { textContent: d.name }),
              el('span', { style: 'font-size:.7rem;color:var(--text-muted);margin-left:6px;', textContent: `×${(d.weight*100).toFixed(0)}%` }),
            ),
            el('div', { style: 'font-size:.85rem;font-weight:700;color:' + barColor + ';', textContent: `${d.score}/5` }),
          ),
          el('div', { style: 'height:8px;background:var(--line);border-radius:4px;overflow:hidden;' },
            el('div', { style: `height:100%;width:${pct}%;background:${barColor};border-radius:4px;transition:width .6s ease;` }),
          ),
          d.evidence ? el('div', {
            style: 'font-size:.75rem;color:var(--text-secondary);margin-top:4px;',
            textContent: `📌 ${d.evidence}`,
          }) : '',
          d.suggestion ? el('div', {
            style: 'font-size:.75rem;color:var(--primary);font-weight:500;margin-top:2px;',
            textContent: `💡 ${d.suggestion}`,
          }) : '',
        );
      }    ),
    ),

    // v3.1: 市场基准参照
    gap.market_reference ? _renderMarketRefBlock(gap.market_reference) : '',

    // 整体评估
    gap.overall_assessment ? el('div', {
      style: 'margin-top:16px;padding:12px;background:var(--accent-light);border-radius:8px;font-size:.9rem;color:var(--indigo-800);line-height:1.6;',
    },
      el('strong', { textContent: '📝 综合评估：' }),
      el('span', { textContent: gap.overall_assessment }),
    ) : '',
  ));
}

/* v3.1: 市场基准参照渲染（返回 DOM 节点，避免 el() 把 HTML 字符串当纯文本） */
function _renderMarketRefBlock(ref) {
	if (!ref || !ref.keyword) return '';
	const children = [
		el('div', { className: 'mr-header', textContent: '📊 市场基准参照' }),
		el('div', { className: 'mr-summary', textContent: ref.summary || '' }),
	];

	if (ref.top_skills?.length) {
		children.push(el('div', { className: 'mr-row' },
			el('span', { className: 'mr-label', textContent: '🔥 热门技能' }),
			el('div', { className: 'mr-tags' },
				...ref.top_skills.map(s => el('span', { className: 'mr-tag', textContent: s }))),
		));
	}
	if (ref.top_cities?.length) {
		children.push(el('div', { className: 'mr-row' },
			el('span', { className: 'mr-label', textContent: '🏙 热门城市' }),
			el('span', { textContent: ref.top_cities.join(' · ') }),
		));
	}
	if (ref.education_distribution?.length) {
		children.push(el('div', { className: 'mr-row' },
			el('span', { className: 'mr-label', textContent: '🎓 学历分布' }),
			el('div', {},
				...ref.education_distribution.map(e => el('span', { className: 'mr-educell' },
					el('b', { textContent: e.education }),
					document.createTextNode(' ' + String(e.count) + '条'),
				)),
			),
		));
	}
	if (ref.salary_range) {
		children.push(el('div', { className: 'mr-row' },
			el('span', { className: 'mr-label', textContent: '💰 薪资范围' }),
			el('span', { textContent: ref.salary_range }),
		));
	}

	return el('div', { className: 'market-ref-card' }, ...children);
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

  const roundColors = ['#C44F3A', '#3A7A6A', '#A08945'];  // v5.0 纸墨：印章红 / 青绿 / 黄铜
  const roundDatasets = [];

  for (let r = 0; r < roundCount; r++) {
    const data = dimDataset.map(d => (d.scores && d.scores[r]) ? d.scores[r] : 0);
    if (data.every(v => v === 0)) continue;
    roundDatasets.push({
      label: report.rounds?.[r]?.round_name || `第${r+1}轮`,
      data,
      borderColor: roundColors[r] || '#C44F3A',
      backgroundColor: (roundColors[r] || '#C44F3A') + '15',
      borderWidth: 2,
      pointBackgroundColor: roundColors[r] || '#C44F3A',
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
          grid: { color: '#DAD6CC' },
          angleLines: { color: '#DAD6CC' },
        },
      },
      plugins: {
        legend: { position: 'bottom', labels: { padding: 16, font: { size: 12 } } },
      },
    },
  });
}
