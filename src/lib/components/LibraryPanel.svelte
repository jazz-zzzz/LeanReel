<script lang="ts">
  import { onMount } from 'svelte';
  import { libraries, selectedLibraryId, selectedFolderId } from '$lib/stores/library';
  import { scanStatus } from '$lib/stores/files';
  import { open } from '@tauri-apps/plugin-dialog';
  import { createLibrary, deleteLibrary, listLibraries, addFolder, removeFolder, type ScanResult } from '$lib/api';
  import { formatAddFolderStatus, scanErrorMessage } from '$lib/scanProgress.js';

  type RefreshFolderResult =
    | { ok: true; result: ScanResult }
    | { ok: false; error: string };

  let {
    onRefreshFolder = async (_folderId: number): Promise<RefreshFolderResult> => ({ ok: false, error: '未配置刷新处理器' }),
  } = $props();

  let expandedLibs = $state(new Set<number>());
  let status = $state('');
  let pending = $state(false);
  let showSearch = $state(false);
  let searchText = $state('');
  let contextMenu = $state<{ x: number; y: number; folderId: number; libId: number } | null>(null);

  async function handleRefreshFolder(folderId: number) {
    pending = true;
    try {
      const result = await onRefreshFolder(folderId);
      if (!result.ok) {
        status = `刷新失败: ${result.error}`;
        scanStatus.set(status);
      }
    } catch (e) {
      status = `刷新失败: ${scanErrorMessage(e)}`;
      scanStatus.set(status);
    } finally {
      pending = false;
    }
  }

  function showContextMenu(e: MouseEvent, folderId: number, libId: number) {
    contextMenu = { x: e.clientX, y: e.clientY, folderId, libId };
  }

  onMount(async () => { await refreshLibraries(); });

  async function refreshLibraries() {
    try {
      const result = await listLibraries();
      libraries.set(result);
    } catch (e) { status = `加载失败: ${e}`; }
  }

  let showCreateDialog = $state(false);
  let newLibName = $state('');

  function openCreateDialog() { newLibName = ''; showCreateDialog = true; }
  function closeCreateDialog() { showCreateDialog = false; }

  async function confirmCreateLibrary() {
    const name = newLibName.trim();
    if (!name) return;
    showCreateDialog = false;
    pending = true;
    try {
      await createLibrary(name);
      await refreshLibraries();
      status = `已创建: ${name}`;
    } catch (e) { status = `创建失败: ${e}`; }
    finally { pending = false; }
  }

  async function openAddFolder(libId: number) {
    const selected = await open({ directory: true, multiple: false, title: '选择文件夹' });
    if (!selected) return;
    pending = true;
    try {
      const folderId = await addFolder(libId, selected);
      await refreshLibraries();
      const refreshResult = await onRefreshFolder(folderId);
      status = formatAddFolderStatus(selected, refreshResult);
      scanStatus.set(status);
    } catch (e) {
      status = `添加失败: ${scanErrorMessage(e)}`;
      scanStatus.set(status);
    }
    finally { pending = false; }
  }

  async function handleDeleteLibrary(libId: number, libName: string) {
    pending = true;
    try {
      await deleteLibrary(libId);
      if ($selectedLibraryId === libId) selectedLibraryId.set(null);
      expandedLibs = new Set(expandedLibs);
      expandedLibs.delete(libId);
      expandedLibs = new Set(expandedLibs);
      await refreshLibraries();
    } catch (e) { status = `删除失败: ${e}`; }
    finally { pending = false; }
  }

  async function handleRemoveFolder(libId: number, folderId: number, folderPath: string) {
    pending = true;
    try {
      await removeFolder(libId, folderId);
      if ($selectedFolderId === folderId) selectedFolderId.set(null);
      await refreshLibraries();
    } catch (e) { status = `移除失败: ${e}`; }
    finally { pending = false; }
  }

  function toggleExpand(libId: number) {
    const next = new Set(expandedLibs);
    if (next.has(libId)) next.delete(libId);
    else next.add(libId);
    expandedLibs = next;
  }

  function selectLibrary(libId: number) {
    selectedLibraryId.set(libId);
    selectedFolderId.set(null);
  }

  function selectFolder(folderId: number) {
    selectedFolderId.set(folderId);
  }

  let filteredLibs = $derived(searchText
    ? $libraries.filter(lib => {
        const matchLib = lib.name.toLowerCase().includes(searchText.toLowerCase());
        const matchFolder = lib.folders.some(f => f.path.toLowerCase().includes(searchText.toLowerCase()));
        return matchLib || matchFolder;
      })
    : $libraries);
