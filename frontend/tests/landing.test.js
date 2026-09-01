/**
 * landing.js 单元测试（v8.6 新增）
 *
 * 覆盖对象：landing.js 顶部的纯函数区 —— 逐字拆分 / 磁性偏移 / 倾斜角 /
 * 时间线进度 / 视差与淡出。这些函数全是边界钳制逻辑，手工拖动验证不可靠，
 * 且是本页动效里唯一「算错会明显感觉违和」的部分。
 *
 * 运行环境是 node（见 vitest.config.js 注释）：landing.js 顶部有 HAS_DOM
 * 守卫，node 下导入不会执行任何 DOM/WebGL 代码；WebGL 渲染路径不在此处
 * mock —— 交给 playwright 真机截图验证（见 CHANGELOG v8.6 验证记录）。
 */
import { describe, it, expect } from 'vitest';
import {
  clampNum,
  charEntries,
  magneticOffset,
  normPointer,
  tiltAngles,
  timelineProgress,
  parallaxShift,
  heroFade,
} from '../src/js/landing.js';

describe('clampNum', () => {
  it('区间内原样返回', () => {
    expect(clampNum(5, 0, 10)).toBe(5);
  });
  it('越界钳到边界', () => {
    expect(clampNum(-3, 0, 10)).toBe(0);
    expect(clampNum(99, 0, 10)).toBe(10);
  });
});

describe('charEntries 逐字拆分', () => {
  it('逐字展开且字序连续', () => {
    const entries = charEntries('求职路');
    expect(entries.map((e) => e.ch)).toEqual(['求', '职', '路']);
    expect(entries.map((e) => e.ci)).toEqual([0, 1, 2]);
  });

  it('offset 跨嵌套元素累计（accent 段的字序接在前段之后）', () => {
    const head = charEntries('从职业定位到');
    const tail = charEntries('拿 Offer', head.length);
    expect(tail[0].ci).toBe(head.length);
    expect(tail.map((e) => e.ch)).toEqual(['拿', ' ', 'O', 'f', 'f', 'e', 'r']);
  });

  it('空串 / null 返回空数组', () => {
    expect(charEntries('')).toEqual([]);
    expect(charEntries(null)).toEqual([]);
  });

  it('代理对（emoji）不被拆散', () => {
    const entries = charEntries('a🎯b');
    expect(entries.map((e) => e.ch)).toEqual(['a', '🎯', 'b']);
  });
});

describe('magneticOffset 磁性偏移', () => {
  it('指针在按钮中心时偏移为 0', () => {
    expect(magneticOffset(100, 50, 100, 50)).toEqual({ x: 0, y: 0 });
  });

  it('偏移随距离线性放大（默认强度 0.28）', () => {
    const off = magneticOffset(110, 50, 100, 50);
    expect(off.x).toBeCloseTo(2.8);
    expect(off.y).toBe(0);
  });

  it('远距离被钳制到 maxDist', () => {
    const off = magneticOffset(500, -500, 100, 50);
    expect(off.x).toBe(12);
    expect(off.y).toBe(-12);
  });

  it('自定义强度与钳制上限生效', () => {
    const off = magneticOffset(120, 60, 100, 50, 0.5, 5);
    expect(off.x).toBe(5);   // 20*0.5=10 钳到 5
    expect(off.y).toBe(5);   // 10*0.5=5
  });
});

describe('normPointer 归一化指针', () => {
  const rect = { left: 0, top: 0, width: 200, height: 100 };

  it('中心 → (0, 0)', () => {
    expect(normPointer(100, 50, rect)).toEqual({ nx: 0, ny: 0 });
  });

  it('四角 → ±1', () => {
    expect(normPointer(0, 0, rect)).toEqual({ nx: -1, ny: -1 });
    expect(normPointer(200, 100, rect)).toEqual({ nx: 1, ny: 1 });
  });

  it('越出元素边界仍钳在 ±1', () => {
    const { nx, ny } = normPointer(9999, -50, rect);
    expect(nx).toBe(1);
    expect(ny).toBe(-1);
  });

  it('零尺寸元素安全返回 0', () => {
    expect(normPointer(10, 10, { left: 0, top: 0, width: 0, height: 0 }))
      .toEqual({ nx: 0, ny: 0 });
  });
});

describe('tiltAngles 3D 倾斜角', () => {
  it('指针上移卡片顶部前倾（rx 为正），右移右缘后倾（ry 为正）', () => {
    expect(tiltAngles(0, -1)).toEqual({ rx: 7, ry: 0 });
    expect(tiltAngles(1, 0)).toEqual({ rx: 0, ry: 7 });
  });

  it('角度不超过 maxDeg', () => {
    const { rx, ry } = tiltAngles(2, -2, 7);
    expect(rx).toBe(7);
    expect(ry).toBe(7);
  });

  it('自定义 maxDeg 生效', () => {
    expect(tiltAngles(0, 1, 4)).toEqual({ rx: -4, ry: 0 });
  });
});

describe('timelineProgress 时间线描边进度', () => {
  const vh = 1000;

  it('区块还在视口下方 → 0', () => {
    expect(timelineProgress(vh, 1200, 800)).toBe(0);
  });

  it('区块顶部越过视口 72% 线时开始生长', () => {
    expect(timelineProgress(vh, 720, 800)).toBe(0);
    expect(timelineProgress(vh, 520, 800)).toBeCloseTo(0.25);
  });

  it('区块底部到达 72% 线时长满，继续滚动保持 1', () => {
    expect(timelineProgress(vh, -80, 800)).toBe(1);
    expect(timelineProgress(vh, -2000, 800)).toBe(1);
  });

  it('零高度区块直接长满（避免除零）', () => {
    expect(timelineProgress(vh, 100, 0)).toBe(1);
  });
});

describe('parallaxShift / heroFade Hero 视差与淡出', () => {
  it('视差只下沉不抬升（负滚动归零）', () => {
    expect(parallaxShift(-50, 0.16)).toBe(0);
    expect(parallaxShift(100, 0.16)).toBeCloseTo(16);
  });

  it('视差系数钳在 0~1', () => {
    expect(parallaxShift(100, 2)).toBe(100);
  });

  it('淡出：不滚动不透明，滚过 70% Hero 高度全透明', () => {
    expect(heroFade(0, 800)).toBe(1);
    expect(heroFade(280, 800)).toBeCloseTo(0.5);
    expect(heroFade(560, 800)).toBe(0);
    expect(heroFade(9999, 800)).toBe(0);
  });

  it('零高度安全返回 0', () => {
    expect(heroFade(10, 0)).toBe(0);
  });
});
