// ===================================================
// positionLibrary.js — v7.0 岗位库
//
// 解决的问题：JD 目前只是一个文本框，每次开练都要重新粘贴。
// 入库存成实体后，练习时直接选用；也让"同一 JD 练多场"的对比有意义。
// ===================================================

import { $, el, toast, fmtDate, emptyState, confirm as confirmDialog } from './utils.js';
import { request } from './api.js';

/** 岗位库面板 */
export function initPositionLibrary() {
  const panel = $('#position-library-panel');
  if (!panel) return;

  panel.innerHTML = '';

  panel.appendChild(el('div', { className: 'card' },
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;' },
      el('div', {},
        el('div', { className: 'card-title', textContent: '💼 岗位库' }),
        el('div', { className: 'library-subtitle', textContent: '保存目标岗位的 JD，练习时直接选用，不必重复粘贴' }),
      ),
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;' },
        el('button', {
          className: 'btn btn-primary btn-press', textContent: '+ 新建岗位',
          onClick: () => showForm(null),
        }),
        el('button', { className: 'btn btn-secondary btn-press', textContent: '🔄 刷新', onClick: loadPositions }),
      ),
    ),
  ));

  panel.appendChild(el('div', { id: 'pl-form-container' }));
  panel.appendChild(el('div', { id: 'pl-list' }));

  loadPositions();
}

// ===== 列表 =====

async function loadPositions() {
  const container = $('#pl-list');
  if (!container) return;
  container.replaceChildren(el('div', { className: 'empty-state' },
    el('div', { className: 'empty-text', textContent: '加载中…' })));

  let rows = [];
  try {
    const data = await request('GET', '/api/positions');
    rows = data.positions || [];
  } catch (err) {
    container.replaceChildren(emptyState({
      icon: '⚠️', title: '加载失败', desc: err.message || '请稍后重试',
    }));
    return;
  }

  if (!rows.length) {
    container.replaceChildren(emptyState({
      icon: '💼',
      title: '还没有岗位',
      desc: '把常练的目标岗位 JD 存进来，之后每次开练直接选用。',
    }));
    return;
  }

  const wrap = el('div', { className: 'library-grid' });
  for (const p of rows) wrap.appendChild(positionCard(p));
  container.replaceChildren(wrap);
}

function positionCard(p) {
  return el('div', { className: 'card card-hover library-card' },
    el('div', { className: 'library-card-head' },
      el('div', { className: 'library-card-title', textContent: p.title || '未命名岗位' }),
      p.department ? el('span', { className: 'lib-badge', textContent: p.department }) : null,
    ),
    el('div', { className: 'library-card-meta' },
      el('span', { textContent: fmtDate(p.updated_at) }),
    ),
    el('div', { className: 'library-card-actions' },
      el('button', {
        className: 'btn btn-sm btn-secondary', textContent: '编辑 JD',
        onClick: async () => {
          try {
            const data = await request('GET', `/api/positions/${p.id}`);
            showForm(data.position);
          } catch (err) {
            toast(err.message || '加载失败', 'error');
          }
        },
      }),
      el('button', {
        className: 'btn btn-sm btn-danger', textContent: '删除',
        onClick: async () => {
          const ok = await confirmDialog(`确定删除岗位「${p.title}」？`,
                                         { title: '删除岗位', okText: '删除', danger: true });
          if (!ok) return;
          try {
            await request('DELETE', `/api/positions/${p.id}`);
            toast('已删除', 'success');
            loadPositions();
          } catch (err) {
            toast(err.message || '删除失败', 'error');
          }
        },
      }),
    ),
    el('div', { id: `pl-detail-${p.id}`, className: 'library-detail hidden' }),
  );
}

// ===== 新建 / 编辑 =====

function showForm(position) {
  const box = $('#pl-form-container');
  const isEdit = !!(position && position.id);

  const title = el('input', {
    className: 'form-input',
    placeholder: '岗位名称，如「高级 Python 工程师」',
    value: position ? (position.title || '') : '',
  });
  const dept = el('input', {
    className: 'form-input',
    placeholder: '部门（可选）',
    value: position ? (position.department || '') : '',
  });
  const jd = el('textarea', {
    className: 'form-textarea',
    placeholder: '粘贴岗位 JD 原文…',
    style: 'min-height:180px;',
    textContent: position ? (position.jd_text || '') : '',
  });

  const submit = el('button', {
    className: 'btn btn-primary', textContent: isEdit ? '保存修改' : '保存',
    onClick: async () => {
      const t = title.value.trim();
      const j = jd.value.trim();
      if (!t) { toast('请填写岗位名称', 'warning'); return; }
      if (!j) { toast('请填写岗位 JD', 'warning'); return; }
      try {
        if (isEdit) {
          await request('PATCH', `/api/positions/${position.id}`,
                        { title: t, jd_text: j, department: dept.value.trim() || null });
        } else {
          await request('POST', '/api/positions',
                        { title: t, jd_text: j, department: dept.value.trim() || null });
        }
        toast(isEdit ? '已保存' : '已添加', 'success');
        box.replaceChildren();
        loadPositions();
      } catch (err) {
        toast(err.message || '保存失败', 'error');
      }
    },
  });

  box.replaceChildren(
    el('div', { className: 'card' },
      el('div', { className: 'card-title', textContent: isEdit ? '✎ 编辑岗位' : '＋ 新建岗位' }),
      el('div', { className: 'form-group' },
        el('label', { className: 'form-label', textContent: '岗位名称' }), title),
      el('div', { className: 'form-group' },
        el('label', { className: 'form-label', textContent: '部门（可选）' }), dept),
      el('div', { className: 'form-group' },
        el('label', { className: 'form-label', textContent: '岗位 JD' }), jd),
      el('div', { style: 'display:flex;gap:8px;justify-content:flex-end;' },
        el('button', {
          className: 'btn btn-secondary', textContent: '取消',
          onClick: () => box.replaceChildren(),
        }),
        submit,
      ),
    ),
  );
  title.focus();
}
