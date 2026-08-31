// ===================================================
// voice.js — v2.3 语音交互模块（TTS + STT）
// v4.2: 升级为"小米 MiMo 云端语音优先 + 浏览器原生降级"双引擎
//   - TTS（朗读/读题）：优先 MiMo-V2.5-TTS，未配 Key / 失败时降级 speechSynthesis
//   - STT（语音转文字）：优先 MiMo-V2.5-ASR（MediaRecorder 录音上传），
//     未配 Key / 失败时降级 SpeechRecognition（仅 Chrome/Edge）
//   - 语音作为输入/输出替代层，不参与诊断内核
// ===================================================

import { toast } from './utils.js';
import { requestVoiceTTS, requestVoiceASR } from './api.js';

// ===== 浏览器能力检测 =====

export const voiceSupport = {
  get tts() {
    return typeof speechSynthesis !== 'undefined';
  },
  get stt() {
    return typeof SpeechRecognition !== 'undefined' ||
           typeof webkitSpeechRecognition !== 'undefined';
  },
  /** 是否可用 MiMo 云端语音（录音采集 + 上传识别） */
  get mimo() {
    return typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof window.MediaRecorder !== 'undefined' &&
      mimoStatus !== 'failed';
  },
};

// ===== MiMo 云端引擎状态 =====
// 'unknown'（未探测）| 'ready'（可用）| 'failed'（熔断中，TTL 过后可重试）
let mimoStatus = 'unknown';

// v7.4: 熔断韧性。旧语义是「一次失败即永久降级」——一次网络抖动、一次自动播放被拒、
// 一次 413，都会让整场面试剩下的题目全部退回浏览器机械音，代价远超故障本身。
// 改为：连续失败累计到阈值才熔断，熔断后过 TTL 允许重新探测一次；
// 开新一场面试时由调用方 resetMimoStatus() 彻底复位。
const MIMO_FAIL_THRESHOLD = 3;      // 连续失败达此次数才熔断
const MIMO_RETRY_TTL_MS = 60_000;   // 熔断后多久允许重新探测
let mimoFailures = 0;
let mimoFailedAt = 0;

export function getMimoStatus() {
  return mimoStatus;
}

/** 复位云端引擎状态（开新一场面试时调用，避免上一场的熔断被继承）。 */
export function resetMimoStatus() {
  mimoStatus = 'unknown';
  mimoFailures = 0;
  mimoFailedAt = 0;
}

function _markMimoOk() {
  mimoStatus = 'ready';
  mimoFailures = 0;
  mimoFailedAt = 0;
}

// v7.4: 当前朗读音色。后端 voice_service 支持 9 个预置音色 + OpenAI 风格别名表，
// 但此前前端每个调用点都硬编码 'default'，配置层的能力在 UI 层完全不可达——
// 加一个模块级设置位把这条通路打通（缓存键含音色，切换后自然失效）。
let currentVoice = 'default';

export function setTTSVoice(name) {
  currentVoice = (name || 'default').trim() || 'default';
}

export function getTTSVoice() {
  return currentVoice;
}

/** 记一次失败。未达阈值只计数（本次降级播，下次仍可重试）；达阈值才熔断。 */
function _markMimoFailed() {
  mimoFailures += 1;
  if (mimoFailures >= MIMO_FAIL_THRESHOLD) {
    mimoStatus = 'failed';
    mimoFailedAt = Date.now();
  }
}

/**
 * 探测 MiMo 语音可用性（后台调用一次 TTS）。
 * 仅 unknown 时执行；ready 直接返回；failed 需等 TTL 过后才重试。
 */
export async function probeMimo() {
  if (mimoStatus === 'ready') return mimoStatus;
  // v7.4: 熔断未过 TTL 不重试——否则每题都浪费一次注定失败的请求
  if (mimoStatus === 'failed' && Date.now() - mimoFailedAt < MIMO_RETRY_TTL_MS) {
    return mimoStatus;
  }
  try {
    const data = await requestVoiceTTS('测试', currentVoice);
    if (data && data.used) _markMimoOk();
    else _markMimoFailed();
  } catch (_) {
    _markMimoFailed();
  }
  if (mimoStatus === 'failed') {
    console.info('[Voice] MiMo 语音连续失败已达阈值，降级为浏览器原生语音');
  }
  return mimoStatus;
}

