<script lang="ts">
  import { VirtualList } from 'svelte-virtuallists';
  import { files, selectedFilePaths } from '$lib/stores/files';
  import type { FileEntry } from '$lib/stores/files';

  let selectedPaths: Set<string> = new Set();
  let allSelected = false;
  let lastClickedIndex: number | null = null;

  $: selectedFilePaths.set([...selectedPaths]);

  interface TreeNode {
    key: string;
    name: string;
    depth: number;
    isFolder: boolean;
    file?: FileEntry;
    expanded: boolean;
    childCount: number;
    children: TreeNode[];
  }

  let collapsedFolders = new Set<string>();
  let flatNodes: TreeNode[] = [];

  // Sorting
  type SortKey = 'name' | 'codec' | 'hdr' | 'resolution' | 'size';
  let sortKey: SortKey = 'name';
  let sortAsc = true;

  $: sortedFiles = sortFiles($files, sortKey, sortAsc);
  $: {
    const tree = buildTree(sortedFiles);
    flatNodes = flattenTree(tree);
  }

  function sortFiles(list: FileEntry[], key: SortKey, asc: boolean): FileEntry[] {
    const sorted = [...list].sort((a, b) => {
      let va: string | number;
      let vb: string | number;
      switch (key) {
        case 'name': va = a.name; vb = b.name; break;
        case 'codec': va = a.codec || ''; vb = b.codec || ''; break;
        case 'hdr': va = a.hdr || ''; vb = b.hdr || ''; break;
        case 'resolution': va = (a.width && a.height) ? a.width * a.height : 0; vb = (b.width && b.height) ? b.width * b.height : 0; break;
        case 'size': va = a.size; vb = b.size; break;
        default: return 0;
      }
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
    return sorted;
  }

  function buildTree(fileList: FileEntry[]): TreeNode[] {
    // Group files by folder prefix
    const folderMap = new Map<string, FileEntry[]>();
    for (const f of fileList) {
      const parts = f.path.split('/');
      parts.pop(); // remove filename
      const folder = parts.join('/');
      if (!folderMap.has(folder)) folderMap.set(folder, []);
      folderMap.get(folder)!.push(f);
    }

    const root: TreeNode[] = [];
    // Sort folders by path depth then alphabetically
    const sortedFolders = [...folderMap.keys()].sort((a, b) => {
      const depthA = a.split('/').length;
      const depthB = b.split('/').length;
      if (depthA !== depthB) return depthA - depthB;
      return a.localeCompare(b);
    });

    for (const folder of sortedFolders) {
      const folderFiles = folderMap.get(folder)!;
      // Create file child nodes
      const fileNodes: TreeNode[] = folderFiles.map((f) => ({
        key: f.path,
        name: f.name,
        depth: 1,
        isFolder: false,
        file: f,
        expanded: false,
        childCount: 0,
        children: [],
      }));

      const folderDepth = folder ? folder.split('/').length : 0;
      const node: TreeNode = {
        key: folder || '__root__',
        name: folder || '(根目录)',
        depth: folderDepth,
        isFolder: true,
        expanded: !collapsedFolders.has(folder),
        childCount: folderFiles.length,
        children: fileNodes,
      };
      root.push(node);
    }

    return root;
  }

  function flattenTree(nodes: TreeNode[]): TreeNode[] {
    const result: TreeNode[] = [];
    for (const node of nodes) {
      result.push(node);
      if (node.isFolder && node.expanded) {
        for (const child of node.children) {
          result.push(child);
        }
      }
    }
    return result;
  }

  function toggleFolder(key: string) {
    if (collapsedFolders.has(key)) {
      collapsedFolders.delete(key);
    } else {
      collapsedFolders.add(key);
    }
    collapsedFolders = collapsedFolders;
    // Triggers reactive rebuild via the $: block
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) { sortAsc = !sortAsc; }
    else { sortKey = key; sortAsc = true; }
    collapsedFolders = new Set(collapsedFolders);
  }

  function sortArrow(key: SortKey): string {
    if (sortKey !== key) return '';
    return sortAsc ? ' ▴' : ' ▾';
  }

  function toggleSelectAll() {
    if (allSelected) { selectedPaths = new Set(); allSelected = false; }
    else { selectedPaths = new Set($files.map(f => f.path)); allSelected = true; }
  }

  function toggleFile(path: string, index?: number, event?: MouseEvent) {
    if (event?.shiftKey && lastClickedIndex !== null && index !== undefined) {
      const start = Math.min(lastClickedIndex, index);
      const end = Math.max(lastClickedIndex, index);
      const next = new Set(selectedPaths);
      for (let i = start; i <= end; i++) {
        const node = flatNodes[i];
        if (node && !node.isFolder && node.file) next.add(node.file.path);
      }
      selectedPaths = next;
    } else {
      const next = new Set(selectedPaths);
      if (next.has(path)) { next.delete(path); } else { next.add(path); }
      selectedPaths = next;
    }
    if (index !== undefined) lastClickedIndex = index;
    allSelected = selectedPaths.size === $files.length && $files.length > 0;
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

  function resDisplay(file: FileEntry): string {
    if (file.width && file.height) return `${file.width} × ${file.height}`;
    return '—';
  }

  function onFolderKeydown(key: string, e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleFolder(key);
    }
  }

  export function getSelectedPaths(): string[] { return [...selectedPaths]; }
</script>

<div class="tree-view">
  {#if $files.length === 0}
    <div class="empty-state">
      <span class="empty-icon">□</span>
      <p>暂无文件</p>
      <p class="empty-sub">新建库并添加文件夹后，文件将显示在此处</p>
    </div>
  {:else}
    <div class="tree-header">
      <div class="tree-header-left">
        <input type="checkbox" checked={allSelected} onchange={toggleSelectAll} />
        <span class="tree-stats">{$files.length} 个文件 / {flatNodes.filter(n => n.isFolder).length} 个文件夹</span>
      </div>
      <span class="tree-sort">
        排序:
        <button class:active={sortKey === 'name'} onclick={() => toggleSort('name')}>名称{sortArrow('name')}</button>
        <button class:active={sortKey === 'codec'} onclick={() => toggleSort('codec')}>编码{sortArrow('codec')}</button>
        <button class:active={sortKey === 'hdr'} onclick={() => toggleSort('hdr')}>HDR{sortArrow('hdr')}</button>
        <button class:active={sortKey === 'resolution'} onclick={() => toggleSort('resolution')}>分辨率{sortArrow('resolution')}</button>
        <button class:active={sortKey === 'size'} onclick={() => toggleSort('size')}>大小{sortArrow('size')}</button>
      </span>
    </div>

    <div class="tree-body">
      <VirtualList items={flatNodes} sizingCalculator={() => 29}>
        {#snippet vl_slot(slot)}
          {@const node = slot.item as TreeNode}
          {@const idx = slot.index as number}
          {#if node.isFolder}
            <div
              class="tree-row folder-row"
              role="button"
              tabindex="0"
              style="padding-left: {node.depth * 16 + 8}px"
              onclick={() => toggleFolder(node.key)}
              onkeydown={(e) => onFolderKeydown(node.key, e)}
            >
              <span class="folder-arrow">{node.expanded ? '▾' : '▸'}</span>
              <span class="folder-name">{node.name}</span>
              <span class="folder-count">{node.childCount} 个文件</span>
            </div>
          {:else if node.file}
            {@const file = node.file}
            <div
              class="tree-row file-row"
              class:selected={selectedPaths.has(file.path)}
              role="option"
              tabindex="0"
              aria-selected={selectedPaths.has(file.path)}
              style="padding-left: {node.depth * 16 + 28}px"
              onclick={(e) => toggleFile(file.path, idx, e)}
              onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleFile(file.path, idx); } }}
            >
              <span class="file-check" role="presentation" onclick={(e) => e.stopPropagation()} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.stopPropagation(); }}>
                <input type="checkbox" checked={selectedPaths.has(file.path)} onchange={() => toggleFile(file.path)} />
              </span>
              <span class="file-name">{file.name}</span>
              <span class="col-codec"><span class="codec-tag {codecTagClass(file.codec || '')}">{file.codec || '—'}</span></span>
              <span class="col-hdr"><span class="hdr-tag {hdrTagClass(file.hdr || '')}">{file.hdr || 'SDR'}</span></span>
              <span class="col-res"><span class="mono">{resDisplay(file)}</span></span>
              <span class="col-size"><span class="mono">{file.size_display}</span></span>
            </div>
          {/if}
        {/snippet}
      </VirtualList>
    </div>

    <div class="tree-footer">
      <span>{$files.length} 个文件</span>
      {#if selectedPaths.size > 0}
        <span class="selected-count">{selectedPaths.size} 已选</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .tree-view {
    height: 100%;
    display: flex;
    flex-direction: column;
  }

  .tree-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px var(--space-lg);
    font-size: var(--font-size-label);
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border-subtle);
    flex-shrink: 0;
    gap: var(--space-md);
  }
  .tree-header-left {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }
  .tree-header button {
    font-size: var(--font-size-label);
    padding: 2px 6px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    border-radius: var(--radius-sm);
  }
  .tree-header button:hover { color: var(--text-primary); background: var(--bg-hover); }
  .tree-header button.active { color: var(--accent); }
  .tree-sort { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }

  .tree-body {
    flex: 1;
    overflow: hidden;
  }

  .tree-row {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 29px;
    padding-right: 8px;
    cursor: pointer;
    font-size: var(--font-size-body);
    transition: background var(--duration-fast) var(--ease-expo);
    outline: none;
  }
  .tree-row:hover { background: var(--bg-hover); }
  .tree-row.selected { background: var(--bg-selected); }
  .tree-row:focus-visible { box-shadow: inset 0 0 0 1px var(--accent-dimmed); }

  .folder-row {
    font-weight: 500;
    color: var(--text-secondary);
  }
  .folder-arrow {
    width: 14px;
    font-size: 10px;
    flex-shrink: 0;
    color: var(--text-muted);
  }
  .folder-name {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .folder-count {
    font-size: var(--font-size-label);
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .file-check {
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }
  .file-name {
    flex: 1;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

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
  .hdr-tag.tag-sdr { background: var(--tag-sdr-bg); color: var(--tag-sdr-text); }
  .hdr-tag.tag-other { color: var(--text-secondary); }

  .col-codec { width: 70px; flex-shrink: 0; }
  .col-hdr { width: 72px; flex-shrink: 0; }
  .col-res { width: 100px; flex-shrink: 0; }
  .col-size { width: 85px; flex-shrink: 0; }

  .mono {
    font-family: var(--font-mono);
    font-size: var(--font-size-mono);
    color: var(--text-secondary);
  }

  .tree-footer {
    display: flex;
    justify-content: space-between;
    padding: 6px 8px;
    border-top: 1px solid var(--border-subtle);
    font-size: var(--font-size-label);
    color: var(--text-secondary);
    flex-shrink: 0;
  }
  .selected-count { color: var(--accent); font-weight: 600; }

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
</style>
