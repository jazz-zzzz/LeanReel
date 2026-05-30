<script lang="ts">
  import { files, selectedFilePaths } from '$lib/stores/files';
  import type { FileEntry } from '$lib/stores/files';

  let selectedPaths: Set<string> = new Set();
  let allSelected = false;

  let filterKey = 'all';

  $: filteredFiles = sortedFiles.filter(f => {
    if (filterKey === 'all') return true;
    if (filterKey === 'checked') return selectedPaths.has(f.path);
    if (f.decision_status) {
      if (filterKey === 'processable') return f.decision_status === 'processable';
      if (filterKey === 'protected') return f.decision_status === 'protected';
      if (filterKey === 'probe_failed') return f.decision_status === 'probe_failed';
    }
    return true;
  });

  $: selectedFilePaths.set([...selectedPaths]);

  type SortKey = 'name' | 'codec' | 'hdr' | 'resolution' | 'size' | 'strategy_match';
  let sortKey: SortKey = 'name';
  let sortAsc = true;
  let scrollTop = 0;
  let scrollEl: HTMLElement;

  const ROW_H = 29; // px — td padding (5+5) + line-height (~19)
  const BUFFER = 8; // extra rows rendered above/below viewport

  $: sortedFiles = sortFiles($files, sortKey, sortAsc);

  // Virtual scroll: only render visible + buffer rows
  $: visibleCount = Math.ceil((scrollEl?.clientHeight ?? 400) / ROW_H) + BUFFER * 2;
  $: startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - BUFFER);
  $: endIdx = Math.min(filteredFiles.length, startIdx + visibleCount);
  $: visibleFiles = filteredFiles.slice(startIdx, endIdx);
  $: topSpacer = startIdx * ROW_H;
  $: bottomSpacer = Math.max(0, (filteredFiles.length - endIdx) * ROW_H);

  function onScroll(e: Event) {
    scrollTop = (e.target as HTMLElement).scrollTop;
  }

  function sortFiles(list: FileEntry[], key: SortKey, asc: boolean): FileEntry[] {
    const sorted = [...list];
    sorted.sort((a, b) => {
      let va: string | number;
      let vb: string | number;
      switch (key) {
        case 'name': va = a.name; vb = b.name; break;
        case 'codec': va = a.codec || ''; vb = b.codec || ''; break;
        case 'hdr': va = a.hdr || ''; vb = b.hdr || ''; break;
        case 'resolution': va = (a.width && a.height) ? a.width * a.height : 0; vb = (b.width && b.height) ? b.width * b.height : 0; break;
        case 'size': va = a.size; vb = b.size; break;
        case 'strategy_match': va = a.decision_text || ''; vb = b.decision_text || ''; break;
        default: return 0;
      }
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
    return sorted;
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) { sortAsc = !sortAsc; }
    else { sortKey = key; sortAsc = true; }
    scrollTop = 0;
    scrollEl?.scrollTo({ top: 0 });
  }

  function sortArrow(key: SortKey): string {
    if (sortKey !== key) return '';
    return sortAsc ? ' ▴' : ' ▾';
  }

  function toggleSelectAll() {
    if (allSelected) { selectedPaths = new Set(); allSelected = false; }
    else { selectedPaths = new Set(filteredFiles.map(f => f.path)); allSelected = true; }
  }

  function toggleFile(path: string) {
    const next = new Set(selectedPaths);
    if (next.has(path)) { next.delete(path); } else { next.add(path); }
    selectedPaths = next;
    allSelected = next.size === $files.length && $files.length > 0;
  }

  $: {
    if (filteredFiles.length === 0) { allSelected = false; }
    else if (selectedPaths.size !== filteredFiles.length) { allSelected = false; }
    else { allSelected = true; }
  }

  function resDisplay(file: FileEntry): string {
    if (file.width && file.height) return `${file.width} × ${file.height}`;
    return '—';
  }

  function codecTagClass(codec: string): string {
    const c = (codec || '').toUpperCase();
    if (c.includes('HEVC') || c.includes('H.265') || c.includes('H265')) return 'tag-hevc';
    if (c.includes('AV1') || c.includes('AV01')) return 'tag-av1';
    return 'tag-other';
  }

  function hdrTagClass(hdr: string): string {
    const h = (hdr || '').toUpperCase();
    if (h.includes('DV') || h.includes('DOLBY')) return 'tag-dv';
    if (h.includes('HDR10+') || h.includes('HDR10')) return 'tag-hdr';
    if (h === 'SDR' || h === 'NONE') return 'tag-sdr';
    return 'tag-other';
  }

  export function getSelectedPaths(): string[] { return [...selectedPaths]; }
</script>

<div class="file-table">
  {#if $files.length === 0}
    <div class="empty-state">
      <span class="empty-icon">□</span>
      <p>暂无文件</p>
      <p class="empty-sub">新建库并添加文件夹后，文件将显示在此处</p>
    </div>
  {:else}
    <table class="table-fixed">
      <thead>
        <tr>
          <th class="col-check"><input type="checkbox" checked={allSelected} onchange={toggleSelectAll} /></th>
          <th class="col-name sortable" class:active={sortKey === 'name'} onclick={() => toggleSort('name')}>文件名{sortArrow('name')}</th>
          <th class="col-codec sortable" class:active={sortKey === 'codec'} onclick={() => toggleSort('codec')}>编码{sortArrow('codec')}</th>
          <th class="col-hdr sortable" class:active={sortKey === 'hdr'} onclick={() => toggleSort('hdr')}>HDR{sortArrow('hdr')}</th>
          <th class="col-res sortable" class:active={sortKey === 'resolution'} onclick={() => toggleSort('resolution')}>分辨率{sortArrow('resolution')}</th>
          <th class="col-size sortable" class:active={sortKey === 'size'} onclick={() => toggleSort('size')}>大小{sortArrow('size')}</th>
          <th class="col-match sortable" class:active={sortKey === 'strategy_match'} onclick={() => toggleSort('strategy_match')}>策略匹配{sortArrow('strategy_match')}</th>
        </tr>
      </thead>
    </table>
    <div class="filter-bar">
      <select bind:value={filterKey}>
        <option value="all">全部 ({$files.length})</option>
        <option value="processable">可处理</option>
        <option value="protected">受保护</option>
        <option value="probe_failed">探测失败</option>
        <option value="checked">已勾选</option>
      </select>
    </div>
    <div class="table-body" bind:this={scrollEl} onscroll={onScroll}>
      <table>
        <colgroup>
          <col class="col-check"><col class="col-name"><col class="col-codec">
          <col class="col-hdr"><col class="col-res"><col class="col-size"><col class="col-match">
        </colgroup>
        <tbody>
          {#if topSpacer > 0}
            <tr style="height: {topSpacer}px" aria-hidden="true"></tr>
          {/if}

          {#each visibleFiles as file, i (file.path)}
            {@const realIdx = startIdx + i}
            <tr
              class:selected={selectedPaths.has(file.path)}
              class:alt={realIdx % 2 === 1}
              onclick={() => toggleFile(file.path)}
            >
              <td class="col-check" onclick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={selectedPaths.has(file.path)} onchange={() => toggleFile(file.path)} />
              </td>
              <td class="col-name" title={file.path}><span class="file-name">{file.name}</span></td>
              <td class="col-codec">
                <span class="codec-tag {codecTagClass(file.codec || '')}">{file.codec || '—'}</span>
              </td>
              <td class="col-hdr">
                <span class="hdr-tag {hdrTagClass(file.hdr || '')}">{file.hdr || 'SDR'}</span>
              </td>
              <td class="col-res"><span class="mono">{resDisplay(file)}</span></td>
              <td class="col-size"><span class="mono">{file.size_display}</span></td>
              <td class="col-match">
                {#if file.decision_text}
                  <span class="match-tag" class:protected={file.decision_status === 'protected'} class:processable={file.decision_status === 'processable'}>
                    {file.decision_text}
                  </span>
                {:else}
                  <span class="no-match">—</span>
                {/if}
              </td>
            </tr>
          {/each}

          {#if bottomSpacer > 0}
            <tr style="height: {bottomSpacer}px" aria-hidden="true"></tr>
          {/if}
        </tbody>
      </table>
    </div>

    <div class="table-footer">
      <span>{filteredFiles.length} 个文件</span>
      {#if selectedPaths.size > 0}
        <span class="selected-count">{selectedPaths.size} 已选</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .file-table {
    height: 100%;
    display: flex;
    flex-direction: column;
  }

  .table-fixed {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    flex-shrink: 0;
  }

  .table-body {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
  }
  .table-body table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
  }

  /* ── Filter bar ───────────────────────────── */
  .filter-bar {
    padding: 4px var(--space-lg);
    flex-shrink: 0;
    display: flex;
    align-items: center;
  }
  .filter-bar select {
    font-size: var(--font-size-label);
  }

  /* ── Empty state ──────────────────────────── */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    gap: var(--space-sm);
  }
  .empty-icon {
    font-size: 28px;
    opacity: 0.3;
    margin-bottom: var(--space-md);
  }
  .empty-sub {
    font-size: var(--font-size-label);
    opacity: 0.6;
  }

  /* ── Table ─────────────────────────────────── */
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
  }
  th.sortable { cursor: pointer; }
  th.sortable:hover { color: var(--text-primary); }
  th.active { color: var(--accent); }

  td {
    padding: 5px 8px;
    font-size: var(--font-size-body);
    line-height: 1.45;
    height: 29px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  tbody tr {
    cursor: pointer;
    transition: background var(--duration-fast) var(--ease-expo);
    background: transparent;
  }
  tbody tr.alt { background: rgba(255, 255, 255, 0.015); }
  tbody tr:hover { background: var(--bg-hover); }
  tbody tr.selected { background: var(--bg-selected); }

  /* ── Columns ──────────────────────────────── */
  .col-check { width: 32px; text-align: center; }
  .col-name { width: auto; }
  .col-codec { width: 70px; }
  .col-hdr { width: 72px; }
  .col-res { width: 100px; }
  .col-size { width: 85px; }
  .col-match { width: 110px; }

  .file-name { font-weight: 500; }

  .mono {
    font-family: var(--font-mono);
    font-size: var(--font-size-mono);
    font-variant-numeric: tabular-nums;
    color: var(--text-secondary);
  }
  .col-res .mono { text-align: right; display: block; }
  .col-size .mono { text-align: right; display: block; }

  /* ── Tags ─────────────────────────────────── */
  .codec-tag, .hdr-tag {
    display: inline-block;
    padding: 0 5px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-label);
    font-weight: 600;
    line-height: 1.7;
  }
  .codec-tag.tag-hevc { background: var(--tag-hevc-bg); color: var(--tag-hevc-text); }
  .codec-tag.tag-av1 { background: var(--tag-av1-bg); color: var(--tag-av1-text); }
  .codec-tag.tag-other { background: var(--bg-surface); color: var(--text-secondary); }

  .hdr-tag.tag-dv { background: var(--tag-dv-bg); color: var(--tag-dv-text); }
  .hdr-tag.tag-hdr { background: var(--tag-hdr-bg); color: var(--tag-hdr-text); }
  .hdr-tag.tag-sdr { color: var(--text-muted); }
  .hdr-tag.tag-other { color: var(--text-secondary); }

  .match-tag {
    display: inline-block;
    padding: 0 6px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-label);
    font-weight: 600;
    background: var(--accent-dimmed);
    color: var(--accent);
  }
  .no-match { color: var(--text-muted); }
  .match-tag.protected { color: var(--text-muted); background: var(--bg-surface); }
  .match-tag.processable { color: var(--success); background: rgba(78, 201, 176, 0.08); }

  /* ── Footer ───────────────────────────────── */
  .table-footer {
    display: flex;
    justify-content: space-between;
    padding: 6px 8px;
    border-top: 1px solid var(--border-subtle);
    font-size: var(--font-size-label);
    color: var(--text-secondary);
    flex-shrink: 0;
  }
  .selected-count { color: var(--accent); font-weight: 600; }
</style>