// ===== 语音状态事件（供外部订阅）=====

const listeners = {};

export function onVoiceEvent(event, callback) {
  if (!listeners[event]) listeners[event] = [];
  listeners[event].push(callback);
  // v6.3: 返回取消函数，供一次性订阅（如 autoReadQuestion 的打断复位）
  return () => {
    listeners[event] = (listeners[event] || []).filter(fn => fn !== callback);
  };
}

function emit(event, data) {
  (listeners[event] || []).forEach(fn => fn(data));
}

// ===== TTS（文字转语音）=====

let ttsUtterance = null;
let ttsSpeaking = false;
let mimoAudio = null;   // 当前 MiMo 播放的 <audio>
// v6.3 语音世代号（真打断的核心）：
// 每次打断递增，所有在飞的 onEnd 回调携带旧世代号即失效。
// 对应 HakiMeet flush() 的教训——只停播放不清回调，结束回调仍会触发后续动作。
let speechSeq = 0;

/** 停止当前朗读（浏览器 + MiMo）。真打断：先摘回调再停止。 */
export function stopSpeaking() {
  speechSeq++;
  if (mimoAudio) {
    const a = mimoAudio;
    mimoAudio = null;
    // 置空回调必须在 pause 之前：保证结束/出错回调不可能再触发后续动作
    a.onended = null;
    a.onerror = null;
    try { a.pause(); } catch (_) {}
    if (a.src && a.src.startsWith('blob:')) {
      try { URL.revokeObjectURL(a.src); } catch (_) {}
    }
  }
  if (ttsSpeaking || speechSynthesis.speaking) {
    speechSynthesis.cancel();
    ttsSpeaking = false;
    ttsUtterance = null;
    emit('tts:stop');
  }
}

/** 是否正在朗读 */
export function isSpeaking() {
  return ttsSpeaking || speechSynthesis.speaking || (mimoAudio !== null && !mimoAudio.paused);
}

// ---- 浏览器 TTS（降级引擎）----
function browserSpeak(text, opts = {}) {
  if (!voiceSupport.tts) {
    console.warn('[Voice] 浏览器 TTS 不可用');
    if (opts.onEnd) opts.onEnd();
    return;
  }
  const seq = speechSeq;   // v6.3: 捕获世代号，打断后旧回调不再触发 onEnd
  // onEnd 一次性守卫：onend/onerror 互斥触发时也不会重复执行
  let ended = false;
  const fireEnd = () => {
    if (ended || seq !== speechSeq) return;
    ended = true;
    if (opts.onEnd) opts.onEnd();
  };
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = opts.lang || 'zh-CN';
  utterance.rate = opts.rate || 0.95;
  utterance.pitch = opts.pitch || 1.0;
  utterance.volume = opts.volume || 1.0;

  const voices = speechSynthesis.getVoices();
  const zhFemale = voices.find(v => v.lang.startsWith('zh') && v.name.includes('Female'))
    || voices.find(v => v.lang.startsWith('zh-CN'))
    || voices.find(v => v.lang.startsWith('zh'));
  if (zhFemale) utterance.voice = zhFemale;

  utterance.onstart = () => {
    ttsSpeaking = true;
    ttsUtterance = utterance;
    emit('tts:start', { text, engine: 'browser' });
  };
  utterance.onend = () => {
    ttsSpeaking = false;
    ttsUtterance = null;
    emit('tts:end');
    fireEnd();
  };
  utterance.onerror = (e) => {
    ttsSpeaking = false;
    ttsUtterance = null;
    emit('tts:error', { error: e.error });
    if (e.error !== 'canceled' && e.error !== 'interrupted') {
      console.warn('[Voice] 浏览器 TTS 错误:', e.error);
    }
    // v6.3 修复（真打断）：canceled/interrupted 是 stopSpeaking 触发的取消，
    // 绝不能当作"自然结束"去调 onEnd —— 否则打断后仍会切回输入态/触发后续动作
    if (e.error !== 'canceled' && e.error !== 'interrupted') fireEnd();
  };

  if (voices.length === 0) {
    speechSynthesis.onvoiceschanged = () => {
      const updated = speechSynthesis.getVoices();
      const best = updated.find(v => v.lang.startsWith('zh') && v.name.includes('Female'))
        || updated.find(v => v.lang.startsWith('zh-CN'))
        || updated.find(v => v.lang.startsWith('zh'));
      if (best) utterance.voice = best;
      speechSynthesis.speak(utterance);
    };
  } else {
    speechSynthesis.speak(utterance);
  }
}

