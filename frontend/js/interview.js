// ===================================================
// interview.js — 面试流程控制 (v2.3: 语音交互)
// ===================================================

import { $, $$, el, toast, DIM_NAMES, scoreClass } from './utils.js';
import { createInterviewWS, request } from './api.js';
import {
  voiceSupport, speak, stopSpeaking, isSpeaking,
  voiceFillTextarea, autoReadQuestion,
} from './voice.js';
import { mountLiveRadar, updateLiveRadar, resetLiveRadar } from './liveRadar.js';

let ws = null;
let currentStyle = 'friendly';
let currentMode = 'simulation';  // v2.4: 面试模式
let pendingFollowUp = false;
let voiceStopFn = null;       // 当前录音停止函数
let voiceState = 'idle';     // 'idle' | 'listening' | 'speaking'
let autoReadEnabled = true;   // 是否自动朗读题目
let currentInterviewerName = ''; // v2.4: 当前面试官名称
let dimWeights = null;        // v2.6: 本场各维度权重

/** 初始化面试 Tab */
export function initInterview() {
  const panel = $('#interview-panel');
  panel.innerHTML = '';

  // 简历 + JD 输入区
  panel.appendChild(el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '📄 面试准备' }),
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
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '简历文本（或粘贴内容）' }),
      el('textarea', { id: 'resume-text', className: 'form-textarea', placeholder: '粘贴简历内容...' }),
    ),
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '岗位描述 JD（可选）' }),
      el('textarea', { id: 'jd-text', className: 'form-textarea',
        placeholder: '粘贴岗位描述，让问题更贴合目标岗位...',
        style: 'min-height: 80px;' }),
    ),
    // v2.4/v2.7: 面试模式选择
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
      ),
    ),
    // v2.7: 自我介绍环节
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '🎤 额外环节' }),
      el('div', { className: 'self-intro-toggle' },
        el('label', { className: 'checkbox-label' },
          el('input', { type: 'checkbox', id: 'self-intro-cb' }),
          el('span', { className: 'checkbox-text', textContent: '包含自我介绍环节（面试开始前，了解候选人的整体背景和沟通能力）' }),
        ),
      ),
    ),
    // v2.7: 题型占比偏好
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '⚖️ 题型偏好（可选，影响题目分布比例）' }),
      el('div', { className: 'type-mix-sliders' },
        typeMixSlider('知识概念', 'knowledge', 34),
        typeMixSlider('项目经验', 'project', 33),
        typeMixSlider('行为/软技能', 'behavior', 33),
      ),
    ),
    // 面试官风格
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
    el('button', {
      id: 'start-btn', className: 'btn btn-primary btn-block',
      textContent: '🚀 开始面试',
      onClick: startInterview,
    }),
  ));

  // 面试进行区
  panel.appendChild(el('div', { id: 'interview-area' }));
}

function selectStyle(style) {
  currentStyle = style;
  $$('.style-option').forEach(el => el.classList.remove('selected'));
  const selected = $(`.style-option[data-style="${style}"]`);
  if (selected) selected.classList.add('selected');
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
    const { uploadResume } = await import('./api.js');
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

async function startInterview() {
  const resumeText = $('#resume-text').value.trim();
  if (!resumeText) { toast('请输入简历内容', 'warning'); return; }

  const jdText = $('#jd-text').value.trim();
  const btn = $('#start-btn');
  btn.disabled = true;
  btn.textContent = '正在生成问题...';

  try {
    const { generateQuestions } = await import('./api.js');
    const includeSelfIntro = $('#self-intro-cb')?.checked ?? false;
    const questionTypeMix = getQuestionTypeMix();
    const result = await generateQuestions(resumeText, jdText, currentStyle, currentMode, includeSelfIntro, questionTypeMix);
    const sessionId = result.session_id;

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
      const btn = $('#start-btn');
      if (btn) btn.style.display = 'block';
    },

    onError: (e) => {
      toast('连接异常', 'error');
    },
  });
}

// 轮次数据
let roundInfo = [];
let currentRound = 0;
let currentQuestion = null;
let currentSessionId = '';  // v2.5: 用于反馈

