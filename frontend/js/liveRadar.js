// ===================================================
// liveRadar.js — 面试进行中的实时四维度雷达图 (v2.6)
// 每完成一题诊断即刷新，无需等到面试结束
// ===================================================

import { $, el } from './utils.js';

let liveChart = null;
let mounted = false;

const AVG_COLOR = '#4F46E5';
const LATEST_COLOR = '#F59E0B';

/**
 * 在指定容器中创建实时雷达卡片（幂等，重复调用只创建一次）
 * @param {HTMLElement} area 面试进行区容器
 */
export function mountLiveRadar(area) {
  if (mounted && $('#live-radar-chart')) return;

  const card = el('div', { className: 'card live-radar-card', id: 'live-radar-card' },
    el('div', { className: 'card-title', textContent: '📡 实时能力雷达' }),
    el('div', { className: 'live-radar-meta', id: 'live-radar-meta',
      textContent: '完成第一题后开始绘制' }),
    el('div', { className: 'chart-container' },
      el('div', { className: 'chart-wrapper' },
        el('canvas', { id: 'live-radar-chart' }),
      ),
    ),
    el('div', { className: 'live-radar-weights', id: 'live-radar-weights' }),
  );

  area.appendChild(card);
  mounted = true;
}

/**
 * 用后端 radar_update 数据刷新雷达图
 * @param {object} snapshot { labels, keys, average, latest, weights, weighted_overall, answered_count }
 */
export function updateLiveRadar(snapshot) {
  if (!snapshot) return;

  const canvas = $('#live-radar-chart');
  if (!canvas || typeof window.Chart === 'undefined') return;

  const keys = snapshot.keys || [];
  const labels = snapshot.labels || [];
  const avgData = keys.map(k => Number(snapshot.average?.[k] ?? 0));
  const latestData = keys.map(k => Number(snapshot.latest?.[k] ?? 0));

  const meta = $('#live-radar-meta');
  if (meta) {
    const overall = Number(snapshot.weighted_overall ?? 0).toFixed(1);
    meta.textContent =
      `已完成 ${snapshot.answered_count || 0} 题 · 加权综合 ${overall} / 5`;
  }

  renderWeightBar(snapshot);

  // 已有实例则原地更新数据，避免每题销毁重建导致闪烁
  if (liveChart) {
    liveChart.data.labels = labels;
    liveChart.data.datasets[0].data = avgData;
    liveChart.data.datasets[1].data = latestData;
    liveChart.update();
    return;
  }

  liveChart = new window.Chart(canvas.getContext('2d'), {
    type: 'radar',
    data: {
      labels,
      datasets: [
        {
          label: '累计平均',
          data: avgData,
          borderColor: AVG_COLOR,
          backgroundColor: AVG_COLOR + '22',
          borderWidth: 2,
          pointBackgroundColor: AVG_COLOR,
          pointRadius: 4,
        },
        {
          label: '本题得分',
          data: latestData,
          borderColor: LATEST_COLOR,
          backgroundColor: LATEST_COLOR + '18',
          borderWidth: 2,
          borderDash: [5, 4],
          pointBackgroundColor: LATEST_COLOR,
          pointRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      animation: { duration: 400 },
      scales: {
        r: {
          min: 0,
          max: 5,
          ticks: { stepSize: 1, backdropColor: 'transparent', font: { size: 10 } },
          pointLabels: { font: { size: 12, weight: '500' } },
          grid: { color: '#E2E8F0' },
          angleLines: { color: '#E2E8F0' },
        },
      },
      plugins: {
        legend: { position: 'bottom', labels: { padding: 12, font: { size: 11 } } },
      },
    },
  });
}

/** 渲染权重条，让用户看到"这个岗位更看重哪一维" */
function renderWeightBar(snapshot) {
  const box = $('#live-radar-weights');
  if (!box || !snapshot.weights) return;

  const keys = snapshot.keys || [];
  const labels = snapshot.labels || [];
  box.innerHTML = '';

  keys.forEach((k, i) => {
    const w = Number(snapshot.weights[k] ?? 0.25);
    box.appendChild(el('div', { className: 'lw-item' },
      el('span', { className: 'lw-name', textContent: labels[i] || k }),
      el('span', { className: 'lw-bar' },
        el('span', { className: 'lw-bar-fill', style: `width:${(w * 100).toFixed(0)}%` }),
      ),
      el('span', { className: 'lw-val', textContent: `${(w * 100).toFixed(0)}%` }),
    ));
  });
}

/** 面试重新开始时重置 */
export function resetLiveRadar() {
  if (liveChart) {
    liveChart.destroy();
    liveChart = null;
  }
  mounted = false;
}
