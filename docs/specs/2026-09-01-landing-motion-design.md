# 落地页秀场动效改版设计稿（v8.7，已落地）

> 2026-09-01。参考对象：[`MengTo/threeui`](https://github.com/MengTo/threeui)（React + Three.js 的 WebGL shader 视觉组件库）。本文是 v8.7 的设计依据与决策记录，实现口径以 CHANGELOG v8.7 为准。

---

## 1. 目标与边界

- **目标**：把 `landing.html`（后端 `/` 返回的独立产品落地页）改造成「动效十足」的秀场页，核心诉求是**大量留白**——元素之间多留空、信息密度压低、不把页面塞满。
- **范围**：只改 landing 落地页。主应用 index.html 及其 JS 一行不动，后端零改动。
- **风格边界**：拉满秀场感（逐字揭示 / 磁性按钮 / 3D 倾斜 / 多层视差 / WebGL 流动墨晕），但**不碰**霓虹辉光、弹跳缓动、粒子爆炸——与 DC-09 专业评测气质保持一致。

## 2. 关键决策记录

| 决策点 | 选项 | 结论 | 理由 |
|---|---|---|---|
| 技术路线 | 纯 CSS / 手写 WebGL / three.js | **three.js**（用户显式选择） | 最接近 threeui 原作观感；代价 735KB min / 190KB gzip，经动态 `import()` 拆为 async chunk，首屏渲染后才拉取，主应用包不受影响 |
| 对 v8.5 决策的覆盖 | v8.5 记录「不引 three.js、不做 shader 实时背景」 | **被用户显式覆盖，仅限 landing 入口** | 落地页是对外展示面，与主应用的工程纪律可以分别定档；CHANGELOG v8.7 已登记 |
| 场景形态 | 3D 几何场景 / 全屏 fragment shader | **shader** | threeui 的标志性观感来自全屏 fragment shader；一次 draw call、无资产加载，比几何场景便宜一个数量级 |
| 色板 | 新色板 / 沿用纸墨印章 | **沿用**（v7.1 基线不动） | shader 三个色源直接取 --stamp / --brass / --teal，底色 --slate-900，与全站同一枚印章 |

## 3. 区块设计（自上而下四区块）

1. **Hero（满屏深墨，`calc(100vh - 56px)`）**：WebGL 流动墨晕铺满背景；eyebrow（JetBrains Mono 大写字距）→ `--text-display-1` 超大衬线标题（逐字揭示，「拿 Offer」朱砂 accent）→ 副标题 / 描述 → 两枚磁性 CTA → 底部滚动提示线。内容极少量大，四周留足呼吸空间。
2. **五步主线（纵向时间线）**：区块标题居中先行；中轴细线随滚动「描边生长」（`scaleY(--tl-p)`，黄铜→朱砂渐变）；五个节点左右交替，圆形序号章（壹-伍）骑跨中轴，节点间距 64px+，每屏最多完整呈现一个节点。720px 以下中轴移到左缘 20px，节点全部排在右侧（沿用 v8.2 既有的窄屏纵向模式）。
3. **核心能力（疏朗 2 列大卡）**：六张卡 2 列排布，gap 32px，hover 3D 倾斜（±7deg）+ 顶部高光跟随 + 景深阴影加深。
4. **页脚 CTA（大留白收束）**：居中一句话 + 一枚主按钮，上下留白 128px+，底部 2px 黄铜线与 Hero 顶线首尾呼应。

## 4. 留白与排版 token（tokens.css 只新增）

| token | 值 | 用途 |
|---|---|---|
| `--space-9 / 10 / 11` | 96 / 128 / 160px | 区块间距、页脚大留白 |
| `--text-display-1` | clamp(42px, 7.2vw, 84px) | Hero 主标题 |
| `--text-display-2` | clamp(30px, 4.2vw, 44px) | 区块标题 |
| `--text-display-3` | clamp(19px, 2.2vw, 24px) | Hero 副标题 |
| `--ld-hero-bg` | 浅色 #171A18 / 深色 #101310 | Hero 恒为深墨底（两主题不变浅，landing.css 头部纪律③） |

## 5. 动效清单（全部挂 prefers-reduced-motion 降级）

| 动效 | 实现 | 关键参数 |
|---|---|---|
| WebGL 流动墨晕 | three.js 全屏三角形 + fbm fragment shader | 桌面 5 octaves / 移动 3；uTime 速率 0.028（约 36s 周期）；pixelRatio ≤ 1.5 |
| 逐字标题揭示 | JS splitChars → `.ld-char` + `--ci` 错峰 | 40ms/字，640ms，上移 0.42em + 旋转 4deg + 模糊消散 |
| 磁性按钮 | pointermove 吸附 + lerp 归位 | 强度 0.28，钳 ±12px，仅 pointer:fine |
| 卡片 3D 倾斜 | normPointer → tiltAngles lerp | perspective 900px，±7deg，高光 --mx/--my 跟随 |
| 时间线描边生长 | ::after scaleY(--tl-p)，scroll rAF 驱动 | 视口 72% 线为生长起止，origin top |
| Hero 视差淡出 | scroll rAF，transform/opacity | 0.16 速率下沉，70% 高度线性淡出 |
| IO 滚动揭示 | .ld-reveal 渐进增强（JS 挂 .ld-js 才隐藏） | threshold 0.12，rootMargin -6% |

## 6. 降级链（任何一环失效都不致命）

1. `prefers-reduced-motion` → DOM 动效全部关闭；时间线直接长满；shader 渲一帧静态（uTime=12）后停摆；滚动提示隐藏。
2. three chunk 加载失败 / WebGL 上下文创建失败 / `webglcontextlost` → canvas 透明，露出 `.ld-hero::before` 的 CSS 径向墨晕（**永久 fallback 层，不可删**）。
3. landing.js 整体未加载 → 页面内容默认可见（不出现 opacity:0 死页）；仅主题切换与动效失效。
4. 移动端 → octaves 降为 3、pixelRatio 封顶、滚动提示隐藏。

## 7. 性能预算

- 每帧成本：1 次全屏 shader draw call；渲染循环只在 Hero 可见（IO threshold 0.02）且页面前台时运行。
- DOM 动效全走 transform/opacity（合成层）；scroll 监听 passive + rAF 节流；lerp 循环无任务自动停摆。
- 包体：landing 入口本体 <10KB；three async chunk 735KB（190KB gzip）仅首屏后拉取；vite `chunkSizeWarningLimit` 提至 800 并注释说明。

## 8. 已修复的关联 bug（实现过程中实测发现）

- 深色模式 Hero 变白底（--slate-800/900 深色被重映射为纸白，v8.2 起即有）→ 新增 `--ld-hero-bg` 专用 token。
- 深色 h1 渐变文字（background-clip:text）与逐字 span 冲突渲染成白色色块 → 深色下 Hero 标题禁用渐变文字。
- 窄屏「拿 Offer」断成「拿Of/fer」→ accent 段 `white-space: nowrap`。

## 9. 验证记录

- `frontend/tests/landing.test.js` 25 例（纯函数钳制逻辑）；vitest 全量 77 passed；`npm run build` 零告警；`pytest tests/test_repo_hygiene.py -q` 5 passed。
- playwright 真机截图：桌面浅/深双主题 + 390px 移动端，逐区块核对，控制台 0 错误 0 警告。
