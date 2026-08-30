# job-crawler UI 设计系统规格

> **用途**：本项目（AI 模拟面试官）全站统一为 job-crawler「纸墨印章 / 编辑数据档案」视觉语言的**唯一权威基线**。
> **抽取来源**：`F:/Desktop/project1-enhanced` 的 `templates/base.html`、`static/theme-dark.css`、`static/theme-toggle.js`、`templates/input.html`、`templates/data.html`、`templates/job_detail.html`、`templates/collect.html`
> **改造原则**：DOM 结构 / 类名 / DOM 顺序 **100% 不动**，仅通过作用域 Token 重映射 + 同名类复刻生效。浅色（米色）为默认风格；深色为第二风格。

---

## 1. 字体引入

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;700;900&family=Noto+Sans+SC:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap">
```

三套字体栈的分工：

| 用途 | 字体 | 字重 |
|---|---|---|
| 标题 `h1~h5`、`.navbar-brand`、`.stamp`、`.home-feature-card .fc-title` | `'Noto Serif SC', serif` | 900（标题）/ 600,700（可选） |
| 正文 / 按钮 / 表单 / 表格 `td` | `'Noto Sans SC', sans-serif` | 400 / 500 / 600 / 700 |
| `.mono`、`.eyebrow`、`.table th`、`.brand-tagline`、`.card[data-no]::before`、薪资数字 | `'JetBrains Mono', monospace` | 500 / 600 |

---

## 2. 设计 Token（浅色 / 米色 — 默认）

```css
:root{
  --paper:#F4F2ED;        /* 页面底色（米色纸张） */
  --card:#FCFAF6;         /* 卡片底色（略亮于纸） */
  --ink:#1F2320;          /* 主文字（墨色） */
  --ink-soft:#667066;     /* 次要文字 / 说明 */
  --stamp:#C44F3A;        /* 印章红（强调） */
  --brass:#A08945;        /* 黄铜（data-no 角标、编号） */
  --line:#DAD6CC;         /* 描边 / 分隔线 */
  --teal:#3A7A6A;         /* 青绿（链接、成功、焦点） */
  --teal-soft:#E8F1ED;    /* 青绿浅底（焦点环、alert-info） */
  --accent:#C44F3A;       /* 强调色（= 印章红，主按钮、印章、active） */
  --accent-light:#FDF0EC; /* 强调浅底（active 导航、alert-danger） */
  --gold:#A08945;         /* 金（= 黄铜） */
}
```

### 基础排版与元素

```css
*{ box-sizing:border-box; }
html{ scroll-behavior:smooth; }
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:'Noto Sans SC',sans-serif; font-size:17px; line-height:1.7;
  padding-top:72px;                       /* 让位 fixed navbar */
}
a{ color:var(--teal); text-decoration:none; }
a:hover{ color:var(--stamp); }
a:focus-visible, button:focus-visible, input:focus-visible{
  outline:2px solid var(--stamp); outline-offset:2px;
}
h1,h2,h3,h4,h5{
  font-family:'Noto Serif SC',serif; font-weight:900; color:var(--ink); margin:0 0 .4em;
}
.mono{ font-family:'JetBrains Mono',monospace; }
.eyebrow{
  font-family:'JetBrains Mono',monospace; font-size:13px; letter-spacing:.12em;
  color:var(--ink-soft); text-transform:uppercase; margin:0 0 8px;
}
.container-main{ max-width:1560px; margin:0 auto; padding:40px 48px 80px; }
```

### 响应式基底

```css
@media (max-width:800px){
  body{ padding-top:108px; }        /* 移动端 navbar 换行变高 */
  .card, .well{ padding:24px 20px; }
}
```

---

## 3. 主题机制（两套风格）

### 3.1 风格切换（浅 ⇄ 深）

- 切换方式：给 **`<html>`** 加/去 `theme-dark` class（实时生效，免刷新）。
- 持久化：`localStorage['theme']` = `'light' | 'dark'`。
- 防 FOUC（`</head>` 前内联）：
  ```html
  <script>
    try{ if(localStorage.getItem('theme')==='dark'){ document.documentElement.classList.add('theme-dark'); } }catch(e){}
  </script>
  ```
- 切换后派发事件供图表重绘：
  ```js
  window.dispatchEvent(new CustomEvent('theme:changed', { detail: { isDark: nowDark } }));
  ```
- 切换按钮文案：`isDark ? '☀ 浅色风' : '🌙 深色风'`（`id="theme-toggle"`）。

### 3.2 深色 Token 覆盖（`html.theme-dark`）

```css
html.theme-dark{
  /* 深色专用 token */
  --bg-page: linear-gradient(135deg,#1C1F3B 0%,#16213E 50%,#1A1040 100%);
  --bg-card: linear-gradient(145deg,rgba(30,35,70,0.85) 0%,rgba(22,28,62,0.95) 100%);
  --text-primary:#FFFFFF;
  --text-secondary:rgba(255,255,255,0.55);
  --text-muted:rgba(255,255,255,0.55);
  --cyan:#5DE0E6; --pink:#FF6EC7; --gold:#FFB84D; --lavender:#B48CFF; --coral:#FF7B8A;
  --border-card:rgba(100,120,200,0.15);
  --radius-sm:12px; --radius-md:16px; --radius-lg:20px; --radius-xl:28px; --radius-full:9999px;

  /* 强调色（默认 cyan，由 theme-toggle.js 切换 --accent-from/--accent-to） */
  --accent-from:#5DE0E6; --accent-to:#B48CFF;

  /* 原米色 token 重映射（内联 var(--*) 自动跟随） */
  --paper:#161A33;
  --card:#1E2346;
  --ink:#FFFFFF;
  --ink-soft:rgba(255,255,255,0.55);
  --stamp:#B48CFF;
  --brass:#8B9FFF;
  --line:rgba(100,120,200,0.18);
  --teal:#5DE0E6;
  --teal-soft:rgba(93,224,230,0.10);
  --accent:#5DE0E6;
  --accent-light:rgba(93,224,230,0.12);
  --gold:#FFB84D;
}

/* 页面基底 + 顶部径向辉光 */
html.theme-dark body{
  background:var(--bg-page) !important; background-attachment:fixed !important;
  color:var(--text-primary) !important;
  font-family:'PingFang SC','SF Pro Display',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif !important;
  position:relative;
}
html.theme-dark body::before{
  content:""; position:fixed; inset:0; z-index:-1; pointer-events:none;
  background:radial-gradient(ellipse at 30% 0%, rgba(78,84,180,0.15) 0%, transparent 60%);
}

/* h1/h2 渐变文字；h3~h5 纯白 */
html.theme-dark h1, html.theme-dark h2{
  font-family:'PingFang SC','SF Pro Display',... !important;
  color:#fff !important;
  background:linear-gradient(90deg,#FFFFFF 30%,#8B9FFF 60%,#FF6EC7 100%);
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
}
html.theme-dark h3, html.theme-dark h4, html.theme-dark h5{
  color:#fff !important; -webkit-text-fill-color:#fff !important; background:none !important;
}
```

### 3.3 语义色切换器（**仅深色下挂载**）

四色定义（`theme-toggle.js`）：

| key | from | to | 色块 |
|---|---|---|---|
| `cyan`（默认） | `#5DE0E6` | `#B48CFF` | 青 |
| `pink` | `#FF6EC7` | `#B48CFF` | 粉 |
| `gold` | `#FFB84D` | `#FF6EC7` | 金 |
| `purple` | `#B48CFF` | `#5DE0E6` | 紫 |

- 写入方式：`document.documentElement.style.setProperty('--accent-from' / '--accent-to', v)`
- 持久化：`sessionStorage['_theme_accent']`
- UI：固定右下角胶囊 `#accent-switcher`，含 `.lbl`（文字「语义色」）+ 4 个 20px 圆点按钮 `[data-accent-btn]`，`.active` 加白色描边。

```css
html.theme-dark #accent-switcher{
  position:fixed; right:18px; bottom:18px; z-index:2000;
  display:flex; align-items:center; gap:8px; padding:10px 14px;
  border-radius:var(--radius-full);
  background:rgba(22,28,62,0.82); backdrop-filter:blur(12px);
  border:1px solid var(--border-card); box-shadow:0 8px 32px rgba(0,0,0,0.35);
}
html.theme-dark #accent-switcher .lbl{ font-size:12px; color:var(--text-secondary); letter-spacing:.05em; }
html.theme-dark #accent-switcher button{
  width:20px; height:20px; border-radius:50%; border:2px solid transparent;
  cursor:pointer; padding:0; transition:transform .2s ease, border-color .2s ease;
}
html.theme-dark #accent-switcher button:hover{ transform:scale(1.15); }
html.theme-dark #accent-switcher button.active{ border-color:#fff; box-shadow:0 0 0 2px rgba(255,255,255,0.25); }
```

---

## 4. 组件清单（全站复刻基线）

> 以下为**浅色**规则；深色覆盖见第 5 节。全站 11 个 Tab 复用这些组件拼装。

### 4.1 导航栏 `.navbar`

```css
.navbar{
  position:fixed; top:0; left:0; right:0; z-index:100;
  background:rgba(252,250,246,.92);
  backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
  border-bottom:1px solid var(--line);
}
.navbar .container{
  max-width:1560px; margin:0 auto; padding:14px 36px;
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;
}
.navbar-header{ display:flex; flex-direction:column; }
.navbar-brand{
  font-family:'Noto Serif SC',serif; font-weight:900; font-size:21px;
  color:var(--ink) !important; display:flex; align-items:center; gap:10px;
}
.navbar-brand::before{                    /* 圆形「招」字印章 */
  content:"招"; display:inline-flex; align-items:center; justify-content:center;
  width:34px; height:34px; border-radius:50%; flex-shrink:0;
  background:var(--accent); color:#fff;
  font-size:15px; font-weight:900; transform:rotate(-6deg);
}
.brand-tagline{
  font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:.14em;
  color:var(--ink-soft); text-transform:uppercase; margin-top:2px; margin-left:44px;
}
ul.nav.navbar-nav{ list-style:none; display:flex; gap:6px; margin:0; padding:0; flex-wrap:wrap; align-items:center; }
ul.nav.navbar-nav li a{
  color:var(--ink-soft); font-weight:500; font-size:15px;
  padding:8px 18px; border-radius:22px; display:inline-block;
  transition:.2s ease; position:relative;
}
ul.nav.navbar-nav li a:hover{ color:var(--ink); background:rgba(196,79,58,.06); }
ul.nav.navbar-nav li a.nav-active{ color:var(--accent); font-weight:700; background:var(--accent-light); }

.nav-badge{                                /* 导航收藏数量角标 */
  display:inline-flex; align-items:center; justify-content:center;
  min-width:18px; height:18px; padding:0 5px; margin-left:6px;
  background:var(--accent); color:#fff; border-radius:999px;
  font-size:11px; font-weight:700; line-height:1;
}
```

**结构**

```html
<nav class="navbar">
  <div class="container">
    <div class="navbar-header">
      <a class="navbar-brand" href="/">招聘信息实时数据分析系统</a>
      <span class="brand-tagline">让数据为求职导航</span>
    </div>
    <ul class="nav navbar-nav">
      <li><a href="/" class="nav-active">首页</a></li>
      <!-- … -->
      <li><a href="/interested">我的收藏<span class="nav-badge" id="interested-badge">3</span></a></li>
    </ul>
    <button id="theme-toggle" class="theme-toggle" type="button" title="切换页面风格（米色 / 深色）">🌗 切换风格</button>
  </div>
</nav>
```

### 4.2 卡片 `.card` / `.well`（含 `data-no` 编号角标）

```css
.card, .well{
  background:var(--card); border:1px solid var(--line); border-radius:20px;
  padding:32px 36px; position:relative; margin-bottom:12px;
  box-shadow:0 1px 4px rgba(0,0,0,.03);
}
.card[data-no]::before, .well[data-no]::before{    /* 档案编号角标 */
  content:attr(data-no); position:absolute; top:-12px; left:24px;
  background:var(--paper); padding:0 10px;
  font-family:'JetBrains Mono',monospace; font-size:12px;
  letter-spacing:.08em; color:var(--brass);
}
```

**结构**：`<div class="card" data-no="查询与采集"> … </div>`

### 4.3 印章 `.stamp`

```css
.stamp{
  display:inline-flex; align-items:center; justify-content:center;
  width:64px; height:64px; border-radius:50%; flex-shrink:0;
  border:2px solid var(--accent); color:var(--accent);
  font-family:'Noto Serif SC',serif; font-weight:900; font-size:13px;
  line-height:1.2; transform:rotate(-9deg); letter-spacing:.03em; text-align:center;
}
```

### 4.4 按钮族 `.btn`

```css
.btn{
  display:inline-flex; align-items:center; justify-content:center; gap:8px;
  font-family:'Noto Sans SC',sans-serif; font-weight:600;
  font-size:15px; padding:12px 28px; border-radius:26px; border:none;
  background:var(--card); color:var(--ink); cursor:pointer; transition:.2s ease;
  box-shadow:0 1px 3px rgba(0,0,0,.05); text-decoration:none;
}
.btn:hover{ background:var(--ink); color:var(--paper); box-shadow:0 4px 14px rgba(0,0,0,.12); }

.btn-primary{ background:var(--accent); color:#fff; }
.btn-primary:hover{ background:#A83E2E; box-shadow:0 4px 16px rgba(196,79,58,.3); }

.btn-info{ background:var(--accent); color:#fff; }      /* 向后兼容旧类名 */
.btn-info:hover{ background:#A83E2E; box-shadow:0 4px 16px rgba(196,79,58,.3); }

.btn-default{ background:var(--card); border:1.5px solid var(--line); }

.btn-outline{ background:transparent; border:1.5px solid var(--line); box-shadow:none; }
.btn-outline:hover{ background:var(--ink); color:var(--paper); border-color:var(--ink); }
```

### 4.5 收藏药丸 `.interest-btn`

```css
.interest-btn{
  border:1.5px solid #2563eb; background:transparent; color:#2563eb;
  border-radius:999px; padding:4px 12px; font-size:12px; font-weight:600;
  cursor:pointer; transition:all .2s ease; white-space:nowrap; font-family:'Noto Sans SC',sans-serif;
}
.interest-btn:hover{ background:#2563eb; color:#fff; transform:scale(1.06); }
.interest-btn.interested{
  background:#2563eb; color:#fff; border-color:#2563eb;
  box-shadow:0 4px 12px rgba(37,99,235,.3);
}
```

**结构**

```html
<button type="button" class="interest-btn interested" onclick="event.stopPropagation(); toggleInterest(id, this)">
  <span class="interest-label">已收藏</span>   <!-- 未收藏时文案「感兴趣」 -->
</button>
```

### 4.6 表单 `.form-control` / `.form-group`

```css
.form-control{
  width:100%; padding:14px 16px; border:1px solid var(--line); border-radius:12px;
  background:#fff; font-family:'Noto Sans SC',sans-serif; font-size:16px; color:var(--ink);
}
.form-control:focus{ outline:none; border-color:var(--teal); box-shadow:0 0 0 3px var(--teal-soft); }
.form-group{ margin-bottom:16px; }
.form-group label{ display:block; font-size:15px; color:var(--ink-soft); margin-bottom:8px; font-weight:600; }

.input-group{ display:flex; }
.input-group .form-control{ border-radius:12px 0 0 12px; }
.input-group-btn .btn{ border-radius:0 12px 12px 0; border-left:none; }
```

### 4.7 表格 `.table`

```css
.table{ width:100%; border-collapse:collapse; }
.table th{
  text-align:left; font-family:'JetBrains Mono',monospace; font-size:12px;
  letter-spacing:.06em; text-transform:uppercase; color:var(--ink-soft);
  border-bottom:2px solid var(--ink); padding:12px 14px;
}
.table td{ padding:14px 14px; border-bottom:1px solid var(--line); font-size:16px; }
.table-bordered td, .table-bordered th{ border:1px solid var(--line); }
.table-bordered th{ border-bottom:2px solid var(--ink); }
.table-striped tr:nth-child(even) td{ background:var(--paper); }
```

**圆角表格变体（列表页 data.html 追加）**

```css
.table { border-radius:12px; overflow:hidden; border-collapse:separate; border-spacing:0; }
.table th:first-child{ border-top-left-radius:12px; }
.table th:last-child{ border-top-right-radius:12px; }
```

### 4.8 提示条 `.alert`

```css
.alert{ padding:14px 18px; border-radius:14px; border-left:4px solid; font-size:16px; }
.alert-danger{ background:var(--accent-light); border-color:var(--accent); color:#9B3025; }
.alert-info{ background:var(--teal-soft); border-color:var(--teal); color:#1D4F42; }
```

### 4.9 已恢复徽章 `.restored-badge`

```css
.restored-badge {
  display:inline-flex; align-items:center; gap:8px;
  background:#e8f5e9; color:#2e7d32; font-size:12px; font-weight:600;
  padding:6px 14px; border-radius:3px; margin-bottom:16px;
}
.restored-badge a{ color:#c62828; text-decoration:none; font-weight:400; margin-left:4px; border-bottom:1px dashed #c62828; }
.restored-badge a:hover{ opacity:.7; }
```

### 4.10 切换风格按钮 `.theme-toggle`（两风格均可见）

```css
.theme-toggle{
  display:inline-flex; align-items:center; gap:6px;
  font-family:'Noto Sans SC',sans-serif; font-weight:600; font-size:14px;
  padding:7px 16px; border-radius:22px; cursor:pointer;
  background:transparent; border:1.5px solid var(--line); color:var(--ink-soft);
  transition:.2s ease; white-space:nowrap;
}
.theme-toggle:hover{ color:var(--ink); border-color:var(--ink); }
```

### 4.11 入场动效 `.fade-up`

```css
@media (prefers-reduced-motion: no-preference){
  .fade-up{ animation:fadeUp .6s ease both; }
  @keyframes fadeUp{ from{opacity:0; transform:translateY(14px);} to{opacity:1; transform:none;} }
}
```

### 4.12 首页功能卡 `.home-feature-*`（可复用为「入口卡 / 功能卡」）

```css
.home-feature-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:34px; }
.home-feature-card{
  background:var(--card); border:1px solid var(--line);
  border-radius:16px; padding:26px 22px 22px;
  text-decoration:none; color:var(--ink); transition:.25s ease;
  display:flex; flex-direction:column; gap:6px;
  box-shadow:0 1px 4px rgba(0,0,0,.03);
}
.home-feature-card:hover{
  transform:translateY(-5px); box-shadow:0 10px 28px rgba(0,0,0,.09); border-color:var(--accent);
}
.home-feature-card .fc-icon{ font-size:30px; line-height:1; margin-bottom:2px; }
.home-feature-card .fc-title{ font-size:17px; font-weight:700; font-family:'Noto Serif SC',serif; color:var(--ink); }
.home-feature-card .fc-desc{ font-size:13px; color:var(--ink-soft); line-height:1.55; }
.home-feature-card .fc-arrow{ display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600; color:var(--accent); margin-top:4px; transition:.2s ease; }
.home-feature-card:hover .fc-arrow{ gap:10px; }
@media (max-width:700px){ .home-feature-grid{ grid-template-columns:1fr; } }
```

### 4.13 城市级联 + 标签 `.city-row` / `.tag-chip` / `.add-city-btn`

```css
.city-row{
  display:flex; gap:10px; align-items:center; flex-wrap:wrap;
  padding:12px 14px; background:#fafafa; border:1px solid #ddd; border-radius:12px;
}
.city-row select{ font-size:15px; padding:10px 12px; border:1px solid #ccc; border-radius:10px; background:#fff; cursor:pointer; }
#provinceSelect{ flex:1.1; min-width:115px; }
#citySelect{ flex:1.4; min-width:135px; }
.add-city-btn{
  font-size:15px; font-weight:600; padding:10px 22px; border:none;
  background:var(--accent); color:#fff; border-radius:22px; cursor:pointer;
  white-space:nowrap; transition:opacity .2s;
}
.add-city-btn:hover:not(:disabled){ opacity:.85; }

.tag-chip{
  display:inline-flex; align-items:center;
  background:linear-gradient(135deg,#e8f0e9,#d4e8d0);
  color:#2a4a35; padding:7px 16px; border-radius:18px; font-size:15px; font-weight:500;
  gap:8px; box-shadow:0 1px 3px rgba(0,0,0,.07);
}
.tag-chip .tag-remove{ cursor:pointer; color:#999; font-size:16px; line-height:1; padding-left:2px; }
.tag-chip .tag-remove:hover{ color:#c33; }
```

### 4.14 列表行交互 `.data-row` / `.job-link`（整行跳详情）

```css
.job-link{ color:var(--ink); text-decoration:none; font-weight:inherit; display:inline-block; transition:color .2s ease; }
.job-link:hover{ color:#2563eb; }

.data-row{ transition:transform .25s ease, background-color .25s ease, box-shadow .25s ease; cursor:pointer; }
.data-row:hover{
  transform:translateY(-3px) scale(1.02);
  background-color:#eef2ff;
  box-shadow:0 6px 20px rgba(37,99,235,.18);
  position:relative; z-index:10;
}
.data-row:hover td{ color:#2563eb; }
.data-row:hover .job-link{ color:#2563eb; }
```

### 4.15 详情页橙色按钮 `.btn-detail`

```css
.btn-detail{
  background:linear-gradient(135deg,#FF6B35,#F7931E);
  border-color:#FF6B35; color:white;
  transition:transform .15s ease, box-shadow .15s ease, filter .15s ease;
}
.btn-detail:hover{ transform:translateY(-2px); box-shadow:0 4px 12px rgba(0,0,0,.2); filter:brightness(1.1); }
```

---

## 5. 深色覆盖要点（同名类 → Token）

> 深色下**不改 HTML**，仅用 `html.theme-dark` 作用域重映射。以下为组件级关键覆盖。

```css
/* 导航栏 */
html.theme-dark .navbar{ background:rgba(22,28,62,0.82) !important; border-bottom:1px solid var(--border-card) !important; }
html.theme-dark .navbar-brand{ color:#fff !important; }
html.theme-dark .navbar-brand::before{ background:linear-gradient(135deg,var(--accent-from),var(--accent-to)) !important; color:#0b0e1f !important; }
html.theme-dark ul.nav.navbar-nav li a{ color:var(--text-secondary) !important; }
html.theme-dark ul.nav.navbar-nav li a:hover{ color:#fff !important; background:rgba(93,224,230,0.10) !important; }
html.theme-dark ul.nav.navbar-nav li a.nav-active{ color:var(--accent-from) !important; font-weight:700 !important; background:rgba(93,224,230,0.12) !important; }

/* 卡片：bg-card 渐变 + 左侧 4px 渐变光条（::after，避开 data-no 的 ::before） */
html.theme-dark .card, html.theme-dark .well{
  background:var(--bg-card) !important;
  border:1px solid var(--border-card) !important;
  border-radius:var(--radius-lg) !important;
  box-shadow:0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04) !important;
  color:var(--text-primary) !important;
  transition:transform .25s cubic-bezier(.4,0,.2,1), box-shadow .25s cubic-bezier(.4,0,.2,1);
}
html.theme-dark .card::after, html.theme-dark .well::after{
  content:""; position:absolute; left:0; top:20%; bottom:20%;
  width:4px; border-radius:0 4px 4px 0;
  background:linear-gradient(180deg,var(--accent-from) 0%,var(--accent-to) 100%);
  box-shadow:0 0 12px rgba(93,224,230,0.25);
}
html.theme-dark .card[data-no]::before{ background:var(--paper) !important; color:var(--brass) !important; }
html.theme-dark .card:hover{ transform:translateY(-2px); box-shadow:0 8px 40px rgba(93,224,230,0.12), inset 0 1px 0 rgba(255,255,255,0.04) !important; }

/* 按钮 */
html.theme-dark .btn{
  background:rgba(30,35,70,0.85) !important; color:#fff !important;
  border:1px solid var(--border-card) !important; border-radius:var(--radius-full) !important;
}
html.theme-dark .btn:hover{ background:rgba(93,224,230,0.16) !important; color:#fff !important; }
html.theme-dark .btn-primary, html.theme-dark .btn-info{
  background:linear-gradient(135deg,var(--accent-from),var(--accent-to)) !important;
  color:#0b0e1f !important; border:none !important;
}
html.theme-dark .btn-primary:hover, html.theme-dark .btn-info:hover{ filter:brightness(1.08); box-shadow:0 8px 40px rgba(93,224,230,0.2) !important; }
html.theme-dark .btn-outline{ background:transparent !important; border:1.5px solid var(--border-card) !important; color:var(--text-primary) !important; }
html.theme-dark .btn-outline:hover{ background:rgba(93,224,230,0.12) !important; }

/* 收藏药丸 → 青描边 */
html.theme-dark .interest-btn{ border:1.5px solid var(--cyan) !important; color:var(--cyan) !important; border-radius:var(--radius-full) !important; }
html.theme-dark .interest-btn:hover{ background:var(--cyan) !important; color:#0b0e1f !important; }
html.theme-dark .interest-btn.interested{ background:var(--cyan) !important; color:#0b0e1f !important; border-color:var(--cyan) !important; }

/* 表单 */
html.theme-dark .form-control{
  background:rgba(15,18,40,0.6) !important; border:1px solid var(--border-card) !important;
  color:#fff !important; border-radius:var(--radius-sm) !important;
}
html.theme-dark .form-control:focus{ border-color:var(--cyan) !important; box-shadow:0 0 0 3px rgba(93,224,230,0.18) !important; }
html.theme-dark .form-group label{ color:var(--text-secondary) !important; }

/* 表格 */
html.theme-dark .table th{ color:var(--text-secondary) !important; border-bottom:2px solid rgba(255,255,255,0.25) !important; }
html.theme-dark .table td{ color:var(--text-primary) !important; border-bottom:1px solid var(--border-card) !important; }
html.theme-dark .table-striped tr:nth-child(even) td{ background:rgba(255,255,255,0.03) !important; }
html.theme-dark .table tbody tr{ transition:background-color .2s ease, transform .2s ease; }

/* 行交互（字面蓝 → token 青） */
html.theme-dark .data-row:hover{ background-color:rgba(93,224,230,0.08) !important; box-shadow:0 6px 20px rgba(93,224,230,0.18) !important; }
html.theme-dark .data-row:hover td{ color:var(--cyan) !important; }
html.theme-dark .data-row:hover .job-link{ color:var(--cyan) !important; }
html.theme-dark .job-link{ color:var(--text-primary) !important; }
html.theme-dark .job-link:hover{ color:var(--cyan) !important; }

/* 提示 / 徽章 */
html.theme-dark .alert{ background:rgba(30,35,70,0.85) !important; color:var(--text-primary) !important; border-left:4px solid var(--cyan) !important; }
html.theme-dark .alert-danger{ border-left-color:var(--coral) !important; }
html.theme-dark .alert-info{ border-left-color:var(--cyan) !important; }
html.theme-dark .eyebrow{ color:var(--text-secondary) !important; }
html.theme-dark .mono{ font-family:'JetBrains Mono',monospace; color:var(--cyan) !important; }

/* 首页组件 */
html.theme-dark .home-hero h1{ font-size:40px !important; letter-spacing:-0.5px !important; line-height:1.2 !important; font-weight:700 !important; }
html.theme-dark .home-hero .subtitle{ color:var(--text-secondary) !important; }
html.theme-dark .city-row{ background:rgba(15,18,40,0.6) !important; border:1px solid var(--border-card) !important; border-radius:var(--radius-sm) !important; }
html.theme-dark .city-row select{ background:rgba(30,35,70,0.9) !important; color:#fff !important; border:1px solid var(--border-card) !important; border-radius:10px !important; }
html.theme-dark .add-city-btn{ background:linear-gradient(135deg,var(--accent-from),var(--accent-to)) !important; color:#0b0e1f !important; border-radius:var(--radius-full) !important; }
html.theme-dark .tag-chip{ background:rgba(93,224,230,0.10) !important; color:var(--cyan) !important; border-radius:var(--radius-full) !important; }
html.theme-dark .home-feature-card{
  background:var(--bg-card) !important; border:1px solid var(--border-card) !important;
  border-radius:var(--radius-md) !important; color:var(--text-primary) !important;
  box-shadow:0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04) !important;
  position:relative; overflow:hidden;
}
html.theme-dark .home-feature-card::before{
  content:""; position:absolute; left:0; top:20%; bottom:20%; width:4px; border-radius:0 4px 4px 0;
  background:linear-gradient(180deg,var(--accent-from),var(--accent-to));
}
html.theme-dark .home-feature-card:hover{ transform:translateY(-5px) !important; border-color:var(--accent-from) !important; }

/* 详情按钮 */
html.theme-dark .btn-detail{ background:linear-gradient(135deg,var(--accent-from),var(--accent-to)) !important; color:#0b0e1f !important; border:none !important; border-radius:var(--radius-full) !important; }

/* 切换按钮 */
html.theme-dark .theme-toggle{ border-color:var(--border-card); color:var(--text-secondary); }
html.theme-dark .theme-toggle:hover{ color:#fff; border-color:var(--cyan); }
```

---

## 6. 页面骨架（DOM + 原文案）

### 6.1 采集首页（input.html）

```html
<div class="home-wrap fade-up">
  <div class="home-hero">
    <p class="eyebrow">招聘市场数据分析</p>
    <h1>招聘信息实时数据分析系统</h1>
    <p class="subtitle">一站式查看岗位分布、薪资水平与技能需求，为你的求职决策提供数据支撑</p>
  </div>

  <div class="card home-card fade-up" data-no="查询与采集">
    <form id="mainForm">
      <div class="form-group">
        <label>岗位名称（支持关键词搜索，非精确匹配）</label>
        <input type="text" class="form-control" name="kw" placeholder="python 开发工程师" autofocus>
      </div>

      <div class="form-group">
        <label>选择城市（可选，不选则全国范围搜索）</label>
        <div class="city-row">
          <select id="provinceSelect"><option value="">← 选择省份</option></select>
          <span style="color:#bbb; font-size:18px; user-select:none;">›</span>
          <select id="citySelect" disabled><option value="">先选省份 →</option></select>
          <button type="button" id="addCityBtn" disabled class="add-city-btn">＋ 添加城市</button>
        </div>
        <div id="selectedCitiesWrap" style="margin-top:10px; display:none;">
          <div style="font-size:14px; color:#999; margin-bottom:8px;">已选城市：</div>
          <div id="selectedCities" style="display:flex; flex-wrap:wrap; gap:8px;"></div>
        </div>
        <input type="hidden" name="city" id="cityHidden">
      </div>

      <div style="display:flex; gap:14px; flex-wrap:wrap;">
        <div class="form-group" style="flex:1; min-width:170px;">
          <label>排序方式（仅"立即实时采集"生效）</label>
          <select class="form-control" name="sort_type" style="font-size:15px;">
            <option value="0">按相关性排序</option>
            <option value="1">最新发布</option>
          </select>
        </div>
        <div class="form-group" style="flex:1; min-width:170px;">
          <label>实时采集页数（仅"立即实时采集"生效，1~5）</label>
          <input type="number" class="form-control" name="pages" value="2" min="1" max="5" style="font-size:15px;">
        </div>
      </div>

      <div style="display:flex; gap:10px; margin-top:4px;">
        <button type="submit" formaction="/list" formmethod="get"
                class="btn btn-default" style="flex:1; padding:12px; font-size:15px;">查询已有数据</button>
        <button type="submit" formaction="/collect" formmethod="post"
                class="btn btn-info" style="flex:1; padding:12px; font-size:15px;">立即实时采集</button>
      </div>
      <p style="color:var(--ink-soft); font-size:13px; margin-top:10px; margin-bottom:0; line-height:1.5;">
        查询已有数据：浏览已收录的岗位信息；实时采集：获取 51job 最新招聘数据（更新前会清空旧记录）。
      </p>
    </form>
  </div>

  <div class="home-feature-grid fade-up">
    <a href="/chart/city" class="home-feature-card">
      <div class="fc-icon">📊</div>
      <div class="fc-title">图表分析</div>
      <div class="fc-desc">城市分布、薪资区间、学历经验占比……多维度数据一图尽览</div>
      <span class="fc-arrow">查看图表 →</span>
    </a>
    <!-- 同构：🎯 薪资洞察 / 💬 智能助手 -->
  </div>
</div>
```

**城市级联交互**：`provinceSelect` → `citySelect` → `＋ 添加城市` → `tag-chip`（含 SVG 定位图标 + `×` 删除）→ 写入隐藏 `cityHidden`（城市名逗号拼接）。

### 6.2 岗位列表页（data.html）

```html
<p class="eyebrow">数据展示</p>
<h2 style="margin-bottom:18px;">招聘数据档案</h2>

<form method="get" action="/list" style="margin-bottom:20px;">
  <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end;">
    <div class="form-group" style="flex:1; min-width:200px; margin-bottom:0;">
      <label>岗位名称</label>
      <input type="text" class="form-control" name="kw" value="{{ kw }}" placeholder="如: python开发工程师">
    </div>
    <div class="form-group" style="flex:1; min-width:180px; margin-bottom:0;">
      <label>城市</label>
      <input type="text" class="form-control" name="city" value="{{ city }}" placeholder="如: 北京,上海">
    </div>
    <button class="btn btn-info" type="submit" style="padding:12px 32px;">🔍 搜索</button>
  </div>
  <p style="margin:6px 0 0 0; font-size:13px; color:var(--ink-soft);">精确匹配，请输入完整岗位名称或城市</p>
</form>

<div class="card" data-no="共 {{ total }} 条记录">
  <table class="table table-bordered table-striped">
    <tr>
      <th>职位</th><th>公司</th><th>城市</th><th>最低薪资(千元)</th><th>最高薪资(千元)</th><th>发布时间</th><th>感兴趣</th>
    </tr>
    <tr class="data-row" onclick="window.location='/job_detail/{id}'">
      <td><a href="/job_detail/{id}" class="job-link">{{ 职位名 }}</a></td>
      <td>{{ 公司 or '-' }}</td>
      <td>{{ 城市 }}</td>
      <td class="mono">{{ 最低薪 }}</td>
      <td class="mono">{{ 最高薪 }}</td>
      <td>{{ 发布时间 }}</td>
      <td>
        <button type="button" class="interest-btn" onclick="event.stopPropagation(); toggleInterest(id, this)">
          <span class="interest-label">感兴趣</span>
        </button>
      </td>
    </tr>
  </table>
  <!-- 空态 -->
  <p style="color:var(--ink-soft); text-align:center; padding:30px 0; margin:0;">
    没有找到匹配的记录,换个关键词试试,比如"爬虫"或"杭州"。
  </p>
</div>

<div style="text-align:center; margin:24px 0;">
  <a href="/list?page=N-1" class="btn btn-default">← 上一页</a>
  <span class="mono" style="margin:0 16px; color:var(--ink-soft); font-size:14px;">第 {{ page }} / {{ total_pages }} 页</span>
  <a href="/list?page=N+1" class="btn btn-default">下一页 →</a>
</div>
```

**关键交互**：整行 `.data-row` 点击跳详情；收藏按钮 `event.stopPropagation()` 阻止冒泡。

### 6.3 岗位详情页（job_detail.html）

```html
<p class="eyebrow">岗位详情</p>
<h2 style="margin-bottom:18px;">职位档案详情</h2>

<div class="card" style="border-left: 4px solid var(--teal);">
  <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:20px; flex-wrap:wrap; gap:12px;">
    <div>
      <h3 style="margin:0 0 8px 0; color:var(--ink); font-size:22px;">{{ 职位名 }}</h3>
      <p style="margin:0; color:var(--ink-soft); font-size:15px;">
        <span style="margin-right:16px;">🏢 {{ 公司 or '未披露' }}</span>
        <span>📍 {{ 地址 }}</span>
      </p>
    </div>
    <div style="display:flex; gap:8px; flex-wrap:wrap;">
      <a href="/list" class="btn btn-default" style="text-decoration:none; font-size:14px;">← 返回列表</a>
      <button type="button" class="interest-btn" onclick="toggleInterest(id, this)">
        <span class="interest-label">感兴趣</span>
      </button>
      <a href="{{ job_url }}" target="_blank" class="btn btn-info btn-detail" style="text-decoration:none; font-size:14px;">🔗 查看详情</a>
    </div>
  </div>

  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:16px; margin-bottom:24px; padding:16px; background:var(--paper); border-radius:12px;">
    <div>
      <div style="font-size:13px; color:var(--ink-soft); margin-bottom:4px;">薪资范围</div>
      <div style="font-size:20px; font-weight:700; color:var(--teal);" class="mono">{{ min }}-{{ max }}K</div>
    </div>
    <div><div style="font-size:13px; color:var(--ink-soft); margin-bottom:4px;">学历要求</div>
         <div style="font-size:16px; font-weight:600;">{{ edu or '不限' }}</div></div>
    <div><div style="font-size:13px; color:var(--ink-soft); margin-bottom:4px;">经验要求</div>
         <div style="font-size:16px; font-weight:600;">{{ exper or '不限' }}</div></div>
    <div><div style="font-size:13px; color:var(--ink-soft); margin-bottom:4px;">发布时间</div>
         <div style="font-size:15px;">{{ dateT or '未知' }}</div></div>
  </div>

  <div>
    <h4 style="margin:0 0 12px 0; font-size:18px; color:var(--ink);">职位描述</h4>
    <div style="padding:16px; background:var(--paper); border-radius:12px; line-height:1.8; white-space:pre-wrap; font-size:15px; color:var(--ink); max-height:400px; overflow-y:auto;">
      {{ content }}
    </div>
  </div>
</div>
```

### 6.4 采集结果页（collect.html）

```html
<p class="eyebrow">实时采集结果</p>
<h2 style="margin-bottom:20px; font-size:30px;">采集结果</h2>

<div class="restored-badge">已恢复上次采集结果 <a href="/collect?clear_collect=1" title="清除采集结果">清除</a></div>
<div class="alert alert-danger">{{ error }}</div>
<div class="alert alert-info">
  采集完成: 关键词"{{ keyword }}" · 城市"{{ city }}", 共抓到 {{ total_count }} 条, 成功写入数据库 <span class="mono">{{ success_count }}</span> 条（已更新最新数据）。
  <br><small style="color:#666;">各城市翻页情况（目标 {{ pages_per_city }} 页/城）：上海: 2 页 · 北京: 2 页</small>
  <br><a href="/list?kw=...&city=...">查看刚采集的数据 →</a> · <a href="/chart">查看更新后的图表 →</a>
</div>

<a href="/" class="btn btn-default" style="margin-top:20px;">← 返回首页继续查询/采集</a>
```

---

## 7. 复刻检查清单（逐项核对用）

- [ ] 字体三件套（Noto Serif SC / Noto Sans SC / JetBrains Mono）已引入且分工正确
- [ ] `:root` 12 个米色 Token 完全一致
- [ ] `body` 底色 `--paper`、正文字号 17px、行高 1.7、`padding-top:72px`
- [ ] `.card` 圆角 20px、`data-no` 角标（JetBrains Mono 12px、黄铜色、`top:-12px`）
- [ ] `.btn` 圆角 26px、`.btn-primary/.btn-info` 印章红 `#C44F3A`、hover `#A83E2E`
- [ ] `.table th` JetBrains Mono 大写 + `border-bottom:2px solid var(--ink)`
- [ ] `.data-row:hover` 上浮 `translateY(-3px) scale(1.02)` + 蓝底 `#eef2ff` + 文字 `#2563eb`
- [ ] `.interest-btn` 蓝色描边药丸 `#2563eb`，`.interested` 实心
- [ ] `.eyebrow` JetBrains Mono 13px、`letter-spacing:.12em`、大写
- [ ] `.stamp` 64px 圆形、`rotate(-9deg)`、2px 印章红描边
- [ ] 主题切换：`html.theme-dark` + `localStorage['theme']` + 防 FOUC 内联脚本
- [ ] 语义色切换器仅深色挂载，写入 `--accent-from/--accent-to`，`sessionStorage['_theme_accent']`
- [ ] 深色卡片左侧 4px 渐变光条（用 `::after`，不与 `data-no` 的 `::before` 冲突）
- [ ] `prefers-reduced-motion` 动效降级
