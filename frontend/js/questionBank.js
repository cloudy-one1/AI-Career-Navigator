// ===================================================
// questionBank.js v2.2 — 题库管理
// ===================================================

import { $, $$, el, toast, fmtDate } from './utils.js';
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
let editingId = null;

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
        style: `background:${currentFilters.favorited ? '#fef3c7' : 'var(--bg-secondary)'};border:1px solid var(--border);`,
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
    favBtn.style.background = currentFilters.favorited ? '#fef3c7' : 'var(--bg-secondary)';
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
      container.appendChild(el('div', { className: 'empty-state' },
        el('div', { className: 'empty-icon', textContent: '📭' }),
        el('div', { className: 'empty-text', textContent: currentFilters.search
          ? '没有匹配的题目，试试其他关键词' : '题库为空，点击"新建题目"开始添加' }),
      ));
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
      const isEditing = editingId === q.id;
      table.appendChild(buildQuestionRow(q, isEditing));
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

function buildQuestionRow(q, isEditing) {
  if (isEditing) {
    return buildEditRow(q);
  }

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
          onClick: () => { editingId = q.id; loadQuestions(); } }),
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

// ===== 编辑行 =====

function buildEditRow(q) {
  const container = $('#qb-form-container');
  container.innerHTML = '';

  container.appendChild(el('div', { className: 'card', style: 'border-left:4px solid var(--primary);' },
    el('div', { style: 'font-weight:600;margin-bottom:12px;', textContent: '✏️ 编辑题目' }),
    el('textarea', { id: 'qb-edit-question', className: 'form-input', style: 'min-height:80px;',
        placeholder: '题目内容', textContent: q.question_text || q.question }),
    el('div', { style: 'display:flex;gap:8px;margin-top:8px;' },
      el('select', { id: 'qb-edit-round', className: 'form-input', style: 'flex:1;' },
        ...ROUND_TYPES.filter(r => r !== '全部阶段').map(rt =>
          el('option', { value: rt, selected: rt === (q.round_type || ''), textContent: rt })),
      ),
      el('input', { id: 'qb-edit-intent', className: 'form-input', style: 'flex:2;', placeholder: '考察意图',
          value: q.intent || '' }),
    ),
    el('div', { style: 'display:flex;gap:8px;margin-top:8px;align-items:center;' },
      el('span', { style: 'font-size:.85rem;color:var(--text-muted);', textContent: '难度:' }),
      el('input', { id: 'qb-edit-diff', type: 'range', min: '1', max: '5', value: q.difficulty || 3,
          style: 'flex:1;', onInput: () => {
            const v = $('#qb-edit-diff').value;
            const lbl = $('#qb-edit-diff-label');
            if (lbl) lbl.textContent = '⭐'.repeat(v);
          } }),
      el('span', { id: 'qb-edit-diff-label', style: 'font-size:.85rem;min-width:60px;', textContent: '⭐'.repeat(q.difficulty || 3) }),
    ),
    el('div', { style: 'display:flex;gap:8px;margin-top:12px;' },
      el('button', { className: 'btn btn-primary', textContent: '💾 保存', onClick: async () => {
          const data = {
            question_text: $('#qb-edit-question').value,
            round_type: $('#qb-edit-round').value,
            intent: $('#qb-edit-intent').value,
            difficulty: parseInt($('#qb-edit-diff').value),
          };
          try {
            await updateQuestion(q.id, data);
            toast('更新成功', 'success');
            editingId = null;
            container.innerHTML = '';
            loadQuestions();
          } catch (e) { toast('更新失败: ' + e.message, 'error'); }
        } }),
      el('button', { className: 'btn btn-secondary', textContent: '取消', onClick: () => {
          editingId = null;
          container.innerHTML = '';
          loadQuestions();
        } }),
    ),
  ));

  container.scrollIntoView({ behavior: 'smooth' });
  return el('div', { style: 'background:#eef2ff;border-radius:8px;margin:4px 0;' });
}

// ===== 新建表单 =====

function showCreateForm() {
  const container = $('#qb-form-container');
  if (!container) return;

  // 如果编辑先取消
  editingId = null;

  container.innerHTML = '';
  container.appendChild(el('div', { className: 'card', style: 'border-left:4px solid var(--success);' },
    el('div', { style: 'font-weight:600;margin-bottom:12px;', textContent: '➕ 新建题目' }),
    el('textarea', { id: 'qb-new-question', className: 'form-input', style: 'min-height:80px;',
        placeholder: '输入题目内容...' }),
    el('div', { style: 'display:flex;gap:8px;margin-top:8px;' },
      el('select', { id: 'qb-new-round', className: 'form-input', style: 'flex:1;' },
        ...ROUND_TYPES.filter(r => r !== '全部阶段').map(rt =>
          el('option', { value: rt, textContent: rt })),
      ),
      el('input', { id: 'qb-new-intent', className: 'form-input', style: 'flex:2;', placeholder: '考察意图（可选）' }),
    ),
    el('div', { style: 'display:flex;gap:8px;margin-top:8px;align-items:center;' },
      el('span', { style: 'font-size:.85rem;color:var(--text-muted);', textContent: '难度:' }),
      el('input', { id: 'qb-new-diff', type: 'range', min: '1', max: '5', value: '3', style: 'flex:1;',
          onInput: () => {
            const v = $('#qb-new-diff').value;
            const lbl = $('#qb-new-diff-label');
            if (lbl) lbl.textContent = '⭐'.repeat(v);
          } }),
      el('span', { id: 'qb-new-diff-label', style: 'font-size:.85rem;min-width:60px;', textContent: '⭐⭐⭐' }),
    ),
    el('div', { style: 'display:flex;gap:8px;margin-top:12px;' },
      el('button', { className: 'btn btn-primary', textContent: '💾 创建', onClick: async () => {
          const text = $('#qb-new-question').value.trim();
          if (!text) { toast('请输入题目内容', 'warning'); return; }
          try {
            await createQuestion({
              question_text: text,
              round_type: $('#qb-new-round').value,
              intent: $('#qb-new-intent').value.trim(),
              difficulty: parseInt($('#qb-new-diff').value),
            });
            toast('创建成功', 'success');
            container.innerHTML = '';
            loadQuestions();
          } catch (e) { toast('创建失败: ' + e.message, 'error'); }
        } }),
      el('button', { className: 'btn btn-secondary', textContent: '取消', onClick: () => {
          container.innerHTML = '';
          loadQuestions();
        } }),
    ),
  ));

  container.scrollIntoView({ behavior: 'smooth' });
  $('#qb-new-question')?.focus();
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
