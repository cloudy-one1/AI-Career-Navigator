/* ===================================================
   landing.js — v8.6 落地页动效总编排（仅 landing.html 使用）
   ---------------------------------------------------
   职责划分：
   - DOM 动效（同步执行）：逐字揭示 / IO 滚动揭示 / 磁性按钮 /
     3D 倾斜卡 / Hero 视差 / 时间线滚动描边 / 主题切换；
   - WebGL Hero（异步）：动态 import('three') 拆 chunk，fbm
     流动墨晕 shader，IO 控制渲染循环启停。

   降级链（任何一环失效都不致命）：
   1. prefers-reduced-motion → 全部 DOM 动效关闭，shader 渲一帧静态；
   2. three chunk 加载失败 / WebGL 上下文创建失败 / contextlost
      → canvas 保持透明，露出 .ld-hero::before 的 CSS 径向墨晕；
   3. 本文件整体加载失败 → 页面内容默认可见（.ld-reveal 不挂 .ld-js
      就不会隐藏），仅主题切换失效。

   测试纪律：本文件顶部是纯函数区（DOM 无关，vitest node 环境直接
   导入覆盖）；底部 boot() 仅在真实浏览器且存在 #ld-page 时执行。
   =================================================== */

/* ══════════════════════════════════════════════════
   1. 纯函数区（DOM 无关，landing.test.js 覆盖）
   ══════════════════════════════════════════════════ */

