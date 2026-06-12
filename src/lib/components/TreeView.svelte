<script lang="ts">
  // import { VirtualList } from 'svelte-virtuallists';
  import { selectedFilePaths } from '$lib/stores/files';
  import { addSelectionRange } from '$lib/selection.js';
  import { getFolderNodeRefreshId } from '$lib/treeNodes.js';
  import type { FileEntry } from '$lib/stores/files';
  import Select from './Select.svelte';

  let {
    files = [] as FileEntry[],
    viewMode = 'tree',
    filterKey = 'all',
    onViewChange = (_v: string) => {},
    onFilterChange = (_v: string) => {},
    onRefreshFolder = async (_folderId: number) => {},
  } = $props();

  let selectedPaths = $derived(new Set($selectedFilePaths));
  let selectionAnchorKey: string | null = null;

  interface TreeNode {
    key: string;
    name: string;
    depth: number;
    isFolder: boolean;
    file?: FileEntry;
    totalSize: number;
    fileCount: number;
    children: TreeNode[];
    folderId?: number;
    expanded?: boolean;
  }

  let expandedFolders = $state(new Set<string>());
  let flatNodes = $state<TreeNode[]>([]);
  let allSelected = $state(false);
  let contextMenu = $state<{ x: number; y: number; folderId: number } | null>(null);
  let visibleFiles = $derived(flatNodes.flatMap(node => node.file ? [node.file] : []));

  type SortKey = 'name' | 'codec' | 'hdr' | 'resolution' | 'size' | 'count';
  let sortKey = $state<SortKey>('name');
  let sortAsc = $state(true);

  let filteredFiles = $derived(files.filter(f => {
    if (filterKey === 'all') return true;
    if (filterKey === 'checked') return selectedPaths.has(f.key);
    if (f.decision_status) {
      if (filterKey === 'processable') return f.decision_status === 'processable';
      if (filterKey === 'protected') return f.decision_status === 'protected';
      if (filterKey === 'probe_failed') return f.decision_status === 'probe_failed';
    }
    return true;
  }));
  let sortedFiles = $derived(sortFiles(filteredFiles, sortKey, sortAsc));

  function formatSize(bytes: number): string {
    if (bytes >= 1_000_000_000) return (bytes / 1_000_000_000).toFixed(1) + ' GB';
    if (bytes >= 1_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB';
    if (bytes >= 1_000) return (bytes / 1_000).toFixed(1) + ' KB';
    return bytes + ' B';
  }
  $effect(() => {
    const tree = buildTree(sortedFiles);
    sortTree(tree, sortKey, sortAsc);
    expandState(tree);
    flatNodes = flattenTree(tree);
  });

  function sortTree(nodes: TreeNode[], key: SortKey, asc: boolean) {
    nodes.sort((a, b) => {
      let va: number; let vb: number;
      switch (key) {
        case 'name': return asc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        case 'size': va = a.totalSize; vb = b.totalSize; break;
        case 'count': va = a.fileCount; vb = b.fileCount; break;
        default: return 0;
      }
      return asc ? va - vb : vb - va;
    });
    for (const node of nodes) {
      if (node.children.length > 0) sortTree(node.children, key, asc);
    }
  }
  let selectableFiles = $derived(files.filter(isSelectable));
  $effect(() => {
    allSelected = selectableFiles.length > 0 && selectableFiles.every(file => selectedPaths.has(file.key));
  });

  function sortFiles(list: FileEntry[], key: SortKey, asc: boolean): FileEntry[] {
    return [...list].sort((a, b) => {
      let va: string | number;
      let vb: string | number;
      switch (key) {
        case 'name': va = a.name; vb = b.name; break;
        case 'codec': va = a.codec || ''; vb = b.codec || ''; break;
        case 'hdr': va = a.hdr || ''; vb = b.hdr || ''; break;
        case 'resolution': va = (a.width && a.height) ? a.width * a.height : 0; vb = (b.width && b.height) ? b.width * b.height : 0; break;
        case 'size': va = a.size; vb = b.size; break;
        case 'count': return 0;
        default: return 0;
      }
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
  }

  function computeAggregates(node: TreeNode): { size: number; count: number } {
    if (!node.isFolder) {
      return { size: node.file?.size || 0, count: 1 };
    }
    let totalSize = 0;
    let totalCount = 0;
    for (const child of node.children) {
      const agg = computeAggregates(child);
      totalSize += agg.size;
      totalCount += agg.count;
    }
    node.totalSize = totalSize;
    node.fileCount = totalCount;
    return { size: totalSize, count: totalCount };
  }

  function buildTree(fileList: FileEntry[]): TreeNode[] {
    if (fileList.length === 0) return [];
    const roots: TreeNode[] = [];
    const folderMap = new Map<string, TreeNode>();

    for (const f of fileList) {
      const normalized = f.path.replace(/\\/g, '/');
      const parts = normalized.split('/');
      const fileName = parts[parts.length - 1];
      const folders = parts.length > 1 ? parts.slice(0, -1) : ['(根目录)'];
      let children = roots;
      const accumulated: string[] = [];

      for (const folder of folders) {
        accumulated.push(folder);
        const folderKey = `folder:${f.folder_id}:${accumulated.join('/')}`;
        let node = folderMap.get(folderKey);
        if (!node) {
          node = {
            key: folderKey,
            name: folder,
            depth: accumulated.length - 1,
            isFolder: true,
            totalSize: 0,
            fileCount: 0,
            children: [],
            folderId: f.folder_id,
          };
          folderMap.set(folderKey, node);
          children.push(node);
        }
        children = node.children;
      }

      const fileNode: TreeNode = {
        key: `file:${f.key}`, name: fileName, depth: folders.length,
        isFolder: false, file: f, totalSize: f.size, fileCount: 1, children: [],
      };
      children.push(fileNode);
    }

    for (const node of roots) computeAggregates(node);
    return roots;
  }

  function expandState(nodes: TreeNode[]) {
    for (const node of nodes) {
      node.expanded = expandedFolders.has(node.key);
      if (node.children.length > 0) expandState(node.children);
    }
  }

  function flattenTree(nodes: TreeNode[]): TreeNode[] {
    const result: TreeNode[] = [];
    for (const node of nodes) {
      result.push(node);
      if (node.isFolder && node.expanded) {
        result.push(...flattenTree(node.children));
      }
    }
    return result;
  }

  function toggleFolder(key: string) {
    const next = new Set(expandedFolders);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    expandedFolders = next;
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) sortAsc = !sortAsc;
    else { sortKey = key; sortAsc = true; }
    expandedFolders = new Set();
  }

  function sortArrow(key: SortKey): string {
    if (sortKey !== key) return '';
    return sortAsc ? ' ▴' : ' ▾';
  }

  function toggleSelectAll() {
    selectedFilePaths.update(current => {
      const next = new Set(current);
      if (allSelected) selectableFiles.forEach(file => next.delete(file.key));
      else selectableFiles.forEach(file => next.add(file.key));
      return [...next];
    });
  }

  function isSelectable(file: FileEntry): boolean {
    return file.decision_status === 'processable';
  }

  function toggleFile(file: FileEntry, event?: MouseEvent) {
    if (!isSelectable(file)) return;
    if (event?.shiftKey && selectionAnchorKey !== null) {
      selectedFilePaths.set(addSelectionRange(visibleFiles, $selectedFilePaths, selectionAnchorKey, file.key));
    } else {
      const next = new Set(selectedPaths);
      if (next.has(file.key)) next.delete(file.key);
      else next.add(file.key);
      selectedFilePaths.set([...next]);
    }
    selectionAnchorKey = file.key;
  }

  // Shared helpers — same as FileTable
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
  function resDisplay(file: FileEntry): string {
    if (file.width && file.height) return `${file.width} × ${file.height}`;
    return '—';
  }
</script>

<div class="tree-view">
  {#if files.length === 0}
    <div class="empty-state">
      <span class="empty-icon">□</span>
      <p>暂无文件</p>
      <p class="empty-sub">新建库并添加文件夹后，文件将显示在此处</p>
    </div>
  {:else}
    <div class="filter-bar">
      <Select value={viewMode}
        options={[{ value: 'flat', label: '平铺视图' }, { value: 'tree', label: '目录树视图' }]}
        onChange={(v) => onViewChange(v)}
      />
      <Select value={filterKey}
        options={[
          { value: 'all', label: `全部 (${files.length})` },
          { value: 'processable', label: '可处理' },
          { value: 'protected', label: '受保护' },
          { value: 'probe_failed', label: '探测失败' },
          { value: 'checked', label: '已勾选' },
        ]}
        onChange={(v) => onFilterChange(v)}
      />
    </div>
    <table class="table-fixed">
      <thead>
        <tr>
          <th class="col-check"><input type="checkbox" checked={allSelected} onchange={toggleSelectAll} /></th>
          <th class="col-name sortable" class:active={sortKey === 'name'} onclick={() => toggleSort('name')}>名称{sortArrow('name')}</th>
          <th class="col-size sortable" class:active={sortKey === 'size'} onclick={() => toggleSort('size')}>大小{sortArrow('size')}</th>
          <th class="col-count sortable" class:active={sortKey === 'count'} onclick={() => toggleSort('count')}>文件数</th>
        </tr>
      </thead>
    </table>
    <div class="tree-body" style="overflow-y:auto">
      <!-- DEBUG: flatNodes={flatNodes.length}, files={files.length} -->
      {#each flatNodes as node (node.key)}
        {#if node.isFolder}
          <div
            class="tree-row folder-row"
            role="button" tabindex="0"
            onclick={() => toggleFolder(node.key)}
            oncontextmenu={(e) => {
              e.preventDefault();
              const folderId = getFolderNodeRefreshId(node);
              if (folderId !== null) contextMenu = { x: e.clientX, y: e.clientY, folderId };
            }}
            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleFolder(node.key); } }}
          >
            <span class="col-check"></span>
            <span class="col-name"><span class="folder-arrow">{node.expanded ? '▾' : '▸'}</span><span class="folder-name">{node.name}</span></span>
            <span class="col-size"><span class="mono">{formatSize(node.totalSize)}</span></span>
            <span class="col-count">{node.fileCount} 个文件</span>
          </div>
        {:else if node.file}
          {@const file = node.file}
          <!-- DO NOT CHANGE: padding-left pixel-aligned with folder name first character -->
          <div
            class="tree-row file-row"
             class:selected={selectedPaths.has(file.key)}
             style="padding-left: {node.depth * 16 + 34}px"
             onclick={(e) => toggleFile(file, e)}
          >
            <span class="col-check" onclick={(e) => e.stopPropagation()}>
              <input type="checkbox" checked={selectedPaths.has(file.key)} disabled={!isSelectable(file)} onclick={(e) => { e.stopPropagation(); toggleFile(file, e); }} />
            </span>
            <span class="col-name" title={file.path}><span class="file-name">{file.name}</span></span>
            <span class="col-codec"><span class="codec-tag {codecTagClass(file.codec || '')}">{file.codec || '—'}</span></span>
            <span class="col-hdr"><span class="hdr-tag {hdrTagClass(file.hdr || '')}">{file.hdr || 'SDR'}</span></span>
            <span class="col-res"><span class="mono">{resDisplay(file)}</span></span>
            <span class="col-size"><span class="mono">{file.size_display}</span></span>
          </div>
        {/if}
      {/each}
    </div>

    <div class="tree-footer">
      <span>{files.length} 个文件</span>
      {#if selectedPaths.size > 0}
        <span class="selected-count">{selectedPaths.size} 已选</span>
      {/if}
    </div>
  {/if}
</div>

{#if contextMenu}
  <div class="context-overlay" role="presentation" onclick={() => contextMenu = null} onkeydown={(e) => e.key === 'Escape' && (contextMenu = null)}>
    <div class="context-menu" style="left: {contextMenu.x}px; top: {contextMenu.y}px">
      <button onclick={() => { const menu = contextMenu; contextMenu = null; if (menu) onRefreshFolder(menu.folderId); }}>
        刷新所在文件夹缓存
      </button>
    </div>
  </div>
{/if}

<style>
  .tree-view { height: 100%; display: flex; flex-direction: column; }
  .filter-bar { display: flex; align-items: center; gap: var(--space-sm); padding: 4px var(--space-lg); flex-shrink: 0; }
  .tree-body { flex: 1; overflow: hidden; }

  .table-fixed {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    flex-shrink: 0;
  }
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

  .tree-row {
    display: flex;
    align-items: center;
    height: 29px;
    padding-left: 8px;
    padding-right: 8px;
    cursor: pointer;
    font-size: var(--font-size-body);
    transition: background var(--duration-fast) var(--ease-expo);
    outline: none;
  }
  .tree-row:hover { background: var(--bg-hover); }
  .tree-row.selected { background: var(--bg-selected); }
  .folder-row { font-weight: 500; color: var(--text-secondary); }
  .folder-arrow { width: 14px; font-size: 10px; flex-shrink: 0; color: var(--text-muted); }
  .folder-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .folder-count { font-size: var(--font-size-label); color: var(--text-muted); }

  .file-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* Column widths */
  .col-check { width: 32px; text-align: center; flex-shrink: 0; }
  .col-name { flex: 1; display: flex; align-items: center; gap: 4px; min-width: 0; }
  .col-codec { width: 70px; flex-shrink: 0; }
  .col-hdr { width: 72px; flex-shrink: 0; }
  .col-res { width: 100px; flex-shrink: 0; }
  .col-size { width: 85px; flex-shrink: 0; }
  .col-count { width: 80px; flex-shrink: 0; color: var(--text-secondary); font-size: var(--font-size-label); }

  /* Same tags as FileTable */
  .codec-tag, .hdr-tag {
    display: inline-block; padding: 0 5px; border-radius: var(--radius-sm);
    font-size: var(--font-size-label); font-weight: 600; line-height: 1.7;
  }
  .codec-tag.tag-hevc { background: var(--tag-hevc-bg); color: var(--tag-hevc-text); }
  .codec-tag.tag-av1 { background: var(--tag-av1-bg); color: var(--tag-av1-text); }
  .codec-tag.tag-other { background: var(--bg-surface); color: var(--text-secondary); }
  .hdr-tag.tag-dv { background: var(--tag-dv-bg); color: var(--tag-dv-text); }
  .hdr-tag.tag-hdr { background: var(--tag-hdr-bg); color: var(--tag-hdr-text); }
  .hdr-tag.tag-sdr { background: var(--tag-sdr-bg); color: var(--tag-sdr-text); }
  .hdr-tag.tag-other { color: var(--text-secondary); }

  .mono {
    font-family: var(--font-mono);
    font-size: var(--font-size-mono);
    color: var(--text-secondary);
  }

  .tree-footer {
    display: flex; justify-content: space-between;
    padding: 6px 8px; border-top: 1px solid var(--border-subtle);
    font-size: var(--font-size-label); color: var(--text-secondary); flex-shrink: 0;
  }
  .selected-count { color: var(--accent); font-weight: 600; }

  .empty-state {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 100%; color: var(--text-muted); gap: var(--space-sm);
  }
  .empty-icon { font-size: 28px; opacity: 0.3; margin-bottom: var(--space-md); }
  .empty-sub { font-size: var(--font-size-label); opacity: 0.6; }

  .context-overlay { position: fixed; inset: 0; z-index: 9999; }
  .context-menu {
    position: fixed;
    background: rgba(18, 22, 28, 0.95);
    backdrop-filter: blur(20px);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 4px;
    min-width: 150px;
  }
  .context-menu button {
    display: block;
    width: 100%;
    padding: 6px 12px;
    text-align: left;
    font-size: var(--font-size-body);
    border: none;
    background: transparent;
    color: var(--text-primary);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .context-menu button:hover { background: var(--bg-hover); }
</style>
