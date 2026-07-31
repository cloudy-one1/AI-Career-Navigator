// ===================================================
// api.js — HTTP API + WebSocket 封装
// ===================================================

const BASE = '';

/** 通用 HTTP 请求 */
export async function request(method, path, body, isForm) {
  const opts = { method };
  if (body && !isForm) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  } else if (body && isForm) {
    opts.body = body;
  }
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || err.detail || res.statusText);
  }
  return res.json();
}

/** 上传简历文件 */
export async function uploadResume(file) {
  const form = new FormData();
  form.append('file', file);
  return request('POST', '/api/sessions/upload', form, true);
}

/** 生成问题（获取 session_id）v2.4: 支持 mode */
export async function generateQuestions(resumeText, jdText, style = 'friendly', mode = 'simulation') {
  return request('POST', '/api/sessions', {
    resume_text: resumeText,
    jd_text: jdText,
    style,
    mode,
  });
}

/** 单题诊断（HTTP 兼容模式） */
export async function diagnose(req) {
  return request('POST', '/api/diagnose', req);
}

/** 技能匹配 */
export async function skillMatch(keywords) {
  return request('POST', '/api/skill-match', { keywords });
}

/** 获取会话详情 */
export async function getSession(sessionId) {
  return request('GET', `/api/sessions/${sessionId}`);
}

/** 获取综合报告 */
export async function getReport(sessionId) {
  return request('GET', `/api/reports/${sessionId}`);
}

/** 获取所有会话 */
export async function listSessions() {
  return request('GET', '/api/sessions');
}

/** 获取所有 AI 后端及当前后端 */
export async function getProviders() {
  return request('GET', '/api/providers');
}

/** 切换 AI 后端 */
export async function switchProvider(provider) {
  return request('POST', '/api/switch-provider', { provider });
}

// ===== v2.2 题库管理 =====

/** 列出题库 */
export async function getQuestionBank(filters = {}) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== '') params.append(k, v);
  }
  return request('GET', `/api/question-bank?${params.toString()}`);
}

/** 创建题目 */
export async function createQuestion(data) {
  return request('POST', '/api/question-bank', data);
}

/** 更新题目 */
export async function updateQuestion(id, data) {
  return request('PUT', `/api/question-bank/${id}`, data);
}

/** 删除题目 */
export async function deleteQuestion(id) {
  return request('DELETE', `/api/question-bank/${id}`);
}

/** 切换收藏 */
export async function toggleFavorite(id) {
  return request('POST', `/api/question-bank/${id}/favorite`);
}

/** 从会话导入 */
export async function importFromSession(sessionId) {
  return request('POST', '/api/question-bank/import', { session_id: sessionId });
}

// ===== WebSocket =====

/**
 * 创建 WebSocket 面试连接
 * @param {string} sessionId
 * @param {object} handlers - { onMessage, onOpen, onClose, onError }
 * @returns {{ send, close }}
 */
export function createInterviewWS(sessionId, handlers) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = location.host;
  const url = `${protocol}//${host}/ws/interview/${sessionId}`;

  const ws = new WebSocket(url);

  ws.onopen = () => {
    console.log('[WS] 已连接');
    if (handlers.onOpen) handlers.onOpen();
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (handlers.onMessage) handlers.onMessage(msg.type, msg.data);
    } catch (err) {
      console.error('[WS] 消息解析失败', err);
    }
  };

  ws.onclose = () => {
    console.log('[WS] 已断开');
    if (handlers.onClose) handlers.onClose();
  };

  ws.onerror = (e) => {
    console.error('[WS] 错误', e);
    if (handlers.onError) handlers.onError(e);
  };

  return {
    // 后端按 {type, data:{...}} 解析，必须保持 data 嵌套，不能展开到顶层
    send(type, data = {}) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type, data }));
      }
    },
    close() { ws.close(); },
    get readyState() { return ws.readyState; },
  };
}