export function clampNum(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

/**
 * 逐字拆分：把一段文本拆成带全局字序的字符条目。
 * Array.from 按码点遍历，代理对（emoji 等）不会被拆散。
 * @param {string} text
 * @param {number} offset 全局字序起始值（跨嵌套元素累计）
 * @returns {{ch: string, ci: number}[]}
 */
export function charEntries(text, offset = 0) {
  if (!text) return [];
  return Array.from(text).map((ch, i) => ({ ch, ci: offset + i }));
}

/**
 * 磁性按钮偏移：指针相对按钮中心的位移按强度吸附，并钳制最大距离。
 * @returns {{x: number, y: number}}
 */
export function magneticOffset(px, py, cx, cy, strength = 0.28, maxDist = 12) {
  return {
    x: clampNum((px - cx) * strength, -maxDist, maxDist),
    y: clampNum((py - cy) * strength, -maxDist, maxDist),
  };
}

/** 指针坐标 → 元素内归一化坐标（中心为 0，边界 ±1，越界钳制） */
export function normPointer(px, py, rect) {
  const nx = rect.width > 0 ? ((px - rect.left) / rect.width) * 2 - 1 : 0;
  const ny = rect.height > 0 ? ((py - rect.top) / rect.height) * 2 - 1 : 0;
  return { nx: clampNum(nx, -1, 1), ny: clampNum(ny, -1, 1) };
}

/**
 * 3D 倾斜角：归一化指针 → rotateX/rotateY 角度。
 * 指针上移（ny<0）卡片顶部前倾（rx>0），左移（nx<0）左缘前倾（ry<0）。
 */
export function tiltAngles(nx, ny, maxDeg = 7) {
  // 归一化 -0：-ny 在 ny 为 +0 时产出 -0，数值上等于 0，
  // 但深比较与快照序列化会把 -0 当成另一个值
  const nz = (v) => (v === 0 ? 0 : v);
  return {
    rx: nz(clampNum(-ny * maxDeg, -maxDeg, maxDeg)),
    ry: nz(clampNum(nx * maxDeg, -maxDeg, maxDeg)),
  };
}

/**
 * 时间线描边进度：区块顶部越过视口 72% 线时开始生长，
 * 区块底部到达视口 72% 线时长满。返回 0~1。
 */
export function timelineProgress(viewportH, rectTop, rectHeight) {
  if (rectHeight <= 0) return 1;
  return clampNum((viewportH * 0.72 - rectTop) / rectHeight, 0, 1);
}

/** Hero 内容视差：滚动距离 × 系数，仅下沉不抬升 */
export function parallaxShift(scrollY, factor) {
  return Math.max(0, scrollY) * clampNum(factor, 0, 1);
}

/** Hero 内容淡出：滚动经过 Hero 高度的 0~70% 时透明度 1→0 */
export function heroFade(scrollY, heroH) {
  if (heroH <= 0) return 0;
  return 1 - clampNum(scrollY / (heroH * 0.7), 0, 1);
}

/* ══════════════════════════════════════════════════
   2. 浏览器环境守卫（node 测试环境导入时不执行任何 DOM 代码）
   ══════════════════════════════════════════════════ */

const HAS_DOM = typeof window !== 'undefined' && typeof document !== 'undefined';

function mq(query) {
  if (!HAS_DOM || typeof window.matchMedia !== 'function') {
    return { matches: false, addEventListener() {}, removeEventListener() {} };
  }
  return window.matchMedia(query);
}

const REDUCED = mq('(prefers-reduced-motion: reduce)');
const FINE_POINTER = mq('(pointer: fine)');

/** 共享 rAF 循环：各交互模块注册 lerp 任务，无任务时自动停摆 */
function createLerpLoop() {
  const tasks = new Set();
  let rafId = 0;
  function tick() {
    tasks.forEach((fn) => fn());
    rafId = tasks.size ? requestAnimationFrame(tick) : 0;
  }
  return {
    add(fn) {
      tasks.add(fn);
      if (!rafId) rafId = requestAnimationFrame(tick);
    },
    remove(fn) {
      tasks.delete(fn);
    },
  };
}

/* ══════════════════════════════════════════════════
   3. 主题切换（v8.5 前在 landing.html 内联，v8.6 迁移至此）
   ══════════════════════════════════════════════════ */

function initThemeToggle() {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const root = document.documentElement;
  const updateLabel = () => {
    btn.textContent = root.classList.contains('theme-dark') ? '☀️ 浅色风' : '🌙 深色风';
  };
  btn.addEventListener('click', () => {
    root.classList.toggle('theme-dark');
    try {
      localStorage.setItem('theme', root.classList.contains('theme-dark') ? 'dark' : 'light');
    } catch (e) { /* 隐私模式写入失败无碍功能 */ }
    updateLabel();
  });
  updateLabel();
}

/* ══════════════════════════════════════════════════
   4. 逐字标题揭示
   ---------------------------------------------------
   遍历标题的子节点：文本节点逐字包 .ld-char；元素节点
   （如 .ld-hero-accent）递归处理以保留其配色。原始文本
   写入 aria-label，字 spans 对读屏隐藏。
   ══════════════════════════════════════════════════ */

function splitChars(el) {
  const original = el.textContent || '';
  if (!original.trim()) return 0;
  el.setAttribute('aria-label', original);
  let count = 0;

  function wrap(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const entries = charEntries(node.nodeValue, count);
      if (!entries.length) return;
      const frag = document.createDocumentFragment();
      entries.forEach(({ ch, ci }) => {
        const span = document.createElement('span');
        span.className = 'ld-char';
        span.setAttribute('aria-hidden', 'true');
        span.style.setProperty('--ci', String(ci));
        span.textContent = ch;
        frag.appendChild(span);
      });
      count += entries.length;
      node.parentNode.replaceChild(frag, node);
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      Array.from(node.childNodes).forEach(wrap);
    }
  }

  Array.from(el.childNodes).forEach(wrap);
  return count;
}

function initSplit() {
  if (REDUCED.matches) return; // 降级：不拆分，标题整句直接可见
  const el = document.querySelector('[data-split]');
  if (el) splitChars(el);
}

/* ══════════════════════════════════════════════════
   5. IO 滚动揭示（渐进增强：JS 挂 .ld-js 才启用隐藏入场）
   ══════════════════════════════════════════════════ */