function handleWSMessage(type, data) {
  const area = $('#interview-area');
  switch (type) {
    case 'interviewer_info':
      area.innerHTML = '';
      roundInfo = data.rounds_info || [];
      area.appendChild(buildStageIndicator(0));
      // v2.4: 显示模式标签
      if (data.mode === 'traditional') {
        const modeBadge = el('div', { className: 'mode-badge',
          textContent: '📝 传统模式 · 5轮次面试' });
        area.appendChild(modeBadge);
      }
      break;

    case 'interviewer_change':
      showInterviewerChange(area, data);
      break;

    // v2.6: 本场诊断维度权重（按 JD 动态计算）
    case 'dimension_weights':
      dimWeights = data;
      showWeightsBanner(area, data);
      mountLiveRadar(area);
      break;

    // v2.6: 流式诊断进度
    case 'diagnosis_status':
      showStreamStatus(area, data);
      break;

    case 'diagnosis_chunk':
      appendStreamChunk('diag', data.text);
      break;

    case 'rewrite_chunk':
      appendStreamChunk('rewrite', data.text);
      break;

    // v2.6: 实时雷达刷新
    case 'radar_update':
      mountLiveRadar(area);
      updateLiveRadar(data);
      break;

    // v2.6: 追问补充已记录
    case 'follow_up_received':
      $('#follow-up-block')?.remove();
      pendingFollowUp = false;
      reactivateAnswerInput();
      break;

    case 'round_start':
      currentRound = data.round;
      area.querySelectorAll('.stage-dot').forEach(d => {
        const r = parseInt(d.dataset.round);
        if (r < currentRound) { d.className = 'stage-dot done'; }
        else if (r === currentRound) { d.className = 'stage-dot current'; }
      });
      area.appendChild(el('div', { className: 'card', style: 'text-align:center;border-left:4px solid var(--primary);' },
        el('div', { style: 'font-size:.9rem;color:var(--text-secondary);', textContent: `📋 第 ${data.round + 1} / ${roundInfo.length} 轮` }),
        el('div', { style: 'font-size:1.1rem;font-weight:600;margin-top:4px;', textContent: data.name }),
      ));
      break;

    case 'question':
      currentQuestion = data;
      showQuestion(area, data);
      break;

    // v2.1: 追加题目（质量不达标时追加）
    case 'extra_question':
      showExtraQuestion(area, data);
      break;

    // v2.1: 质量检查结果
    case 'round_quality_check':
      showQualityCheck(area, data);
      break;

    case 'diagnosis_result':
      showDiagnosis(area, data);
      break;

    // v2.1: 安全拦截
    case 'security_block':
      toast('⚠ 回答被拦截: ' + data.reason, 'error');
      // 重新激活输入
      const sbBtn = $('#submit-answer');
      if (sbBtn) { sbBtn.disabled = false; sbBtn.textContent = '提交回答'; }
      const sbInput = $('#answer-input');
      if (sbInput) { sbInput.disabled = false; sbInput.value = ''; sbInput.focus(); }
      break;

    case 'follow_up':
      pendingFollowUp = true;
      showFollowUp(area, data.question);
      break;

    case 'round_summary':
      showRoundSummary(area, data);
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
  currentInterviewerName = data.current.name;

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
  );

  // 回答区（含语音输入按钮）
  const answerArea = el('div', { className: 'answer-area' },
    el('div', { className: 'answer-input-wrap' },
      el('textarea', { id: 'answer-input', className: 'answer-textarea', placeholder: '在此输入你的回答...' }),
      voiceSupport.stt ? el('button', {
        id: 'voice-input-btn',
        className: 'voice-btn voice-btn-mic',
        title: '语音输入',
        innerHTML: '<span class="voice-icon">🎤</span>',
        onClick: toggleVoiceInput,
      }) : '',
    ),
    el('div', { className: 'answer-actions' },
      el('button', {
        id: 'submit-answer', className: 'btn btn-primary',
        textContent: '提交回答',
        onClick: submitAnswer,
      }),
    ),
  );

  area.appendChild(qCard);
  area.appendChild(answerArea);
  $('#answer-input')?.focus();
  pendingFollowUp = false;

  // 自动朗读题目
  if (autoReadEnabled && voiceSupport.tts) {
    autoReadQuestion(data.question, (state) => {
      voiceState = state === 'speaking' ? 'speaking' : 'idle';
      updateVoiceButtonStates();
    });
    voiceState = 'speaking';
    updateVoiceButtonStates();
  }
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

function toggleVoiceInput() {
  if (voiceState === 'listening') {
    // 停止录音
    if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
    voiceState = 'idle';
    updateVoiceButtonStates();
    return;
  }

  const textarea = $('#answer-input');
  if (!textarea) return;

  voiceStopFn = voiceFillTextarea(textarea, (state) => {
    voiceState = state;
    updateVoiceButtonStates();
    if (state === 'idle') voiceStopFn = null;
  });

  if (voiceStopFn) {
    voiceState = 'listening';
    updateVoiceButtonStates();
  }
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
    micBtn.classList.toggle('active', voiceState === 'listening');
    const icon = micBtn?.querySelector('.voice-icon');
    if (icon) icon.textContent = voiceState === 'listening' ? '⏹' : '🎤';
  }

  // 录音时改变 textarea 边框颜色
  const textarea = $('#answer-input');
  if (textarea) {
    textarea.classList.toggle('listening', voiceState === 'listening');
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
      voiceSupport.stt ? el('button', {
        id: 'fu-voice-input-btn',
        className: 'voice-btn voice-btn-mic',
        title: '语音输入',
        innerHTML: '<span class="voice-icon">🎤</span>',
        onClick: toggleFuVoiceInput,
      }) : '',
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
        onClick: () => { stopSpeaking(); skipFollowUp(); },
      }),
    ),
  );

  // 添加到答案区域后面
  const answerArea = area.querySelector('.answer-area');
  if (answerArea) answerArea.after(fuDiv);
  else area.appendChild(fuDiv);
  $('#fu-answer-input')?.focus();
}

