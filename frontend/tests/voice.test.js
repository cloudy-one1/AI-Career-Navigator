/**
 * voice.js 单元测试（v7.4 新增）
 *
 * 为什么补这套测试：voice.js 有 23KB，其中两块逻辑此前零自动化覆盖——
 *   1. 世代号守卫（真打断）：纯竞态逻辑，靠手工点按钮验证不可靠；
 *   2. VAD 状态机（校准窗 / minSpeechMs / silenceMs / maxDurationMs 四条件交织）：
 *      需要按时间推进才能测，手工只能撞运气。
 * 这两块又恰好是 v6.3 / v6.4 反复修过的地方，改动时最容易悄悄回归。
 *
 * 运行环境为 node（见 vitest.config.js 注释）：MediaRecorder / AudioContext /
 * speechSynthesis 在 jsdom / happy-dom 里同样没有实现，全都得打桩。
 */
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';

vi.mock('../src/js/api.js', () => ({
  requestVoiceTTS: vi.fn(),
  requestVoiceASR: vi.fn(),
}));
vi.mock('../src/js/utils.js', () => ({ toast: vi.fn() }));

import { requestVoiceTTS } from '../src/js/api.js';

// ─────────────────────────── 全局打桩 ───────────────────────────

const utterances = [];

class FakeAudio {
  static instances = [];
  constructor(src) {
    this.src = src;
    this.paused = true;
    this.onended = null;
    this.onerror = null;
    FakeAudio.instances.push(this);
  }
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  /** 模拟"自然播放结束" */
  end() { if (this.onended) this.onended(); }
}

class FakeAnalyser {
  constructor() { this.fftSize = 2048; this.rms = 0; }
  getFloatTimeDomainData(buf) { buf.fill(this.rms); }
}

class FakeAudioContext {
  static instances = [];
  constructor() {
    this.state = 'running';
    this.analyser = new FakeAnalyser();
    FakeAudioContext.instances.push(this);
  }
  createMediaStreamSource() { return { connect: () => {} }; }
  createAnalyser() { return this.analyser; }
  resume() {}
  close() { this.state = 'closed'; }
}

class FakeMediaRecorder {
  static instances = [];
  static isTypeSupported = (t) => t === 'audio/webm;codecs=opus';
  constructor(stream, opts) {
    this.stream = stream;
    this.mimeType = (opts && opts.mimeType) || 'audio/webm';
    this.state = 'inactive';
    this.ondataavailable = null;
    this.onstop = null;
    FakeMediaRecorder.instances.push(this);
  }
  start() { this.state = 'recording'; }
  stop() {
    if (this.state === 'inactive') return;
    this.state = 'inactive';
    if (this.ondataavailable) this.ondataavailable({ data: { size: 128 } });
    if (this.onstop) this.onstop();
  }
}

function installGlobals() {
  globalThis.window = globalThis;              // 让 window.X 直接命中 globalThis.X
  globalThis.document = {};                    // voice.js 只在启动探测处判 typeof document
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    writable: true,
    value: {
      mediaDevices: {
        getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop() {} }] })),
      },
    },
  });
  globalThis.speechSynthesis = {
    speaking: false,
    onvoiceschanged: null,
    cancel: vi.fn(),
    getVoices: () => [{ lang: 'zh-CN', name: 'Ting Female' }],
    speak(u) { this.speaking = true; utterances.push(u); },
  };
  globalThis.SpeechSynthesisUtterance = class {
    constructor(text) { this.text = text; }
  };
  globalThis.MediaRecorder = FakeMediaRecorder;
  globalThis.AudioContext = FakeAudioContext;
  globalThis.Audio = FakeAudio;
  globalThis.URL.createObjectURL = () => 'blob:fake-audio';
  globalThis.URL.revokeObjectURL = () => {};
}

/** 刷空所有微任务（mimoSpeak 的 .then 链靠它推进） */
const flush = () => new Promise((r) => setTimeout(r, 0));

