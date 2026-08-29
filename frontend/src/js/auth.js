// ===================================================
// auth.js — v7.0 认证：token 存取 + 账户面板（登录/注册）
//
// 设计前提：认证是**可关闭的**（AUTH_ENABLED=false 时后端返回匿名身份），
// 因此本模块的所有分支都必须能在"后端认为不需要登录"时正常工作，
// 而不是假设登录一定存在。
// ===================================================

import { $, el, toast } from './utils.js';

const TOKEN_KEY = 'aims_token';
const USER_KEY = 'aims_user';

/** 已登录用户（null = 未登录 / 匿名） */
let _user = null;

/** 初始化标记：面板首次进入时才做一次服务端校验，避免每次切 tab 都发请求 */
let _checked = false;

// ===== token 存取 =====

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';   // 隐私模式下 localStorage 可能不可用，降级为无 token
  }
}

function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* 存不下就只在内存里保留会话，不阻断使用 */
  }
}

export function getUser() {
  return _user;
}

export function isLoggedIn() {
  return !!(getToken() && _user);
}

/** 退出登录：清 token → 清内存用户 → 重绘面板 → 通知全局 */
export function logout() {
  setToken('');
  _user = null;
  try {
    localStorage.removeItem(USER_KEY);
  } catch { /* 忽略存储异常 */ }
  renderPanel();
  window.dispatchEvent(new CustomEvent('auth:changed'));
}

// ===== 与后端通信 =====

async function api(path, method, body) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || res.statusText || '请求失败');
  }
  return data;
}

/**
 * 启动时拉取身份。
 *
 * 用 /api/auth/me 而不是只信 localStorage：本地 token 可能已过期或被吊销，
 * 服务端才是唯一权威。失败时静默降级为未登录——登录态是增强项，
 * 拿不到不该阻断用户使用其他面板。
 */
async function fetchMe() {
  try {
    const me = await api('/api/auth/me', 'GET');
    setToken(getToken());
    _user = (me && !me.is_anonymous && me.id) ? me : null;
  } catch {
    // 401（过期/被删）也是走这里：清掉失效 token，避免每页都带着坏 token 请求
    const t = getToken();
    if (t) setToken('');
    _user = null;
  }
}

// ===== 面板渲染 =====

function rolePicker(selected, onPick) {
  const box = el('div', { className: 'role-seg' });
  const opts = [
    { v: 'jobseeker', label: '求职者' },
    { v: 'recruiter', label: '招聘者' },
  ];
  for (const o of opts) {
    box.appendChild(el('button', {
      type: 'button',
      className: `role-seg-btn${selected === o.v ? ' selected' : ''}`,
      textContent: o.label,
      onclick: () => onPick(o.v),
    }));
  }
  return box;
}

function renderLoggedIn() {
  const panel = $('#account-panel');
  panel.replaceChildren(
    el('div', { className: 'card auth-card' },
      el('div', { className: 'card-title', textContent: '账户' }),
      el('div', { className: 'auth-user' },
        el('span', { className: 'auth-avatar', textContent: (_user.username || '?')[0].toUpperCase() }),
        el('div', { className: 'auth-user-main' },
          el('div', { className: 'auth-user-name', textContent: _user.display_name || _user.username }),
          el('div', {
            className: 'auth-user-meta',
            textContent: `@${_user.username} · ${_user.role === 'recruiter' ? '招聘者' : '求职者'}`,
          }),
        ),
      ),
      el('div', { className: 'auth-note' },
        '登录后的面试记录、简历库与岗位库会绑定到该账户，其他人无法查看。'),
      el('div', { className: 'auth-actions' },
        el('button', {
          className: 'btn btn-secondary btn-press', textContent: '退出登录',
          onclick: () => { logout(); toast('已退出登录', 'info'); },
        }),
      ),
    ),
  );
}

