// ===================================================
// interview.js — 面试流程控制 (v2.3: 语音交互)
// ===================================================

import { $, $$, el, toast, DIM_NAMES, scoreClass, escHtml } from './utils.js';
// v7.3.1: 原先另有 4 处 await import('./api.js')，但本文件顶部已静态引用 api.js，
// Vite 每次构建都告警「dynamic import will not move module into another chunk」——
// 动态化零收益，统一收敛到这里。
import {
  createInterviewWS, request,
  getCompanyProfiles, uploadResume, uploadJd, generateQuestions,
  refreshProfile,   // v8.0: 出报告后让能力档案的缓存失效
} from './api.js';
import {
  voiceSupport, speak, stopSpeaking, isSpeaking,
  voiceFillWithASR, autoReadQuestion, getMimoStatus, prefetchTTS,
  // v7.4: 熔断复位（开新一场不再继承上一场的降级）、音色设置、电平事件订阅
  resetMimoStatus, setTTSVoice, onVoiceEvent,
} from './voice.js';

// v7.4: 可选朗读音色（与后端 voice_service.PRESET_VOICES 一致，default 走服务端配置）
const TTS_VOICE_OPTIONS = ['冰糖', '茉莉', '苏打', '白桦', 'Mia', 'Chloe', 'Milo', 'Dean'];

// v7.4: 免手模式参数。自动提交是"替用户做决定"，必须留足反悔余地——
// 短文本不提交（误触）、提交前倒计时可取消（想再补充）。
const HANDSFREE_MIN_CHARS = 10;    // 转写文本低于此长度不自动提交
const HANDSFREE_COUNTDOWN_MS = 3000;
import { mountLiveRadar, updateLiveRadar, resetLiveRadar } from './liveRadar.js';

let ws = null;
let currentStyle = 'friendly';
let currentMode = 'simulation';  // v2.4: 面试模式

// v7.0: 从库选用的简历/岗位 id。
// 语义约定：非空时才随会话提交，一旦用户手改文本框就置空（内容以编辑框为准）。
let selectedResumeId = null;
let selectedPositionId = null;
let voiceStopFn = null;       // 当前录音停止函数
let voiceState = 'idle';     // 'idle' | 'listening' | 'processing' | 'speaking'
// v7.4: 免手模式（默认关）。开后：念完题自动开麦 → VAD 判断说完自动停录转写
// → 倒计时 3 秒自动提交。全部走既有入口，不开新的状态分支。
let handsFreeEnabled = false;
let autoSubmitTimer = null;   // 自动提交倒计时句柄（非 null 即"倒计时进行中"）
let autoSubmitDeadline = 0;
// v6.1: 最近一次输入来源（'text' | 'voice'），随 answer 上报；
// 后端据此对语音回答启用 ASR 转写容错评分（借鉴 offerMaster）
let lastInputSource = 'text';
let dimWeights = null;        // v2.6: 本场各维度权重
// v6.2: 思考时长采集 —— 题目/追问展示时刻，提交时算出秒数随 answer 上报，
// 最终进入报告的 qaBreakdown（借鉴 GrillMind 的 thinkingSeconds）
let questionShownAt = 0;
let followUpShownAt = 0;

// ===== v6.3 集中状态机（借鉴 HakiMeet InterviewView 的单一状态驱动）=====
// 会话阶段收敛为单一 state + setPhase() 入口，跨模块副作用统一在这里驱动。
// phase 语义：setup（引导页）→ starting（建会话/连 WS 中）→ active（会话中）
//            → done（已出报告）。断线重连不算阶段变化（onClose ≠ 结束）。
// v6.3 清理的死状态：pendingFollowUp（无读取）、currentInterviewerName（无读取）、
// autoReadEnabled（无写入恒 true，判断处直接保留 voiceSupport.tts 条件）。
const PHASE = { SETUP: 'setup', STARTING: 'starting', ACTIVE: 'active', DONE: 'done' };
const session = {
  phase: PHASE.SETUP,
  inputLocked: false,     // 诊断进行中锁输入（各锁定/恢复路径的公共判据）
};

function setPhase(next) {
  if (session.phase === next) return;
  session.phase = next;
  // 副作用统一驱动：Header 面试状态灯（app.js updateInterviewStatus 读取）。
  // 保留 window 全局镜像以兼容 app.js / report.js 的既有读取，避免连带改动。
  window._interviewActive = next === PHASE.ACTIVE;
  if (next === PHASE.SETUP) session.inputLocked = false;
}

/** 输入锁定统一入口。锁定只做 disabled；恢复时是否清空/聚焦由调用方决定
 *  （各路径语义不同：正常恢复清空、超时保留草稿、拦截清空并聚焦）。 */
function setInputLocked(locked, { clear = false, focus = false } = {}) {
  session.inputLocked = locked;
  const btn = $('#submit-answer');
  const input = $('#answer-input');
  if (btn) btn.disabled = locked;
  if (input) input.disabled = locked;
  if (locked) return;
  if (clear && input) input.value = '';
  if (focus && input) input.focus();
}

/** 计算从 shownAt 到现在的秒数（非法/未计时返回 0） */
function elapsedSeconds(shownAt) {
  if (!shownAt) return 0;
  return Math.max(0, Math.round((Date.now() - shownAt) / 100) / 10);
}

let setupStep = 1; // v4.0: 三步引导当前步骤