function initReveal() {
  const items = document.querySelectorAll('.ld-reveal');
  if (!items.length || REDUCED.matches || !('IntersectionObserver' in window)) return;
  items.forEach((el) => el.classList.add('ld-js'));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  items.forEach((el) => io.observe(el));
}

/* ══════════════════════════════════════════════════
   6. 磁性按钮（指针吸附 + 离开归位，lerp 平滑）
   ══════════════════════════════════════════════════ */

function initMagnetic() {
  if (REDUCED.matches || !FINE_POINTER.matches) return;
  const loop = createLerpLoop();
  document.querySelectorAll('[data-magnetic]').forEach((el) => {
    let tx = 0, ty = 0, cx = 0, cy = 0, active = false;
    const apply = () => {
      cx += (tx - cx) * 0.16;
      cy += (ty - cy) * 0.16;
      el.style.transform = `translate3d(${cx.toFixed(2)}px, ${cy.toFixed(2)}px, 0)`;
      if (!active && Math.abs(cx) < 0.1 && Math.abs(cy) < 0.1) {
        el.style.transform = '';
        loop.remove(apply);
      }
    };
    el.addEventListener('pointermove', (e) => {
      const rect = el.getBoundingClientRect();
      const off = magneticOffset(e.clientX, e.clientY, rect.left + rect.width / 2, rect.top + rect.height / 2);
      tx = off.x; ty = off.y; active = true;
      loop.add(apply);
    });
    el.addEventListener('pointerleave', () => {
      tx = 0; ty = 0; active = false;
      loop.add(apply);
    });
  });
}

/* ══════════════════════════════════════════════════
   7. 卡片 3D 倾斜 + 高光跟随（--mx/--my 供 ::before 径向渐变定位）
   ══════════════════════════════════════════════════ */

function initTilt() {
  if (REDUCED.matches || !FINE_POINTER.matches) return;
  const loop = createLerpLoop();
  document.querySelectorAll('[data-tilt]').forEach((el) => {
    let tRx = 0, tRy = 0, rx = 0, ry = 0, hovering = false;
    const apply = () => {
      rx += (tRx - rx) * 0.14;
      ry += (tRy - ry) * 0.14;
      el.style.transform = `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`;
      if (!hovering && Math.abs(rx) < 0.05 && Math.abs(ry) < 0.05) {
        el.style.transform = '';
        loop.remove(apply);
      }
    };
    el.addEventListener('pointermove', (e) => {
      const rect = el.getBoundingClientRect();
      const { nx, ny } = normPointer(e.clientX, e.clientY, rect);
      const angles = tiltAngles(nx, ny);
      tRx = angles.rx; tRy = angles.ry; hovering = true;
      el.style.setProperty('--mx', `${(((nx + 1) / 2) * 100).toFixed(1)}%`);
      el.style.setProperty('--my', `${(((ny + 1) / 2) * 100).toFixed(1)}%`);
      loop.add(apply);
    });
    el.addEventListener('pointerleave', () => {
      tRx = 0; tRy = 0; hovering = false;
      loop.add(apply);
    });
  });
}

/* ══════════════════════════════════════════════════
   8. Hero 视差 + 时间线滚动描边（共享一个 scroll 被动监听）
   ══════════════════════════════════════════════════ */

function initScrollFX() {
  const heroInner = document.querySelector('[data-parallax]');
  const hero = document.getElementById('ld-hero');
  const timeline = document.getElementById('ld-timeline');
  if (REDUCED.matches) {
    // 降级：时间线直接长满，不做滚动联动
    if (timeline) timeline.style.setProperty('--tl-p', '1');
    return;
  }
  if (!heroInner && !timeline) return;

  let ticking = false;
  const update = () => {
    ticking = false;
    const vh = window.innerHeight;
    if (hero && heroInner) {
      const heroH = hero.offsetHeight;
      const y = window.scrollY || 0;
      if (y <= heroH) {
        const factor = parseFloat(heroInner.dataset.parallax || '0.16');
        heroInner.style.transform = `translate3d(0, ${parallaxShift(y, factor).toFixed(1)}px, 0)`;
        heroInner.style.opacity = heroFade(y, heroH).toFixed(3);
      }
    }
    if (timeline) {
      const rect = timeline.getBoundingClientRect();
      timeline.style.setProperty('--tl-p', timelineProgress(vh, rect.top, rect.height).toFixed(4));
    }
  };
  const onScroll = () => {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(update);
    }
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  update();
}

