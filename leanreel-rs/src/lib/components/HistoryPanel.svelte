<script lang="ts">
  import { onMount } from 'svelte';
  import { showHistory } from '$lib/stores/history';
  import { getHistory } from '$lib/api';
  import type { HistoryEntry } from '$lib/stores/history';

  let history: HistoryEntry[] = [];
  let loading = true;
  let error = '';
  let statusFilter: 'all' | 'success' | 'failed' = 'all';

  type SortKey = keyof HistoryEntry | 'delta_bytes' | '';
  let sortKey: SortKey = 'completed_at';
  let sortAsc = false;

  onMount(async () => {
    try { history = await getHistory(); }
    catch (e) { error = `加载失败: ${e}`; }
    finally { loading = false; }
  });

  $: filtered = history.filter(e => {
    if (statusFilter === 'success') return e.success;
    if (statusFilter === 'failed') return !e.success && e.status !== 'pending' && e.status !== 'running';
    return true;
  });

  $: sorted = sortList(filtered, sortKey, sortAsc);

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

  function closePanel() { showHistory.set(false); }
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') closePanel(); }} />

<div class="history-overlay" onclick={closePanel} role="dialog">
  <div class="history-sheet" onclick={(e) => e.stopPropagation()}>
    <div class="history-header">
      <button class="ghost" onclick={closePanel}>
        <span class="back-arrow">←</span> 返回
      </button>
      <h2>转换历史</h2>
      <div class="filter-bar">
        <button class="chip" class:active={statusFilter === 'all'} onclick={() => statusFilter = 'all'}>全部</button>
        <button class="chip" class:active={statusFilter === 'success'} onclick={() => statusFilter = 'success'}>成功</button>
        <button class="chip" class:active={statusFilter === 'failed'} onclick={() => statusFilter = 'failed'}>失败</button>
      </div>
    </div>

    {#if loading}
      <div class="loading">加载中...</div>
    {:else if error}
      <div class="error">{error}</div>
    {:else if sorted.length === 0}
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
            </tr>
          </thead>
          <tbody>
            {#each sorted as rec, i (rec.id)}
              <tr class:alt={i % 2 === 1}>
                <td class="col-status"><span class="status-badge {rec.status}">{statusLabel(rec.status)}</span></td>
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
                <td>{rec.strategy_name}</td>
                <td><span class="encoder-tag">{encoderLabel(rec.encoder)}</span></td>
                <td class="mono-col">{formatDuration(rec.duration_ms)}</td>
                <td class="col-time">{rec.started_at ? rec.started_at.replace('T', ' ').substring(0, 16) : '—'}</td>
                <td class="col-time">{rec.completed_at ? rec.completed_at.replace('T', ' ').substring(0, 16) : '—'}</td>
                <td class="mono-col">{rec.source_deleted ? '已删' : '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</div>

<style>
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
</style>