// ---- MiMo TTS（主引擎）----
function mimoSpeak(text, opts = {}) {
  const seq = speechSeq;   // v6.3: 世代守卫
  return new Promise((resolve) => {
    requestVoiceTTS(text, currentVoice)
      .then((data) => {
        // 拿到音频时已被打断：不得开始播放（否则"停了又响"）
        if (seq !== speechSeq) { resolve(false); return; }
        if (!data || !data.used || !data.audio_b64) {
          resolve(false);
          return;
        }
        // Base64 -> ArrayBuffer -> Blob -> <audio>
        const binary = atob(data.audio_b64);
        const buffer = new ArrayBuffer(binary.length);
        const view = new Uint8Array(buffer);
        for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);
        const blob = new Blob([buffer], { type: data.format === 'wav' ? 'audio/wav' : 'audio/mpeg' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        mimoAudio = audio;
        emit('tts:start', { text, engine: 'mimo' });
        // v7.4: 一次性守卫（与 browserSpeak 的 `ended` 标志对齐）。
        // MiMo 路径此前漏了它：onended / onerror / play().catch 是三条独立收口路径，
        // 个别浏览器会在播放结束时既走 ended 又抛 error，onEnd 就被调用两次——
        // 调用方（autoReadQuestion 切回输入、免手模式自动开麦）会连锁执行两遍。
        let settled = false;
        const finishMimo = (ok) => {
          if (settled) return;
          settled = true;
          mimoAudio = null;
          URL.revokeObjectURL(url);
          if (ok) emit('tts:end');
          // 被打断时一律不触发 onEnd（世代守卫的既有语义）
          if (seq === speechSeq && opts.onEnd) opts.onEnd();
          resolve(ok);
        };
        audio.onended = () => finishMimo(true);
        audio.onerror = () => {
          if (seq !== speechSeq) { resolve(false); return; }  // 已被打断，stopSpeaking 已清理
          finishMimo(false);
        };
        audio.play().catch(() => {
          if (seq !== speechSeq) { resolve(false); return; }
          finishMimo(false);
        });
      })
      .catch(() => resolve(false));
  });
}

/**
 * 朗读文本（MiMo 优先，失败降级浏览器）
 * @param {string} text
 * @param {object} [opts] - { rate, pitch, volume, lang, onEnd }
 */
export async function speak(text, opts = {}) {
  if (!text || !text.trim()) { if (opts.onEnd) opts.onEnd(); return; }
  // v7.4: 未探测、或熔断已过 TTL，都重新探测一次（probeMimo 内部会挡掉 TTL 内的重试）
  if (mimoStatus !== 'ready') await probeMimo();

  const seq = speechSeq;   // v6.3: 世代守卫
  if (mimoStatus === 'ready') {
    const ok = await mimoSpeak(text, opts);
    if (seq !== speechSeq) return;   // 朗读期间被打断：不得降级续播
    if (ok) { _markMimoOk(); return; }
    // v7.4: 只计一次失败，不立刻熔断 —— 单次抖动（网络/自动播放策略/413）不该让
    // 这场面试后续的题全部退回机械音。连续失败达阈值才降级。
    _markMimoFailed();
    browserSpeak(text, opts);
  } else {
    browserSpeak(text, opts);
  }
}

// ===== STT（语音转文字）=====

const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let sttListening = false;

/**
 * 开始语音识别（浏览器降级引擎）
 * @param {object} [opts] - { lang, continuous, interimResults, onResult, onInterim, onEnd }
 */
export function startListening(opts = {}) {
  if (!voiceSupport.stt) {
    toast('当前浏览器不支持语音识别（请使用 Chrome 或 Edge）', 'warning');
    return false;
  }
  stopSpeaking();
  if (recognition) {
    try { recognition.abort(); } catch (_) {}
  }
  recognition = new SpeechRecognitionAPI();
  recognition.lang = opts.lang || 'zh-CN';
  recognition.continuous = opts.continuous ?? true;
  recognition.interimResults = opts.interimResults ?? true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    sttListening = true;
    emit('stt:start');
  };
  recognition.onresult = (event) => {
    let interim = '';
    let final = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) final += transcript;
      else interim += transcript;
    }
    if (final && opts.onResult) {
      opts.onResult(final);
      emit('stt:result', { text: final, isFinal: true });
    }
    if (interim && opts.onInterim) {
      opts.onInterim(interim);
      emit('stt:interim', { text: interim });
    }
  };
  recognition.onerror = (event) => {
    sttListening = false;
    emit('stt:error', { error: event.error });
    if (event.error === 'not-allowed') {
      toast('麦克风权限被拒绝，请在浏览器设置中允许麦克风访问', 'error');
    } else if (event.error !== 'no-speech' && event.error !== 'aborted') {
      console.warn('[Voice] 浏览器 STT 错误:', event.error);
    }
    if (opts.onEnd) opts.onEnd();
  };
  recognition.onend = () => {
    sttListening = false;
    emit('stt:end');
    if (opts.onEnd) opts.onEnd();
  };

  try {
    recognition.start();
    return true;
  } catch (e) {
    console.error('[Voice] 浏览器 STT 启动失败:', e);
    sttListening = false;
    return false;
  }
}

