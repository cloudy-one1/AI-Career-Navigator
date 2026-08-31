import { defineConfig } from 'vite';

// v7.4: 前端单元测试。此前 voice.js（23KB，含世代号竞态与 VAD 状态机）零自动化覆盖，
// 只能靠手工点击验证——而这两块恰恰是最容易在改动中悄悄回归的地方。
// 运行环境刻意选 node 而非 happy-dom：voice.js 依赖的 MediaRecorder / AudioContext /
// speechSynthesis 在 DOM 模拟库里也没实现，仍需逐个打桩，多引一个依赖没有收益。
export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/**/*.test.js'],
    globals: false,
  },
});
