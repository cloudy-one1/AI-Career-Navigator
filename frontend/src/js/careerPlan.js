// ===================================================
// careerPlan.js — 职业规划 Tab（时间轴多阶段路径）
// v3.2: 以 Gap 六维快照为基线，渲染 LLM 推理出的多阶段发展路径
// v8.x: 三模式入口——岗位库规划 / 手动填写 / 人生彩蛋
// ===================================================

import { $, el, toast } from './utils.js';
import { callCareerPlan, request, uploadResume } from './api.js';

let chartInstance = null;
let currentMode = 'library'; // 'library' | 'manual' | 'life'

/** 初始化职业规划 Tab（幂等：已渲染则跳过） */
export function initCareerPlan() {
  const panel = $('#career-plan-panel');
  if (!panel || panel.dataset.ready) return;
  panel.dataset.ready = '1';

  panel.appendChild(renderHeader());

  const modeArea = el('div', { id: 'career-mode-area' });
  panel.appendChild(modeArea);

  const resultBox = el('div', { id: 'career-result' });
  panel.appendChild(resultBox);

  switchMode('library');
}

/** 顶部说明 + 模式切换卡片 */
function renderHeader() {
  return el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '🧭 职业路径规划' }),
    el('div', { style: 'font-size:.85rem;color:var(--text-secondary);margin-bottom:16px;line-height:1.7;' },
      '基于你的简历与目标岗位，先刻画「你现在的位置」（六维匹配快照），再推理出一条可执行的多阶段发展路径（时间轴 + 每阶段需补技能 + 里程碑 + 岗位跃迁）。',
    ),
    el('div', { className: 'career-mode-grid' },
      modeCard('library', '💼', '岗位库规划', '从岗位库选择目标岗位，一键生成发展路径'),
      modeCard('manual', '✍️', '手动填写规划', '自定义目标岗位与 JD，灵活制定路径'),
      modeCard('life', '🌌', '人生规划', '不止职场，探索更广阔的人生可能性'),
    ),
  );
}

function modeCard(key, icon, title, desc) {
  const card = el('div', {
    className: `career-mode-card ${key === currentMode ? 'active' : ''}`,
    dataset: { mode: key },
    onClick: () => switchMode(key),
  },
    el('div', { className: 'career-mode-icon', textContent: icon }),
    el('div', { className: 'career-mode-title', textContent: title }),
    el('div', { className: 'career-mode-desc', textContent: desc }),
  );
  return card;
}

/** 切换模式 */
function switchMode(mode) {
  currentMode = mode;

  // 更新卡片激活态
  $$('.career-mode-card').forEach(c => {
    c.classList.toggle('active', c.dataset.mode === mode);
  });

  const area = $('#career-mode-area');
  area.innerHTML = '';

  if (mode === 'library') {
    area.appendChild(renderLibraryMode());
    loadPositionPicker();
  } else if (mode === 'manual') {
    area.appendChild(renderManualMode());
  } else if (mode === 'life') {
    area.appendChild(renderLifeMode());
  }
}

// ===================================================
// 模式 1：岗位库规划
// ===================================================

function renderLibraryMode() {
  return el('div', { className: 'card' },
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '目标岗位（从岗位库选择）' }),
      el('select', { id: 'career-lib-position', className: 'form-input' },
        el('option', { value: '', textContent: '请选择岗位…' }),
      ),
    ),
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '简历内容' }),
      el('div', { style: 'display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap;' },
        el('textarea', {
          id: 'career-resume-text',
          className: 'form-textarea',
          placeholder: '粘贴简历内容（与面试 Tab 共用），至少 10 字…',
          style: 'flex:1;min-width:200px;',
        }),
      ),
      el('div', { style: 'display:flex;gap:8px;margin-top:8px;' },
        el('label', { className: 'btn btn-sm btn-secondary', style: 'cursor:pointer;display:inline-flex;align-items:center;gap:4px;' },
          '📄 上传简历',
          el('input', {
            type: 'file', accept: '.pdf,.docx,.txt', style: 'display:none;',
            onChange: e => handleResumeUpload(e.target),
          }),
        ),
        el('button', {
          id: 'career-use-interview-resume',
          className: 'btn btn-sm btn-secondary',
          textContent: '📋 复用面试 Tab 的简历',
          onClick: copyResumeFromInterview,
        }),
      ),
    ),
    el('div', { style: 'display:flex;gap:12px;flex-wrap:wrap;' },
      el('div', { className: 'form-group', style: 'flex:1;min-width:160px;' },
        el('label', { className: 'form-label', textContent: '目标年限（年）' }),
        el('select', { id: 'career-timeframe', className: 'form-input' },
          ...[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(y =>
            el('option', { value: String(y), textContent: `${y} 年`, ...(y === 3 ? { selected: '' } : {}) })
          ),
        ),
      ),
    ),
    el('button', { id: 'career-plan-btn', className: 'btn btn-primary', textContent: '🚀 生成职业路径', onClick: submitLibraryPlan }),
  );
}