/** 停止语音识别 */
export function stopListening() {
  if (recognition) {
    try { recognition.stop(); } catch (_) {}
    sttListening = false;
    emit('stt:stop');
  }
}

/** 是否正在监听 */
export function isListening() {
  return sttListening;
}

// ===== MiMo ASR 录音采集（MediaRecorder）=====

let mediaRecorder = null;
let mediaStream = null;
let recordedChunks = [];
let recording = false;

// ===== v6.2: VAD 静音节流（借鉴 GrillMind 的语音链路设计）=====
// 半双工录音的固有缺陷：停止完全靠用户手动点，忘记点就会上传几十秒空白音频 ——
// ASR 慢、按量计费、还容易从噪声里"幻听"出文字。
// 做法：录音期间用 AnalyserNode 采样音量（RMS），连续静音达到阈值即自动停录。
// 只做"何时停"的节流判断，不做端点检测（不裁剪已录音频），语义上仍是半双工。

const VAD_DEFAULTS = {
  silenceMs: 2500,        // 连续静音多久判定"说完了"
  minSpeechMs: 800,       // 至少采集到这么久的语音才允许自动停（防刚开口就误停）
  maxDurationMs: 120000,  // 单次录音硬上限，防忘记停止
  threshold: 0.02,        // 音量阈值（RMS，0-1）—— adaptive 关闭时的固定兜底值
  tickMs: 100,            // 采样间隔
  // v7.4: 预滚噪声校准（pre-roll calibration）。固定 0.02 两头不讨好——
  // 嘈杂环境底噪长期超阈，"说完"永远检测不到，只能等 120s 硬上限兜底；
  // 低增益麦克风又把整段语音判成静音，同样拖到硬上限。
  // 做法：开录后先用 calibrationMs 取窗口内**最小** RMS 当底噪（用户此时多半还没开口），
  // 阈值 = 底噪 × gain + margin，再夹在 [minThreshold, maxThreshold]。
  // 刻意不做"连续自适应"：慢升快降那套会把持续说话逐渐学成底噪，反而更不可靠，
  // 也会让同一场面试里前后的判定标准漂移。校准一次、全程固定，行为可预测可复现。
  adaptive: true,
  calibrationMs: 700,     // 开录后先观察这么久，期间只估底噪、不做停录判断
  thresholdGain: 2.0,
  thresholdMargin: 0.012, // 安静环境下抬一点，避免把呼吸声当语音
  minThreshold: 0.008,
  maxThreshold: 0.12,
};

let vadTimer = null;
let vadAudioCtx = null;

