// ===================================================
// api.js — HTTP API + WebSocket 封装
// ===================================================

// v8.3: 原先在这里静态 import getToken 并统一注入 Authorization 头，
// 认证下线后请求层不再需要感知身份，回归纯粹的 HTTP 封装。

const BASE = '';

/** 通用 HTTP 请求；opts.raw=true 时返回原始 Response（文件下载等非 JSON 场景） */
export async function request(method, path, body, isForm, { raw = false } = {}) {
  const opts = { method };
  const headers = {};
  if (body && !isForm) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  } else if (body && isForm) {
    opts.body = body;
  }
  if (Object.keys(headers).length) opts.headers = headers;

  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || err.detail || res.statusText);
  }
  return raw ? res : res.json();
}

/** 上传简历文件（临时使用，不入简历库）
 *  注意：后端会把文本截断到 5000 字（历史兼容行为，勿改）。 */
export async function uploadResume(file) {
  const form = new FormData();
  form.append('file', file);
  return request('POST', '/api/sessions/upload', form, true);
}

/** v7.0: 上传简历并入库（返回完整文本长度，不截断 —— 截断会让后续出题看到不完整的简历） */
export async function uploadResumeToLibrary(file) {
  const form = new FormData();
  form.append('file', file);
  return request('POST', '/api/resumes/upload', form, true);
}

/** 获取已入库简历详情（含 raw_text 全文） */
export async function getResume(id) {
  return request('GET', `/api/resumes/${id}`);
}

/** v7.0.2: 上传 JD 文件（PDF/TXT/DOCX），解析结果回填 JD 文本框（不入岗位库） */
export async function uploadJd(file) {
  const form = new FormData();
  form.append('file', file);
  return request('POST', '/api/upload-jd', form, true);
}

/** 生成问题（获取 session_id）v2.4: 支持 mode。v2.7: 支持自我介绍 + 题型占比。v6.5: 支持目标公司风格 */
export async function generateQuestions(resumeText, jdText, style = 'friendly', mode = 'simulation', includeSelfIntro = false, questionTypeMix = {}, companyProfile = '', resumeId = null, positionId = null) {
  return request('POST', '/api/sessions', {
    resume_text: resumeText,
    jd_text: jdText,
    style,
    mode,
    include_self_intro: includeSelfIntro,
    question_type_mix: questionTypeMix,
    company_profile: companyProfile || null,   // 空串 = 后端按 JD 自动匹配
    // v7.0: 简历/岗位库关联。为 null 时后端忽略，行为与旧版完全一致。
    resume_id: resumeId || null,
    position_id: positionId || null,
  });
}

/** v6.5: 获取全部公司风格配置（目标公司选择器用） */
export async function getCompanyProfiles() {
  return request('GET', '/api/company-profiles');
}

/** 获取会话详情 */
export async function getSession(sessionId) {
  return request('GET', `/api/sessions/${sessionId}`);
}

/** 获取综合报告 */
export async function getReport(sessionId) {
  return request('GET', `/api/reports/${sessionId}`);
}