async function loadPositionPicker() {
  const sel = $('#career-lib-position');
  if (!sel) return;
  try {
    const data = await request('GET', '/api/positions');
    const rows = data.positions || [];
    sel.replaceChildren(
      el('option', { value: '', textContent: '请选择岗位…' }),
      ...rows.map(p => el('option', { value: JSON.stringify({ id: p.id, title: p.title, jd: p.jd_text || '' }), textContent: p.title || '未命名岗位' })),
    );
  } catch (e) {
    sel.replaceChildren(el('option', { value: '', textContent: '岗位库加载失败' }));
  }
}

async function submitLibraryPlan() {
  const sel = $('#career-lib-position');
  const positionStr = sel?.value;
  if (!positionStr) { toast('请先从岗位库选择一个岗位', 'warning'); return; }

  let position;
  try { position = JSON.parse(positionStr); } catch { toast('岗位数据异常', 'error'); return; }

  const resumeText = $('#career-resume-text').value.trim();
  const timeframeYears = parseInt($('#career-timeframe').value, 10) || 3;

  if (!resumeText) { toast('请输入简历内容', 'warning'); return; }

  await doSubmit({ resumeText, targetRole: position.title, jdText: position.jd, timeframeYears });
}

// ===================================================
// 模式 2：手动填写规划
// ===================================================

function renderManualMode() {
  return el('div', { className: 'card' },
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '简历内容' }),
      el('div', { style: 'display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap;' },
        el('textarea', {
          id: 'career-resume-text',
          className: 'form-textarea',
          placeholder: '粘贴简历内容（与面试 Tab 共用），至少 10 字…',
          style: 'flex:1;min-width:200px;',
        }),
      ),
      el('div', { style: 'display:flex;gap:8px;margin-top:8px;' },
        el('label', { className: 'btn btn-sm btn-secondary', style: 'cursor:pointer;display:inline-flex;align-items:center;gap:4px;' },
          '📄 上传简历',
          el('input', {
            type: 'file', accept: '.pdf,.docx,.txt', style: 'display:none;',
            onChange: e => handleResumeUpload(e.target),
          }),
        ),
        el('button', {
          id: 'career-use-interview-resume',
          className: 'btn btn-sm btn-secondary',
          textContent: '📋 复用面试 Tab 的简历',
          onClick: copyResumeFromInterview,
        }),
      ),
    ),
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '目标岗位 / 角色' }),
      el('input', {
        id: 'career-target-role',
        className: 'form-input',
        placeholder: '例如：高级后端工程师 / 技术负责人',
      }),
    ),
    el('div', { style: 'display:flex;gap:12px;flex-wrap:wrap;' },
      el('div', { className: 'form-group', style: 'flex:1;min-width:160px;' },
        el('label', { className: 'form-label', textContent: '目标年限（年）' }),
        el('select', { id: 'career-timeframe', className: 'form-input' },
          ...[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(y =>
            el('option', { value: String(y), textContent: `${y} 年`, ...(y === 3 ? { selected: '' } : {}) })
          ),
        ),
      ),
      el('div', { className: 'form-group', style: 'flex:1;min-width:160px;' },
        el('label', { className: 'form-label', textContent: '目标岗位 JD（可选，更精准）' }),
        el('textarea', {
          id: 'career-jd-text',
          className: 'form-textarea',
          style: 'min-height:56px;',
          placeholder: '粘贴目标岗位 JD 描述（可选）…',
        }),
      ),
    ),
    el('button', { id: 'career-plan-btn', className: 'btn btn-primary', textContent: '🚀 生成职业路径', onClick: submitManualPlan }),
  );
}