function toggleFuVoiceInput() {
  if (voiceState === 'listening') {
    if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
    voiceState = 'idle';
    updateFuVoiceUI();
    return;
  }

  const textarea = $('#fu-answer-input');
  if (!textarea) return;

  voiceStopFn = voiceFillTextarea(textarea, (state) => {
    voiceState = state;
    updateFuVoiceUI();
    if (state === 'idle') voiceStopFn = null;
  });

  if (voiceStopFn) {
    voiceState = 'listening';
    updateFuVoiceUI();
  }
}

function updateFuVoiceUI() {
  const micBtn = $('#fu-voice-input-btn');
  if (micBtn) {
    micBtn.classList.toggle('active', voiceState === 'listening');
    const icon = micBtn.querySelector('.voice-icon');
    if (icon) icon.textContent = voiceState === 'listening' ? '⏹' : '🎤';
  }
  const textarea = $('#fu-answer-input');
  if (textarea) {
    textarea.classList.toggle('listening', voiceState === 'listening');
  }
}

function submitAnswer() {
  const input = $('#answer-input');
  const answer = input.value.trim();
  if (!answer) { toast('请输入回答', 'warning'); return; }

  // 停止语音
  stopSpeaking();
  if (voiceStopFn) { voiceStopFn(); voiceStopFn = null; }
  voiceState = 'idle';
  updateVoiceButtonStates();

  const btn = $('#submit-answer');
  btn.disabled = true;
  btn.textContent = '诊断中...';

  input.disabled = true;
  // 后端读取 msg.data.text
  ws.send('answer', { text: answer, is_follow_up: false });
}

function submitFollowUp() {
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

  ws.send('answer', { text: answer, is_follow_up: true });
}