/** 初始化面试 Tab（v4.0：三步引导 Setup） */
export function initInterview() {
  const panel = $('#interview-panel');
  panel.innerHTML = '';
  setupStep = 1;
  // v7.4: Tab 重建 = 引导页 DOM 重建，免手开关会回到未勾选，状态必须同步复位，
  // 否则出现"复选框没勾但行为已开启"的隐性不一致。
  handsFreeEnabled = false;
  cancelAutoSubmit();
  // v6.3: Tab 重建即回到 setup。会话 UI 无法跨重建恢复——
  // 显式重置状态机优于让 phase 与 DOM 静默脱节（子代理调研的最高危路径）。
  setPhase(PHASE.SETUP);

  panel.appendChild(el('div', { id: 'setup-view', className: 'setup-layout' },
    // ── 左侧：分步引导 ──
    el('div', { className: 'card setup-steps-card' },
      // 步骤条
      el('div', { className: 'steps', id: 'setup-steps' },
        el('div', { className: 'step active', 'data-step': '1' },
          el('span', { className: 'step-dot', textContent: '1' }),
          el('span', { className: 'step-label', textContent: '简历与岗位' }),
        ),
        el('div', { className: 'step', 'data-step': '2' },
          el('span', { className: 'step-dot', textContent: '2' }),
          el('span', { className: 'step-label', textContent: '面试偏好' }),
        ),
        el('div', { className: 'step', 'data-step': '3' },
          el('span', { className: 'step-dot', textContent: '3' }),
          el('span', { className: 'step-label', textContent: '题型与风格' }),
        ),
      ),

      // Step 1：简历与岗位
      el('div', { className: 'step-card active', 'data-step-card': '1' },
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '上传简历文件' }),
          el('div', { className: 'form-upload' },
            el('input', { id: 'resume-file', type: 'file', accept: '.pdf,.docx,.txt,.doc' }),
            el('button', {
              id: 'upload-btn', className: 'btn btn-secondary btn-sm',
              textContent: '解析文件',
              onClick: handleUpload,
            }),
          ),
        ),
        // v7.0: 简历来源 —— 库内选用 / 本地粘贴上传。
        // 库只是"填充器"：选中后把文本写进下面同一个 textarea，之后仍可编辑。
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '简历来源' }),
          sourceSwitch('resume-src', [
            { v: 'paste', label: '粘贴 / 上传' },
            { v: 'library', label: '从简历库选择' },
          ], v => onSourceChange('resume', v)),
          el('div', { id: 'resume-library-picker', className: 'hidden' }),
        ),
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '简历文本（必填，可直接粘贴）' }),
          el('textarea', { id: 'resume-text', className: 'form-textarea',
            placeholder: '粘贴简历内容，或点击上方"解析文件"自动填入...',
            // v7.0: 手改文本即脱离"库来源"——提交内容以编辑框为准，
            // 避免"选了 A 简历却发出去手改后的内容且仍标记成 A"这种难以归因的情况。
            onInput: () => { selectedResumeId = null; updateSummary(); } }),
        ),
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '岗位来源' }),
          sourceSwitch('jd-src', [
            { v: 'paste', label: '粘贴 JD' },
            { v: 'library', label: '从岗位库选择' },
          ], v => onSourceChange('jd', v)),
          el('div', { id: 'jd-library-picker', className: 'hidden' }),
        ),
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '岗位描述 JD（可选，让问题更贴合）' }),
          // v7.0.2: JD 支持文件上传解析（PDF/TXT/DOCX），解析结果回填文本框
          el('div', { className: 'form-upload' },
            el('input', { id: 'jd-file', type: 'file', accept: '.pdf,.txt,.docx' }),
            el('button', {
              id: 'upload-jd-btn', className: 'btn btn-secondary btn-sm',
              textContent: '解析文件',
              onClick: handleJdUpload,
            }),
          ),
          el('textarea', { id: 'jd-text', className: 'form-textarea',
            placeholder: '粘贴目标岗位描述，或点击上方"解析文件"自动填入...',
            style: 'min-height: 80px;',
            onInput: () => { selectedPositionId = null; updateSummary(); } }),
        ),
      ),

      // Step 2：面试偏好
      el('div', { className: 'step-card', 'data-step-card': '2' },
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '📋 面试模式' }),
          el('div', { className: 'mode-selector' },
            el('div', { className: 'mode-option selected', 'data-mode': 'simulation',
              innerHTML: '<div class="mode-name">🎯 拟真模式</div><div class="mode-desc">6阶段大厂面试流程</div>',
              onClick: () => selectMode('simulation'),
            }),
            el('div', { className: 'mode-option', 'data-mode': 'traditional',
              innerHTML: '<div class="mode-name">📝 传统模式</div><div class="mode-desc">5轮次经典面试（笔试→技术面→综合→自定义）</div>',
              onClick: () => selectMode('traditional'),
            }),
            el('div', { className: 'mode-option', 'data-mode': 'coach',
              innerHTML: '<div class="mode-name">🎓 教练模式</div><div class="mode-desc">先教后问，降低门槛</div>',
              onClick: () => selectMode('coach'),
            }),
            // v5.0: 新增拷打 / 只面试模式（对标 agent-interview-coach）
            el('div', { className: 'mode-option', 'data-mode': 'hardcore',
              innerHTML: '<div class="mode-name">🔥 拷打模式</div><div class="mode-desc">高压追问，专抓名词堆砌与真实性漏洞</div>',
              onClick: () => selectMode('hardcore'),
            }),
            el('div', { className: 'mode-option', 'data-mode': 'interview_only',
              innerHTML: '<div class="mode-name">🤐 只面试模式</div><div class="mode-desc">只问不解析，还原真实面试节奏</div>',
              onClick: () => selectMode('interview_only'),
            }),
          ),
        ),
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '🎤 额外环节' }),
          el('div', { className: 'self-intro-toggle' },
            el('label', { className: 'checkbox-label' },
              el('input', { type: 'checkbox', id: 'self-intro-cb', onchange: updateSummary }),
              el('span', { className: 'checkbox-text', textContent: '包含自我介绍环节（面试开始前，了解候选人的整体背景和沟通能力）' }),
            ),
          ),
        ),
        // v6.5: 目标公司风格（借鉴 interviewerAgent 的 companies/*.yaml 配置层）
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '🏢 目标公司风格' }),
          el('select', { id: 'company-select', className: 'session-mode-select', onchange: updateSummary }),
          el('span', { className: 'session-mode-hint',
            textContent: '不同公司的评判标准与追问清单不同；默认按 JD 关键词自动匹配' }),
        ),
        // v7.4: 语音设置。此前音色只能改 .env 重启服务（前端所有调用点硬编码 'default'），
        // 免手模式则完全没有入口——把这两项能力暴露到 UI 层。
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '🔊 语音设置' }),
          el('select', {
            id: 'tts-voice-select', className: 'session-mode-select',
            onchange: () => { setTTSVoice($('#tts-voice-select').value); updateSummary(); },
          },
            el('option', { value: 'default', textContent: '默认音色（跟随服务端 MIMO_TTS_VOICE）' }),
            ...TTS_VOICE_OPTIONS.map(v => el('option', { value: v, textContent: `音色：${v}` })),
          ),
          el('span', { className: 'session-mode-hint',
            textContent: '未配置 MIMO_API_KEY 时自动降级浏览器原生语音，音色与免手模式均不生效' }),
          el('div', { className: 'self-intro-toggle' },
            el('label', { className: 'checkbox-label' },
              el('input', {
                type: 'checkbox', id: 'handsfree-cb',
                onchange: () => {
                  handsFreeEnabled = !!$('#handsfree-cb')?.checked;
                  updateSummary();
                },
              }),
              el('span', { className: 'checkbox-text',
                textContent: `免手模式：念完题自动开麦，说完自动停录并倒计时 ${HANDSFREE_COUNTDOWN_MS / 1000} 秒自动提交（倒计时期间可取消；转写少于 ${HANDSFREE_MIN_CHARS} 字不提交）` }),
            ),
          ),
        ),
      ),

      // Step 3：题型与风格
      el('div', { className: 'step-card', 'data-step-card': '3' },
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '🎭 面试官风格' }),
          el('div', { className: 'style-selector' },
            el('div', { className: 'style-option selected', 'data-style': 'friendly',
              innerHTML: '<div class="style-name">友好型</div><div class="style-desc">鼓励式提问</div>',
              onClick: () => selectStyle('friendly'),
            }),
            el('div', { className: 'style-option', 'data-style': 'strict',
              innerHTML: '<div class="style-name">严格型</div><div class="style-desc">深度追问技术细节</div>',
              onClick: () => selectStyle('strict'),
            }),
            el('div', { className: 'style-option', 'data-style': 'pressure',
              innerHTML: '<div class="style-name">压力型</div><div class="style-desc">模拟高压面试场景</div>',
              onClick: () => selectStyle('pressure'),
            }),
          ),
        ),
        el('div', { className: 'form-group' },
          el('label', { className: 'form-label', textContent: '⚖️ 题型偏好（可选，影响题目分布比例）' }),
          el('div', { className: 'type-mix-sliders' },
            typeMixSlider('知识概念', 'knowledge', 34),
            typeMixSlider('项目经验', 'project', 33),
            typeMixSlider('行为/软技能', 'behavior', 33),
          ),
          el('div', { className: 'mix-balance-row' },
            el('button', {
              className: 'btn btn-ghost btn-sm',
              textContent: '一键均衡 33/33/34',
              onClick: () => {
                [['knowledge', 34], ['project', 33], ['behavior', 33]].forEach(([k, v]) => {
                  const slider = $(`#mix-slider-${k}`);
                  if (slider) slider.value = v;
                  updateMixValue(k);
                });
                updateSummary();
              },
            }),
          ),
        ),
      ),

      // 步骤导航
      el('div', { className: 'step-nav' },
        el('button', { id: 'prev-step-btn', className: 'btn btn-ghost',
          textContent: '上一步', onClick: () => setSetupStep(setupStep - 1) }),
        el('button', { id: 'next-step-btn', className: 'btn btn-primary',
          textContent: '下一步', onClick: handleNextStep }),
      ),
    ),

    // ── 右侧：配置摘要 + 开始 ──
    el('div', { className: 'setup-summary' },
      el('div', { className: 'card' },
        el('div', { className: 'card-title', textContent: '本场配置' }),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '简历' }),
          el('span', { className: 'summary-value', id: 'summary-resume', textContent: '未填写' }),
        ),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '岗位' }),
          el('span', { className: 'summary-value', id: 'summary-jd', textContent: '未填写' }),
        ),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '模式' }),
          el('span', { className: 'summary-value', id: 'summary-mode', textContent: '拟真模式' }),
        ),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '风格' }),
          el('span', { className: 'summary-value', id: 'summary-style', textContent: '友好型' }),
        ),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '题型' }),
          el('span', { className: 'summary-value', id: 'summary-mix', textContent: '知识34% · 项目33% · 行为33%' }),
        ),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '自我介绍' }),
          el('span', { className: 'summary-value', id: 'summary-self', textContent: '不包含' }),
        ),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '公司' }),
          el('span', { className: 'summary-value', id: 'summary-company', textContent: '自动匹配' }),
        ),
        el('div', { className: 'summary-item' },
          el('span', { className: 'summary-label', textContent: '语音' }),
          el('span', { className: 'summary-value', id: 'summary-voice', textContent: '默认音色' }),
        ),
        el('button', {
          id: 'start-btn', className: 'btn btn-primary btn-block',
          textContent: '🚀 开始面试',
          onClick: startInterview,
        }),
      ),
    ),
  ));

  // 面试进行区（实战态 / 复盘态挂载点）
  panel.appendChild(el('div', { id: 'interview-area', className: 'hidden' }));

  updateSummary();
  loadCompanyProfiles();   // v6.5: 异步填充公司风格下拉（失败静默，保留兜底选项）
}

/* v7.0: 来源分段控件（与 mode-option / style-option 同构，不引入新组件） */
function sourceSwitch(id, options, onPick) {
  const box = el('div', { className: 'source-switch', id });
  options.forEach((o, i) => {
    box.appendChild(el('button', {
      type: 'button',
      className: `source-option${i === 0 ? ' selected' : ''}`,
      'data-value': o.v,
      textContent: o.label,
      onClick: e => {
        [...box.querySelectorAll('.source-option')].forEach(b => b.classList.remove('selected'));
        e.currentTarget.classList.add('selected');
        onPick(o.v);
      },
    }));
  });
  return box;
}

/* v7.0: 切换简历/岗位来源 —— 切到"库"时加载选择器 */
async function onSourceChange(kind, value) {
  const pickerId = kind === 'resume' ? '#resume-library-picker' : '#jd-library-picker';
  const picker = $(pickerId);
  if (!picker) return;
  if (value !== 'library') {
    picker.classList.add('hidden');
    picker.replaceChildren();
    return;
  }
  picker.classList.remove('hidden');
  picker.replaceChildren(el('div', { className: 'library-hint', textContent: '加载中…' }));
  try {
    const path = kind === 'resume' ? '/api/resumes' : '/api/positions';
    const data = await request('GET', path);
    const rows = (kind === 'resume' ? data.resumes : data.positions) || [];
    if (!rows.length) {
      picker.replaceChildren(el('div', { className: 'library-hint' },
        kind === 'resume' ? '简历库还是空的，可先到「简历库」上传一份。'
                          : '岗位库还是空的，可先到「岗位库」添加一个。'));
      return;
    }
    const sel = el('select', { className: 'form-input' },
      el('option', { value: '', textContent: '— 请选择 —' }),
      ...rows.map(r => el('option', { value: r.id, textContent: r.title || r.id })),
    );
    sel.addEventListener('change', () => applyFromLibrary(kind, sel.value));
    picker.replaceChildren(sel);
  } catch (err) {
    picker.replaceChildren(el('div', { className: 'library-hint', textContent: err.message || '加载失败' }));
  }
}

/* v7.0: 把库内资源填入编辑框（只做填充，不锁定 —— 用户仍可继续编辑） */
async function applyFromLibrary(kind, id) {
  if (!id) {
    if (kind === 'resume') selectedResumeId = null; else selectedPositionId = null;
    updateSummary();
    return;
  }
  try {
    const data = await request('GET', kind === 'resume' ? `/api/resumes/${id}` : `/api/positions/${id}`);
    const item = kind === 'resume' ? data.resume : data.position;
    if (!item) return;
    const target = $(kind === 'resume' ? '#resume-text' : '#jd-text');
    target.value = kind === 'resume' ? (item.raw_text || '') : (item.jd_text || '');
    if (kind === 'resume') selectedResumeId = id; else selectedPositionId = id;
    toast(kind === 'resume' ? '已填入简历' : '已填入岗位 JD', 'success');
    updateSummary();
  } catch (err) {
    toast(err.message || '加载失败', 'error');
  }
}