async function submitManualPlan() {
  const resumeText = $('#career-resume-text').value.trim();
  const targetRole = $('#career-target-role').value.trim();
  const jdText = $('#career-jd-text').value.trim();
  const timeframeYears = parseInt($('#career-timeframe').value, 10) || 3;

  if (!resumeText) { toast('请输入简历内容', 'warning'); return; }
  if (!targetRole) { toast('请输入目标岗位 / 角色', 'warning'); return; }

  await doSubmit({ resumeText, targetRole, jdText, timeframeYears });
}

// ===================================================
// 模式 3：人生规划彩蛋
// ===================================================

function renderLifeMode() {
  return el('div', { className: 'card career-life-card' },
    el('div', { className: 'career-life-emoji', textContent: '🌌' }),
    el('div', { className: 'card-title', style: 'text-align:center;margin-bottom:8px;', textContent: '人生不止职场' }),
    el('div', { style: 'font-size:.9rem;color:var(--text-secondary);text-align:center;line-height:1.7;max-width:520px;margin:0 auto 18px;' },
      '职业规划只是人生的一小部分。如果你想知道「我想过怎样的一生」「如何找到真正的热爱」「除了升职加薪还有什么活法」——豆包的人生规划智能体，或许能给你一些灵感。',
    ),
    el('div', { style: 'text-align:center;' },
      el('a', {
        href: 'https://www.doubao.com/',
        target: '_blank',
        rel: 'noopener noreferrer',
        className: 'btn btn-primary',
        style: 'display:inline-flex;align-items:center;gap:6px;',
      },
        el('span', { textContent: '✨ 去豆包探索人生更多可能' }),
        el('span', { textContent: '→' }),
      ),
    ),
    el('div', { style: 'margin-top:14px;font-size:.75rem;color:var(--text-muted);text-align:center;' },
      '彩蛋：跳转外部平台，与AI 求职领航无关，纯友情推荐。',
    ),
  );
}

// ===================================================
// 通用提交与渲染
// ===================================================

async function doSubmit({ resumeText, targetRole, jdText = '', timeframeYears = 3 }) {
  const btn = $('#career-plan-btn');
  btn.disabled = true;
  btn.textContent = '⏳ 正在推理职业路径…';

  const resultBox = $('#career-result');
  resultBox.innerHTML = '';
  resultBox.appendChild(el('div', { className: 'card' },
    el('div', { style: 'display:flex;align-items:center;gap:10px;color:var(--text-secondary);font-size:.9rem;' },
      el('span', { className: 'loading-spinner' }),
      el('span', { textContent: '正在分析现状并推理多阶段发展路径（约 10-30 秒）…' }),
    ),
  ));

  try {
    const plan = await callCareerPlan({ resumeText, targetRole, jdText, timeframeYears });
    resultBox.innerHTML = '';
    renderPlan(resultBox, plan);
  } catch (e) {
    resultBox.innerHTML = '';
    resultBox.appendChild(el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '🧭 职业路径规划' }),
      el('div', { className: 'empty-state', textContent: `规划暂时不可用：${e.message || '请稍后重试'}` }),
    ));
  } finally {
    btn.disabled = false;
    btn.textContent = '🚀 生成职业路径';
  }
}

/** 复用面试 Tab 的简历文本框内容 */
function copyResumeFromInterview() {
  const resumeText = $('#resume-text');
  const target = $('#career-resume-text');
  if (!resumeText || !resumeText.value.trim()) {
    toast('面试 Tab 的简历为空，请先粘贴简历', 'warning');
    return;
  }
  target.value = resumeText.value.trim();
  toast('已复用面试简历', 'success');
}

/** 上传简历文件并解析回填到 textarea */
async function handleResumeUpload(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  input.value = ''; // 允许重复选同一个文件
  toast('正在解析简历…', 'info');
  try {
    const data = await uploadResume(file);
    const textarea = $('#career-resume-text');
    if (textarea && data.text) {
      textarea.value = data.text;
      toast(`已解析 ${file.name}（${data.length} 字）`, 'success');
    }
  } catch (err) {
    toast(err.message || '简历解析失败', 'error');
  }
}