let voice;
let dateSpy = null;

beforeAll(async () => {
  installGlobals();
  voice = await import('../src/js/voice.js');
});

beforeEach(() => {
  FakeAudio.instances.length = 0;
  FakeMediaRecorder.instances.length = 0;
  FakeAudioContext.instances.length = 0;
  utterances.length = 0;
  // 真实浏览器 cancel()/结束后会把 speaking 置回 false，桩不会，必须手动复位，
  // 否则上一场测试的残留会让 isSpeaking() 恒为 true
  globalThis.speechSynthesis.speaking = false;
  requestVoiceTTS.mockReset();
  voice.resetMimoStatus();
  voice.stopSpeaking();
});

afterEach(async () => {
  vi.useRealTimers();
  if (dateSpy) { dateSpy.mockRestore(); dateSpy = null; }
  if (voice.isRecording()) await voice.stopRecording();
});

// ───────────────── A. 世代号守卫（v6.3 真打断） ─────────────────

describe('世代号守卫：打断不得继续播放，也不得触发结束回调', () => {
  it('打断发生在 TTS 请求在飞时——不得开始播放，且不触发 onEnd（"停了又响"的根因）', async () => {
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();
    expect(voice.getMimoStatus()).toBe('ready');

    let release;
    requestVoiceTTS.mockImplementationOnce(() => new Promise((r) => { release = r; }));
    const onEnd = vi.fn();
    voice.speak('题目文本', { onEnd });
    voice.stopSpeaking();                                  // 用户点了静音
    release({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await flush();

    expect(FakeAudio.instances.length).toBe(0);            // 从未创建 audio
    expect(onEnd).not.toHaveBeenCalled();
  });

  it('播放中打断——先摘 onended 再 pause，迟到的结束事件不再触发 onEnd', async () => {
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });

    const onEnd = vi.fn();
    voice.speak('题目文本', { onEnd });
    await flush();
    const a = FakeAudio.instances.at(-1);
    expect(a && a.paused).toBe(false);                     // 正在播放

    voice.stopSpeaking();
    expect(a.paused).toBe(true);
    expect(a.onended).toBeNull();                          // 回调已被摘除
    a.end();                                               // 浏览器迟到的 ended
    expect(onEnd).not.toHaveBeenCalled();
  });

  it('自然播放结束——onEnd 只触发一次（onend/onerror 互斥触发也不重复）', async () => {
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });

    const onEnd = vi.fn();
    voice.speak('题目文本', { onEnd });
    await flush();
    const a = FakeAudio.instances.at(-1);
    a.end();
    a.end();
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it('浏览器 TTS 被 cancel——canceled 不得当作自然结束触发 onEnd', async () => {
    requestVoiceTTS.mockRejectedValue(new Error('boom'));   // probe 失败 → 走浏览器降级
    const onEnd = vi.fn();
    await voice.speak('题目文本', { onEnd });

    const u = utterances.at(-1);
    expect(u).toBeTruthy();
    u.onerror({ error: 'interrupted' });
    expect(onEnd).not.toHaveBeenCalled();

    u.onend();                                              // 真正结束后仍应触发一次
    expect(onEnd).toHaveBeenCalledTimes(1);
  });
});

// ───────────────── B. 熔断韧性（v7.4） ─────────────────