function renderAuthForm(defaultMode = 'login') {
  const panel = $('#account-panel');
  let mode = defaultMode;   // login | register
  let role = 'jobseeker';

  const render = () => {
    const isLogin = mode === 'login';

    const username = el('input', {
      className: 'form-input', id: 'auth-username',
      placeholder: '字母 / 数字 / 下划线，3-32 位', autocomplete: 'username',
    });
    const password = el('input', {
      className: 'form-input', id: 'auth-password', type: 'password',
      placeholder: '至少 8 位', autocomplete: isLogin ? 'current-password' : 'new-password',
    });
    const errBox = el('div', { className: 'auth-error hidden' });
    const submit = el('button', {
      className: 'btn btn-primary btn-block btn-press',
      textContent: isLogin ? '登录' : '注册并登录',
    });

    const form = el('form', { className: 'auth-form' },
      el('div', { className: 'form-group' },
        el('label', { className: 'form-label', textContent: '用户名' }), username),
      el('div', { className: 'form-group' },
        el('label', { className: 'form-label', textContent: '密码' }), password),
    );

    if (!isLogin) {
      form.appendChild(el('div', { className: 'form-group' },
        el('label', { className: 'form-label', textContent: '身份' }),
        rolePicker(role, v => { role = v; render(); }),
      ));
    }

    form.appendChild(errBox);
    form.appendChild(submit);

    form.addEventListener('submit', async e => {
      e.preventDefault();
      errBox.classList.add('hidden');
      submit.disabled = true;
      submit.textContent = '处理中…';
      try {
        const body = { username: username.value.trim(), password: password.value };
        if (!isLogin) body.role = role;
        const data = await api(isLogin ? '/api/auth/login' : '/api/auth/register',
                               'POST', body);
        setToken(data.access_token);
        _user = data.user;
        toast(isLogin ? '登录成功' : '注册成功', 'success');
        renderPanel();
        window.dispatchEvent(new CustomEvent('auth:changed'));
      } catch (err) {
        errBox.textContent = err.message || '操作失败，请重试';
        errBox.classList.remove('hidden');
        submit.disabled = false;
        submit.textContent = isLogin ? '登录' : '注册并登录';
      }
    });

    // 切换登录/注册：整块重绘，避免两套表单各留一份状态
    const switchLine = isLogin
      ? el('div', { className: 'auth-switch' }, '还没有账号？',
          el('button', {
            type: 'button', className: 'auth-link',
            textContent: '注册一个', onclick: () => render.call(null),
          }))
      : el('div', { className: 'auth-switch' }, '已有账号？',
          el('button', {
            type: 'button', className: 'auth-link',
            textContent: '去登录', onclick: () => { mode = 'login'; render(); },
          }));

    panel.replaceChildren(
      el('div', { className: 'card auth-card' },
        el('div', { className: 'card-title', textContent: isLogin ? '登录' : '注册' }),
        form,
        switchLine,
        el('div', { className: 'auth-note auth-note-dim' },
          '不登录也可以直接使用模拟面试——登录后只是让简历、岗位与历史记录能跨设备归集到你的账户下。'),
      ),
    );
    // 注册态的"注册一个"按钮需要切到 register 后重绘
    if (isLogin) {
      const btn = panel.querySelector('.auth-link');
      if (btn) btn.onclick = () => { mode = 'register'; render(); };
    }
  };

  render();
}

export function renderPanel() {
  const panel = $('#account-panel');
  if (!panel) return;
  if (isLoggedIn()) renderLoggedIn();
  else renderAuthForm();
}

/** 面板初始化（app.js 的 switchTab 调用） */
export async function initAuth() {
  if (!_checked) {
    _checked = true;
    await fetchMe();
  }
  renderPanel();
  updateHeaderUser();
}

/** 顶部用户区 */
export function updateHeaderUser() {
  const btn = $('#user-btn');
  if (!btn) return;
  btn.classList.remove('hidden');
  const label = btn.querySelector('.user-btn-label');
  const avatar = btn.querySelector('.user-btn-avatar');
  if (isLoggedIn()) {
    btn.classList.add('logged-in');
    label.textContent = _user.display_name || _user.username;
    avatar.textContent = (_user.username || '?')[0].toUpperCase();
    btn.title = `已登录：${_user.username}`;
  } else {
    btn.classList.remove('logged-in');
    label.textContent = '未登录';
    avatar.textContent = '?';
    btn.title = '点击登录 / 注册';
  }
}

/** 供 app.js 在启动与登录态变化时调用 */
export async function refreshAuthStatus() {
  _checked = true;
  await fetchMe();
  renderPanel();
  updateHeaderUser();
}
