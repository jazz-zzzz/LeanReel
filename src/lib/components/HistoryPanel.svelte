<script lang="ts">
  import { showHistory, history } from '$lib/stores/history';
  import { queue } from '$lib/stores/queue';
  import { cancelActiveQueueItems, cancelQueueItem } from '$lib/queueProgress.js';
  import { cancelEncode, cancelTask } from '$lib/api';
  import type { HistoryEntry } from '$lib/stores/history';

  let statusFilter = $state<'all' | 'success' | 'failed'>('all');

  type SortKey = keyof HistoryEntry | 'delta_bytes' | '';
  let sortKey = $state<SortKey>('completed_at');
  let sortAsc = $state(false);
  let cmdDetail = $state<string | null>(null);
  let showAllActive = $state(false);

  let activeTasks = $derived($queue.filter(q => q.status === 'pending' || q.status === 'running'));
  let visibleActive = $derived(showAllActive ? activeTasks : activeTasks.slice(0, 5));
  let hasMore = $derived(activeTasks.length > 5);

  let filtered = $derived($history.filter(e => {
    if (statusFilter === 'success') return e.success;
    if (statusFilter === 'failed') return !e.success && e.status !== 'pending' && e.status !== 'running';
    return true;
  }));

  let sorted = $derived(sortList(filtered, sortKey, sortAsc));

  function deltaBytes(rec: HistoryEntry): number {
    return (rec.source_size_bytes || 0) - (rec.output_size_bytes || 0);
  }

  function sortList(list: HistoryEntry[], key: SortKey, asc: boolean): HistoryEntry[] {
    if (!key) return list;
    return [...list].sort((a, b) => {
      let va: string | number | boolean | null | undefined;
      let vb: string | number | boolean | null | undefined;
      if (key === 'delta_bytes') {
        va = deltaBytes(a);
        vb = deltaBytes(b);
      } else {
        va = a[key];
        vb = b[key];
      }
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'number' && typeof vb === 'number') return asc ? va - vb : vb - va;
      const cmp = String(va).localeCompare(String(vb));
      return asc ? cmp : -cmp;
    });
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) sortAsc = !sortAsc;
    else { sortKey = key; sortAsc = false; }
  }

  function sortArrow(key: SortKey): string {
    if (sortKey !== key) return '';
    return sortAsc ? ' ▴' : ' ▾';
  }

  function statusLabel(s: string): string {
    const m: Record<string,string> = { completed:'成功', failed:'失败', cancelled:'已取消', running:'运行中', pending:'等待中', discarded:'已丢弃', skipped:'已跳过' };
    return m[s] || s;
  }

  function formatBytes(b: number): string {
    if (!b) return '—';
    if (b >= 1e9) return (b / 1e9).toFixed(1) + ' GB';
    if (b >= 1e6) return (b / 1e6).toFixed(1) + ' MB';
    if (b >= 1e3) return (b / 1e3).toFixed(1) + ' KB';
    return b + ' B';
  }

  function formatDuration(ms: number): string {
    if (!ms) return '—';
    const s = ms / 1000;
    if (s < 60) return s.toFixed(0) + 's';
    if (s < 3600) return Math.floor(s / 60) + 'm ' + (s % 60).toFixed(0) + 's';
    return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
  }

  function encoderLabel(e: string): string {
    const m: Record<string,string> = { libx265:'HEVC', hevc_nvenc:'HEVC', av1_nvenc:'AV1', h264_nvenc:'H.264', copy:'流复制' };
    return m[e] || e;
  }

  interface PerfMetrics {
    max_fps?: number;
    avg_bitrate_kbps?: number;
    smb_read_bytes_sec?: number;
    smb_write_bytes_sec?: number;
    smb_avg_bytes_per_request?: number;
    smb_avg_queue_length?: number;
  }

  function parsePerf(json: string): PerfMetrics | null {
    if (!json) return null;
    try { return JSON.parse(json); } catch { return null; }
  }

  function fmtBytesSec(b: number | undefined): string {
    if (!b) return '—';
    if (b > 1e9) return (b/1e9).toFixed(1) + ' GB/s';
    if (b > 1e6) return (b/1e6).toFixed(1) + ' MB/s';
    if (b > 1e3) return (b/1e3).toFixed(0) + ' KB/s';
    return b.toFixed(0) + ' B/s';
  }

  function fmtNum(v: number | undefined, unit: string): string {
    if (v == null) return '—';
    return v.toFixed(0) + unit;
  }

  function closePanel() { showHistory.set(false); }

  async function cancelAllTasks() {
    await cancelEncode();
    queue.update(cancelActiveQueueItems);
  }

  async function cancelOneTask(jobId: string) {
    await cancelTask(jobId);
    queue.update(items => cancelQueueItem(items, jobId));
  }
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') closePanel(); }} />

