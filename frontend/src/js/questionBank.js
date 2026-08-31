// ===================================================
// questionBank.js v2.2 — 题库管理
// ===================================================

import { $, $$, el, toast, fmtDate, emptyState } from './utils.js';
import {
  getQuestionBank,
  createQuestion,
  updateQuestion,
  deleteQuestion,
  toggleFavorite,
  importFromSession,
} from './api.js';

const ROUND_TYPES = ['全部阶段', '破冰环节', '技术广度', '技术深度', '项目拷问', '行为面试', '反问收尾'];

let currentFilters = { round_type: '', search: '', favorited: false, source: '' };

/** 初始化题库面板 */
export function initQuestionBank() {
  const panel = $('#question-bank-panel');
  if (!panel) return;

  panel.innerHTML = '';

  // 头部：标题 + 操作按钮
  panel.appendChild(el('div', { className: 'card' },
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;' },
      el('div', { className: 'card-title', textContent: '📚 题库管理' }),
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;' },
        el('button', { id: 'btn-new-question', className: 'btn btn-primary', textContent: '+ 新建题目', onClick: showCreateForm }),
        el('button', { id: 'btn-import-session', className: 'btn btn-secondary', textContent: '📥 导入', onClick: showImportForm }),
        // v6.3 onboarding: 模板一键下载，消解"题库该存什么"的疑问
        el('button', { id: 'btn-download-template', className: 'btn btn-secondary', textContent: '📄 模板', onClick: downloadTemplate }),
      ),
    ),
  ));

  // 过滤栏
  panel.appendChild(el('div', { className: 'card' },
    el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center;' },
      el('select', { id: 'qb-filter-round', className: 'form-input', style: 'max-width:150px;',
          onChange: () => { currentFilters.round_type = $('#qb-filter-round').value === '全部阶段' ? '' : $('#qb-filter-round').value; loadQuestions(); } },
        ...ROUND_TYPES.map(rt => el('option', { value: rt, textContent: rt })),
      ),
      el('input', { id: 'qb-filter-search', className: 'form-input', style: 'max-width:250px;', placeholder: '搜索题目或意图...',
          onInput: () => { currentFilters.search = $('#qb-filter-search').value; loadQuestions(); } }),
      el('button', {
        id: 'qb-filter-fav', className: 'btn btn-sm',
        style: `background:${currentFilters.favorited ? 'var(--amber-50)' : 'var(--bg-secondary)'};border:1px solid var(--border);`,
        textContent: currentFilters.favorited ? '⭐ 已收藏' : '☆ 收藏',
        onClick: () => { currentFilters.favorited = !currentFilters.favorited; loadQuestions(); },
      }),
      el('button', { className: 'btn btn-sm btn-secondary', textContent: '🔄 刷新', onClick: loadQuestions }),
    ),
  ));

  // 题目列表 + 编辑表单容器
  panel.appendChild(el('div', { id: 'qb-list' }));
  panel.appendChild(el('div', { id: 'qb-form-container' }));
  panel.appendChild(el('div', { id: 'qb-import-container' }));

  loadQuestions();
}

// ===== 加载列表 =====

async function loadQuestions() {
  const container = $('#qb-list');
  container.innerHTML = el('div', { className: 'empty-state' },
    el('div', { className: 'empty-text', textContent: '加载中...' }),
  ).innerHTML;

  // 更新收藏按钮样式
  const favBtn = $('#qb-filter-fav');
  if (favBtn) {
    favBtn.style.background = currentFilters.favorited ? 'var(--amber-50)' : 'var(--bg-secondary)';
    favBtn.textContent = currentFilters.favorited ? '⭐ 已收藏' : '☆ 收藏';
  }

  try {
    const data = await getQuestionBank({
      round_type: currentFilters.round_type,
      search: currentFilters.search,
      favorited: currentFilters.favorited ? '1' : '',
      source: currentFilters.source,
    });

    const questions = data.questions || [];
    if (questions.length === 0) {
      container.innerHTML = '';
      // v6.3: 空状态三件套 + 空库时的模板下载引导
      const empty = currentFilters.search
        ? emptyState({ icon: '🔍', title: '没有匹配的题目', desc: '试试其他关键词，或清除筛选条件' })
        : emptyState({
            icon: '📭', title: '题库还是空的',
            desc: '手动新建、从历史面试导入，或先下载模板看看题库该长什么样。',
          });
      if (!currentFilters.search) {
        empty.appendChild(el('div', {
          style: 'margin-top:12px;display:flex;gap:8px;justify-content:center;',
        }, el('button', {
          className: 'btn btn-sm btn-primary btn-press',
          textContent: '下载题库模板', onClick: downloadTemplate,
        })));
      }
      container.appendChild(empty);
      return;
    }

    container.innerHTML = '';
    const table = el('div', { className: 'qb-table' });

    // 表头
    table.appendChild(el('div', { className: 'qb-row qb-header' },
      el('div', { className: 'qb-cell qb-cell-fav', textContent: '⭐' }),
      el('div', { className: 'qb-cell qb-cell-stage', textContent: '阶段' }),
      el('div', { className: 'qb-cell qb-cell-question', textContent: '题目' }),
      el('div', { className: 'qb-cell qb-cell-intent', textContent: '意图' }),
      el('div', { className: 'qb-cell qb-cell-diff', textContent: '难度' }),
      el('div', { className: 'qb-cell qb-cell-usage', textContent: '使用' }),
      el('div', { className: 'qb-cell qb-cell-actions', textContent: '操作' }),
    ));

    questions.forEach(q => {
      table.appendChild(buildQuestionRow(q));
    });

    container.appendChild(table);

    // 总计
    container.appendChild(el('div', {
      style: 'text-align:center;font-size:.8rem;color:var(--text-muted);margin-top:8px;',
      textContent: `共 ${data.total || questions.length} 道题目`,
    }));
  } catch (e) {
    toast('加载题库失败: ' + e.message, 'error');
  }
}

