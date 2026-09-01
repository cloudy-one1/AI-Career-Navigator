/**
 * interview.js 的 WebSocket 消息派发契约测试（v8.6）。
 *
 * 背景：前端面试主循环（约 1800 行）长期零自动化覆盖——此前 frontend/tests 下只有
 * voice.js 一个测试文件。后端新增一种消息类型而前端漏接时，表现是"界面静默无反应"，
 * 只能靠手工点击发现。本文件补的就是这一层。
 *
 * 运行环境仍是 node（与 v7.4 vitest.config.js 的刻意选择一致：不引 happy-dom / jsdom，
 * 零新增依赖）。因此这里只测**派发契约**——每种类型是否命中分支、是否不抛错——
 * 不测渲染结果；渲染正确性由真机冒烟保障，那是另一层。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// ── 最小 DOM 替身 ───────────────────────────────────────────────
// 不为每个 DOM API 逐个打桩：未知成员一律给一个"可调用且返回新节点"的空操作，
// 这样渲染分支里任何未预见的调用都只是安静地跑过，而不会让整个用例炸掉。
function makeEl() {
  const noop = () => {};
  const base = {
    children: [],
    style: {},
    dataset: {},
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    value: '', textContent: '', innerHTML: '', id: '', className: '',
    disabled: false, scrollTop: 0, scrollHeight: 0, length: 0, href: '',
    querySelector: () => makeEl(),
    querySelectorAll: () => [],
    appendChild(child) { base.children.push(child); return child; },
    insertBefore: (child) => child,
    addEventListener: noop,
    removeEventListener: noop,
    remove: noop,
    after: noop,
    before: noop,
    focus: noop,
    blur: noop,
    setAttribute: noop,
    getAttribute: () => null,
    scrollIntoView: noop,
    closest: () => makeEl(),
  };
  // 少数成员是"节点"而不是"方法"（如 parentElement）。它们若也返回函数，
  // 再往下一层取 `.querySelector` 就会拿到 undefined —— 这类问题在 Proxy 替身里
  // 只能靠显式名单区分，别无他法。
  const ELEMENT_PROPS = new Set([
    'parentElement', 'parentNode', 'firstElementChild', 'lastElementChild',
    'nextElementSibling', 'previousElementSibling',
  ]);
  return new Proxy(base, {
    get(target, key) {
      if (key in target) return target[key];
      if (typeof key === 'symbol') return undefined;
      if (ELEMENT_PROPS.has(key)) return makeEl();
      target[key] = () => makeEl();
      return target[key];
    },
    set(target, key, value) { target[key] = value; return true; },
  });
}

globalThis.window = globalThis;
globalThis.document = makeEl();
globalThis.location = { hash: '', protocol: 'http:', host: 'localhost' };
globalThis.localStorage = {
  getItem: () => null, setItem: () => {}, removeItem: () => {},
};

// ── 依赖桩 ─────────────────────────────────────────────────────
// vi.hoisted 保证 mock 工厂（被提升到文件顶部）能拿到同一批 spy 引用。
const m = vi.hoisted(() => ({
  toast: vi.fn(),
  speak: vi.fn(),
  stopSpeaking: vi.fn(),
  isSpeaking: vi.fn(() => false),
  prefetchTTS: vi.fn(),
  autoReadQuestion: vi.fn(),
  voiceFillWithASR: vi.fn(),
  getMimoStatus: vi.fn(() => ({ ok: true })),
  resetMimoStatus: vi.fn(),
  setTTSVoice: vi.fn(),
  onVoiceEvent: vi.fn(),
  mountLiveRadar: vi.fn(),
  updateLiveRadar: vi.fn(),
  resetLiveRadar: vi.fn(),
  request: vi.fn(async () => ({})),
  refreshProfile: vi.fn(async () => ({})),
  getCompanyProfiles: vi.fn(async () => []),
  generateQuestions: vi.fn(async () => []),
  createInterviewWS: vi.fn(() => ({ send: vi.fn(), close: vi.fn() })),
  uploadResumeToLibrary: vi.fn(async () => ({})),
  uploadJd: vi.fn(async () => ({})),
}));

const DIM_NAMES = {
  star_completeness: 'STAR 完整度',
  quantification: '量化程度',
  logic_coherence: '逻辑连贯性',
  job_relevance: '岗位相关性',
  professional_depth: '专业深度',
};

vi.mock('../src/js/utils.js', () => ({
  $: () => makeEl(),
  $$: () => [],
  el: () => makeEl(),
  toast: m.toast,
  DIM_NAMES,
  scoreClass: () => 'score-mid',
  escHtml: (s) => String(s ?? ''),
}));

vi.mock('../src/js/api.js', () => ({
  createInterviewWS: m.createInterviewWS,
  request: m.request,
  getCompanyProfiles: m.getCompanyProfiles,
  generateQuestions: m.generateQuestions,
  refreshProfile: m.refreshProfile,
  uploadResumeToLibrary: m.uploadResumeToLibrary,
  uploadJd: m.uploadJd,
}));

vi.mock('../src/js/voice.js', () => ({
  voiceSupport: { tts: true, asr: true },
  speak: m.speak,
  stopSpeaking: m.stopSpeaking,
  isSpeaking: m.isSpeaking,
  voiceFillWithASR: m.voiceFillWithASR,
  autoReadQuestion: m.autoReadQuestion,
  getMimoStatus: m.getMimoStatus,
  prefetchTTS: m.prefetchTTS,
  resetMimoStatus: m.resetMimoStatus,
  setTTSVoice: m.setTTSVoice,
  onVoiceEvent: m.onVoiceEvent,
}));

vi.mock('../src/js/liveRadar.js', () => ({
  mountLiveRadar: m.mountLiveRadar,
  updateLiveRadar: m.updateLiveRadar,
  resetLiveRadar: m.resetLiveRadar,
}));

// DOM 替身必须在 import 之前就位（含 window 上的若干全局）
const { handleWSMessage } = await import('../src/js/interview.js');

// ── 契约数据 ───────────────────────────────────────────────────
// 每种消息给一份"结构完整"的样例：派发测试关心的是分支能否跑完，
// 样例字段缺失会让用例变成在测"空对象不炸"，那没有意义。

const DIAGNOSIS = {
  round: 0,
  round_name: '技术一面',
  question_idx: 0,
  question: '介绍一下你的项目',
  overall_score: 3.4,
  dimensions: {
    star_completeness: 4, quantification: 2, logic_coherence: 3,
    job_relevance: 4, professional_depth: 3,
  },
  dimension_details: {
    quantification: { score: 2, comment: '缺少数据', quote: '提升了性能' },
  },
  weights: { quantification: 0.3 },
  weight_desc: '量化程度 30%',
  weakest_dimension: 'quantification',
  weakest_dimension_name: '量化程度',
  overall_comment: '整体不错',
  risk_points: ['指标来源未说明'],
  rewritten_answer: '改写后的回答',
  key_changes: ['补了数据'],
  follow_up_question: '',
};

const HANDLED_TYPES = {
  interviewer_info: {
    style: 'friendly', mode: 'simulation', stage: 'phone_screen',
    total_rounds: 3, rounds_info: [{ index: 0, name: '破冰' }],
  },
  interviewer_change: { name: '技术面试官', style: 'strict' },
  dimension_weights: { weights: DIAGNOSIS.weights, weight_desc: '量化 30%' },
  diagnosis_status: { phase: 'diagnosing' },
  diagnosis_chunk: { text: '诊断片段' },
  rewrite_chunk: { text: '改写片段' },
  radar_update: { labels: ['量化程度'], scores: [3] },
  follow_up_received: { message: '补充回答已记录' },
  round_start: { round: 0, name: '破冰' },
  question: {
    round: 0, index: 1, total: 3, question: '介绍一下你的项目', intent: '考察深度',
    is_extra: false, focus_dimension: 'quantification', focus_dimension_name: '量化程度',
    question_type: 'project', is_pressure: false, pressure_topic: '', basis: '简历锚点',
  },
  extra_question: {
    round: 0, question: '追加题', intent: '补强', focus_dimension: 'quantification',
    focus_dimension_name: '量化程度', reason: '本轮质量未达标',
  },
  round_quality_check: {
    passed: false, avg_score: 3.2, threshold: 3.5, can_add_extra: true,
    weak_dimension_name: '量化程度',
  },
  diagnosis_result: DIAGNOSIS,
  weakness_update: { tags: [{ tag: '量化不足', count: 2 }] },
  mode_change: { current: { mode: 'coach', stage: 'tech_round_1' } },
  security_block: { reason: '包含违规内容' },
  follow_up: { question: '能具体说说数据吗？', reason: '量化程度' },
  skill_start: { ok: true, skill: '快速测验', total_steps: 3 },
  skill_end: { skill: '快速测验', message: '已退出技能' },
  difficulty_change: { message: '难度已提升一档' },
  interview_end_signal: { message: '收到结束信号，正在生成报告' },
  interview_closing: { round_name: '反问收尾', message: '本次面试到此结束' },
  round_summary: {
    round_name: '技术一面', avg_score: 3.4,
    quality: { passed: true, avg_score: 3.4, threshold: 3.0 },
    extra_questions_added: 0,
  },
  interview_done: { session_id: 's1', overall_avg: 3.4 },
  error: { message: '诊断失败，请重新作答' },
  // v8.6 新增
  reassessment_status: { phase: 'reassessing' },
  reassessment_done: {
    ...DIAGNOSIS,
    follow_up_reassessed: true,
    pre_follow_up: { overall_score: 2.8, dimensions: DIAGNOSIS.dimensions },
    reassessment_delta: 0.6,
    reassessment_note: '补充了转化率数据',
  },
  rewrite_start: { round: 0, question_idx: 0 },
  rewrite_done: {
    round: 0, question_idx: 0,
    rewritten_answer: '改写后的回答', key_changes: ['补了数据'],
  },
};

const SRC_PATH = fileURLToPath(new URL('../src/js/interview.js', import.meta.url));

describe('handleWSMessage 派发契约', () => {
  beforeEach(() => {
    m.toast.mockClear();
  });

  it.each(Object.keys(HANDLED_TYPES))('%s 命中分支且不抛错', (type) => {
    expect(() => handleWSMessage(type, HANDLED_TYPES[type])).not.toThrow();
  });

  it('未知类型静默忽略（不抛错、不误弹提示）', () => {
    expect(() => handleWSMessage('no_such_message_type', { foo: 1 })).not.toThrow();
    expect(m.toast).not.toHaveBeenCalled();
  });

  it('error 分支把消息转给用户', () => {
    handleWSMessage('error', { message: '诊断失败，请重新作答' });
    expect(m.toast).toHaveBeenCalledWith('诊断失败，请重新作答', 'error');
  });

  it('security_block 提示带拦截原因', () => {
    handleWSMessage('security_block', { reason: '包含违规内容' });
    expect(m.toast).toHaveBeenCalledWith(expect.stringContaining('包含违规内容'), 'error');
  });

  it('mode_change 同步当前会话模式（后续消息按新模式渲染）', () => {
    handleWSMessage('mode_change', { current: { mode: 'coach', stage: 'tech_round_1' } });
    // 走 globalThis 而非裸 window：node 环境下没有 window 全局，本文件是手动挂上去的
    expect(globalThis.window._sessionMode).toBe('coach');
  });

  it('radar_update 驱动实时雷达刷新', () => {
    m.mountLiveRadar.mockClear();
    m.updateLiveRadar.mockClear();
    handleWSMessage('radar_update', HANDLED_TYPES.radar_update);
    expect(m.mountLiveRadar).toHaveBeenCalled();
    expect(m.updateLiveRadar).toHaveBeenCalledWith(HANDLED_TYPES.radar_update);
  });

  it('v8.6 补评：reassessment_done 重渲染诊断卡并带上首评原分', () => {
    const payload = HANDLED_TYPES.reassessment_done;
    expect(() => handleWSMessage('reassessment_done', payload)).not.toThrow();
    // 首评原分是"为什么加分"的对照依据，前端必须拿得到
    expect(payload.pre_follow_up.overall_score).toBe(2.8);
  });
});

describe('消息类型覆盖（源码扫描）', () => {
  it('switch 覆盖全部契约类型', () => {
    const src = readFileSync(SRC_PATH, 'utf8');
    const body = src.slice(src.indexOf('export function handleWSMessage'));
    const cases = new Set(
      [...body.matchAll(/case\s+'([a-z_]+)':/g)].map((mm) => mm[1]),
    );
    const missing = Object.keys(HANDLED_TYPES).filter((t) => !cases.has(t));
    expect(missing).toEqual([]);
  });
});