/* ══════════════════════════════════════════════════
   9. WebGL Hero：three.js fbm 流动墨晕
   ---------------------------------------------------
   观感目标：「呼吸的墨」——印章红 / 黄铜 / 青绿在墨黑底上
   以 30s+ 周期缓慢流动，随指针轻微视差。色值取自 tokens.css
   的纸墨色板（--slate-900 / --stamp / --brass / --teal）。
   ══════════════════════════════════════════════════ */

const HERO_FRAG = /* glsl */ `
precision highp float;
uniform float uTime;
uniform vec2 uRes;
uniform vec2 uPointer;
uniform int uOctaves;
uniform vec3 uInk;
uniform vec3 uStamp;
uniform vec3 uBrass;
uniform vec3 uTeal;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 6; i++) {
    if (i >= uOctaves) break;
    v += a * noise(p);
    p = p * 2.03 + vec2(11.3, 7.9);
    a *= 0.52;
  }
  return v;
}
void main() {
  vec2 uv = gl_FragCoord.xy / uRes.xy;
  vec2 p = uv;
  p.x *= uRes.x / uRes.y;
  float t = uTime * 0.028;
  vec2 q = p * 1.45 + (uPointer - 0.5) * 0.18;

  float f1 = fbm(q + vec2(t, -t * 0.6));
  float f2 = fbm(q * 1.35 + vec2(-t * 0.8, t * 0.5) + 4.7);
  float f3 = fbm(q * 0.85 + vec2(t * 0.4, t * 0.9) + 9.2);

  vec3 col = uInk;
  col = mix(col, uStamp, smoothstep(0.42, 0.92, f1) * 0.50);
  col = mix(col, uBrass, smoothstep(0.50, 0.95, f2) * 0.34);
  col = mix(col, uTeal,  smoothstep(0.55, 0.98, f3) * 0.28);

  /* 四周压暗、中心微亮：引导视线落在标题上，也让上下衔接处更沉稳 */
  float vig = smoothstep(1.25, 0.35, length(uv - vec2(0.5, 0.55)));
  col *= mix(0.80, 1.0, vig);

  gl_FragColor = vec4(col, 1.0);
}
`;