/* v6.5: 目标公司风格下拉（选项来自 GET /api/company-profiles） */
async function loadCompanyProfiles() {
  const sel = $('#company-select');
  if (!sel) return;
  // 先放兜底选项，接口失败时用户仍可用（自动匹配 / 不启用）
  const autoOpt = () => el('option', { value: '', textContent: '🔍 自动匹配（按 JD 关键词）' });
  const noneOpt = () => el('option', { value: 'none', textContent: '🚫 不启用公司风格' });
  sel.replaceChildren(autoOpt(), noneOpt());
  try {
    const profiles = await getCompanyProfiles();
    if (!Array.isArray(profiles) || !profiles.length) return;
    // 公司名来自后端 YAML 配置（半可信）：走 DOM 赋值而非模板串拼接，杜绝属性位逃逸
    sel.replaceChildren(autoOpt(),
      ...profiles.map(p => el('option', { value: p.name, textContent: p.display_name })),
      noneOpt());
  } catch (_) { /* 公司风格层不可用：保留兜底选项即可 */ }
}

/* v4.0: 步骤切换 */
function setSetupStep(step) {
  setupStep = Math.min(3, Math.max(1, step));
  $$('#setup-steps .step').forEach(s => {
    const n = parseInt(s.dataset.step, 10);
    s.classList.toggle('active', n === setupStep);
    s.classList.toggle('done', n < setupStep);
  });
  $$('.step-card').forEach(c => c.classList.toggle('active', parseInt(c.dataset.stepCard, 10) === setupStep));

  const prevBtn = $('#prev-step-btn');
  const nextBtn = $('#next-step-btn');
  if (prevBtn) prevBtn.style.visibility = setupStep === 1 ? 'hidden' : 'visible';
  if (nextBtn) nextBtn.textContent = setupStep === 3 ? '🚀 开始面试' : '下一步';
}

/* v4.0: 下一步（含即时校验） */
function handleNextStep() {
  if (setupStep === 1) {
    const resumeText = $('#resume-text').value.trim();
    if (!resumeText) { toast('请先填写简历内容（可直接粘贴或上传解析）', 'warning'); return; }
  }
  if (setupStep < 3) setSetupStep(setupStep + 1);
  else startInterview();
}

/* v4.0: 实时刷新右侧配置摘要 */
function updateSummary() {
  const set = (id, text) => { const node = $(`#${id}`); if (node) node.textContent = text; };
  // v7.0: 区分"手填"与"库内选用"，让用户在开始前能确认本场用的是哪份材料
  set('summary-resume', $('#resume-text').value.trim()
    ? (selectedResumeId ? '库内选用' : '已填写') : '未填写');
  set('summary-jd', $('#jd-text').value.trim()
    ? (selectedPositionId ? '库内选用' : '已填写') : '未填写');
  const modeNames = { simulation: '拟真模式', traditional: '传统模式', coach: '教练模式', hardcore: '拷打模式', interview_only: '只面试模式' };
  set('summary-mode', modeNames[currentMode] || currentMode);
  const styleNames = { friendly: '友好型', strict: '严格型', pressure: '压力型' };
  set('summary-style', styleNames[currentStyle] || currentStyle);
  const mix = getQuestionTypeMix();
  set('summary-mix', `知识${mix.knowledge}% · 项目${mix.project}% · 行为${mix.behavior}%`);
  set('summary-self', $('#self-intro-cb')?.checked ? '包含' : '不包含');
  // v6.5: 公司风格摘要
  const companySel = $('#company-select');
  if (companySel) {
    const v = companySel.value;
    const label = v === 'none' ? '不启用'
      : (v ? (companySel.options[companySel.selectedIndex]?.textContent || v) : '自动匹配');
    set('summary-company', label);
  }
  // v7.4: 语音摘要（音色 + 免手模式）
  const voiceSel = $('#tts-voice-select');
  const voiceName = voiceSel && voiceSel.value !== 'default' ? voiceSel.value : '默认音色';
  const hf = $('#handsfree-cb')?.checked ? ' · 免手' : '';
  set('summary-voice', `${voiceName}${hf}`);
}

/* v4.0: 进入实战态（隐藏 Setup，显示面试进行区） */
function enterSessionView() {
  $('#setup-view')?.classList.add('hidden');
  const area = $('#interview-area');
  if (area) area.classList.remove('hidden');
}

function selectStyle(style) {
  currentStyle = style;
  $$('.style-option').forEach(el => el.classList.remove('selected'));
  const selected = $(`.style-option[data-style="${style}"]`);
  if (selected) selected.classList.add('selected');
  updateSummary();
}

// v2.4: 选择面试模式
function selectMode(mode) {
  currentMode = mode;
  $$('.mode-option').forEach(el => el.classList.remove('selected'));
  const selected = $(`.mode-option[data-mode="${mode}"]`);
  if (selected) selected.classList.add('selected');
}

// v2.7: 题型占比滑块
function typeMixSlider(label, key, defaultValue) {
  return el('div', { className: 'type-mix-item' },
    el('div', { className: 'type-mix-header' },
      el('span', { className: 'type-mix-label', textContent: label }),
      el('span', { className: 'type-mix-value', id: `mix-val-${key}`, textContent: `${defaultValue}%` }),
    ),
    el('input', {
      type: 'range', className: 'type-mix-range', id: `mix-slider-${key}`,
      min: '0', max: '100', value: defaultValue,
      onInput: () => updateMixValue(key),
    }),
  );
}

function updateMixValue(key) {
  const slider = $(`#mix-slider-${key}`);
  const valSpan = $(`#mix-val-${key}`);
  if (slider && valSpan) {
    valSpan.textContent = `${slider.value}%`;
  }
  updateSummary();
}

function getQuestionTypeMix() {
  return {
    knowledge: parseInt($('#mix-slider-knowledge')?.value || 34),
    project: parseInt($('#mix-slider-project')?.value || 33),
    behavior: parseInt($('#mix-slider-behavior')?.value || 33),
  };
}

