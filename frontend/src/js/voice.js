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
// 'unknown'（未探测）| 'ready'（可用）| 'failed'（本次会话已失败，降级浏览器）
let mimoStatus = 'unknown';

export function getMimoStatus() {
  return mimoStatus;
}

/**
 * 探测 MiMo 语音可用性（后台调用一次 TTS）。
 * 仅 unknown 时执行；ready/failed 直接返回。
 */
export async function probeMimo() {
  if (mimoStatus !== 'unknown') return mimoStatus;
  try {
    const data = await requestVoiceTTS('测试', 'default');
    mimoStatus = data && data.used ? 'ready' : 'failed';
  } catch (_) {
    mimoStatus = 'failed';
  }
  if (mimoStatus === 'failed') {
    console.info('[Voice] MiMo 语音不可用，已降级为浏览器原生语音');
  }
  return mimoStatus;
}

// ===== 语音状态事件（供外部订阅）=====

const listeners = {};

export function onVoiceEvent(event, callback) {
  if (!listeners[event]) listeners[event] = [];
  listeners[event].push(callback);
}

function emit(event, data) {
  (listeners[event] || []).forEach(fn => fn(data));
}

// ===== TTS（文字转语音）=====

let ttsUtterance = null;
let ttsSpeaking = false;
let mimoAudio = null;   // 当前 MiMo 播放的 <audio>

/** 停止当前朗读（浏览器 + MiMo） */
export function stopSpeaking() {
  if (mimoAudio) {
    try { mimoAudio.pause(); } catch (_) {}
    mimoAudio = null;
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
    if (opts.onEnd) opts.onEnd();
  };
  utterance.onerror = (e) => {
    ttsSpeaking = false;
    ttsUtterance = null;
    emit('tts:error', { error: e.error });
    if (e.error !== 'canceled' && e.error !== 'interrupted') {
      console.warn('[Voice] 浏览器 TTS 错误:', e.error);
    }
    if (opts.onEnd) opts.onEnd();
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
  return new Promise((resolve) => {
    requestVoiceTTS(text, 'default')
      .then((data) => {
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
        audio.onended = () => {
          mimoAudio = null;
          URL.revokeObjectURL(url);
          emit('tts:end');
          if (opts.onEnd) opts.onEnd();
          resolve(true);
        };
        audio.onerror = () => {
          mimoAudio = null;
          URL.revokeObjectURL(url);
          if (opts.onEnd) opts.onEnd();
          resolve(false);
        };
        audio.play().catch(() => {
          mimoAudio = null;
          URL.revokeObjectURL(url);
          if (opts.onEnd) opts.onEnd();
          resolve(false);
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
  // 未探测时先探测，避免首读降级
  if (mimoStatus === 'unknown') await probeMimo();

  if (mimoStatus === 'ready') {
    const ok = await mimoSpeak(text, opts);
    if (!ok) {
      // 本次失败，降级并标记，后续直接走浏览器
      mimoStatus = 'failed';
      browserSpeak(text, opts);
    }
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
  threshold: 0.02,        // 音量阈值（RMS，0-1）
  tickMs: 100,            // 采样间隔
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

    vadTimer = setInterval(() => {
      if (!recording) { _stopVad(); return; }
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      if (rms > cfg.threshold) { speechMs += cfg.tickMs; silenceMs = 0; }
      else { silenceMs += cfg.tickMs; }

      const elapsed = Date.now() - startedAt;
      if (elapsed >= cfg.maxDurationMs) {
        _stopVad();
        if (onAutoStop) onAutoStop('max_duration');
        return;
      }
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
  if (vadTimer) { clearInterval(vadTimer); vadTimer = null; }
  if (vadAudioCtx) {
    try { vadAudioCtx.close(); } catch (_) { /* 关闭失败不影响流程 */ }
    vadAudioCtx = null;
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
  const autoStop = () => { if (stopFn) stopFn(); };

  const stop = async () => {
    if (cancelled) return;
    cancelled = true;
    setState('processing');
    const blob = await stopRecording();
    if (!blob) { setState('idle'); return; }
    const result = await transcribeRecording(blob);
    if (result.ok && result.text) {
      textarea.value += (textarea.value && !/[\s。，,]$/.test(textarea.value) ? '，' : '') + result.text;
      textarea.scrollTop = textarea.scrollHeight;
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
  requestVoiceTTS(clean, 'default').catch(() => {});
}

/**
 * 收到新问题时自动朗读（MiMo 优先，降级浏览器）
 * @param {string} questionText
 * @param {Function} [onStateChange]
 */
export async function autoReadQuestion(questionText, onStateChange, onEnd) {
  if (!voiceSupport.tts) { if (onEnd) onEnd(); return; }
  const clean = cleanForTTS(questionText);
  const setState = (s) => { if (onStateChange) onStateChange(s); };
  setState('speaking');
  await speak(clean, {
    rate: 0.9,
    // v6.2: 朗读结束回调 —— 供调用方切回文字输入（聚焦输入框、收起语音态）
    onEnd: () => { setState('idle'); if (onEnd) onEnd(); },
  });
}

// ===== 启动时后台探测 MiMo 可用性 =====
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  probeMimo();
}