describe('MiMo 熔断：单次抖动不得让整场面试退回机械音', () => {
  it('单次 TTS 失败不熔断——下一次仍走云端', async () => {
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();

    requestVoiceTTS.mockResolvedValueOnce({ used: false, message: 'MiMo TTS 请求超时' });
    voice.speak('A', {});
    await flush();
    expect(voice.getMimoStatus()).toBe('ready');            // 关键：仍是 ready
    expect(utterances.length).toBe(1);                      // 本次由浏览器兜底播出

    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'BBBB', format: 'wav' });
    voice.speak('B', {});
    await flush();
    expect(FakeAudio.instances.length).toBe(1);             // 第二次重新走回云端
  });

  it('连续失败达到阈值（3 次）才熔断', async () => {
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();

    for (let i = 0; i < 2; i++) {
      requestVoiceTTS.mockResolvedValueOnce({ used: false, message: 'fail' });
      voice.speak(`Q${i}`, {});
      await flush();
      expect(voice.getMimoStatus()).toBe('ready');
    }
    requestVoiceTTS.mockResolvedValueOnce({ used: false, message: 'fail' });
    voice.speak('Q3', {});
    await flush();
    expect(voice.getMimoStatus()).toBe('failed');
  });

  it('熔断后 TTL 内不重试，TTL 过期后允许重新探测', async () => {
    dateSpy = vi.spyOn(Date, 'now').mockReturnValue(1_000_000);
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();

    requestVoiceTTS.mockResolvedValue({ used: false, message: 'fail' });
    for (let i = 0; i < 3; i++) { voice.speak(`Q${i}`, {}); await flush(); }
    expect(voice.getMimoStatus()).toBe('failed');

    dateSpy.mockReturnValue(1_000_000 + 30_000);            // 30s 后，TTL（60s）未过
    requestVoiceTTS.mockClear();
    await voice.probeMimo();
    expect(requestVoiceTTS).not.toHaveBeenCalled();         // 不浪费注定失败的请求

    dateSpy.mockReturnValue(1_000_000 + 61_000);            // 61s 后
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();
    expect(voice.getMimoStatus()).toBe('ready');
  });

  it('resetMimoStatus 复位——新一场面试不继承上一场的降级', async () => {
    requestVoiceTTS.mockResolvedValue({ used: false, message: 'fail' });
    for (let i = 0; i < 3; i++) { voice.speak(`Q${i}`, {}); await flush(); }
    expect(voice.getMimoStatus()).toBe('failed');

    voice.resetMimoStatus();
    expect(voice.getMimoStatus()).toBe('unknown');

    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();
    expect(voice.getMimoStatus()).toBe('ready');
  });
});

// ───────────────── C. VAD 状态机 ─────────────────