async function handleUpload() {
  const fileInput = $('#resume-file');
  const file = fileInput.files[0];
  if (!file) { toast('请先选择文件', 'warning'); return; }

  const btn = $('#upload-btn');
  btn.disabled = true;
  btn.textContent = '解析中...';

  try {
    const res = await uploadResume(file);
    $('#resume-text').value = res.text;
    toast('简历解析成功', 'success');
  } catch (e) {
    toast('解析失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '解析文件';
  }
}

// v7.0.2: JD 文件上传解析（测评问题 #2）—— 与 handleUpload 同款交互
async function handleJdUpload() {
  const fileInput = $('#jd-file');
  const file = fileInput.files[0];
  if (!file) { toast('请先选择文件', 'warning'); return; }

  const btn = $('#upload-jd-btn');
  btn.disabled = true;
  btn.textContent = '解析中...';

  try {
    const res = await uploadJd(file);
    $('#jd-text').value = res.text;
    selectedPositionId = null;   // 上传内容以编辑框为准，脱离岗位库关联
    toast('JD 解析成功', 'success');
    updateSummary();
  } catch (e) {
    toast('解析失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '解析文件';
  }
}

async function startInterview() {
  const resumeText = $('#resume-text').value.trim();
  if (!resumeText) { toast('请输入简历内容', 'warning'); return; }

  const jdText = $('#jd-text').value.trim();
  const btn = $('#start-btn');
  btn.disabled = true;
  btn.textContent = '正在生成问题...';

  try {
    const includeSelfIntro = $('#self-intro-cb')?.checked ?? false;
    const questionTypeMix = getQuestionTypeMix();
    const companyProfile = $('#company-select')?.value ?? '';   // v6.5: 目标公司风格
    // v7.0: 只在"确实来自库且未被手改"时带 id —— 编辑框内容始终是权威来源。
    const result = await generateQuestions(
      resumeText, jdText, currentStyle, currentMode, includeSelfIntro,
      questionTypeMix, companyProfile, selectedResumeId, selectedPositionId);
    const sessionId = result.session_id;

    // v4.0: 进入实战态
    enterSessionView();
    setPhase(PHASE.STARTING);   // v6.3: 状态机进入"连接中"

    // 连接 WebSocket
    connectWS(sessionId);
  } catch (e) {
    toast('启动失败: ' + e.message, 'error');
    btn.disabled = false;
    btn.textContent = '🚀 开始面试';
  }
}

function connectWS(sessionId) {
  currentSessionId = sessionId;
  setPhase(PHASE.ACTIVE);   // v6.3: 状态灯等副作用由 setPhase 统一驱动（原 window._interviewActive = true）
  // v3.1: 重置模块级状态，防止快速开始两次面试时状态污染
  // v6.3 补全：此前漏掉 voiceState / lastInputSource / 计时器 / 思考计时，
  // 快速开始第二场会继承上一场污染（子代理调研风险 #4）
  roundInfo = [];
  currentRound = 0;
  currentQuestion = null;
  voiceState = 'idle';
  // v7.4: 新一场面试复位云端语音熔断。否则上一场因网络抖动降级后，
  // 这一场会一直停在浏览器机械音，用户只能刷新页面。
  resetMimoStatus();
  cancelAutoSubmit();
  lastInputSource = 'text';
  questionShownAt = 0;
  followUpShownAt = 0;
  clearTimeout(_answerTimeout);
  const area = $('#interview-area');
  area.innerHTML = '';
  resetLiveRadar();
  dimWeights = null;

  ws = createInterviewWS(sessionId, {
    onOpen: () => {
      $('#start-btn').style.display = 'none';
      area.innerHTML = '<div class="streaming-indicator"><div class="streaming-dots"><div class="streaming-dot"></div><div class="streaming-dot"></div><div class="streaming-dot"></div></div>正在连接面试官...</div>';
    },

    onMessage: handleWSMessage,

    onClose: () => {
      clearTimeout(_answerTimeout);
      const btn = $('#start-btn');
      if (btn) btn.style.display = 'block';
    },

    onError: (e) => {
      toast('连接异常', 'error');
    },

    // v3.1: 断线重连回调
    onReconnect: (attempt, delay) => {
      toast(`连接断开，${Math.round(delay/1000)}秒后重连 (${attempt}/5)...`, 'warning');
    },

    onReconnectFailed: () => {
      clearTimeout(_answerTimeout);
      toast('连接失败，请刷新页面后重试', 'error');
      // 恢复输入（v6.3: 统一入口；语义：重连失败 = 解锁 + 保留草稿文字）
      const sbBtn = $('#submit-answer');
      if (sbBtn) sbBtn.textContent = '提交回答';
      setInputLocked(false);
    },
  });
}

// 轮次数据
let roundInfo = [];
let currentRound = 0;
let currentQuestion = null;
let currentSessionId = '';  // v2.5: 用于反馈
let _answerTimeout = null;  // v3.1: 回答超时计时器

// v4.0: 初始化实战双栏布局（对话流 + 固定诊断面板）
function initSessionLayout(data) {
  const area = $('#interview-area');
  area.classList.remove('hidden');
  area.innerHTML = '';
  roundInfo = data.rounds_info || [];
  area.appendChild(el('div', { className: 'session-layout' },
    el('div', { className: 'chat-flow', id: 'chat-flow' }),
    el('div', { className: 'diag-sidebar', id: 'diag-sidebar' }),
  ));
  const sidebar = $('#diag-sidebar');
  // 阶段进度
  sidebar.appendChild(buildStageIndicator(0));
  // v2.4: 显示模式标签；v5.0: 显示模式 + 阶段 + 会话中切换
  const modeNames = { simulation: '🎯 拟真模式', traditional: '📝 传统模式', coach: '🎓 教练模式', hardcore: '🔥 拷打模式', interview_only: '🤐 只面试模式' };
  const stageNames = { phone_screen: '电话筛选面', tech_round_1: '技术一面', tech_round_2: '技术二面', hr: 'HR 面' };
  sidebar.appendChild(el('div', { className: 'mode-badge', id: 'session-mode-badge',
    textContent: `${modeNames[data.mode] || data.mode} · ${stageNames[data.stage] || '进行中'}` }));

  // v5.0: 会话中切换模式的快捷菜单（下拉）
  sidebar.appendChild(el('div', { className: 'session-mode-switch', id: 'session-mode-switch',
    innerHTML: `
      <select class="session-mode-select" id="session-mode-select">
        ${Object.entries(modeNames).map(([v, label]) => `<option value="${v}" ${v === data.mode ? 'selected' : ''}>${label}</option>`).join('')}
      </select>
      <span class="session-mode-hint">切换面试模式（下一轮生效）</span>` }));

  const modeSelect = $('#session-mode-select');
  if (modeSelect) modeSelect.addEventListener('change', () => {
    const next = modeSelect.value;
    if (next && next !== (window._sessionMode || data.mode)) {
      if (ws && typeof ws.send === 'function') {
        ws.send('switch_mode', { mode: next });
      }
    }
  });
  window._sessionMode = data.mode;

  // v6.6: 面试技能入口（有状态多轮，走完自动退回正式面试；技能轮不计入本题评分）
  sidebar.appendChild(el('div', { className: 'session-skill-bar', id: 'session-skill-bar',
    innerHTML: `
      <div class="skill-bar-title">🛠 面试技能</div>
      <div class="skill-bar-actions">
        <button class="btn btn-ghost btn-sm" data-skill="quick_quiz">⚡ 快速测验</button>
        <button class="btn btn-ghost btn-sm" data-skill="concept_teach">💡 概念讲解</button>
        <button class="btn btn-ghost btn-sm" data-skill="tech_compare">⚖️ 技术对比</button>
      </div>
      <span class="skill-bar-hint" id="skill-bar-hint">临时插入，走完自动回到面试；技能轮不计入评分</span>` }));

  document.querySelectorAll('#session-skill-bar [data-skill]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (ws && typeof ws.send === 'function') {
        ws.send('skill', { action: 'activate', name: btn.dataset.skill });
      }
    });
  });
}

// v6.6: 技能条状态（激活时禁用其它技能按钮 + 显示进度与退出入口）
function setSkillBarActive(active, skillName = '', step = 1, total = 1) {
  document.querySelectorAll('#session-skill-bar [data-skill]').forEach(b => { b.disabled = active; });
  const hint = $('#skill-bar-hint');
  if (!hint) return;
  if (!active) {
    hint.textContent = '临时插入，走完自动回到面试；技能轮不计入评分';
    return;
  }
  hint.innerHTML = `进行中：<b>${escHtml(skillName)}</b>　${Number(step)}/${Number(total)} · <a href="#" id="skill-exit">退出技能</a>`;
  $('#skill-exit')?.addEventListener('click', (e) => {
    e.preventDefault();
    if (ws && typeof ws.send === 'function') ws.send('skill', { action: 'deactivate' });
  });
}

// v6.6: 技能轮推进时刷新进度（step 由后端随消息带回）
function updateSkillProgress(skillName, step, total) {
  setSkillBarActive(true, skillName, step, total);
}

function handleWSMessage(type, data) {
  switch (type) {
    case 'interviewer_info':
      initSessionLayout(data);
      break;

    case 'interviewer_change':
      showInterviewerChange($('#chat-flow'), data);
      break;

    // v2.6: 本场诊断维度权重（按 JD 动态计算）
    case 'dimension_weights':
      dimWeights = data;
      showWeightsBanner($('#diag-sidebar'), data);
      mountLiveRadar($('#diag-sidebar'));
      break;

    // v2.6: 流式诊断进度
    case 'diagnosis_status':
      showStreamStatus($('#chat-flow'), data);
      break;

    case 'diagnosis_chunk':
      appendStreamChunk('diag', data.text);
      break;

    case 'rewrite_chunk':
      appendStreamChunk('rewrite', data.text);
      break;

    // v2.6: 实时雷达刷新
    case 'radar_update':
      mountLiveRadar($('#diag-sidebar'));
      updateLiveRadar(data);
      break;

    // v2.6: 追问补充已记录
    case 'follow_up_received':
      $('#follow-up-block')?.remove();
      reactivateAnswerInput();
      break;

    case 'round_start':
      currentRound = data.round;
      document.querySelectorAll('.stage-dot').forEach(d => {
        const r = parseInt(d.dataset.round);
        if (r < currentRound) { d.className = 'stage-dot done'; }
        else if (r === currentRound) { d.className = 'stage-dot current'; }
      });
      const flowEl = $('#chat-flow');
      if (flowEl) flowEl.appendChild(el('div', { className: 'card', style: 'text-align:center;border-left:4px solid var(--primary);' },
        el('div', { style: 'font-size:.9rem;color:var(--text-secondary);', textContent: `📋 第 ${data.round + 1} / ${roundInfo.length} 轮` }),
        el('div', { style: 'font-size:1.1rem;font-weight:600;margin-top:4px;', textContent: data.name }),
      ));
      break;

    case 'question':
      currentQuestion = data;
      showQuestion($('#chat-flow'), data);
      break;

    // v2.1: 追加题目（质量不达标时追加）
    case 'extra_question':
      showExtraQuestion($('#chat-flow'), data);
      break;

    // v2.1: 质量检查结果
    case 'round_quality_check':
      showQualityCheck($('#chat-flow'), data);
      break;

    case 'diagnosis_result':
      showDiagnosis($('#chat-flow'), data);
      break;

    // v5.0: 薄弱点实时累计面板
    case 'weakness_update':
      renderWeaknessPanel(data);
      break;

    // v5.0: 会话中模式切换确认
    case 'mode_change':
      if (data && data.current) {
        window._sessionMode = data.current.mode;
        const badge = $('#session-mode-badge');
        if (badge) {
          const names = { simulation: '🎯 拟真模式', traditional: '📝 传统模式', coach: '🎓 教练模式', hardcore: '🔥 拷打模式', interview_only: '🤐 只面试模式' };
          const stageNames = { phone_screen: '电话筛选面', tech_round_1: '技术一面', tech_round_2: '技术二面', hr: 'HR 面' };
          badge.textContent = `${names[data.current.mode] || data.current.mode} · ${stageNames[data.current.stage] || '进行中'}`;
        }
        const sel = $('#session-mode-select');
        if (sel) sel.value = data.current.mode;
        if (data.message && data.message !== '模式未变化') toast(data.message, 'info');
      }
      break;

    // v2.1: 安全拦截
    case 'security_block':
      toast('⚠ 回答被拦截: ' + data.reason, 'error');
      // 重新激活输入（v6.3: 统一入口；语义：安全拦截 = 解锁 + 清空 + 聚焦）
      const sbBtn = $('#submit-answer');
      if (sbBtn) sbBtn.textContent = '提交回答';
      setInputLocked(false, { clear: true, focus: true });
      break;

    case 'follow_up':
      prefetchTTS(data.question);  // v6.1: 追问同样预取 TTS
      showFollowUp($('#chat-flow'), data.question);
      // v6.6: 技能轮的发言携带 skill/step/total → 刷新侧边栏进度
      if (data.skill) updateSkillProgress(data.skill, data.step, data.total);
      break;

    // v6.6: 面试技能激活 / 结束
    case 'skill_start':
      if (data && data.ok) {
        setSkillBarActive(true, data.skill, 1, data.total_steps);
        toast(`🛠 ${data.message || '已进入技能环节'}`, 'info');
      } else {
        toast((data && data.message) || '技能激活失败', 'error');
      }
      break;

    case 'skill_end':
      setSkillBarActive(false);
      if (data && data.message) toast(`✅ ${data.message}`, 'info');
      break;

    // v6.6: 动态难度变档 —— 必须让用户看见"难度在动"，否则分数变化无法归因
    case 'difficulty_change':
      toast((data && data.message) || '难度已调整', 'info');
      break;

    // v6.1: 候选人输入"结束面试"退出口令（后端 is_end_signal 命中）
    case 'interview_end_signal':
      toast(data.message || '收到结束信号，正在生成面评报告……', 'info');
      stopSpeaking();
      break;

    // v6.2: 收尾阶段（最后一轮答完，工程层发出收束语）
    case 'interview_closing':
      showClosingMessage($('#chat-flow'), data);
      break;

    case 'round_summary':
      showRoundSummary($('#chat-flow'), data);
      break;

    case 'interview_done':
      finishInterview(data);
      break;

    case 'error':
      toast(data.message, 'error');
      break;
  }
}