/** v2.7: 导出复盘 Markdown。走 request({raw}) 统一出口，便于集中处理错误 */
export async function exportReview(sessionId) {
  const res = await request('GET', `/api/reports/${sessionId}/review`, null, false, { raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `review_${sessionId}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

/** v2.7: 获取全局薄弱点聚合。v8.4: 支持按岗位过滤 */
export async function getGlobalWeaknessProfile(positionId = null) {
  const qs = positionId ? `?position_id=${encodeURIComponent(positionId)}` : '';
  return request('GET', `/api/weakness-profile${qs}`);
}

// ===== v6.3 长期记忆闭环 =====

/** 薄弱点明细（记忆图谱数据源）。v8.4: 支持按岗位过滤 */
export async function getWeaknessPoints(includeResolved = false, limit = 200, positionId = null) {
  let qs = `?include_resolved=${includeResolved}&limit=${limit}`;
  if (positionId) qs += `&position_id=${encodeURIComponent(positionId)}`;
  return request('GET', `/api/weakness-profile/points${qs}`);
}

/** 标记已解决 / 恢复未解决 */
export async function resolveWeakness(pointId, resolved = true) {
  return request('PUT', `/api/weakness-profile/${pointId}/resolve`, { resolved });
}

/** 删除单条薄弱点（物理删除，不可恢复） */
export async function deleteWeakness(pointId) {
  return request('DELETE', `/api/weakness-profile/${pointId}`);
}

/** 获取所有会话 */
export async function listSessions() {
  return request('GET', '/api/sessions');
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

/** 切换岗位「感兴趣」收藏（持久化到 market.db，返回 { job_id, is_interested }） */
export async function toggleMarketInterest(jobId) {
  return request('POST', `/api/market/jobs/${jobId}/interest`);
}

/**
 * [v8.2] 把市场岗位导入岗位库，之后面试页可直接选用这份 JD。
 * 幂等：重复导入不产生第二条，返回 { position, created }，created=false 表示此前已导入。
 */
export async function addMarketJobToPosition(jobId) {
  return request('POST', `/api/market/jobs/${jobId}/to-position`);
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

/** v7.0: 岗位库列表（供长期记忆页岗位选择器使用） */
export async function listPositions(limit = 100) {
  return request('GET', `/api/positions?limit=${limit}`);
}

/** 市场统计概览 */
export async function getMarketStats(keyword = '') {
  const params = new URLSearchParams();
  if (keyword) params.append('keyword', keyword);
  return request('GET', `/api/market/stats?${params.toString()}`);
}

/**
 * [v8.2] 全部分析图表的聚合数据（一次性取回，避免每张卡片各发一次请求）。
 * 空库返回 total=0 + 各维度空骨架，调用方据此渲染空态。
 */
export async function getMarketCharts(keyword = '') {
  const params = new URLSearchParams();
  if (keyword) params.append('keyword', keyword);
  return request('GET', `/api/market/charts?${params.toString()}`);
}

/**
 * [v8.2] 对指定图表 section 生成 AI 解读（服务端 TTL 缓存 5 分钟）。
 *
 * 后端对「无数据 / 无 Key / LLM 异常」一律返回 { error } 而非 5xx，
 * 因此这里不做异常转换，由调用方在卡片内降级展示。
 */
export async function getMarketInsight({ section, keyword = '', fresh = false }) {
  const form = new URLSearchParams();
  form.append('section', section);
  if (keyword) form.append('keyword', keyword);
  form.append('fresh', String(fresh));
  return request('POST', '/api/market/insight', form, true);
}

/**
 * [v8.0] 求职档案（能力档案首屏数据源）。
 * 失败返回 null 而非抛出——档案是首屏，取不到就降级渲染，绝不能挡住其他功能。
 */
export async function fetchProfile() {
  try {
    return await request('GET', '/api/profile');
  } catch (e) {
    console.warn('[档案] 拉取失败，首屏降级:', e && e.message);
    return null;
  }
}

/**
 * [v8.0] 让服务端档案缓存失效（面试出报告后调用）。
 * 没有它，完成一场面试后要等最多 60 秒才在能力档案看到更新——而"练完档案就变"
 * 恰恰是陪跑闭环最需要被看见的那一刻。静默失败：最坏情况是继续用旧缓存。
 */
export async function refreshProfile() {
  try {
    await request('POST', '/api/profile/refresh');
  } catch (e) {
    console.warn('[档案] 缓存失效失败（不影响使用）:', e && e.message);
  }
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
 *   （v8.3: 已移除 onUnauthorized，服务端不再返回 4001）
 * @returns {{ send, close }}
 */
export function createInterviewWS(sessionId, handlers) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = location.host;
  const baseUrl = `${protocol}//${host}/ws/interview/${sessionId}`;

  let ws = null;
  let _intentionalClose = false;
  let _sessionExpired = false;  // 会话已失效标记，防止收不到 error 消息时仍重连
  let _reconnectAttempts = 0;
  const _maxReconnectAttempts = 5;
  const _baseDelay = 1000; // 1s
  const _maxDelay = 30000;  // 30s

  function _connect() {
    // 连接不再带 token query 参数（此前是因 WS API 不支持自定义请求头
    // 而做的兜底，随认证一并下线）。
    ws = new WebSocket(baseUrl);

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
      // v8.3: 原先还有 4001（未授权）分支——那是 WS 握手鉴权的产物，
      // 认证下线后服务端不再发此码，分支连同 handlers.onUnauthorized 一并删除。
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