/** 启动 VAD 采样；reason 为 'silence'（静音）或 'max_duration'（超时） */
function _startVad(stream, onAutoStop, opts = {}) {
  _stopVad();
  const cfg = { ...VAD_DEFAULTS, ...opts };
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    vadAudioCtx = ctx;
    if (ctx.state === 'suspended' && typeof ctx.resume === 'function') ctx.resume();

    const buf = new Float32Array(analyser.fftSize);
    const startedAt = Date.now();
    let speechMs = 0;
    let silenceMs = 0;
    let noiseFloor = Infinity;   // v7.4: 校准窗内取最小 RMS
    let threshold = cfg.threshold;
    let calibrated = !cfg.adaptive;

    vadTimer = setInterval(() => {
      if (!recording) { _stopVad(); return; }
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);

      const elapsed = Date.now() - startedAt;
      // 硬上限放在校准之前：否则 calibrationMs > maxDurationMs 时会永远卡在校准窗
      if (elapsed >= cfg.maxDurationMs) {
        _stopVad();
        if (onAutoStop) onAutoStop('max_duration');
        return;
      }

      // v7.4: 校准窗内只估底噪，不做停录判断（此时用户多半还没开口）
      if (!calibrated) {
        if (rms < noiseFloor) noiseFloor = rms;
        emit('stt:level', { level: Math.min(1, rms / Math.max(cfg.threshold * 3, 1e-6)),
          rms, threshold, speech: false, calibrating: true });
        if (elapsed < cfg.calibrationMs) return;
        const base = Number.isFinite(noiseFloor) ? noiseFloor : 0;
        threshold = Math.min(
          cfg.maxThreshold,
          Math.max(cfg.minThreshold, base * cfg.thresholdGain + cfg.thresholdMargin),
        );
        calibrated = true;
      }

      if (rms > threshold) { speechMs += cfg.tickMs; silenceMs = 0; }
      else { silenceMs += cfg.tickMs; }

      // v7.4: 电平外抛 —— 云端 ASR 是请求-响应协议，整段录完才有字，
      // 中间没有任何反馈。把已有的 RMS 复用出来做音量条，用户至少能看到"在收声"。
      emit('stt:level', {
        level: Math.min(1, rms / Math.max(threshold * 3, 1e-6)),
        rms,
        threshold,
        speech: rms > threshold,
      });
      // 已经说过话 + 静音够久 → 认为本段回答结束
      if (speechMs >= cfg.minSpeechMs && silenceMs >= cfg.silenceMs) {
        _stopVad();
        if (onAutoStop) onAutoStop('silence');
      }
    }, cfg.tickMs);
  } catch (e) {
    // VAD 是增强项，失败不应阻断录音本身
    console.warn('[Voice] VAD 初始化失败，回退为手动停止:', e);
    vadTimer = null;
  }
}

function _stopVad() {
  const wasRunning = vadTimer !== null;
  if (vadTimer) { clearInterval(vadTimer); vadTimer = null; }
  if (vadAudioCtx) {
    try { vadAudioCtx.close(); } catch (_) { /* 关闭失败不影响流程 */ }
    vadAudioCtx = null;
  }
  // v7.4: 采样停止后归零电平，否则音量条会停在最后一帧的高度上
  if (wasRunning) {
    emit('stt:level', { level: 0, rms: 0, threshold: 0, speech: false, stopped: true });
  }
}

/** 是否正在录音 */
export function isRecording() {
  return recording;
}

/**
 * 开始录音（MediaRecorder 采集，识别交给后端 MiMo-ASR）
 *
 * v6.2: 支持 VAD 静音节流 —— 传入 onAutoStop 后，检测到说完（连续静音）或超时
 * 会自动回调，由调用方执行停止与转写；vad:false 可显式关闭（保留手动停止语义）。
 *
 * @param {object} [opts] - { vad, silenceMs, minSpeechMs, maxDurationMs, threshold, onAutoStop }
 * @returns {Promise<MediaRecorder|null>}
 */