// v2.4: 面试官切换动画
function showInterviewerChange(area, data) {
  if (!data || !data.current) return;

  const isFirst = !data.previous;

  const badge = el('div', {
    className: `interviewer-badge${isFirst ? ' interviewer-fade-in' : ' interviewer-switch'}`,
  },
    el('div', { className: 'intv-icon', textContent: isFirst ? '👋' : '🔄' }),
    el('div', { className: 'intv-info' },
      el('div', {
        className: 'intv-event',
        textContent: isFirst
          ? `面试开始`
          : `${data.previous.name} → ${data.current.name}`,
      }),
      el('div', { className: 'intv-name', textContent: data.current.name }),
      data.current.description
        ? el('div', { className: 'intv-desc', textContent: data.current.description })
        : '',
    ),
  );

  area.appendChild(badge);

  // 自动移除动画卡片
  setTimeout(() => {
    badge.classList.add('interviewer-fade-out');
    setTimeout(() => badge.remove(), 400);
  }, 4000);
}

function buildStageIndicator(currentRound) {
  const div = el('div', { className: 'interview-stage', id: 'stage-container' });
  roundInfo.forEach((r, i) => {
    if (i > 0) div.appendChild(el('span', { className: 'stage-connector' }));
    const cls = i === currentRound ? 'stage-dot current' : 'stage-dot';
    div.appendChild(el('span', { className: cls, 'data-round': String(i) }));
    div.appendChild(el('span', { className: 'stage-label', textContent: r.name }));
  });
  return div;
}

// v5.0: 薄弱点实时累计面板（对标 agent-interview-coach 的 /今日弱点）
function renderWeaknessPanel(data) {
  const sidebar = $('#diag-sidebar');
  if (!sidebar) return;
  const container = $('#weakness-panel');
  const tags = (data && data.tags) || [];
  const counts = (data && data.counts) || {};

  if (!container) {
    if (!tags.length) return;
    const panel = el('div', { className: 'card weakness-panel', id: 'weakness-panel' },
      el('div', { className: 'card-title', textContent: '⚠️ 薄弱点（跨轮累计）' }),
      el('div', { className: 'weakness-tags', id: 'weakness-tags' }),
      data.recovery_active ? el('div', { className: 'recovery-banner',
        textContent: '🛟 已进入「不会答恢复」辅导' }) : '',
    );
    sidebar.appendChild(panel);
  }

  const tagsBox = $('#weakness-tags');
  if (tagsBox) {
    tagsBox.innerHTML = '';
    if (!tags.length) {
      tagsBox.appendChild(el('div', { className: 'weakness-empty', textContent: '暂无薄弱点标签' }));
    } else {
      tags.forEach(t => {
        const cnt = counts[t] || 1;
        tagsBox.appendChild(el('span', { className: 'weakness-tag',
          textContent: `${t} ×${cnt}` }));
      });
    }
  }
  // 恢复横幅
  const banner = $('#weakness-panel .recovery-banner');
  if (data && data.recovery_active && !banner) {
    $('#weakness-panel').appendChild(el('div', { className: 'recovery-banner',
      textContent: '🛟 已进入「不会答恢复」辅导' }));
  }
}

function showQuestion(area, data) {
  // 移除旧的题目卡片
  const oldQ = area.querySelector('.question-card');
  if (oldQ) oldQ.remove();
  const oldA = area.querySelector('.answer-area');
  if (oldA) oldA.remove();
  // 停止之前的语音
  stopSpeaking();
  if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
  voiceState = 'idle';

  // v2.7: 教练模式——知识点讲解卡片
  if (data.question_type === 'coach_tip') {
    const tipCard = el('div', { className: 'question-card coach-tip-card' },
      el('div', { className: 'question-meta' },
        el('span', { className: 'round-badge coach-badge', textContent: '🎓 教练引导' }),
      ),
      el('div', { className: 'question-header' },
        el('div', { className: 'question-text', textContent: data.question }),
      ),
      el('div', { className: 'coach-content', textContent: data.intent || '' }),
    );
    const continueArea = el('div', { className: 'answer-area' },
      el('div', { className: 'answer-actions' },
        el('button', {
          id: 'submit-answer', className: 'btn btn-primary',
          textContent: '明白了，继续面试 →',
          onClick: () => {
            ws.send('answer', { text: '（已阅读教练引导）', is_follow_up: false });
          },
        }),
      ),
    );
    area.appendChild(tipCard);
    area.appendChild(continueArea);
    return;
  }

  // 题目区（含朗读按钮）—— 后端 index 已是从 1 开始的序号
  const qCard = el('div', { className: 'question-card' },
    el('div', { className: 'question-meta' },
      el('span', { className: 'round-badge', textContent: `第 ${data.round + 1} 轮 · 第 ${data.index}/${data.total} 题` }),
      // v6.3: 压力题徽章（pressure_bank 注入的意外问题，与简历/JD 无关）
      data.is_pressure
        ? el('span', {
            className: 'pressure-badge',
            textContent: `⚡ 压力题${data.pressure_topic ? ` · ${data.pressure_topic}` : ''}`,
          })
        : '',
      data.focus_dimension_name
        ? el('span', { className: 'focus-badge', textContent: `🎯 补强：${data.focus_dimension_name}` })
        : '',
    ),
    el('div', { className: 'question-header' },
      el('div', { className: 'question-text', textContent: data.question }),
      voiceSupport.tts ? el('button', {
        id: 'speak-question-btn',
        className: 'voice-btn voice-btn-speaker',
        title: '朗读题目',
        innerHTML: '<span class="voice-icon">🔊</span>',
        onClick: (e) => toggleReadQuestion(e, data.question),
      }) : '',
    ),
    data.intent ? el('div', { className: 'question-intent', textContent: `🎯 考察: ${data.intent}` }) : '',
    // v6.4: 本题依据（后端确定性拼装，空串不渲染——宁缺毋谎）
    data.basis ? el('div', { className: 'question-basis', textContent: `📌 本题依据：${data.basis}` }) : '',
  );

  // 回答区（含语音输入按钮；v4.0: sticky 底部浮起输入条）
  const answerArea = el('div', { className: 'answer-area answer-dock' },
    el('div', { className: 'answer-input-wrap' },
      el('textarea', { id: 'answer-input', className: 'answer-textarea', placeholder: '在此输入你的回答...' }),
      (voiceSupport.stt || voiceSupport.mimo) ? el('button', {
        id: 'voice-input-btn',
        className: 'voice-btn voice-btn-mic',
        title: voiceSupport.mimo ? '语音输入（MiMo）' : '语音输入',
        innerHTML: '<span class="voice-icon">🎤</span>',
        // v7.4: 包一层箭头函数，否则 toggleVoiceInput(opts) 会收到 MouseEvent
        onClick: () => toggleVoiceInput(),
      }) : '',
      // v7.4: 录音电平条（VAD 已有 RMS，复用即可，绝对定位不挤占布局）
      el('div', { className: 'voice-level', id: 'voice-level' },
        el('div', { className: 'voice-level-fill' })),
    ),
    el('div', { className: 'answer-actions' },
      el('button', {
        id: 'submit-answer', className: 'btn btn-primary',
        textContent: '提交回答',
        onClick: submitAnswer,
      }),
      // v7.4: 免手模式自动提交倒计时（仅免手模式开启且转写成功后显示）
      el('div', { className: 'auto-submit-hint', id: 'auto-submit-hint' },
        el('span', { className: 'auto-submit-label', textContent: '3 秒后自动提交' }),
        el('div', { className: 'auto-submit-track' },
          el('div', { className: 'auto-submit-fill' })),
        el('button', {
          type: 'button', className: 'btn btn-ghost btn-sm',
          textContent: '取消', onClick: cancelAutoSubmit,
        }),
      ),
    ),
  );

  area.appendChild(qCard);
  area.appendChild(answerArea);
  $('#answer-input')?.focus();
  questionShownAt = Date.now();   // v6.2: 开始计本题思考时长
  followUpShownAt = 0;

  // v7.4: 换题即撤销上一题遗留的自动提交倒计时（DOM 是重建的，句柄必须手动清）
  cancelAutoSubmit();
  // v6.1: 收到新题先预取 TTS（后端 LRU 缓存，用户点朗读时零等待）
  prefetchTTS(data.question);
  const answerInput = $('#answer-input');
  if (answerInput) {
    // 手动键入 → 输入来源重置为 text；ASR 程序化填充不触发 input 事件，不会误重置
    answerInput.addEventListener('input', () => {
      lastInputSource = 'text';
      cancelAutoSubmit();   // v7.4: 用户动手打字 = 不想被自动提交
    });
  }

  // 自动朗读题目（v6.3: autoReadEnabled 恒真死开关已移除）
  if (voiceSupport.tts) {
    autoReadQuestion(data.question, (state) => {
      voiceState = state === 'speaking' ? 'speaking' : 'idle';
      updateVoiceButtonStates();
      if (state === 'idle') cancelAutoSubmit();
    }, () => {
      refocusAnswerInput();   // v6.2: 朗读结束自动切回文字输入
      armHandsFree();         // v7.4: 免手模式下念完题直接开麦
    });
    voiceState = 'speaking';
    updateVoiceButtonStates();
  }
}