// ===== 构建题目行（或编辑行）=====

function buildQuestionRow(q) {
  const diffStars = '⭐'.repeat(q.difficulty || 1) + '☆'.repeat(5 - (q.difficulty || 1));

  return el('div', { className: `qb-row ${q.is_favorited ? 'qb-fav' : ''}` },
    el('div', { className: 'qb-cell qb-cell-fav' },
      el('span', {
        style: `cursor:pointer;font-size:1.1rem;`,
        textContent: q.is_favorited ? '⭐' : '☆',
        onClick: async (e) => { e.stopPropagation(); await toggleFavorite(q.id); loadQuestions(); },
      }),
    ),
    el('div', { className: 'qb-cell qb-cell-stage' },
      el('span', { className: 'qb-tag', textContent: q.round_type || '通用' }),
    ),
    el('div', { className: 'qb-cell qb-cell-question' },
      el('span', { style: 'line-height:1.5;', textContent: q.question_text || q.question }),
    ),
    el('div', { className: 'qb-cell qb-cell-intent' },
      el('span', { style: 'font-size:.8rem;color:var(--text-muted);', textContent: q.intent || '-' }),
    ),
    el('div', { className: 'qb-cell qb-cell-diff', style: 'font-size:.7rem;', textContent: diffStars }),
    el('div', { className: 'qb-cell qb-cell-usage', style: 'text-align:center;', textContent: q.usage_count || 0 }),
    el('div', { className: 'qb-cell qb-cell-actions' },
      el('button', { className: 'btn btn-sm', style: 'margin-right:4px;', textContent: '✏️', title: '编辑',
          onClick: () => openEditQbModal(q) }),
      el('button', { className: 'btn btn-sm btn-danger', textContent: '🗑️', title: '删除',
          onClick: async () => {
            if (!confirm('确定删除这道题目吗？')) return;
            await deleteQuestion(q.id);
            toast('已删除', 'info');
            loadQuestions();
          } }),
    ),
  );
}

// ===== 新建/编辑 Modal（v4.0）=====

function openEditQbModal(q) {
  openQbFormModal({
    title: '✏️ 编辑题目',
    initial: {
      question_text: q.question_text || q.question,
      round_type: q.round_type || '',
      intent: q.intent || '',
      difficulty: q.difficulty || 3,
    },
    submitLabel: '💾 保存',
    onSubmit: async (data) => { await updateQuestion(q.id, data); toast('更新成功', 'success'); },
  });
}

function openCreateQbModal() {
  openQbFormModal({
    title: '➕ 新建题目',
    initial: { round_type: '', difficulty: 3 },
    submitLabel: '💾 创建',
    onSubmit: async (data) => { await createQuestion(data); toast('创建成功', 'success'); },
  });
}

/** 通用题目表单 Modal */
function openQbFormModal({ title, initial = {}, submitLabel, onSubmit }) {
  const overlay = el('div', { className: 'modal-overlay' });
  const close = () => { overlay.remove(); document.body.classList.remove('drawer-open'); };

  const diffVal = initial.difficulty ?? 3;
  const diffLabel = el('span', { className: 'qb-diff-label', textContent: '⭐'.repeat(diffVal) });

  const questionInput = el('textarea', { className: 'form-input', style: 'min-height:80px;',
    placeholder: '输入题目内容...', textContent: initial.question_text || '' });
  const roundSelect = el('select', { className: 'form-input', style: 'flex:1;' },
    ...ROUND_TYPES.filter(r => r !== '全部阶段').map(rt =>
      el('option', { value: rt, selected: rt === (initial.round_type || ''), textContent: rt })));
  const intentInput = el('input', { className: 'form-input', style: 'flex:2;', placeholder: '考察意图（可选）',
    value: initial.intent || '' });
  const diffInput = el('input', { type: 'range', min: '1', max: '5', value: String(diffVal), style: 'flex:1;',
    onInput: () => { diffLabel.textContent = '⭐'.repeat(Number(diffInput.value)); } });

  const modal = el('div', { className: 'modal', role: 'dialog', 'aria-label': title },
    el('div', { className: 'modal-header' },
      el('div', { className: 'modal-title', textContent: title }),
      el('button', { className: 'btn btn-ghost btn-sm', textContent: '✕', onClick: close }),
    ),
    el('div', { className: 'modal-body' },
      questionInput,
      el('div', { style: 'display:flex;gap:8px;margin-top:8px;' }, roundSelect, intentInput),
      el('div', { className: 'qb-diff-row' },
        el('span', { className: 'qb-diff-caption', textContent: '难度' }),
        diffInput,
        diffLabel,
      ),
    ),
    el('div', { className: 'modal-footer' },
      el('button', { className: 'btn btn-secondary', textContent: '取消', onClick: close }),
      el('button', { className: 'btn btn-primary', textContent: submitLabel, onClick: async () => {
          const text = questionInput.value.trim();
          if (!text) { toast('请输入题目内容', 'warning'); return; }
          try {
            await onSubmit({
              question_text: text,
              round_type: roundSelect.value,
              intent: intentInput.value.trim(),
              difficulty: parseInt(diffInput.value, 10),
            });
            close();
            loadQuestions();
          } catch (e) { toast('保存失败: ' + e.message, 'error'); }
        } }),
    ),
  );

  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  document.body.classList.add('drawer-open');
  questionInput.focus();
}

