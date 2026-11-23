import {stat} from './common/ui.js';
import {features, models} from '../constants/domain.js';
import {crewName} from '../stores/studio.js';
import {esc, fixed, signed} from '../utils/format.js';

export function maeBars(metrics, scale) {
  return `<div class="mae-bars">${['lasso','baseline'].map(key => `<div><span>${models[key]}</span>
    <span class="bar-track" aria-hidden="true"><i class="bar ${key}" style="--length:${100 * metrics[key] / scale}%"></i></span><strong class="mono">${fixed(metrics[key],3)} h</strong></div>`).join('')}</div>`;
}

export function predictions(rows) {
  return `<div class="table-wrap"><table class="predictions"><thead><tr><th>工单号</th><th>实际 h</th><th>Lasso h</th><th>中位数 h</th></tr></thead><tbody>${rows.map(row => `<tr><td class="mono">${esc(row.code)}</td><td>${fixed(row.actual)}</td><td>${fixed(row.lasso)}</td><td>${fixed(row.baseline)}</td></tr>`).join('')}</tbody></table></div>`;
}

export function foldDetails(fold) {
  return `<details class="fold"><summary><span><b>${esc(crewName(fold.crew))}</b><small>${fold.test_samples} 条验证样本</small></span>
      <span class="mono">${fixed(fold.mae.lasso,3)} <i>/</i> ${fixed(fold.mae.baseline,3)} h</span></summary>
    <p class="subtle">训练组 ${fold.train_crews.map(crew => esc(crewName(crew))).join('、')} · ${fold.train_samples} 条</p>${coefficients(fold.fit)}${predictions(fold.predictions)}</details>`;
}

export function coefficients(fit) {
  return `<p class="subtle">训练目标均值 ${fixed(fit.target_mean,3)} h · 基线中位数 ${fixed(fit.median,3)} h · Lasso 截距 ${signed(fit.intercept)} h</p>
    <div class="table-wrap"><table class="coefficients"><thead><tr><th>接单特征</th><th>均值</th><th>总体标准差</th><th>标准化系数 h</th><th>原尺度 h / 单位</th></tr></thead><tbody>${fit.features.map(item => `<tr><td>${features[item.key]}${item.scale === 0 ? ' <small>常量列</small>' : ''}</td><td>${fixed(item.mean,3)}</td><td>${fixed(item.scale,3)}</td><td>${signed(item.standard_coefficient)}</td><td class="${item.hours_per_unit === 0 ? 'muted' : 'actual'}">${signed(item.hours_per_unit)}</td></tr>`).join('')}</tbody></table></div>`;
}

const sources = {settled: '已结算残差', report: '报告留出样本', blend: '本组残差 + 共享池'};

export function calibrationNote(calibration) {
  const shared = calibration.shared;
  const crew = calibration.crew;
  const own = calibration.scope === 'crew';
  const counts = `本组已结算 ${crew.settled_count} 条、报告样本 ${crew.report_count} 条`;
  const ownLine = own
    ? `${counts}；按本组残差池计算，单侧分位 ${fixed(calibration.offset,3)} h${crew.lifted ? `（较共享高 ${fixed(crew.uplift,3)} h，已单独上调）` : '（未高于共享分位）'}。`
    : `${counts}，没有本组残差，暂用共享分位 ${fixed(calibration.offset,3)} h。`;
  return `<p class="subtle">本次校准：${own ? '本组校准' : '共享回退'} · 含 ${sources[calibration.source] ?? esc(calibration.source)} · 残差池 ${calibration.sample_count} 条 · ${fixed(calibration.coverage*100,0)}% 单侧分位 ${fixed(calibration.offset,3)} h。</p>
    <p class="subtle">${ownLine}</p>
    <p class="subtle">共享分位 ${fixed(shared.offset,3)} h（${sources[shared.source] ?? esc(shared.source)} · ${shared.sample_count} 条），供无本组样本的组回退。</p>`;
}

export function issuedEstimates(rows) {
  if (!rows.length) return `<p class="empty">本报告尚未发出排期上限。用下方试估表单填写工单号与摄制组后即可发出。</p>`;
  return `<div class="table-wrap"><table class="estimates"><thead><tr><th>工单号 / 摄制组</th><th>点估计 h</th><th>上限 h</th><th>校准来源</th><th>发出时间</th></tr></thead><tbody>${rows.map(row => `<tr>
    <td><small class="mono row-code">${esc(row.order_code)}</small>${esc(crewName(row.crew))}</td>
    <td class="mono">${fixed(row.point_hours)}</td><td class="mono actual">${fixed(row.upper_hours)}</td>
    <td>${row.calibration.scope === 'crew' ? '本组' : '共享'} · ${sources[row.calibration.source] ?? esc(row.calibration.source)} · ${row.calibration.sample_count} 条</td>
    <td class="mono">${esc(new Date(row.created_at).toLocaleString('zh-CN', {hour12:false}))}</td></tr>`).join('')}</tbody></table></div>`;
}

export function reconciliation(reporting) {
  const summary = reporting.summary;
  const coverage = summary.coverage === null ? '—' : `${fixed(summary.coverage*100,1)}%`;
  const mae = summary.mae === null ? '—' : `${fixed(summary.mae,3)} h`;
  const bias = summary.mean_signed_error === null ? '—' : `${signed(summary.mean_signed_error)} h`;
  const rows = reporting.items;
  const body = rows.length ? `<div class="table-wrap"><table class="estimates"><thead><tr><th>工单号 / 视频</th><th>组</th><th>点估计 h</th><th>上限 h</th><th>实际 h</th><th>偏差 h</th><th>上限内</th><th>结算时间</th></tr></thead><tbody>${rows.map(item => `
    <tr><td><small class="mono row-code">${esc(item.order_code)}</small>${esc(item.title ?? '未结算工单')}</td><td>${esc(crewName(item.crew))}</td>
    <td class="mono">${fixed(item.point_hours)}</td><td class="mono actual">${fixed(item.upper_hours)}</td>
    <td class="mono">${item.settled ? fixed(item.actual_hours) : '待结算'}</td>
    <td class="mono ${item.signed_error > 0 ? 'actual' : ''}">${item.settled ? signed(item.signed_error) : '—'}</td>
    <td>${item.settled ? (item.within_cap ? '<span class="status published">上限内</span>' : '<span class="status failed">超出上限</span>') : '<span class="status">待结算</span>'}</td>
    <td class="mono">${item.settled_at ? esc(new Date(item.settled_at).toLocaleString('zh-CN', {hour12:false})) : '—'}</td></tr>`).join('')}</tbody></table></div>`
    : `<p class="empty">本报告尚无试估工单，暂无可对账记录。</p>`;
  return `<div class="metrics reconcile-metrics">${stat('已发出上限', summary.issued, '单')}${stat('已结算', summary.settled, `待结算 ${summary.pending}`)}${stat('上限覆盖率', coverage, `${summary.covered}/${summary.settled}`)}${stat('点估计 MAE', mae, `偏差 ${bias}`)}</div>${body}`;
}