// ===== v7.4 音量电平可视化 =====
// 云端 ASR 是请求-响应协议，整段录完才有字，中间没有任何反馈（反而不如浏览器
// 原生 STT 有 interim 结果上屏）。VAD 本来就在算 RMS，复用它做一条电平条，
// 让用户至少看到"麦克风在收声"。

onVoiceEvent('stt:level', (data) => {
  $$('.voice-level').forEach((box) => {
    const fill = box.querySelector('.voice-level-fill');
    if (!fill) return;
    if (data.stopped) {
      box.classList.remove('on');
      fill.style.width = '0%';
      return;
    }
    box.classList.add('on');
    fill.style.width = `${Math.round((data.level || 0) * 100)}%`;
  });
});

// ===== v7.4 免手模式 =====

/** 朗读结束后自动开麦（仅免手模式；要求云端语音，浏览器原生 STT 没有自动停录语义） */
function armHandsFree() {
  if (!handsFreeEnabled || session.inputLocked) return;
  if (voiceState !== 'idle' || autoSubmitTimer) return;
  if (!voiceSupport.mimo) return;
  // 追问块存在时优先对追问录音，否则对主回答
  if ($('#fu-answer-input')) toggleFuVoiceInput({ onTranscribed: onVoiceTranscribed });
  else toggleVoiceInput({ onTranscribed: onVoiceTranscribed });
}

/** VAD 判断"说完了"并成功转写后的回调：满足条件则进入自动提交倒计时 */
function onVoiceTranscribed(text, meta) {
  if (!handsFreeEnabled || !meta || meta.reason !== 'auto') return;
  const input = $('#fu-answer-input') || $('#answer-input');
  if (!input || input.disabled) return;
  // 太短不自动提交——多半是误触或只"嗯"了一声，替用户提交只会丢一次作答机会
  if ((input.value || '').trim().length < HANDSFREE_MIN_CHARS) return;
  scheduleAutoSubmit();
}

/** 主回答区与追问区在 DOM 中共存，倒计时控件按"当前活动区"定位，取消时全量复位 */
function _autoSubmitEls() {
  const isFollowUp = !!$('#fu-answer-input');
  const hint = $(isFollowUp ? '#fu-auto-submit-hint' : '#auto-submit-hint');
  return {
    isFollowUp,
    hint,
    fill: hint ? hint.querySelector('.auto-submit-fill') : null,
    label: hint ? hint.querySelector('.auto-submit-label') : null,
  };
}

function scheduleAutoSubmit() {
  cancelAutoSubmit();
  const { isFollowUp, hint, fill, label } = _autoSubmitEls();
  if (!hint) return;
  hint.classList.add('on');

  autoSubmitDeadline = Date.now() + HANDSFREE_COUNTDOWN_MS;
  const tick = () => {
    const left = autoSubmitDeadline - Date.now();
    if (left <= 0) {
      if (fill) fill.style.transform = 'scaleX(0)';
      cancelAutoSubmit();
      if (isFollowUp) submitFollowUp();
      else submitAnswer();
      return;
    }
    if (fill) fill.style.transform = `scaleX(${left / HANDSFREE_COUNTDOWN_MS})`;
    if (label) label.textContent = `${Math.ceil(left / 1000)} 秒后自动提交`;
    autoSubmitTimer = setTimeout(tick, 100);
  };
  tick();
}

/** 取消自动提交倒计时（提交/换题/用户动手输入/点麦克风时调用） */
function cancelAutoSubmit() {
  const wasPending = autoSubmitTimer !== null;
  if (autoSubmitTimer) { clearTimeout(autoSubmitTimer); autoSubmitTimer = null; }
  autoSubmitDeadline = 0;
  $$('.auto-submit-hint').forEach(h => h.classList.remove('on'));
  $$('.auto-submit-fill').forEach(f => { f.style.transform = 'scaleX(1)'; });
  $$('.auto-submit-label').forEach(l => { l.textContent = '3 秒后自动提交'; });
  return wasPending;
}

// ===== v2.3 语音交互 =====