/** 渲染完整规划结果 */
function renderPlan(container, plan) {
  // 1. 现状基线（Gap 六维快照）
  if (plan.baseline_gap && plan.baseline_gap.dimensions?.length) {
    container.appendChild(renderBaseline(plan.baseline_gap));
  }

  // 2. 时间轴路径（核心）
  if (plan.stages?.length) {
    container.appendChild(renderTimeline(plan.stages));
  } else {
    container.appendChild(el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: '🧭 职业路径' }),
      el('div', { className: 'empty-state', textContent: '未生成阶段路径' }),
    ));
  }

  // 3. 技能进度图（Chart.js 累计曲线）
  if (plan.stages?.length) {
    container.appendChild(renderSkillChart(plan.stages));
  }

  // 4. 总结与风险
  container.appendChild(renderSummary(plan));
}

/** 现状基线卡片：你现在的位置 */
function renderBaseline(gap) {
  const riskColors = { '低': 'var(--success)', '中': '#F59E0B', '高': 'var(--danger)' };
  const riskColor = riskColors[gap.risk_level] || 'var(--ink-soft)';

  return el('div', { className: 'card career-baseline' },
    el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;' },
      el('div', {},
        el('div', { className: 'card-title', style: 'margin-bottom:4px;', textContent: '📍 你现在的位置' }),
        el('div', { style: 'font-size:.78rem;color:var(--text-muted);', textContent: '以简历-目标岗位六维匹配快照作为路径起点锚定' }),
      ),
      el('div', { style: 'text-align:right;' },
        el('div', { style: 'font-size:1.6rem;font-weight:800;color:var(--primary);', textContent: `${gap.overall_score.toFixed(1)}/5` }),
        el('div', {
          style: `display:inline-block;padding:2px 12px;border-radius:12px;font-size:.75rem;font-weight:600;color:white;background:${riskColor};margin-top:4px;`,
          textContent: `匹配风险：${gap.risk_level}`,
        }),
      ),
    ),
    el('div', { className: 'career-dims', style: 'margin-top:14px;' },
      ...gap.dimensions.map(d => {
        const pct = (d.score / 5) * 100;
        const barClass = d.score >= 4 ? 'high' : d.score >= 3 ? 'mid' : 'low';
        return el('div', { className: 'career-dim-row' },
          el('div', { className: 'career-dim-head' },
            el('span', { className: 'career-dim-name', textContent: d.name }),
            el('span', { className: 'career-dim-score', style: `color:${d.score >= 4 ? 'var(--success)' : d.score >= 3 ? '#F59E0B' : 'var(--danger)'};`, textContent: `${d.score}/5` }),
          ),
          el('div', { className: 'dim-bar' },
            el('div', { className: `dim-bar-fill ${barClass}`, style: `width:${pct}%;` }),
          ),
        );
      }),
    ),
    gap.overall_assessment ? el('div', {
      style: 'margin-top:12px;padding:10px 14px;background:var(--accent-light);border-radius:8px;font-size:.82rem;color:var(--indigo-800);line-height:1.6;',
    },
      el('strong', { textContent: '📝 现状评估：' }),
      el('span', { textContent: gap.overall_assessment }),
    ) : '',
  );
}

/** 时间轴路径（核心） */
function renderTimeline(stages) {
  const card = el('div', { className: 'card career-path-card' },
    el('div', { className: 'card-title', textContent: '🛤️ 职业发展路径（时间轴）' }),
    el('div', { className: 'career-timeline' },
      ...stages.map(stage => renderStage(stage)),
    ),
  );
  return card;
}

