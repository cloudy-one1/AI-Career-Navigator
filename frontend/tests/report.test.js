// report.test.js — 报告 Tab 纯逻辑（v8.16）：引用证据抽取 + 背诵材料映射
import { describe, it, expect } from 'vitest';
import { quoteEvidenceList, buildRewriteMap } from '../src/js/report.js';

describe('quoteEvidenceList（引用证据抽取）', () => {
  it('只取非空 quote，维度名与核实结论一一对应', () => {
    const details = {
      quantification: { quote: '  把响应时间从 800ms 降到 200ms  ', quote_verified: true },
      job_relevance: { quote: '编造的原话', quote_verified: false },
      logic_coherence: { quote: '', quote_verified: true },   // 空 → 不进
      star_completeness: { quote: null },                     // 空 → 不进
    };
    const list = quoteEvidenceList(details);
    expect(list).toEqual([
      { key: 'quantification', name: '量化程度', quote: '把响应时间从 800ms 降到 200ms', verified: true },
      { key: 'job_relevance', name: '岗位相关性', quote: '编造的原话', verified: false },
    ]);
  });

  it('quote_verified 缺省视为已核（不灰显）', () => {
    const list = quoteEvidenceList({ logic_coherence: { quote: '原话' } });
    expect(list[0].verified).toBe(true);
  });

  it('空 / 畸形 details 安全退化', () => {
    expect(quoteEvidenceList(undefined)).toEqual([]);
    expect(quoteEvidenceList(null)).toEqual([]);
    expect(quoteEvidenceList('nonsense')).toEqual([]);
    expect(quoteEvidenceList({ quantification: 'not-an-object' })).toEqual([]);
  });
});

describe('buildRewriteMap（背诵材料映射）', () => {
  it('题干 → 改写答案与要点；无改写答案的条目不进映射', () => {
    const map = buildRewriteMap([
      { question: ' 介绍一下你的项目 ', rewritten_answer: ' 参考答案全文 ', key_changes: ['补了数据'] },
      { question: '没有改写的题', rewritten_answer: '' },
    ]);
    expect(map.size).toBe(1);
    expect(map.get('介绍一下你的项目')).toEqual({
      rewritten_answer: '参考答案全文',
      key_changes: ['补了数据'],
    });
    expect(map.has('没有改写的题')).toBe(false);
  });

  it('同题干取首条（后到的不覆盖先到的）', () => {
    const map = buildRewriteMap([
      { question: 'Q', rewritten_answer: '第一条', key_changes: [] },
      { question: 'Q', rewritten_answer: '第二条', key_changes: [] },
    ]);
    expect(map.get('Q').rewritten_answer).toBe('第一条');
  });

  it('空 / 畸形输入安全退化', () => {
    expect(buildRewriteMap(undefined).size).toBe(0);
    expect(buildRewriteMap([null, {}]).size).toBe(0);
  });
});