<div class="history-overlay" onclick={closePanel} role="dialog">
  <div class="history-sheet" onclick={(e) => e.stopPropagation()}>
    <div class="history-header" data-tauri-drag-region>
      <button class="ghost" onclick={closePanel}>
        <span class="back-arrow">←</span> 返回
      </button>
      <h2>任务</h2>
      <div class="filter-bar">
        <button class="chip" class:active={statusFilter === 'all'} onclick={() => statusFilter = 'all'}>全部</button>
        <button class="chip" class:active={statusFilter === 'success'} onclick={() => statusFilter = 'success'}>成功</button>
        <button class="chip" class:active={statusFilter === 'failed'} onclick={() => statusFilter = 'failed'}>失败</button>
      </div>
      {#if activeTasks.length > 0}
        <button class="ghost danger" onclick={cancelAllTasks}>全部取消</button>
      {/if}
    </div>

    {#if activeTasks.length > 0}
      <div class="active-tasks">
        {#each visibleActive as item (item.id)}
          <div class="active-row" class:running={item.status === 'running'} class:done={item.status === 'done'} class:failed={item.status === 'failed'}>
            {#if item.status === 'running'}<span class="spinner"></span>{:else}<span class="pending-dot"></span>{/if}
            <span class="active-name">{item.fileName}</span>
            <span class="active-strategy">{item.strategyName}</span>
            <div class="active-progress"><div class="active-progress-bar"><div class="active-progress-fill" style="width:{item.progress}%"></div></div></div>
            <span class="active-pct">{item.progress}%</span>
            {#if item.status === 'pending' || item.status === 'running'}
              <button class="ghost danger" onclick={() => cancelOneTask(item.id)}>取消</button>
            {/if}
          </div>
        {/each}
        {#if hasMore}
          <button class="ghost" onclick={() => showAllActive = !showAllActive} style="font-size:11px">{showAllActive ? '收起' : `展开更多 (${activeTasks.length - 5})`}</button>
        {/if}
      </div>
    {/if}

    {#if sorted.length === 0}
      <div class="empty">暂无转换记录</div>
    {:else}
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th class="col-status">状态</th>
              <th class="sortable" class:active={sortKey === 'source_path'} onclick={() => toggleSort('source_path')}>源文件{sortArrow('source_path')}</th>
              <th class="sortable mono-col" class:active={sortKey === 'source_size_bytes'} onclick={() => toggleSort('source_size_bytes')}>源体积{sortArrow('source_size_bytes')}</th>
              <th class="sortable mono-col" class:active={sortKey === 'output_size_bytes'} onclick={() => toggleSort('output_size_bytes')}>输出体积{sortArrow('output_size_bytes')}</th>
              <th class="sortable mono-col" class:active={sortKey === 'delta_bytes'} onclick={() => toggleSort('delta_bytes')}>节省量{sortArrow('delta_bytes')}</th>
              <th class="sortable mono-col" class:active={sortKey === 'savings_pct'} onclick={() => toggleSort('savings_pct')}>节省率{sortArrow('savings_pct')}</th>
              <th class="sortable mono-col" class:active={sortKey === 'cq_value'} onclick={() => toggleSort('cq_value')}>CQ{sortArrow('cq_value')}</th>
              <th class="sortable" class:active={sortKey === 'strategy_name'} onclick={() => toggleSort('strategy_name')}>策略{sortArrow('strategy_name')}</th>
              <th class="sortable" class:active={sortKey === 'encoder'} onclick={() => toggleSort('encoder')}>编码器{sortArrow('encoder')}</th>
              <th class="sortable mono-col" class:active={sortKey === 'duration_ms'} onclick={() => toggleSort('duration_ms')}>耗时{sortArrow('duration_ms')}</th>
              <th class="sortable" class:active={sortKey === 'started_at'} onclick={() => toggleSort('started_at')}>开始时间{sortArrow('started_at')}</th>
              <th class="sortable" class:active={sortKey === 'completed_at'} onclick={() => toggleSort('completed_at')}>完成时间{sortArrow('completed_at')}</th>
              <th class="sortable mono-col" class:active={sortKey === 'source_deleted'} onclick={() => toggleSort('source_deleted')}>源已删{sortArrow('source_deleted')}</th>
              <th class="mono-col">FPS</th>
              <th class="mono-col">码率</th>
              <th class="mono-col">SMB读</th>
              <th class="mono-col">SMB写</th>
              <th class="mono-col">B/Req</th>
            </tr>
          </thead>
          <tbody>
            {#each sorted as rec, i (rec.id)}
              {@const p = parsePerf(rec.performance_metrics)}
              <tr class:alt={i % 2 === 1}>
                <td class="col-status">
                  {#if rec.status === 'failed' && rec.error_message}
                    <span class="status-badge {rec.status} clickable" onclick={() => cmdDetail = rec.error_message}>{statusLabel(rec.status)}</span>
                  {:else}
                    <span class="status-badge {rec.status}">{statusLabel(rec.status)}</span>
                  {/if}
                </td>
                <td class="col-path" title={rec.source_path}>
                  <span class:deleted={rec.source_deleted}>
                    {rec.source_path.split(/[/\\]/).pop() || rec.source_path}
                  </span>
                </td>
                <td class="mono-col">{formatBytes(rec.source_size_bytes)}</td>
                <td class="mono-col">{formatBytes(rec.output_size_bytes)}</td>
                <td class="mono-col">
                  {#if deltaBytes(rec) > 0}
                    <span class="savings-pos">{formatBytes(deltaBytes(rec))}</span>
                  {:else if deltaBytes(rec) < 0}
                    <span class="savings-neg">+{formatBytes(-deltaBytes(rec))}</span>
                  {:else}
                    —
                  {/if}
                </td>
                <td class="mono-col">
                  {#if rec.savings_pct > 0}
                    <span class="savings-pos">{rec.savings_pct.toFixed(0)}%</span>
                  {:else}
                    —
                  {/if}
                </td>
                <td class="mono-col">{rec.cq_value ? rec.cq_value : '—'}</td>
                <td class="clickable" onclick={() => cmdDetail = rec.ffmpeg_command || '(无记录)'}>{rec.strategy_name}</td>
                <td><span class="encoder-tag">{encoderLabel(rec.encoder)}</span></td>
                <td class="mono-col">{formatDuration(rec.duration_ms)}</td>
                <td class="col-time">{rec.started_at ? rec.started_at.replace('T', ' ').substring(0, 16) : '—'}</td>
                <td class="col-time">{rec.completed_at ? rec.completed_at.replace('T', ' ').substring(0, 16) : '—'}</td>
                <td class="mono-col">{rec.source_deleted ? '已删' : '—'}</td>
                <td class="mono-col">{p?.max_fps ? p.max_fps.toFixed(0) : '—'}</td>
                <td class="mono-col">{p?.avg_bitrate_kbps ? (p.avg_bitrate_kbps > 999 ? (p.avg_bitrate_kbps/1000).toFixed(1)+'M' : p.avg_bitrate_kbps+'k') : '—'}</td>
                <td class="mono-col">{fmtBytesSec(p?.smb_read_bytes_sec)}</td>
                <td class="mono-col">{fmtBytesSec(p?.smb_write_bytes_sec)}</td>
                <td class="mono-col">{fmtNum(p?.smb_avg_bytes_per_request, '')}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</div>

{#if cmdDetail}
  <div class="cmd-overlay" onclick={() => cmdDetail = null} onkeydown={(e) => e.key === 'Escape' && (cmdDetail = null)}>
    <div class="cmd-box" onclick={(e) => e.stopPropagation()}>
      <h3>{cmdDetail?.startsWith('ffmpeg') || cmdDetail?.includes(' -i ') ? 'FFmpeg 命令' : '详细信息'}</h3>
      <pre class="cmd-text">{cmdDetail}</pre>
      <div class="cmd-actions">
        <button class="ghost" onclick={() => cmdDetail = null}>关闭</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .cmd-overlay { position: fixed; inset: 0; z-index: 10000; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; }
  .cmd-box { background: rgba(20,28,36,0.96); backdrop-filter: blur(40px); border: 1px solid var(--border-default); border-radius: var(--radius-lg); padding: var(--space-xl); display: flex; flex-direction: column; gap: var(--space-md); max-width: 750px; width: 90%; }
  .cmd-box h3 { font-size: var(--font-size-body); font-weight: 600; }
  .cmd-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); }
  .cmd-text { font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary); white-space: pre-wrap; word-break: break-all; max-height: 400px; overflow-y: auto; background: rgba(0,0,0,0.2); padding: var(--space-md); border-radius: var(--radius-sm); }
  .clickable { cursor: pointer; color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .clickable:hover { color: var(--accent-hover); }

  .history-overlay {
    position: fixed; inset: 0; z-index: 1000;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
  }
  .history-sheet {
    height: 100%;
    background: var(--bg-window);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: var(--space-xl) var(--space-2xl);
  }

  .history-header {
    display: flex;
    align-items: center;
    gap: var(--space-xl);
    margin-bottom: var(--space-xl);
    flex-shrink: 0;
  }
  .history-header h2 {
    font-size: var(--font-size-body);
    font-weight: 600;
    color: var(--text-primary);
  }
  .back-arrow { font-size: 14px; margin-right: 4px; }

  .filter-bar { display: flex; gap: var(--space-xs); }
  .chip {
    padding: 3px 12px;
    border: 1px solid var(--border-default);
    border-radius: 12px;
    background: var(--bg-surface);
    color: var(--text-secondary);
    font-size: var(--font-size-label);
    cursor: pointer;
    transition: all var(--duration-fast) var(--ease-expo);
  }
  .chip:hover { border-color: var(--border-focus); color: var(--text-primary); }
  .chip.active { background: var(--accent-dimmed); border-color: var(--accent); color: var(--accent); }

  .loading, .error, .empty {
    flex: 1; display: flex; align-items: center; justify-content: center;
    color: var(--text-muted); font-size: var(--font-size-body);
  }
  .error { color: var(--danger); }

  .table-scroll { flex: 1; overflow: auto; }

  table { width: 100%; border-collapse: collapse; min-width: 1300px; }

  th {
    text-align: left;
    padding: 7px 8px;
    font-size: var(--font-size-label);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border-subtle);
    user-select: none;
    background: rgba(20, 28, 36, 0.60);
    white-space: nowrap;
  }
  th.sortable { cursor: pointer; }
  th.sortable:hover { color: var(--text-primary); }
  th.active { color: var(--accent); }

  td {
    padding: 5px 8px;
    font-size: var(--font-size-body);
    border-bottom: 1px solid var(--border-subtle);
    white-space: nowrap;
  }
  tbody tr.alt { background: rgba(255, 255, 255, 0.015); }
  tbody tr:hover { background: var(--bg-hover); }

  .col-status { width: 56px; }
  .col-time { font-size: var(--font-size-label); color: var(--text-secondary); }

  .mono-col {
    font-family: var(--font-mono);
    font-size: var(--font-size-mono);
    font-variant-numeric: tabular-nums;
    color: var(--text-secondary);
    text-align: right;
  }

  .status-badge {
    display: inline-block;
    padding: 0 5px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-surface);
  }
  .status-badge.completed { color: var(--success); background: rgba(78, 201, 176, 0.10); }
  .status-badge.failed { color: var(--danger); background: rgba(241, 76, 76, 0.10); }
  .status-badge.running { color: var(--accent); background: var(--accent-dimmed); }

  .deleted { text-decoration: line-through; color: var(--text-muted); }
  .savings-pos { color: var(--success); font-weight: 600; }
  .savings-neg { color: var(--danger); font-weight: 600; }
  .encoder-tag {
    display: inline-block;
    padding: 0 5px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
    font-weight: 600;
    background: var(--tag-hevc-bg);
    color: var(--tag-hevc-text);
  }

  .col-path { max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
  .active-tasks { display: flex; flex-direction: column; gap: 2px; margin-bottom: var(--space-md); flex-shrink: 0; }
  .active-row { display: flex; align-items: center; gap: var(--space-sm); padding: 5px 8px; border-radius: var(--radius-sm); background: var(--bg-surface); font-size: var(--font-size-body); }
  .active-row.running { border: 1px solid var(--accent-dimmed); }
  .active-row.done { opacity: 0.6; }
  .active-row.failed { border: 1px solid rgba(241,76,76,0.2); }
  .active-status { font-size: 14px; width: 20px; text-align: center; flex-shrink: 0; }
  .active-row.running .active-status { color: var(--accent); }
  .active-row.done .active-status { color: var(--success); }
  .active-row.failed .active-status { color: var(--danger); }
  .active-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .active-strategy { color: var(--text-secondary); font-size: var(--font-size-label); }
  .active-progress { width: 80px; }
  .active-progress-bar { height: 3px; background: var(--border-subtle); border-radius: 2px; overflow: hidden; }
  .active-progress-fill { height: 100%; background: var(--accent); transition: width 0.5s var(--ease-expo); }
  .active-pct { font-family: var(--font-mono); font-size: var(--font-size-mono); color: var(--text-secondary); width: 36px; text-align: right; }
  .active-text { font-size: var(--font-size-label); color: var(--text-secondary); width: 60px; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border-subtle); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .pending-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted); display: inline-block; flex-shrink: 0; }
</style>