const HERO_VERT = /* glsl */ `
void main() {
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

/** 纸墨色板 → shader 色源（与 tokens.css 同源，改动色板时同步此处） */
const HERO_COLORS = {
  uInk: [0x17 / 255, 0x1a / 255, 0x18 / 255],     // --slate-900 #171A18
  uStamp: [0xc4 / 255, 0x4f / 255, 0x3a / 255],   // --stamp #C44F3A
  uBrass: [0xa0 / 255, 0x89 / 255, 0x45 / 255],   // --brass #A08945
  uTeal: [0x3a / 255, 0x7a / 255, 0x6a / 255],    // --teal #3A7A6A
};

async function initHeroGL() {
  const canvas = document.getElementById('ld-hero-gl');
  const hero = document.getElementById('ld-hero');
  if (!canvas || !hero) return;

  let THREE;
  try {
    THREE = await import('three');
  } catch (err) {
    console.warn('[landing] three.js 加载失败，回退 CSS 渐变墨晕。', err);
    return;
  }

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: false,
      alpha: false,
      powerPreference: 'low-power',
    });
  } catch (err) {
    console.warn('[landing] WebGL 上下文创建失败，回退 CSS 渐变墨晕。', err);
    return;
  }

  const isMobile = mq('(max-width: 767px)').matches;
  const uniforms = {
    uTime: { value: 0 },
    uRes: { value: new THREE.Vector2(1, 1) },
    uPointer: { value: new THREE.Vector2(0.5, 0.5) },
    uOctaves: { value: isMobile ? 3 : 5 },
    uInk: { value: new THREE.Vector3(...HERO_COLORS.uInk) },
    uStamp: { value: new THREE.Vector3(...HERO_COLORS.uStamp) },
    uBrass: { value: new THREE.Vector3(...HERO_COLORS.uBrass) },
    uTeal: { value: new THREE.Vector3(...HERO_COLORS.uTeal) },
  };

  // 全屏三角形：一次 draw call 铺满，无几何场景开销
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(
    new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), 3));
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: HERO_VERT,
    fragmentShader: HERO_FRAG,
    depthTest: false,
    depthWrite: false,
  });
  const scene = new THREE.Scene();
  scene.add(new THREE.Mesh(geo, material));
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));

  function resize() {
    const w = hero.clientWidth || 1;
    const h = hero.clientHeight || 1;
    renderer.setSize(w, h, false);
    const pr = renderer.getPixelRatio();
    uniforms.uRes.value.set(w * pr, h * pr);
  }
  resize();
  if ('ResizeObserver' in window) {
    new ResizeObserver(resize).observe(hero);
  } else {
    window.addEventListener('resize', resize, { passive: true });
  }

  // 指针视差：lerp 跟随，让墨晕有「景深」而不是硬跟随
  let ptrX = 0.5, ptrY = 0.5;
  if (FINE_POINTER.matches && !REDUCED.matches) {
    hero.addEventListener('pointermove', (e) => {
      const rect = hero.getBoundingClientRect();
      const { nx, ny } = normPointer(e.clientX, e.clientY, rect);
      ptrX = (nx + 1) / 2;
      ptrY = 1 - (ny + 1) / 2; // GL 的 y 轴向上
    }, { passive: true });
  }

  let elapsed = 0;
  let last = 0;
  let running = false;
  const loop = (now) => {
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    elapsed += dt;
    uniforms.uTime.value = elapsed;
    const u = uniforms.uPointer.value;
    u.x += (ptrX - u.x) * 0.05;
    u.y += (ptrY - u.y) * 0.05;
    renderer.render(scene, camera);
  };

  const start = () => {
    if (running) return;
    running = true;
    last = performance.now();
    renderer.setAnimationLoop(loop);
  };
  const stop = () => {
    running = false;
    renderer.setAnimationLoop(null);
  };

  if (REDUCED.matches) {
    // 降级：渲一帧静态墨晕（比纯 CSS 渐变更有质感），永不启动循环
    uniforms.uTime.value = 12.0;
    renderer.render(scene, camera);
  } else {
    let heroVisible = false;
    const sync = () => {
      if (heroVisible && !document.hidden) start(); else stop();
    };
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((entries) => {
        heroVisible = entries[0] ? entries[0].isIntersecting : true;
        sync();
      }, { threshold: 0.02 }).observe(hero);
    } else {
      heroVisible = true;
    }
    document.addEventListener('visibilitychange', sync);
    sync();
  }

  // 上下文丢失：放弃 WebGL，露出 CSS 渐变层；页面卸载时释放 GL 资源
  canvas.addEventListener('webglcontextlost', (e) => {
    e.preventDefault();
    stop();
    canvas.style.display = 'none';
    console.warn('[landing] WebGL 上下文丢失，回退 CSS 渐变墨晕。');
  });
  window.addEventListener('pagehide', () => {
    stop();
    geo.dispose();
    material.dispose();
    renderer.dispose();
  });
}

/* ══════════════════════════════════════════════════
   10. boot：仅真实浏览器且是 landing 页时执行
   ══════════════════════════════════════════════════ */

function boot() {
  initThemeToggle();
  initSplit();
  initReveal();
  initMagnetic();
  initTilt();
  initScrollFX();
  initHeroGL(); // async，失败路径内部已全部捕获
}

if (HAS_DOM && document.getElementById('ld-page')) {
  boot();
}