function toggleReadQuestion(e, questionText) {
  if (isSpeaking()) {
    stopSpeaking();
    voiceState = 'idle';
  } else {
    speak(questionText.replace(/[*_~`#]/g, '').replace(/\n{2,}/g, '，').replace(/\n/g, '，').trim(), {
      rate: 0.9,
      onEnd: () => { voiceState = 'idle'; updateVoiceButtonStates(); },
    });
    voiceState = 'speaking';
  }
  updateVoiceButtonStates();
}

function toggleVoiceInput(opts = {}) {
  cancelAutoSubmit();   // v7.4: 用户自己动麦克风 → 撤销待提交的倒计时
  if (voiceState === 'listening' || voiceState === 'processing') {
    // 停止录音/识别
    if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
    voiceState = 'idle';
    updateVoiceButtonStates();
    return;
  }

  const textarea = $('#answer-input');
  if (!textarea) return;
  lastInputSource = 'voice';  // v6.1: 标记本次回答来自语音输入

  // v4.2: MiMo ASR 优先，浏览器 STT 降级
  voiceFillWithASR(textarea, (state) => {
    voiceState = state;
    updateVoiceButtonStates();
    if (state === 'idle') {
      voiceStopFn = null;
      refocusAnswerInput(textarea);   // v6.2: 转写结束自动切回文字输入
    }
  }, opts).then((stop) => {
    voiceStopFn = stop;
    if (voiceStopFn) {
      voiceState = 'listening';
      updateVoiceButtonStates();
    }
  });
}

function updateVoiceButtonStates() {
  // 朗读按钮
  const speakBtn = $('#speak-question-btn');
  if (speakBtn) {
    speakBtn.classList.toggle('active', voiceState === 'speaking');
    const icon = speakBtn.querySelector('.voice-icon');
    if (icon) icon.textContent = voiceState === 'speaking' ? '🔇' : '🔊';
  }

  // 麦克风按钮
  const micBtn = $('#voice-input-btn');
  if (micBtn) {
    micBtn.classList.toggle('active', voiceState === 'listening' || voiceState === 'processing');
    const icon = micBtn?.querySelector('.voice-icon');
    if (icon) icon.textContent = voiceState === 'processing' ? '⏳' : (voiceState === 'listening' ? '⏹' : '🎤');
  }

  // v4.2: 语音引擎角标（MiMo / 浏览器降级）
  syncEngineBadge(micBtn);

  // 录音时改变 textarea 边框颜色
  const textarea = $('#answer-input');
  if (textarea) {
    textarea.classList.toggle('listening', voiceState === 'listening');
  }
}

/**
 * v6.2: 语音环节结束后的"切回文字"动作（借鉴 GrillMind 的 TTS 结束自动切回）。
 * 朗读结束 / 转写结束后把焦点还给输入框并恢复占位提示，
 * 避免用户停在语音态、不知道可以直接打字。
 * @param {HTMLTextAreaElement|null} textarea
 */
function refocusAnswerInput(textarea) {
  const target = textarea || $('#answer-input') || $('#fu-answer-input');
  if (!target || target.disabled) return;
  if (typeof target.placeholder === 'string' && target.placeholder.startsWith('🎤')) {
    target.placeholder = '在此输入你的回答...';
  }
  target.focus();
  try { target.setSelectionRange(target.value.length, target.value.length); } catch (_) { /* 部分浏览器不支持 */ }
}

/**
 * 在麦克风按钮旁同步"语音引擎"角标
 * @param {HTMLElement|null} micBtn
 */
function syncEngineBadge(micBtn) {
  if (!micBtn || !micBtn.parentElement) return;
  let badge = micBtn.parentElement.querySelector('.voice-engine-badge');
  if (getMimoStatus() === 'ready') {
    if (badge) badge.remove();
    return;
  }
  if (!badge) {
    badge = el('span', { className: 'voice-engine-badge', textContent: '浏览器语音' });
    micBtn.parentElement.appendChild(badge);
  }
}

function showFollowUp(area, question) {
  stopSpeaking();

  const fuDiv = el('div', { className: 'follow-up-prompt', id: 'follow-up-block' },
    el('div', { className: 'fu-label', textContent: '💬 面试官追问' }),
    el('div', { className: 'question-header', style: 'margin-top:4px;' },
      el('div', { className: 'fu-question', textContent: question }),
      voiceSupport.tts ? el('button', {
        className: 'voice-btn voice-btn-speaker voice-btn-sm',
        title: '朗读追问',
        innerHTML: '<span class="voice-icon">🔊</span>',
        onClick: (e) => toggleReadQuestion(e, question),
      }) : '',
    ),
    el('div', { className: 'answer-input-wrap', style: 'margin-top:12px;' },
      el('textarea', { id: 'fu-answer-input', className: 'answer-textarea', placeholder: '补充你的回答...' }),
      (voiceSupport.stt || voiceSupport.mimo) ? el('button', {
        id: 'fu-voice-input-btn',
        className: 'voice-btn voice-btn-mic',
        title: voiceSupport.mimo ? '语音输入（MiMo）' : '语音输入',
        innerHTML: '<span class="voice-icon">🎤</span>',
        onClick: () => toggleFuVoiceInput(),
      }) : '',
      el('div', { className: 'voice-level' },
        el('div', { className: 'voice-level-fill' })),
    ),
    el('div', { className: 'answer-actions', style: 'margin-top:8px;' },
      el('button', {
        className: 'btn btn-primary',
        textContent: '提交补充',
        onClick: submitFollowUp,
      }),
      el('button', {
        className: 'btn btn-secondary',
        textContent: '跳过追问',
        onClick: () => { stopSpeaking(); cancelAutoSubmit(); skipFollowUp(); },
      }),
      el('div', { className: 'auto-submit-hint', id: 'fu-auto-submit-hint' },
        el('span', { className: 'auto-submit-label', textContent: '3 秒后自动提交' }),
        el('div', { className: 'auto-submit-track' },
          el('div', { className: 'auto-submit-fill' })),
        el('button', {
          type: 'button', className: 'btn btn-ghost btn-sm',
          textContent: '取消', onClick: cancelAutoSubmit,
        }),
      ),
    ),
  );

  // 添加到答案区域后面
  const answerArea = area.querySelector('.answer-area');
  if (answerArea) answerArea.after(fuDiv);
  else area.appendChild(fuDiv);
  cancelAutoSubmit();   // v7.4: 主回答区遗留的倒计时不应作用到追问上
  $('#fu-answer-input')?.focus();
  followUpShownAt = Date.now();   // v6.2: 开始计追问思考时长

  // v6.2: 自动朗读追问（与题目一致），朗读结束自动切回文字输入
  if (voiceSupport.tts) {
    autoReadQuestion(question, (state) => {
      voiceState = state === 'speaking' ? 'speaking' : 'idle';
      updateVoiceButtonStates();
      if (state === 'idle') cancelAutoSubmit();
    }, () => {
      refocusAnswerInput($('#fu-answer-input'));
      armHandsFree();         // v7.4: 免手模式下念完追问直接开麦
    });
    voiceState = 'speaking';
    updateVoiceButtonStates();
  }
}

function toggleFuVoiceInput(opts = {}) {
  cancelAutoSubmit();   // v7.4: 同 toggleVoiceInput
  if (voiceState === 'listening' || voiceState === 'processing') {
    if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
    voiceState = 'idle';
    updateFuVoiceUI();
    return;
  }

  const textarea = $('#fu-answer-input');
  if (!textarea) return;
  lastInputSource = 'voice';  // v6.1: 标记本次回答来自语音输入

  // v4.2: MiMo ASR 优先，浏览器 STT 降级
  voiceFillWithASR(textarea, (state) => {
    voiceState = state;
    updateFuVoiceUI();
    if (state === 'idle') {
      voiceStopFn = null;
      refocusAnswerInput(textarea);   // v6.2: 转写结束自动切回文字输入
    }
  }, opts).then((stop) => {
    voiceStopFn = stop;
    if (voiceStopFn) {
      voiceState = 'listening';
      updateFuVoiceUI();
    }
  });
}

function updateFuVoiceUI() {
  const micBtn = $('#fu-voice-input-btn');
  if (micBtn) {
    micBtn.classList.toggle('active', voiceState === 'listening' || voiceState === 'processing');
    const icon = micBtn.querySelector('.voice-icon');
    if (icon) icon.textContent = voiceState === 'processing' ? '⏳' : (voiceState === 'listening' ? '⏹' : '🎤');
  }
  const textarea = $('#fu-answer-input');
  if (textarea) {
    textarea.classList.toggle('listening', voiceState === 'listening');
  }
}

function submitAnswer() {
  cancelAutoSubmit();   // v7.4: 手动提交即撤销倒计时（自动提交也走这里，幂等）
  const input = $('#answer-input');
  const answer = input.value.trim();
  if (!answer) { toast('请输入回答', 'warning'); return; }

  // 停止语音
  stopSpeaking();
  if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
  voiceState = 'idle';
  updateVoiceButtonStates();

  const btn = $('#submit-answer');
  setInputLocked(true);        // v6.3: 走统一锁定入口（session.inputLocked 同步置位）
  btn.textContent = '诊断中...';

  input.disabled = true;
  // 后端读取 msg.data.text；v6.1: 上报输入来源（voice → ASR 容错评分），随后重置
  // v6.2: 附加本题思考时长（秒），进入报告 qaBreakdown
  ws.send('answer', {
    text: answer,
    is_follow_up: false,
    source: lastInputSource,
    thinking_seconds: elapsedSeconds(questionShownAt),
  });
  lastInputSource = 'text';
  questionShownAt = 0;

  // v3.1: 超时恢复 — 35秒无响应则重新激活输入
  _answerTimeout = setTimeout(() => {
    if (btn.disabled) {
      btn.disabled = false;
      btn.textContent = '提交回答';
      input.disabled = false;
      toast('诊断超时，请重试', 'warning');
    }
  }, 35000);
}

function submitFollowUp() {
  cancelAutoSubmit();   // v7.4: 同 submitAnswer
  const input = $('#fu-answer-input');
  if (!input) return;
  const answer = input.value.trim();
  if (!answer) { toast('请输入补充回答', 'warning'); return; }

  // 停止语音
  stopSpeaking();
  if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
  voiceState = 'idle';

  input.disabled = true;
  // 禁用按钮
  const buttons = $('#follow-up-block')?.querySelectorAll('button');
  buttons?.forEach(b => b.disabled = true);

  ws.send('answer', {
    text: answer,
    is_follow_up: true,
    source: lastInputSource,
    thinking_seconds: elapsedSeconds(followUpShownAt),
  });
  lastInputSource = 'text';  // v6.1: 上报后重置输入来源
  followUpShownAt = 0;

  // v3.1: 超时恢复 — 35秒无响应则重新激活
  _answerTimeout = setTimeout(() => {
    if (input.disabled) {
      input.disabled = false;
      buttons?.forEach(b => b.disabled = false);
      toast('诊断超时，请重试', 'warning');
    }
  }, 35000);
}

function skipFollowUp() {
  $('#follow-up-block')?.remove();
  stopSpeaking();
  ws.send('skip_follow_up', {});
}

// ===== v2.6: 权重横幅 =====

function showWeightsBanner(area, data) {
  const old = area.querySelector('.weights-banner');
  if (old) old.remove();

  const isDynamic = data.source === 'llm';
  const banner = el('div', {
    className: 'card weights-banner',
    style: `border-left:4px solid ${isDynamic ? 'var(--primary)' : 'var(--text-muted)'};`,
  },
    el('div', { className: 'card-title',
      textContent: isDynamic ? '⚖️ 本岗位评分权重（已按 JD 动态调整）' : '⚖️ 评分权重（五维等权）' }),
    el('div', { className: 'weights-desc', textContent: data.weight_desc || '' }),
    data.reason ? el('div', {
      style: 'font-size:.8rem;color:var(--text-secondary);margin-top:6px;',
      textContent: `📌 ${data.reason}`,
    }) : '',
  );
  area.appendChild(banner);
}

// ===== v2.6: 流式诊断渲染 =====

function showStreamStatus(area, data) {
  let box = $('#stream-box');
  if (!box) {
    box = el('div', { className: 'diagnosis-panel stream-box', id: 'stream-box' },
      el('div', { className: 'stream-status', id: 'stream-status' }),
      el('div', { className: 'stream-body', id: 'stream-diag' }),
      el('div', { className: 'stream-body stream-rewrite', id: 'stream-rewrite' }),
    );
    const qCard = area.querySelector('.question-card');
    if (qCard) qCard.after(box);
    else area.appendChild(box);
  }

  const status = $('#stream-status');
  if (!status) return;

  if (data.phase === 'diagnosing') {
    status.innerHTML =
      '<span class="streaming-dots"><span class="streaming-dot"></span>'
      + '<span class="streaming-dot"></span><span class="streaming-dot"></span></span>'
      + ' 诊断师正在分析你的回答...';
  } else if (data.phase === 'rewriting') {
    status.innerHTML =
      '<span class="streaming-dots"><span class="streaming-dot"></span>'
      + '<span class="streaming-dot"></span><span class="streaming-dot"></span></span>'
      + ' 改写专家正在生成示范回答...';
  }
}

function appendStreamChunk(kind, text) {
  if (!text) return;
  const target = $(kind === 'diag' ? '#stream-diag' : '#stream-rewrite');
  if (!target) return;
  target.textContent += text;
  target.scrollTop = target.scrollHeight;
}

function clearStreamBox() {
  $('#stream-box')?.remove();
}

function reactivateAnswerInput() {
  clearTimeout(_answerTimeout);  // v3.1: 收到响应，取消超时
  // v6.3: 统一走 setInputLocked（语义：正常恢复 = 解锁 + 清空 + 聚焦）
  const btn = $('#submit-answer');
  if (btn) btn.textContent = '提交回答';
  setInputLocked(false, { clear: true, focus: true });
}

function showDiagnosis(area, data) {
  // 移除旧的诊断面板与流式过程框
  area.querySelector('.diagnosis-panel:not(.stream-box)')?.remove();
  clearStreamBox();
  area.querySelector('.streaming-indicator')?.remove();
  $('#follow-up-block')?.remove();

  // v2.6: 后端返回 dimension_details（含 score/comment）与加权 overall_score
  const details = data.dimension_details || {};
  const oScore = Number(data.overall_score || 0);
  const weights = data.weights || dimWeights?.weights || {};
  const weakest = data.weakest_dimension || '';
  // v4.0: 原文对照（读取当前回答输入）
  const rawAnswer = ($('#answer-input')?.value || '').trim();

  const diagPanel = el('div', { className: 'diagnosis-panel' },
    el('div', { className: 'diag-section' },
      el('div', { className: 'diag-section-title', textContent: '📊 各维度诊断' }),

      // v4.0: 环形总分 Hero（5 分制）
      el('div', { className: 'diag-hero' },
        el('div', {
          className: 'diag-hero-ring',
          innerHTML: `
            <svg class="score-ring" viewBox="0 0 120 120" width="120" height="120" role="img" aria-label="本题综合评分 ${oScore.toFixed(1)} 分（满分 5 分）">
              <circle class="ring-track" cx="60" cy="60" r="52"></circle>
              <circle class="ring-fill" cx="60" cy="60" r="52" stroke-dasharray="326.7" stroke-dashoffset="${(326.7 * (1 - Math.min(oScore, 5) / 5)).toFixed(1)}"></circle>
              <text class="ring-text" x="60" y="60" text-anchor="middle" dominant-baseline="central">${oScore.toFixed(1)}</text>
            </svg>`,
        }),
        el('div', { className: 'diag-hero-info' },
          el('div', { className: 'diag-hero-score-label', textContent: '本题综合评分 · 满分 5' }),
          data.weight_desc ? el('div', { className: 'diag-hero-weight', textContent: `权重：${data.weight_desc}` }) : '',
          data.overall_comment ? el('div', { className: 'diag-hero-comment', textContent: `💬 ${data.overall_comment}` }) : '',
          weakest ? el('span', { className: 'badge badge-warning', textContent: `优先改进：${data.weakest_dimension_name || DIM_NAMES[weakest] || weakest}` }) : '',
        ),
      ),

      // 各维度
      el('div', { className: 'diag-dimensions' },
        ...Object.entries(DIM_NAMES).map(([key, name]) => {
          const dim = details[key] || {};
          const s = Number(dim.score || 0);
          const w = weights[key];
          const isWeak = key === weakest;
          return el('div', { className: `dim-item${isWeak ? ' dim-weak' : ''}` },
            el('div', { className: 'dim-name',
              textContent: w != null ? `${name} · ${(w * 100).toFixed(0)}%` : name }),
            el('div', { className: 'dim-bar' },
              el('div', { className: `dim-bar-fill ${scoreClass(s)}`, style: `width:${s * 20}%` }),
            ),
            el('div', { className: 'dim-score', textContent: String(s) }),
            isWeak ? el('span', { className: 'dim-weak-badge', textContent: '最弱项' }) : '',
            el('div', { className: 'dim-comment', textContent: dim.comment || '' }),
            // v7.3: 评分依据原话（DimensionScore.quote，v7.0 字段首次渲染）+ 黄铜扫描线
            dim.quote ? el('div', { className: 'quote-evidence quote-scan', textContent: `「${dim.quote}」` }) : '',
          );
        }),
      ),

      // v2.7: 风险点识别
      data.risk_points?.length ? el('div', { className: 'diag-risk-section' },
        el('div', { className: 'diag-risk-title', textContent: '⚠️ 回答风险点' }),
        el('ul', { className: 'diag-risk-list' },
          ...data.risk_points.map(rp => el('li', { textContent: rp })),
        ),
      ) : '',
    ),

    // 改写示范（v4.0: 原文 / 示范对照）
    data.rewritten_answer ? el('div', { className: 'diag-section' },
      el('div', { className: 'diag-section-title', textContent: '✨ 改写示范' }),
      el('div', { className: 'rewrite-section' },
        rawAnswer ? el('div', { className: 'rewrite-block' },
          el('div', { className: 'rewrite-block-label', textContent: '你的回答' }),
          el('div', { className: 'rewrite-original', textContent: rawAnswer }),
        ) : '',
        el('div', { className: 'rewrite-block' },
          el('div', { className: 'rewrite-block-label rewrite-label-ai', textContent: 'AI 示范' }),
          el('div', { className: 'rewrite-answer', textContent: data.rewritten_answer }),
        ),
      ),
      data.key_changes?.length ? el('div', {},
        el('div', { style: 'font-size:.8rem;color:var(--text-secondary);margin-bottom:6px;', textContent: '关键改动：' }),
        el('ul', { className: 'key-changes' },
          ...data.key_changes.map(c => el('li', { textContent: c })),
        ),
      ) : '',
    ) : '',

    // v2.5: 诊断反馈按钮
    el('div', { className: 'diag-feedback' },
      el('span', { className: 'feedback-label', textContent: '这个诊断有用吗？' }),
      el('button', {
        className: 'feedback-btn feedback-up',
        title: '诊断准确',
        innerHTML: '👍',
        onClick: () => submitFeedback('up', weakest),
      }),
      el('button', {
        className: 'feedback-btn feedback-down',
        title: '诊断不够准确',
        innerHTML: '👎',
        onClick: () => submitFeedback('down', weakest),
      }),
    ),
  );

  // 插入到题目卡片之后
  const qCard = area.querySelector('.question-card');
  if (qCard) qCard.after(diagPanel);
  else area.appendChild(diagPanel);

  // 有追问时保持输入禁用，等追问块出现；否则立即恢复
  if (!data.follow_up_question) {
    reactivateAnswerInput();
  }
}

/**
 * v6.2: 收尾阶段消息（工程层发出，最后一轮答完即收束）。
 * 与"候选人主动喊结束"区分开：这是正常流程走到结尾，语气上给一个明确的收束信号。
 */
function showClosingMessage(area, data) {
  area.appendChild(el('div', { className: 'card', style: 'border-left:4px solid var(--primary);' },
    el('div', { style: 'font-size:.9rem;color:var(--text-secondary);', textContent: '🏁 面试收尾' }),
    el('div', { style: 'margin-top:6px;font-weight:600;', textContent: data.round_name || '' }),
    el('div', { style: 'margin-top:6px;line-height:1.6;',
      textContent: data.message || '本次面试到此结束，正在生成面评报告……' }),
  ));
}

function showRoundSummary(area, data) {
  // v2.1: 显示质量检查结果
  let qualityHtml = '';
  if (data.quality) {
    const q = data.quality;
    const icon = q.passed ? '✅' : '⚠️';
    const summary = q.passed
      ? `本轮加权均分 ${Number(q.avg_score)}/5，达到阈值 ${Number(q.threshold)}`
      : `本轮加权均分 ${Number(q.avg_score)}/5，未达阈值 ${Number(q.threshold)}`
        + (q.weak_dimension_name ? `，薄弱环节：${escHtml(q.weak_dimension_name)}` : '');
    qualityHtml = `
      <div style="margin-top:8px;padding:8px 12px;background:${q.passed ? 'var(--emerald-50)' : 'var(--amber-50)'};border-radius:8px;font-size:.85rem;">
        ${icon} ${summary}
      </div>`;
  }

  area.appendChild(el('div', { className: 'card', style: 'border-left:4px solid var(--success);' },
    el('div', { style: 'font-size:.9rem;color:var(--text-secondary);', textContent: '✅ 本轮完成' }),
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;margin-top:8px;' },
      el('div', { style: 'font-weight:600;', textContent: data.round_name }),
      el('div', { style: 'font-size:1.2rem;font-weight:700;color:var(--primary);', textContent: data.avg_score + ' / 5' }),
    ),
    qualityHtml ? el('div', { innerHTML: qualityHtml }) : '',
    data.extra_questions_added > 0
      ? el('div', { style: 'font-size:.8rem;color:var(--text-secondary);margin-top:4px;',
          textContent: `📝 本轮追加了 ${data.extra_questions_added} 道补充题` })
      : '',
  ));
}

// ===== v2.1: 质量检查 + 追加题 =====

function showQualityCheck(area, data) {
  // 移除旧的质量提示
  const oldQC = area.querySelector('.quality-check-banner');
  if (oldQC) oldQC.remove();

  const passed = data.passed;
  const icon = passed ? '✅' : '⚠️';
  const bg = passed ? 'var(--emerald-50)' : 'var(--amber-50)';
  const border = passed ? 'var(--success)' : 'var(--warning)';

  const reason = passed
    ? '本轮质量达标，进入下一环节'
    : (data.can_add_extra
        ? `薄弱环节：${escHtml(data.weak_dimension_name) || '待定'} — 将追加针对性问题`
        : '追加题次数已用尽，进入下一环节');

  const banner = el('div', {
    className: 'quality-check-banner',
    style: `padding:10px 16px;margin:8px 0;background:${bg};border-left:4px solid ${border};border-radius:8px;font-size:.85rem;`,
    innerHTML: `${icon} <strong>质量检查：</strong>加权平均分 ${Number(data.avg_score)}/5 （阈值 ${Number(data.threshold)}） — ${reason}`,
  });

  area.appendChild(banner);
}

function showExtraQuestion(area, data) {
  // 显示追加提示
  area.appendChild(el('div', {
    className: 'card',
    style: 'border-left:4px solid var(--warning);background:var(--amber-50);margin-bottom:8px;',
    innerHTML: `
      <div style="font-size:.85rem;color:var(--text-secondary);">⚠️ 本轮质量未达标，面试官追加一题</div>
      <div style="font-size:.8rem;color:var(--text-secondary);margin-top:2px;">
        ${escHtml(data.reason) || '针对薄弱环节追加提问'}
      </div>
    `,
  }));
}

function finishInterview(data) {
  // 面试已完成，主动关闭连接（后端 handler 返回也会关连接，提前关避免误触发重连）
  if (ws && ws.close) ws.close();
  // v6.3 修复：close 后必须置空。否则二次面试 connectWS 前，
  // 任何 ws.send（如教练模式的提示音通知）会打到旧 socket 静默丢失。
  ws = null;
  const area = $('#interview-area');
  area.classList.add('hidden');

  // v4.0: 回到准备态（重建 Setup，清除已填内容）
  setPhase(PHASE.DONE);      // v6.3: 先入 done（副作用：状态灯熄灭）
  initInterview();           // 内部 setPhase(SETUP) 重建引导页

  // 保存报告数据到全局，供 report.js 使用
  // 后端 interview_done 的 data 即为报告本体
  const report = data?.report || data;
  window._latestReport = report;
  window._latestSessionId = report?.session_id || currentSessionId;

  // v8.0: 本场产生了新的能力数据 —— 让档案缓存立即失效，
  // 切回能力档案时看到的就是本场演练之后的状态（否则最多延迟 60 秒）。
  refreshProfile();

  resetLiveRadar();
}

// v2.5: 提交诊断反馈
async function submitFeedback(type, dimension) {
  if (!currentSessionId || !currentQuestion) return;

  const parent = $('#interview-area');
  if (!parent) return;

  const feedbackBtn = type === 'up' ? '.feedback-up' : '.feedback-down';
  const btn = parent.querySelector(feedbackBtn);
  if (btn) {
    btn.textContent = type === 'up' ? '👍 ✓' : '👎 ✓';
    btn.disabled = true;
    setTimeout(() => { btn.textContent = type === 'up' ? '👍' : '👎'; btn.disabled = false; }, 2000);
  }

  try {
    await request('POST', '/api/feedback', {
      session_id: currentSessionId,
      round_idx: currentRound,
      question_idx: currentQuestion.index ?? 0,
      feedback_type: type,
      dimension: dimension,
      current_score: 0,
    });
  } catch (_e) {
    // 静默失败
  }
}