</script>

<div class="library-panel">
  <div class="panel-top">
    <h2>库</h2>
    <div class="top-actions">
      <button class="ghost icon-btn" onclick={() => showSearch = !showSearch} title="搜索" aria-label="搜索库和文件夹">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
      </button>
    </div>
  </div>

  {#if showSearch}
    <input
      type="text"
      class="search-input"
      placeholder="搜索库或文件夹..."
      bind:value={searchText}
    />
  {/if}

  <button class="create-btn" onclick={openCreateDialog} disabled={pending}>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
    新建库
  </button>

  {#if status}
    <p class="status-text">{status}</p>
  {/if}

  {#if filteredLibs.length === 0}
    <p class="empty-hint">{searchText ? '无匹配结果' : '新建一个库开始'}</p>
  {:else}
    <div class="lib-list">
      {#each filteredLibs as lib (lib.id)}
        <div class="lib-item">
          <div
            class="lib-row"
            class:selected={$selectedLibraryId === lib.id}
            role="button"
            tabindex="0"
            onclick={() => selectLibrary(lib.id)}
            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') selectLibrary(lib.id); }}
          >
            <button
              class="ghost expand-btn"
              onclick={(e) => { e.stopPropagation(); toggleExpand(lib.id); }}
              aria-label={expandedLibs.has(lib.id) ? '折叠' : '展开'}
            >
              <span class="arrow">{expandedLibs.has(lib.id) ? '▾' : '▸'}</span>
            </button>
            <span class="lib-name">{lib.name}</span>
            <button
              class="ghost icon-btn delete-btn"
              onclick={(e) => { e.stopPropagation(); handleDeleteLibrary(lib.id, lib.name); }}
              disabled={pending}
              title="删除库"
              aria-label="删除库"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <path d="M18 6 6 18M6 6l12 12"/>
              </svg>
            </button>
          </div>

          {#if expandedLibs.has(lib.id)}
            <div class="folder-list">
              {#each lib.folders as folder (folder.id)}
                <div
                  class="folder-row"
                  class:selected={$selectedFolderId === folder.id}
                  role="button"
                  tabindex="0"
                  onclick={() => selectFolder(folder.id)}
                  oncontextmenu={(e) => { e.preventDefault(); showContextMenu(e, folder.id, lib.id); }}
                  onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') selectFolder(folder.id); }}
                >
                  <span class="folder-icon">▸</span>
                  <span class="folder-path" title={folder.path}>{folder.path}</span>
                  <button
                    class="ghost icon-btn delete-btn"
                    onclick={(e) => { e.stopPropagation(); handleRemoveFolder(lib.id, folder.id, folder.path); }}
                    disabled={pending}
                    title="移除文件夹"
                    aria-label="移除文件夹"
                  >
                    <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                      <path d="M18 6 6 18M6 6l12 12"/>
                    </svg>
                  </button>
                </div>
              {/each}

              <button class="add-folder-btn" onclick={() => openAddFolder(lib.id)} disabled={pending}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
                添加文件夹
              </button>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

{#if contextMenu}
  <div class="context-overlay" onclick={() => contextMenu = null} onkeydown={(e) => e.key === 'Escape' && (contextMenu = null)}>
    <div class="context-menu" style="left: {contextMenu.x}px; top: {contextMenu.y}px">
      <button onclick={() => { const menu = contextMenu; contextMenu = null; if (menu) handleRefreshFolder(menu.folderId); }}>
        刷新缓存
      </button>
    </div>
  </div>
{/if}

{#if showCreateDialog}
  <div class="dialog-overlay" onclick={closeCreateDialog} onkeydown={(e) => e.key === 'Escape' && closeCreateDialog()}>
    <div class="dialog-box" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.key === 'Enter' && confirmCreateLibrary()}>
      <h3>新建库</h3>
      <input type="text" placeholder="输入库名称..." bind:value={newLibName} autofocus />
      <div class="dialog-actions">
        <button class="ghost" onclick={closeCreateDialog}>取消</button>
        <button class="primary" onclick={confirmCreateLibrary} disabled={!newLibName.trim()}>创建</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .library-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    gap: var(--space-sm);
  }

  .panel-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  h2 {
    font-size: var(--font-size-label);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
  }

  .top-actions { display: flex; gap: 2px; }

  .icon-btn {
    width: 24px; height: 24px;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    color: var(--text-secondary);
  }
  .icon-btn:hover { color: var(--text-primary); }

  .search-input {
    font-size: var(--font-size-label);
  }

  .create-btn, .add-folder-btn {
    display: flex; align-items: center; gap: 5px;
    width: 100%; padding: 5px 8px;
    font-size: var(--font-size-label); color: var(--text-secondary);
    border: 1px dashed var(--border-default); border-radius: var(--radius-sm);
    background: transparent; cursor: pointer;
  }
  .create-btn:hover, .add-folder-btn:hover { color: var(--text-primary); border-color: var(--border-focus); background: var(--bg-hover); }
  .create-btn:disabled, .add-folder-btn:disabled { opacity: 0.35; cursor: not-allowed; }

  .status-text {
    font-size: var(--font-size-sm);
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .empty-hint {
    font-size: var(--font-size-label);
    color: var(--text-muted);
    text-align: center;
    padding: var(--space-2xl) 0;
  }

  .lib-list {
    display: flex;
    flex-direction: column;
    gap: 1px;
    flex: 1;
    overflow-y: auto;
  }

  .lib-row {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 4px 4px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--duration-fast) var(--ease-expo);
  }
  .lib-row:hover { background: var(--bg-hover); }
  .lib-row.selected { background: var(--bg-selected); }

  .expand-btn {
    width: 18px; height: 18px;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--text-muted);
    font-size: 10px;
    flex-shrink: 0;
  }
  .expand-btn:hover { color: var(--text-primary); }

  .arrow {
    display: inline-block;
    font-size: 10px;
    line-height: 1;
  }

  .lib-name {
    flex: 1;
    font-size: var(--font-size-body);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .delete-btn {
    opacity: 0;
    transition: opacity var(--duration-fast) var(--ease-expo);
  }
  .lib-row:hover .delete-btn,
  .folder-row:hover .delete-btn { opacity: 1; }
  .delete-btn:hover { color: var(--danger); }

  .folder-list {
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .folder-row {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 3px 4px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-size: var(--font-size-body);
    transition: background var(--duration-fast) var(--ease-expo);
  }
  .folder-row:hover { background: var(--bg-hover); }
  .folder-row.selected { background: var(--bg-selected); }

  .folder-icon {
    flex-shrink: 0;
    font-size: 8px;
    color: var(--text-muted);
  }

  .folder-path {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-secondary);
    font-size: var(--font-size-body);
  }


  .context-overlay { position: fixed; inset: 0; z-index: 9999; }
  .context-menu { position: fixed; background: rgba(18, 22, 28, 0.95); backdrop-filter: blur(20px); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 4px; min-width: 120px; }
  .context-menu button { display: block; width: 100%; padding: 6px 12px; text-align: left; font-size: var(--font-size-body); border: none; background: transparent; color: var(--text-primary); border-radius: var(--radius-sm); cursor: pointer; }
  .context-menu button:hover { background: var(--bg-hover); }

  .dialog-overlay { position: fixed; inset: 0; z-index: 10000; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; }
  .dialog-box { background: rgba(20,28,36,0.94); backdrop-filter: blur(40px); -webkit-backdrop-filter: blur(40px); border: 1px solid var(--border-default); border-radius: var(--radius-lg); padding: var(--space-xl); min-width: 320px; display: flex; flex-direction: column; gap: var(--space-md); }
  .dialog-box h3 { font-size: var(--font-size-body); font-weight: 600; }
  .dialog-box input { width: 100%; }
  .dialog-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); }
</style>