export async function startRecording(opts = {}) {
  if (recording) return mediaRecorder;
  if (!voiceSupport.mimo) {
    toast('当前环境不支持录音', 'warning');
    return null;
  }
  // v7.4: 开麦前必须先停朗读。浏览器降级路径 startListening() 一直有这句，
  // MiMo 主路径却漏了 —— 结果面试官还在念题时用户点麦克风，外放的题目语音被
  // 自己的麦克风采集，连同真回答一起送进 ASR，还会触发 ASR 容错评分把串扰盖掉。
  stopSpeaking();
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    toast('无法访问麦克风，请检查浏览器权限设置', 'error');
    return null;
  }
  recordedChunks = [];
  // MiMo ASR 声明仅支持 mp3/mpeg/wav 的 data URL，故优先尝试 mp4（mpeg）格式
  const mime = (typeof MediaRecorder.isTypeSupported === 'function'
    ? ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm']
        .find(t => MediaRecorder.isTypeSupported(t))
    : undefined);
  mediaRecorder = new MediaRecorder(mediaStream, mime ? { mimeType: mime } : undefined);
  mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size) recordedChunks.push(e.data); };
  mediaRecorder.onstop = () => {
    recording = false;
    if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
    emit('stt:end');
  };
  mediaRecorder.start();
  recording = true;
  emit('stt:start');

  // v6.2: VAD 节流（默认开启；opts.vad === false 时保留纯手动停止）
  if (opts.vad !== false) {
    _startVad(mediaStream, (reason) => {
      if (typeof opts.onAutoStop === 'function') opts.onAutoStop(reason);
    }, opts);
  }
  return mediaRecorder;
}

/**
 * 停止录音并返回音频 Blob
 * @returns {Promise<Blob|null>}
 */
export function stopRecording() {
  return new Promise((resolve) => {
    _stopVad();   // v6.2: 手动停止时同步清掉 VAD 采样器
    if (!mediaRecorder || mediaRecorder.state === 'inactive') {
      recording = false;
      resolve(null);
      return;
    }
    mediaRecorder.onstop = () => {
      recording = false;
      if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
      emit('stt:end');
      if (!recordedChunks.length) {
        resolve(null);
        return;
      }
      const type = mediaRecorder.mimeType || 'audio/webm';
      resolve(new Blob(recordedChunks, { type }));
    };
    mediaRecorder.stop();
  });
}

/**
 * 上传录音 -> MiMo-ASR -> 转写文本
 * @returns {Promise<{ok:boolean, text:string, message:string}>}
 */
export async function transcribeRecording(blob) {
  if (!blob) return { ok: false, text: '', message: '无录音数据' };
  try {
    const data = await requestVoiceASR(blob);
    return { ok: !!data.ok, text: data.text || '', message: data.message || '' };
  } catch (e) {
    return { ok: false, text: '', message: e.message || '语音识别失败' };
  }
}

// ===== 便捷方法：语音输入到文本框 =====

/**
 * 浏览器 STT：将实时识别结果追加到 textarea（降级引擎）
 * @param {HTMLTextAreaElement} textarea
 * @param {Function} [onStateChange] - (state: 'idle'|'listening'|'processing')
 * @returns {Function} 停止函数
 */
export function voiceFillTextarea(textarea, onStateChange) {
  if (!voiceSupport.stt) {
    toast('当前浏览器不支持语音识别', 'warning');
    return () => {};
  }
  const setState = (s) => { if (onStateChange) onStateChange(s); };
  setState('listening');
  let lastFinal = '';
  let paused = false;

  const stop = startListening({
    lang: 'zh-CN',
    continuous: true,
    interimResults: true,
    onResult: (text) => {
      if (lastFinal) {
        const overlap = findOverlap(lastFinal, text);
        textarea.value += text.slice(overlap);
      } else {
        textarea.value += text;
      }
      lastFinal = text;
      textarea.scrollTop = textarea.scrollHeight;
    },
    onInterim: (text) => {
      if (!paused) {
        textarea.placeholder = `🎤 正在聆听... "${text.slice(0, 40)}${text.length > 40 ? '...' : ''}"`;
      }
    },
    onEnd: () => {
      textarea.placeholder = '在此输入你的回答...';
      setState('idle');
    },
  });

  if (!stop) {
    setState('idle');
    return () => {};
  }

  return () => {
    paused = true;
    stopListening();
    textarea.placeholder = '在此输入你的回答...';
    setState('idle');
  };
}

/**
 * MiMo ASR：录音 -> 上传识别 -> 填入 textarea（主引擎）。
 * 未配 Key / 录音失败时自动降级为浏览器 STT。
 * @returns {Function} 停止/取消函数
 */
