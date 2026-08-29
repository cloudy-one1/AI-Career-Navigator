// ===================================================
// resumeLibrary.js — v7.0 简历库
//
// 存在的意义：同一份简历想练第二场，不必重新上传、重新解析（解析要调 LLM）。
// 不登录也能用（后端 AUTH_ENABLED=false 时 owner 为匿名），因此不能假设一定有归属。
// ===================================================

import { $, el, toast, fmtDate, emptyState, confirm as confirmDialog } from './utils.js';
import { request, uploadResumeToLibrary } from './api.js';

/** 简历库面板 */
export function initResumeLibrary() {
  const panel = $('#resume-library-panel');
  if (!panel) return;

  panel.innerHTML = '';

  panel.appendChild(el('div', { className: 'card' },
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;' },
      el('div', {},
        el('div', { className: 'card-title', textContent: '📄 简历库' }),
        el('div', { className: 'library-subtitle', textContent: '入库后可在多场面试中直接选用，不必重复上传与解析' }),
      ),
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;' },
        el('label', { className: 'btn btn-primary btn-press', style: 'margin:0;cursor:pointer;' },
          '⬆ 上传简历',
          el('input', {
            type: 'file', accept: '.pdf,.docx,.txt', style: 'display:none;',
            onChange: e => handleUpload(e.target),
          }),
        ),
        el('button', {
          className: 'btn btn-secondary btn-press', textContent: '✎ 粘贴文本',
          onClick: showCreateForm,
        }),
        el('button', { className: 'btn btn-secondary btn-press', textContent: '🔄 刷新', onClick: loadResumes }),
      ),
    ),
  ));

  panel.appendChild(el('div', { id: 'rl-form-container' }));
  panel.appendChild(el('div', { id: 'rl-list' }));

  loadResumes();
}

// ===== 列表 =====

async function loadResumes() {
  const container = $('#rl-list');
  if (!container) return;
  container.replaceChildren(el('div', { className: 'empty-state' },
    el('div', { className: 'empty-text', textContent: '加载中…' })));

  let rows = [];
  try {
    const data = await request('GET', '/api/resumes');
    rows = data.resumes || [];
  } catch (err) {
    container.replaceChildren(emptyState({
      icon: '⚠️', title: '加载失败', desc: err.message || '请稍后重试',
    }));
    return;
  }

  if (!rows.length) {
    container.replaceChildren(emptyState({
      icon: '📄',
      title: '还没有简历',
      desc: '上传一份简历入库后，之后每次开练都可以直接选用，不用再传一次。',
    }));
    return;
  }

  const wrap = el('div', { className: 'library-grid' });
  for (const r of rows) wrap.appendChild(resumeCard(r));
  container.replaceChildren(wrap);
}

function resumeCard(r) {
  const parsed = r.parsed_json ? '已解析' : '未解析';
  return el('div', { className: 'card card-hover library-card' },
    el('div', { className: 'library-card-head' },
      el('div', { className: 'library-card-title', textContent: r.title || '未命名简历' }),
      el('span', { className: `lib-badge${r.parsed_json ? ' ok' : ''}`, textContent: parsed }),
    ),
    el('div', { className: 'library-card-meta' },
      r.filename ? el('span', { textContent: r.filename }) : null,
      el('span', { textContent: `${r.char_count || 0} 字` }),
      el('span', { textContent: fmtDate(r.updated_at) }),
    ),
    el('div', { className: 'library-card-actions' },
      el('button', {
        className: 'btn btn-sm btn-secondary', textContent: '预览',
        onClick: () => showDetail(r.id),
      }),
      el('button', {
        className: 'btn btn-sm btn-secondary', textContent: '重命名',
        onClick: () => showRenameForm(r),
      }),
      el('button', {
        className: 'btn btn-sm btn-danger', textContent: '删除',
        onClick: async () => {
          const ok = await confirmDialog(`确定删除简历「${r.title}」？该操作不可恢复。`,
                                         { title: '删除简历', okText: '删除', danger: true });
          if (!ok) return;
          try {
            await request('DELETE', `/api/resumes/${r.id}`);
            toast('已删除', 'success');
            loadResumes();
          } catch (err) {
            toast(err.message || '删除失败', 'error');
          }
        },
      }),
    ),
    el('div', { id: `rl-detail-${r.id}`, className: 'library-detail hidden' }),
  );
}

