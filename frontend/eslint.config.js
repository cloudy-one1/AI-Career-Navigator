// ===================================================
// ESLint 配置（flat config，ESLint 9/10）
// ---------------------------------------------------
// 为什么引入：Vite 构建对“未定义标识符”静默放行——Rollup 会把 el 这类
// 未导入的引用当作合法的全局变量，构建照常成功，直到运行时才炸。
// 本项目的 renderJourneyProgress 就因此缺失 import 导致整个壳层初始化
// 中断（侧栏渲染了、点击全死、右侧空白）。
// no-undef 是唯一能在构建前拦下这类问题的检查。
// ===================================================

import js from '@eslint/js';
import globals from 'globals';

export default [
  // 全局忽略：构建产物与依赖
  { ignores: ['dist/**', 'node_modules/**'] },

  js.configs.recommended,

  // 浏览器端源码
  {
    files: ['src/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        // main.js 顶部注入 window.Chart，供 report.js / liveRadar.js / careerPlan.js
        // 以全局方式引用（兼容早期 CDN 版 Chart 的写法）。这是既定契约，
        // 在此显式登记，否则这些调用点会被 no-undef 判为未定义。
        Chart: 'readonly',
      },
    },
    rules: {
      // 核心目标：拦住未导入/未声明的标识符（本次事故的直接原因）
      'no-undef': 'error',
      // 中文排版会用到全角空格（U+3000）作分隔符，属正常文案而非脏字符；
      // 因此只禁止字符串/模板/注释之外的不规则空白。
      'no-irregular-whitespace': ['error', {
        skipStrings: true, skipTemplates: true, skipComments: true,
      }],
      'no-unused-vars': ['warn', {
        args: 'after-used',
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
      }],
      // 静默吞掉异常会让故障难以定位，空 catch 必须写明原因
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },

  // 构建配置与 Node 环境测试（vitest 断言为显式 import，无需注入测试 globals）
  {
    files: ['tests/**/*.js', 'vite.config.js', 'vitest.config.js', 'eslint.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.node,
    },
  },
];