// ===== 新建表单 =====

function showCreateForm() {
  openCreateQbModal();
}

// ===== 导入表单 =====

function showImportForm() {
  const container = $('#qb-import-container');
  if (!container) return;

  container.innerHTML = '';
  container.appendChild(el('div', { className: 'card', style: 'border-left:4px solid var(--warning);' },
    el('div', { style: 'font-weight:600;margin-bottom:12px;', textContent: '📥 从面试会话导入题目' }),
    el('div', { style: 'display:flex;gap:8px;' },
      el('input', { id: 'qb-import-session-id', className: 'form-input', style: 'flex:1;', placeholder: '输入 Session ID...' }),
      el('button', { className: 'btn btn-primary', textContent: '导入', onClick: async () => {
          const sid = $('#qb-import-session-id').value.trim();
          if (!sid) { toast('请输入 Session ID', 'warning'); return; }
          try {
            const result = await importFromSession(sid);
            toast(`导入了 ${result.imported_count} 道题目`, 'success');
            container.innerHTML = '';
            loadQuestions();
          } catch (e) { toast('导入失败: ' + e.message, 'error'); }
        } }),
    ),
    el('button', { className: 'btn btn-sm btn-secondary', style: 'margin-top:8px;', textContent: '取消', onClick: () => {
        container.innerHTML = '';
      } }),
  ));

  container.scrollIntoView({ behavior: 'smooth' });
}

// ===== v6.3 onboarding: 题库模板一键下载（借鉴 HakiMeet QuestionBankView）=====
// 模板对齐后端 CreateQuestionRequest 字段（question_text/round_type/intent/tags/difficulty），
// 内联真实示例题，Blob 触发下载 —— 把"我该往题库里放什么"这个疑问在页面上直接消解掉。
function downloadTemplate() {
  const md = [
    '# 题库模板（AI 求职陪跑）',
    '',
    '按下面的字段说明整理题目后，在「题库管理 → 新建题目」中录入；',
    '也可以把本文件交给任意 AI，让它按你的 JD 批量生成同格式题目。',
    '',
    '## 字段说明',
    '',
    '| 字段 | 必填 | 说明 |',
    '|---|---|---|',
    '| question_text | 是 | 题目正文（面试官口吻） |',
    '| round_type | 否 | 阶段：破冰环节 / 技术广度 / 技术深度 / 项目拷问 / 行为面试 / 反问收尾 |',
    '| intent | 否 | 考察意图（一句话） |',
    '| tags | 否 | 标签，逗号分隔，如：Python,并发 |',
    '| difficulty | 否 | 难度 1-5（默认 3） |',
    '',
    '## 示例题目',
    '',
    '### 示例 1',
    '- question_text: 请介绍一个你最有代表性的项目，重点讲清楚业务背景、你的角色和最终可量化的结果。',
    '- round_type: 项目拷问',
    '- intent: 考察 STAR 完整性与量化表达能力',
    '- tags: 项目经历,STAR',
    '- difficulty: 3',
    '',
    '### 示例 2',
    '- question_text: 高并发场景下缓存与数据库的一致性你是怎么保证的？发生过不一致吗，怎么定位的？',
    '- round_type: 技术深度',
    '- intent: 考察专业深度与真实踩坑经验，识别背题式回答',
    '- tags: 缓存,一致性,Redis',
    '- difficulty: 4',
    '',
    '### 示例 3',
    '- question_text: 和同事在技术方案上产生严重分歧时，你会怎么推进？举一个真实发生的例子。',
    '- round_type: 行为面试',
    '- intent: 考察协作与沟通，验证行为面试回答的真实性',
    '- tags: 协作,沟通',
    '- difficulty: 3',
    '',
  ].join('\n');
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '题库模板.md';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('模板已下载', 'success');
}