// ===== 预览（展开显示摘要，不另开弹窗）=====

async function showDetail(id) {
  const box = $(`#rl-detail-${id}`);
  if (!box) return;
  if (!box.classList.contains('hidden')) {
    box.classList.add('hidden');
    box.replaceChildren();
    return;
  }
  box.classList.remove('hidden');
  box.replaceChildren(el('div', { className: 'library-detail-text', textContent: '加载中…' }));
  try {
    const data = await request('GET', `/api/resumes/${id}`);
    const text = data.resume?.raw_text || '';
    box.replaceChildren(el('div', { className: 'library-detail-text', textContent: text.slice(0, 1200) + (text.length > 1200 ? '…' : '') }));
  } catch (err) {
    box.replaceChildren(el('div', { className: 'library-detail-text', textContent: err.message || '加载失败' }));
  }
}

// ===== 新建（粘贴文本）=====

function showCreateForm() {
  const box = $('#rl-form-container');
  const title = el('input', { className: 'form-input', placeholder: '简历名称，如「张三-后端-3年」' });
  const text = el('textarea', {
    className: 'form-textarea', placeholder: '粘贴简历全文…', style: 'min-height:160px;',
  });

  const form = el('div', { className: 'card' },
    el('div', { className: 'card-title', textContent: '✎ 新增简历（粘贴文本）' }),
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '名称' }), title),
    el('div', { className: 'form-group' },
      el('label', { className: 'form-label', textContent: '简历内容' }), text),
    el('div', { style: 'display:flex;gap:8px;justify-content:flex-end;' },
      el('button', {
        className: 'btn btn-secondary', textContent: '取消',
        onClick: () => box.replaceChildren(),
      }),
      el('button', {
        className: 'btn btn-primary', textContent: '保存',
        onClick: async () => {
          const body = title.value.trim();
          const raw = text.value.trim();
          if (!raw) { toast('请粘贴简历内容', 'warning'); return; }
          try {
            await request('POST', '/api/resumes', {
              title: body || '未命名简历', raw_text: raw,
            });
            toast('已入库', 'success');
            box.replaceChildren();
            loadResumes();
          } catch (err) {
            toast(err.message || '保存失败', 'error');
          }
        },
      }),
    ),
  );
  box.replaceChildren(form);
  title.focus();
}

// ===== 重命名 =====

function showRenameForm(r) {
  const box = $(`#rl-detail-${r.id}`);
  if (!box) return;
  box.classList.remove('hidden');
  const input = el('input', { className: 'form-input', value: r.title || '' });
  box.replaceChildren(
    el('div', { className: 'library-detail-text' },
      el('div', { style: 'margin-bottom:6px;font-size:.8rem;color:var(--text-secondary);', textContent: '重命名' }),
      el('div', { style: 'display:flex;gap:8px;' },
        input,
        el('button', {
          className: 'btn btn-sm btn-primary', textContent: '保存',
          onClick: async () => {
            try {
              await request('PATCH', `/api/resumes/${r.id}`, { title: input.value.trim() });
              toast('已保存', 'success');
              loadResumes();
            } catch (err) {
              toast(err.message || '保存失败', 'error');
            }
          },
        }),
      ),
    ),
  );
  input.focus();
}

// ===== 上传（复用现有上传接口拿文本，再入库）=====

async function handleUpload(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  input.value = '';   // 允许重复选同一个文件
  toast('正在解析简历…', 'info');
  try {
    // 用 /api/resumes/upload 而非 /api/sessions/upload：后者为兼容旧前端把文本截断到
    // 5000 字，入库场景下截断会静默丢内容（之后出题看到的简历是不完整的）。
    await uploadResumeToLibrary(file);
    toast('简历已入库', 'success');
    loadResumes();
  } catch (err) {
    toast(err.message || '上传失败', 'error');
  }
}