describe('VAD 节流', () => {
  const cfg = { calibrationMs: 300, silenceMs: 500, minSpeechMs: 200, maxDurationMs: 60_000 };

  it('说完（语音达标 + 静音达阈值）自动停录', async () => {
    vi.useFakeTimers();
    const onAutoStop = vi.fn();
    await voice.startRecording({ ...cfg, onAutoStop });
    const ctx = FakeAudioContext.instances.at(-1);

    ctx.analyser.rms = 0;                                   // 校准窗：安静
    await vi.advanceTimersByTimeAsync(300);
    ctx.analyser.rms = 0.3;                                 // 开口说话
    await vi.advanceTimersByTimeAsync(400);
    ctx.analyser.rms = 0;                                   // 停口
    await vi.advanceTimersByTimeAsync(600);

    expect(onAutoStop).toHaveBeenCalledWith('silence');
  });

  it('语音未达 minSpeechMs 就静音——不自动停（防刚开口就误停）', async () => {
    vi.useFakeTimers();
    const onAutoStop = vi.fn();
    await voice.startRecording({ ...cfg, onAutoStop });
    const ctx = FakeAudioContext.instances.at(-1);

    ctx.analyser.rms = 0;
    await vi.advanceTimersByTimeAsync(300);
    ctx.analyser.rms = 0.3;
    await vi.advanceTimersByTimeAsync(100);                 // 仅 100ms < 200ms
    ctx.analyser.rms = 0;
    await vi.advanceTimersByTimeAsync(2000);

    expect(onAutoStop).not.toHaveBeenCalled();
  });

  it('达到硬上限——自动停录并给出 max_duration 原因', async () => {
    vi.useFakeTimers();
    const onAutoStop = vi.fn();
    await voice.startRecording({
      ...cfg, maxDurationMs: 2000, silenceMs: 600_000, onAutoStop,
    });
    const ctx = FakeAudioContext.instances.at(-1);
    ctx.analyser.rms = 0.3;                                 // 一直说
    await vi.advanceTimersByTimeAsync(2200);

    expect(onAutoStop).toHaveBeenCalledWith('max_duration');
  });

  it('嘈杂环境下仍能检测到"说完"——预滚校准把底噪抬到阈值之下', async () => {
    vi.useFakeTimers();
    const onAutoStop = vi.fn();
    await voice.startRecording({ ...cfg, onAutoStop });
    const ctx = FakeAudioContext.instances.at(-1);

    ctx.analyser.rms = 0.06;                                // 校准窗：房间底噪 0.06
    await vi.advanceTimersByTimeAsync(300);                 // 阈值 = 0.06*2 + 0.012 → 夹到 0.12
    ctx.analyser.rms = 0.30;                                // 说话
    await vi.advanceTimersByTimeAsync(400);
    ctx.analyser.rms = 0.06;                                // 停口，回到房间底噪
    await vi.advanceTimersByTimeAsync(600);

    expect(onAutoStop).toHaveBeenCalledWith('silence');
  });

  it('固定阈值（adaptive:false）在同一嘈杂场景下检测不到"说完"——这正是预滚校准存在的理由', async () => {
    vi.useFakeTimers();
    const onAutoStop = vi.fn();
    await voice.startRecording({ ...cfg, adaptive: false, onAutoStop });
    const ctx = FakeAudioContext.instances.at(-1);

    ctx.analyser.rms = 0.06;                                // 固定阈值 0.02 会把底噪当语音
    await vi.advanceTimersByTimeAsync(300);
    ctx.analyser.rms = 0.30;
    await vi.advanceTimersByTimeAsync(400);
    ctx.analyser.rms = 0.06;
    await vi.advanceTimersByTimeAsync(600);

    expect(onAutoStop).not.toHaveBeenCalled();              // 底噪仍 > 0.02，静音永远累积不起来
  });

  it('vad:false —— 不启动采样器，保留纯手动停止语义', async () => {
    await voice.startRecording({ vad: false });
    expect(FakeAudioContext.instances.length).toBe(0);
  });

  it('采样期间外抛 stt:level，停止后归零（云端 ASR 唯一的中间反馈）', async () => {
    vi.useFakeTimers();
    const levels = [];
    const off = voice.onVoiceEvent('stt:level', (d) => levels.push(d));

    await voice.startRecording({ ...cfg, onAutoStop: () => {} });
    const ctx = FakeAudioContext.instances.at(-1);
    ctx.analyser.rms = 0;
    await vi.advanceTimersByTimeAsync(300);
    ctx.analyser.rms = 0.3;
    await vi.advanceTimersByTimeAsync(200);

    expect(levels.length).toBeGreaterThan(0);
    expect(levels.some((l) => l.speech === true)).toBe(true);
    expect(levels.some((l) => l.calibrating === true)).toBe(true);

    await voice.stopRecording();
    expect(levels.at(-1).stopped).toBe(true);
    expect(levels.at(-1).level).toBe(0);
    off();
  });
});

// ───────────────── D. 开麦前先停朗读（v7.4 P1 修复） ─────────────────

describe('开麦与朗读互斥', () => {
  it('开麦前先停朗读——否则外放的题目语音会被自己的麦克风采进回答', async () => {
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });
    await voice.probeMimo();
    requestVoiceTTS.mockResolvedValueOnce({ used: true, audio_b64: 'AAAA', format: 'wav' });

    voice.speak('请介绍一下你自己', {});
    await flush();
    const a = FakeAudio.instances.at(-1);
    expect(a.paused).toBe(false);                           // 面试官正在念题

    await voice.startRecording({ vad: false });
    expect(a.paused).toBe(true);                            // 开麦瞬间必须已停
    expect(voice.isSpeaking()).toBe(false);
  });
});
