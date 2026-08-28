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

/** 生成问题（获取 session_id）v2.4: 支持 mode。v2.7: 支持自我介绍 + 题型占比 */
export async function generateQuestions(resumeText, jdText, style = 'friendly', mode = 'simulation', includeSelfIntro = false, questionTypeMix = {}) {
  return request('POST', '/api/sessions', {
    resume_text: resumeText,
    jd_text: jdText,
    style,
    mode,
    include_self_intro: includeSelfIntro,
    question_type_mix: questionTypeMix,
  });
}

/** 单题诊断（HTTP 兼容模式） */
export async function diagnose(req) {
  return request('POST', '/api/diagnose', req);
}

/** 获取会话详情 */
export async function getSession(sessionId) {
  return request('GET', `/api/sessions/${sessionId}`);
}

/** 获取综合报告 */
export async function getReport(sessionId) {
  return request('GET', `/api/reports/${sessionId}`);
}

/** v2.7: 导出复盘 Markdown */
export async function exportReview(sessionId) {
  const res = await fetch(BASE + `/api/reports/${sessionId}/review`);
  if (!res.ok) throw new Error('导出复盘失败');
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `review_${sessionId}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

/** v2.7: 获取薄弱点画像 */
export async function getWeaknessProfile(sessionId) {
  return request('GET', `/api/weakness-profile/${sessionId}`);
}

/** v2.7: 获取全局薄弱点聚合 */
export async function getGlobalWeaknessProfile() {
  return request('GET', `/api/weakness-profile`);
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

// ===== v3.1: Gap 分析 =====

/** 简历-岗位 Gap 分析（按会话） */
export async function getGapAnalysis(sessionId) {
  return request('GET', `/api/gap-analysis/${sessionId}`);
}

/** 简历-岗位 Gap 分析（直接提交文本） */
export async function runGapAnalysis({ resumeText, jdText, keyword = '' }) {
  return request('POST', '/api/gap-analysis', {
    resume_text: resumeText,
    jd_text: jdText,
    keyword,
  });
}

/** 跨岗位对比：一份简历 vs 多个岗位 */
export async function crossJobCompare(resumeText, jdList) {
  return request('POST', '/api/cross-job-compare', {
    resume_text: resumeText,
    jd_list: jdList,  // [{title, text}, ...]
  });
}

// ===== v3.3: 市场数据（实时采集 + 岗位库）=====

/** 启动 51job 实时采集（后台任务，返回 task_id） */
export async function startMarketCrawl({ keyword, cities, pages = 3, sortType = '0', token = '' }) {
  const form = new URLSearchParams();
  form.append('keyword', keyword);
  cities.forEach(c => form.append('cities', c));
  form.append('pages', String(pages));
  form.append('sort_type', String(sortType));
  if (token) form.append('token', token);
  return request('POST', '/api/market/crawl', form, true);
}

/** 查询采集任务状态（轮询） */
export async function getCrawlStatus(taskId) {
  return request('GET', `/api/market/crawl/status/${taskId}`);
}

/** 省份→城市级联数据 */
export async function getCityMap() {
  return request('GET', '/api/market/city-map');
}

/** 岗位详情（含 Gap 分析用 JD 文本） */
export async function getMarketJob(jobId) {
  return request('GET', `/api/market/jobs/${jobId}`);
}

/** 岗位列表（过滤 + 分页） */
export async function getMarketJobs(filters = {}, page = 0, limit = 50) {
  const params = new URLSearchParams();
  params.append('limit', String(limit));
  params.append('offset', String(page * limit));
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== '') params.append(k, v);
  }
  return request('GET', `/api/market/jobs?${params.toString()}`);
}

/** 市场统计概览 */
export async function getMarketStats(keyword = '') {
  const params = new URLSearchParams();
  if (keyword) params.append('keyword', keyword);
  return request('GET', `/api/market/stats?${params.toString()}`);
}

// ===== v3.2: 职业规划 =====

/** 职业路径规划（时间轴多阶段） */
export async function callCareerPlan({ resumeText, targetRole, jdText = '', timeframeYears = 3 }) {
  return request('POST', '/api/career-plan', {
    resume_text: resumeText,
    target_role: targetRole,
    jd_text: jdText,
    timeframe_years: timeframeYears,
  });
}

// ===== WebSocket =====

/**
 * 创建 WebSocket 面试连接（含自动重连）
 * @param {string} sessionId
 * @param {object} handlers - { onMessage, onOpen, onClose, onError, onReconnect, onReconnectFailed }
 * @returns {{ send, close }}
 */
export function createInterviewWS(sessionId, handlers) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = location.host;
  const url = `${protocol}//${host}/ws/interview/${sessionId}`;

  let ws = null;
  let _intentionalClose = false;
  let _sessionExpired = false;  // 会话已失效标记，防止收不到 error 消息时仍重连
  let _reconnectAttempts = 0;
  const _maxReconnectAttempts = 5;
  const _baseDelay = 1000; // 1s
  const _maxDelay = 30000;  // 30s

  function _connect() {
    ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('[WS] 已连接');
      if (_sessionExpired) {
        // 会话已失效，不再重置计数，直接关闭
        _intentionalClose = true;
        console.error('[WS] 会话已失效，关闭连接');
        ws.close();
        return;
      }
      _reconnectAttempts = 0;  // 重连成功后重置计数
      if (handlers.onOpen) handlers.onOpen();
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        // 会话不存在属于不可恢复错误（服务端重启导致内存会话丢失/会话过期），
        // 重试必然再次被拒，立即置为失效并停止重连，交由 onClose 恢复"开始面试"入口
        if (msg.type === 'error' && msg.data && msg.data.message === '会话不存在') {
          _sessionExpired = true;
          _intentionalClose = true;
          console.error('[WS] 会话已失效，停止重连');
          ws.close();
        }
        if (handlers.onMessage) handlers.onMessage(msg.type, msg.data);
      } catch (err) {
        console.error('[WS] 消息解析失败', err);
      }
    };

    ws.onclose = (e) => {
      console.log('[WS] 已断开', e.code, e.reason);
      // 1000 = 服务端正常关闭（面试完成后 handler 返回），不是断线，不重连
      if (e.code === 1000 && !_intentionalClose) {
        console.log('[WS] 面试连接正常关闭');
        if (handlers.onClose) handlers.onClose();
        return;
      }
      // 服务端用 4000/session_not_found 标识会话不存在，兜底停止重连
      if (!_sessionExpired && e.code === 4000 && e.reason === 'session_not_found') {
        _sessionExpired = true;
        _intentionalClose = true;
        console.error('[WS] 会话已失效，停止重连');
      }
      if (_sessionExpired || _intentionalClose) {
        if (handlers.onClose) handlers.onClose();
        return;
      }
      if (_reconnectAttempts < _maxReconnectAttempts) {
        const delay = Math.min(_baseDelay * Math.pow(2, _reconnectAttempts), _maxDelay);
        _reconnectAttempts++;
        console.log(`[WS] 将在 ${delay}ms 后重连 (第 ${_reconnectAttempts}/${_maxReconnectAttempts} 次)`);
        if (handlers.onReconnect) handlers.onReconnect(_reconnectAttempts, delay);
        setTimeout(_connect, delay);
      } else {
        console.error('[WS] 重连失败，已达最大重试次数');
        if (handlers.onReconnectFailed) handlers.onReconnectFailed();
        if (handlers.onClose) handlers.onClose();
      }
    };

    ws.onerror = (e) => {
      console.error('[WS] 错误', e);
      if (handlers.onError) handlers.onError(e);
    };
  }

  _connect();

  return {
    // 后端按 {type, data:{...}} 解析，必须保持 data 嵌套，不能展开到顶层
    send(type, data = {}) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type, data }));
      }
    },
    close() {
      _intentionalClose = true;
      ws.close();
    },
    get readyState() { return ws ? ws.readyState : WebSocket.CLOSED; },
  };
}

// ===== v4.2: 小米 MiMo 云端语音（TTS / ASR）=====
// 返回约定：TTS -> { used, audio_b64, format, message }；ASR -> { ok, text, message }
// used/ok=false 表示未配 Key 或云端失败，由前端降级到浏览器原生语音。

/** 文本 -> MiMo TTS -> Base64 音频 */
export async function requestVoiceTTS(text, voice = 'default') {
  return request('POST', '/api/voice/tts', { text, voice });
}

/** 上传录音 -> MiMo ASR -> 转写文本 */
export async function requestVoiceASR(blob) {
  const form = new FormData();
  form.append('file', blob, 'recording.webm');
  return request('POST', '/api/voice/asr', form, true);
}