function skipFollowUp() {
  $('#follow-up-block')?.remove();
  pendingFollowUp = false;
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
  const submitBtn = $('#submit-answer');
  if (submitBtn) {
    submitBtn.disabled = false;
    submitBtn.textContent = '提交回答';
  }
  const answerInput = $('#answer-input');
  if (answerInput) {
    answerInput.value = '';
    answerInput.disabled = false;
    answerInput.focus();
  }
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

  const diagPanel = el('div', { className: 'diagnosis-panel' },
    el('div', { className: 'diag-section' },
      el('div', { className: 'diag-section-title', textContent: '📊 各维度诊断' }),

      // 总评分（加权）
      el('div', { className: 'overall-score' },
        el('div', { className: 'score-value', textContent: oScore.toFixed(1) }),
        el('div', { className: 'score-label', textContent: '加权综合评分 / 5' }),
        data.weight_desc ? el('div', {
          style: 'font-size:.75rem;color:var(--text-muted);margin-top:4px;',
          textContent: `权重：${data.weight_desc}`,
        }) : '',
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
            el('div', { className: 'dim-comment', textContent: dim.comment || '' }),
          );
        }),
      ),

      data.overall_comment ? el('div', {
        className: 'diag-overall-comment',
        textContent: `💬 ${data.overall_comment}`,
      }) : '',

      weakest ? el('div', {
        className: 'diag-weak-hint',
        textContent: `🔍 当前最薄弱：${data.weakest_dimension_name || DIM_NAMES[weakest] || weakest}`,
      }) : '',

      // v2.7: 风险点识别
      data.risk_points?.length ? el('div', { className: 'diag-risk-section' },
        el('div', { className: 'diag-risk-title', textContent: '⚠️ 回答风险点' }),
        el('ul', { className: 'diag-risk-list' },
          ...data.risk_points.map(rp => el('li', { textContent: rp })),
        ),
      ) : '',
    ),

    // 改写示范
    data.rewritten_answer ? el('div', { className: 'diag-section' },
      el('div', { className: 'diag-section-title', textContent: '✨ 改写示范' }),
      el('div', { className: 'rewrite-section' },
        el('div', { className: 'rewrite-answer', textContent: data.rewritten_answer }),
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

function showRoundSummary(area, data) {
  // v2.1: 显示质量检查结果
  let qualityHtml = '';
  if (data.quality) {
    const q = data.quality;
    const icon = q.passed ? '✅' : '⚠️';
    const summary = q.passed
      ? `本轮加权均分 ${q.avg_score}/5，达到阈值 ${q.threshold}`
      : `本轮加权均分 ${q.avg_score}/5，未达阈值 ${q.threshold}`
        + (q.weak_dimension_name ? `，薄弱环节：${q.weak_dimension_name}` : '');
    qualityHtml = `
      <div style="margin-top:8px;padding:8px 12px;background:${q.passed ? '#e8f5e9' : '#fff3e0'};border-radius:8px;font-size:.85rem;">
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
  const bg = passed ? '#e8f5e9' : '#fff3e0';
  const border = passed ? 'var(--success)' : 'var(--warning)';

  const reason = passed
    ? '本轮质量达标，进入下一环节'
    : (data.can_add_extra
        ? `薄弱环节：${data.weak_dimension_name || '待定'} — 将追加针对性问题`
        : '追加题次数已用尽，进入下一环节');

  const banner = el('div', {
    className: 'quality-check-banner',
    style: `padding:10px 16px;margin:8px 0;background:${bg};border-left:4px solid ${border};border-radius:8px;font-size:.85rem;`,
    innerHTML: `${icon} <strong>质量检查：</strong>加权平均分 ${data.avg_score}/5 （阈值 ${data.threshold}） — ${reason}`,
  });

  area.appendChild(banner);
}

function showExtraQuestion(area, data) {
  // 显示追加提示
  area.appendChild(el('div', {
    className: 'card',
    style: 'border-left:4px solid var(--warning);background:#fff3e0;margin-bottom:8px;',
    innerHTML: `
      <div style="font-size:.85rem;color:var(--text-secondary);">⚠️ 本轮质量未达标，面试官追加一题</div>
      <div style="font-size:.8rem;color:var(--text-secondary);margin-top:2px;">
        ${data.reason || '针对薄弱环节追加提问'}
      </div>
    `,
  }));
}

function finishInterview(data) {
  const area = $('#interview-area');
  area.innerHTML = '';

  area.appendChild(el('div', { className: 'card', style: 'text-align:center;border-left:4px solid var(--primary);' },
    el('div', { style: 'font-size:1.3rem;font-weight:600;color:var(--primary);', textContent: '🎉 面试完成！' }),
    el('div', { style: 'font-size:.9rem;color:var(--text-secondary);margin-top:8px;', textContent: '切换到「报告」Tab 查看综合评估' }),
    el('button', {
      className: 'btn btn-primary', style: 'margin-top:16px;',
      textContent: '查看综合报告',
      onClick: () => { document.querySelector('[data-tab="report"]')?.click(); },
    }),
  ));

  $('#start-btn').style.display = 'block';
  $('#start-btn').disabled = false;
  $('#start-btn').textContent = '🚀 开始面试';

  // 保存报告数据到全局，供 report.js 使用
  // 后端 interview_done 的 data 即为报告本体
  const report = data?.report || data;
  window._latestReport = report;
  window._latestSessionId = report?.session_id || currentSessionId;

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
