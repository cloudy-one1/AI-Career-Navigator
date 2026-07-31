// ===================================================
// voice.js — v2.3 语音交互模块（TTS + STT）
// 基于浏览器 Web Speech API，无需后端
// ===================================================

import { toast } from './utils.js';

// ===== 浏览器能力检测 =====

export const voiceSupport = {
  get tts() {
    return typeof speechSynthesis !== 'undefined';
  },
  get stt() {
    return typeof SpeechRecognition !== 'undefined' ||
           typeof webkitSpeechRecognition !== 'undefined';
  },
};

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

/**
 * 朗读文本
 * @param {string} text
 * @param {object} [opts] - { rate, pitch, volume, lang, onEnd }
 */
export function speak(text, opts = {}) {
  if (!voiceSupport.tts) {
    console.warn('[Voice] TTS 不可用');
    return;
  }

  // 先停止之前的朗读
  stopSpeaking();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = opts.lang || 'zh-CN';
  utterance.rate = opts.rate || 0.95;    // 稍慢，便于理解面试题
  utterance.pitch = opts.pitch || 1.0;
  utterance.volume = opts.volume || 1.0;

  // 选一个中文女声（更自然的面试官声音）
  const voices = speechSynthesis.getVoices();
  const zhFemale = voices.find(v => v.lang.startsWith('zh') && v.name.includes('Female'))
    || voices.find(v => v.lang.startsWith('zh-CN'))
    || voices.find(v => v.lang.startsWith('zh'));
  if (zhFemale) utterance.voice = zhFemale;

  utterance.onstart = () => {
    ttsSpeaking = true;
    ttsUtterance = utterance;
    emit('tts:start', { text });
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
      console.warn('[Voice] TTS 错误:', e.error);
    }
  };

  // 确保 voices 已加载（Chrome 异步加载）
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

/** 停止朗读 */
export function stopSpeaking() {
  if (ttsSpeaking || speechSynthesis.speaking) {
    speechSynthesis.cancel();
    ttsSpeaking = false;
    ttsUtterance = null;
    emit('tts:stop');
  }
}

/** 是否正在朗读 */
export function isSpeaking() {
  return ttsSpeaking || speechSynthesis.speaking;
}

// ===== STT（语音转文字）=====

const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let sttListening = false;

/**
 * 开始语音识别
 * @param {object} [opts] - { lang, continuous, interimResults, onResult, onInterim, onEnd }
 */
export function startListening(opts = {}) {
  if (!voiceSupport.stt) {
    toast('当前浏览器不支持语音识别（请使用 Chrome 或 Edge）', 'warning');
    return false;
  }

  // 停止朗读（避免麦克风冲突）
  stopSpeaking();

  // 如果已有实例则先中止
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
      if (event.results[i].isFinal) {
        final += transcript;
      } else {
        interim += transcript;
      }
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
    } else if (event.error === 'no-speech') {
      // 静默处理：用户没说话
    } else if (event.error !== 'aborted') {
      console.warn('[Voice] STT 错误:', event.error);
    }

    if (opts.onEnd) opts.onEnd();
  };

  recognition.onend = () => {
    sttListening = false;
    emit('stt:end');

    // 如果仍在 active 状态但 recognition 自己停了，尝试重启
    // （continuous 模式下偶尔会自动停止）
    if (opts._autoRestart && sttListening === false) {
      // 不做自动重启，由外部控制
    }

    if (opts.onEnd) opts.onEnd();
  };

  try {
    recognition.start();
    return true;
  } catch (e) {
    console.error('[Voice] STT 启动失败:', e);
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

// ===== 便捷方法：语音输入到文本框 =====

/**
 * 将语音识别结果追加到指定 textarea
 * @param {HTMLTextAreaElement} textarea
 * @param {Function} [onStateChange] - 状态变化回调 (state: 'idle'|'listening'|'processing')
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
      // 追加最终结果到 textarea
      if (lastFinal) {
        // 去掉与前一段的重叠
        const overlap = findOverlap(lastFinal, text);
        const append = text.slice(overlap);
        textarea.value += append;
      } else {
        textarea.value += text;
      }
      lastFinal = text;

      // 自动滚动
      textarea.scrollTop = textarea.scrollHeight;
    },
    onInterim: (text) => {
      // 更新 placeholder 显示实时识别
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

/**
 * 收到新问题时自动朗读
 * @param {string} questionText
 * @param {Function} [onStateChange]
 */
export function autoReadQuestion(questionText, onStateChange) {
  if (!voiceSupport.tts) return;

  // 清理问题文本（去掉 Markdown 标记、特殊符号）
  const clean = questionText
    .replace(/[*_~`#]/g, '')
    .replace(/\n{2,}/g, '，')
    .replace(/\n/g, '，')
    .trim();

  const setState = (s) => { if (onStateChange) onStateChange(s); };

  setState('speaking');
  speak(clean, {
    rate: 0.9,
    onEnd: () => setState('idle'),
  });
}