/** 单个阶段节点 + 卡片 */
function renderStage(stage) {
  const node = el('div', { className: 'career-stage' },
    el('div', { className: 'career-node' },
      el('div', { className: 'career-node-dot' }),
      el('div', { className: 'career-node-time', textContent: stage.timeframe || `阶段 ${stage.order}` }),
    ),
    el('div', { className: 'career-stage-card', style: `animation-delay:${(stage.order || 1) * 80}ms;` },
      el('div', { className: 'career-stage-head' },
        el('span', { className: 'career-stage-index', textContent: `第 ${stage.order} 阶段` }),
        el('span', { className: 'career-stage-title', textContent: stage.title || '阶段' }),
      ),
      stage.target_level ? el('div', { className: 'career-stage-target' },
        el('span', { className: 'career-target-label', textContent: '目标层级' }),
        el('span', { textContent: stage.target_level }),
      ) : '',

      stage.skills_to_acquire?.length ? el('div', { className: 'career-stage-block' },
        el('div', { className: 'career-stage-block-title', textContent: '🛠 需补技能' }),
        el('div', { className: 'career-tags' },
          ...stage.skills_to_acquire.map(s => el('span', { className: 'career-tag', textContent: s })),
        ),
      ) : '',

      stage.milestones?.length ? el('div', { className: 'career-stage-block' },
        el('div', { className: 'career-stage-block-title', textContent: '🏁 里程碑' }),
        el('ul', { className: 'career-milestones' },
          ...stage.milestones.map(m => el('li', { textContent: m })),
        ),
      ) : '',

      stage.transition_action ? el('div', { className: 'career-transition' },
        el('span', { className: 'career-transition-icon', textContent: '⏭' }),
        el('span', { textContent: stage.transition_action }),
      ) : '',

      stage.rationale ? el('div', { className: 'career-rationale' },
        el('span', { className: 'career-rationale-label', textContent: '为何此顺序：' }),
        el('span', { textContent: stage.rationale }),
      ) : '',
    ),
  );
  return node;
}

/** 技能累计曲线（Chart.js 条形图） */
function renderSkillChart(stages) {
  const card = el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '📈 技能补强累计曲线' }),
    el('div', { style: 'font-size:.78rem;color:var(--text-muted);margin-bottom:12px;',
      textContent: '柱高 = 到该阶段为止累计需要补强的技能数量，直观呈现推进节奏与工作量。' }),
    el('div', { className: 'chart-container', style: 'max-width:720px;' },
      el('div', { style: 'position:relative;height:260px;' },
        el('canvas', { id: 'career-skill-chart' }),
      ),
    ),
  );

  // 等待 DOM 挂载后再初始化图表
  requestAnimationFrame(() => drawSkillChart(stages));
  return card;
}

function drawSkillChart(stages) {
  const canvas = $('#career-skill-chart');
  if (!canvas) return;
  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }

  const labels = stages.map((s, i) => s.timeframe || `阶段 ${s.order || i + 1}`);
  let acc = 0;
  const data = stages.map(s => { acc += (s.skills_to_acquire?.length || 0); return acc; });

  const ctx = canvas.getContext('2d');
  chartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '累计需补技能数',
        data,
        backgroundColor: labels.map((_, i) => {
          const palette = ['#C44F3A', '#3A7A6A', '#A08945', '#2C6455', '#9B3025', '#8B9FFF', '#B48CFF']; // v5.0 纸墨调色板
          return palette[i % palette.length];
        }),
        borderRadius: 6,
        maxBarThickness: 48,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: '#DAD6CC' } },
        x: { grid: { display: false } },
      },
    },
  });
}

/** 总结与风险 */
function renderSummary(plan) {
  const riskColors = { '低': 'var(--success)', '中': '#F59E0B', '高': 'var(--danger)' };
  const riskBg = { '低': 'rgba(16,185,129,.1)', '中': 'rgba(245,158,11,.1)', '高': 'rgba(239,68,68,.1)' };
  const riskColor = riskColors[plan.risk_level] || 'var(--ink-soft)';

  return el('div', { className: 'card career-summary' },
    el('div', { className: 'card-title', textContent: '🧾 路径总结' }),
    plan.summary ? el('div', { style: 'font-size:.9rem;line-height:1.8;color:var(--text);', textContent: plan.summary }) : '',
    plan.risk_level ? el('div', { style: 'margin-top:12px;' },
      el('span', {
        style: `display:inline-block;padding:4px 16px;border-radius:999px;font-size:.8rem;font-weight:700;color:${riskColor};background:${riskBg[plan.risk_level] || 'rgba(100,116,139,.1)'};`,
        textContent: `规划风险：${plan.risk_level}`,
      }),
      el('span', { style: 'margin-left:8px;font-size:.75rem;color:var(--text-muted);', textContent: '路径由 AI 基于有限信息推理，实际推进请结合行业真实数据校验。' }),
    ) : '',
  );
}

// v8.x: 兼容 utils 中未导出 $$ 的情况，本地兜底
function $$(sel) { return Array.from(document.querySelectorAll(sel)); }