export async function voiceFillWithASR(textarea, onStateChange, opts = {}) {
  if (!voiceSupport.mimo) {
    return voiceFillTextarea(textarea, onStateChange);
  }
  const setState = (s) => { if (onStateChange) onStateChange(s); };

  setState('listening');
  // v6.2: 开启 VAD 静音节流 —— 说完后自动停录并转写，无需手动再点一次停止。
  // 自动停止与手动点停止共用同一个 stop()，cancelled 标志保证只执行一次。
  const recorder = await startRecording({
    ...opts,
    onAutoStop: (reason) => {
      if (reason === 'max_duration') toast('录音已达上限，已自动结束并识别', 'info');
      autoStop();
    },
  });
  if (!recorder) {
    // 录音不可用，降级浏览器 STT
    return voiceFillTextarea(textarea, onStateChange);
  }
  let cancelled = false;
  let stopFn = null;
  // v7.4: 区分停止来源 —— 免手模式只对"VAD 判断说完了"的自动停止做自动提交，
  // 用户手动点停止语义上是"我还要再说一段"，不能替他提交。
  const autoStop = () => { if (stopFn) stopFn('auto'); };

  const stop = async (reason = 'manual') => {
    if (cancelled) return;
    cancelled = true;
    setState('processing');
    const blob = await stopRecording();
    if (!blob) { setState('idle'); return; }
    const result = await transcribeRecording(blob);
    if (result.ok && result.text) {
      textarea.value += (textarea.value && !/[\s。，,]$/.test(textarea.value) ? '，' : '') + result.text;
      textarea.scrollTop = textarea.scrollHeight;
      if (typeof opts.onTranscribed === 'function') {
        opts.onTranscribed(result.text, { reason });
      }
    } else if (!result.ok) {
      toast(result.message || '语音识别失败，已使用浏览器识别', 'warning');
    }
    setState('idle');
  };

  stopFn = stop;   // v6.2: 供 VAD 自动停止回调使用
  return stop;
}

/** 找两个字符串的最大重叠长度 */
function findOverlap(a, b) {
  if (!a || !b) return 0;
  const maxLen = Math.min(a.length, b.length);
  for (let i = maxLen; i > 0; i--) {
    if (b.startsWith(a.slice(-i))) return i;
  }
  return 0;
}

// ===== 自动朗读问题（面试场景）=====

/** 清理文本用于 TTS（去 Markdown 符号、换行转逗号） */
function cleanForTTS(text) {
  return (text || '')
    .replace(/[*_~`#]/g, '')
    .replace(/\n{2,}/g, '，')
    .replace(/\n/g, '，')
    .trim();
}

/**
 * v6.1: 预取 TTS（借鉴 offerMaster"后台预合成"延迟优化）。
 * 收到新题/追问时后台请求一次合成，后端 LRU 缓存生效；
 * 用户随后点朗读/开自动朗读时直接命中缓存，零等待。
 * 静默失败：预取只是优化，不影响主流程。
 * @param {string} questionText
 */
export function prefetchTTS(questionText) {
  if (mimoStatus !== 'ready') return;
  const clean = cleanForTTS(questionText);
  if (!clean) return;
  requestVoiceTTS(clean, currentVoice).catch(() => {});
}

/**
 * 收到新问题时自动朗读（MiMo 优先，降级浏览器）
 * @param {string} questionText
 * @param {Function} [onStateChange]
 */
export async function autoReadQuestion(questionText, onStateChange, onEnd) {
  if (!voiceSupport.tts) { if (onEnd) onEnd(); return; }
  const seq = speechSeq;                 // v6.3: 世代号
  const clean = cleanForTTS(questionText);
  const setState = (s) => { if (onStateChange) onStateChange(s); };
  setState('speaking');

  // v6.3: onEnd 一次性守卫 + 打断复位。
  // 语义区分：自然结束 → 复位 UI 且通知调用方（切回文字输入）；
  // 被打断（tts:stop）→ 仅复位 UI，绝不触发调用方的连锁动作。
  let finished = false;
  const finish = (fireCallback) => {
    if (finished) return;
    finished = true;
    offStop();
    setState('idle');
    if (fireCallback && seq === speechSeq && onEnd) onEnd();
  };
  const offStop = onVoiceEvent('tts:stop', () => finish(false));

  await speak(clean, {
    rate: 0.9,
    // v6.2: 朗读结束回调 —— 供调用方切回文字输入（聚焦输入框、收起语音态）
    onEnd: () => finish(true),
  });
  finish(false);   // 兜底：speak 同步返回（引擎不可用等）也复位
}

// ===== 启动时后台探测 MiMo 可用性 =====
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  probeMimo();
}
