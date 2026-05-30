<script lang="ts">
  import { onMount } from 'svelte';
  import { files, scanStatus, scanProgress, selectedFilePaths } from '$lib/stores/files';
  import { strategies, selectedStrategy } from '$lib/stores/strategy';
  import { showHistory } from '$lib/stores/history';
  import { selectedLibraryId, selectedFolderId, libraries } from '$lib/stores/library';
  import { queue } from '$lib/stores/queue';
  import { getLibraryFiles, getFolderFiles, scanDirectory, loadStrategies, startEncode } from '$lib/api';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { listen } from '@tauri-apps/api/event';
  import LibraryPanel from '$lib/components/LibraryPanel.svelte';
  import FileTable from '$lib/components/FileTable.svelte';
  import StrategyPanel from '$lib/components/StrategyPanel.svelte';
  import QueuePanel from '$lib/components/QueuePanel.svelte';
  import HistoryPanel from '$lib/components/HistoryPanel.svelte';

  const appWindow = getCurrentWindow();

  let currentPath = '';
  let showQueue = false;

  $: showQueue = $queue.length > 0;

  onMount(async () => {
    listen<{done: number, total: number}>('scan-progress', (event) => {
      scanProgress.set({ done: event.payload.done, total: event.payload.total });
      if (event.payload.done >= event.payload.total && event.payload.total > 0) {
        setTimeout(() => scanProgress.set(null), 1500);
      }
    });

    try {
      const result = await loadStrategies();
      strategies.set(result.strategies);
      if (result.strategies.length > 0) {
        selectedStrategy.set(result.strategies[0]);
      }
    } catch (e) {
      scanStatus.set(`策略加载失败: ${e}`);
    }
    try {
      const result = await getLibraryFiles(0);
      files.set(result.files);
      scanStatus.set(`${result.total_files} 个文件`);
    } catch (_) {}
  });

  $: if ($selectedFolderId) { loadFolderFiles($selectedFolderId); }
  $: if ($selectedLibraryId && !$selectedFolderId) { loadLibraryFiles($selectedLibraryId); }

  async function loadFolderFiles(folderId: number) {
    try {
      const result = await getFolderFiles(folderId);
      files.set(result.files);
      scanStatus.set(`${result.total_files} 个文件`);
    } catch (e) { scanStatus.set(`加载失败: ${e}`); }
  }

  async function loadLibraryFiles(libraryId: number) {
    try {
      const result = await getLibraryFiles(libraryId);
      files.set(result.files);
      scanStatus.set(`${result.total_files} 个文件`);
    } catch (e) { scanStatus.set(`加载失败: ${e}`); }
  }

  async function handleScan(path: string) {
    if (!path) return;
    scanStatus.set('扫描中...');
    try {
      const result = await scanDirectory(path, $selectedFolderId ?? 0);
      files.set(result.files);
      scanStatus.set(`扫描完成: ${result.total_files} 文件, ${result.probe_ok} 成功`);
    } catch (e) { scanStatus.set(`错误: ${e}`); }
  }

  async function handleEncode() {
    const selected = $selectedFilePaths;
    const strategy = $selectedStrategy;
    if (selected.length === 0) { scanStatus.set('请先选择要编码的文件'); return; }
    if (!strategy) { scanStatus.set('请先选择一个压缩策略'); return; }

    scanStatus.set('正在提交编码任务...');
    try {
      const result = await startEncode(selected, strategy.name);
      queue.update(current => {
        const now = [...current];
        for (const filePath of selected) {
          now.push({
            id: `encode-${filePath}-${Date.now()}`,
            fileName: filePath.split(/[/\\]/).pop() || filePath,
            strategyName: strategy.name,
            progress: 0,
            status: 'pending',
            statusText: '排队中'
          });
        }
        return now;
      });
      scanStatus.set(result);
    } catch (e) { scanStatus.set(`错误: ${e}`); }
  }
</script>

<div class="app-shell" class:has-queue={showQueue}>
  <!-- Titlebar: full-width drag region -->
  <div class="titlebar" data-tauri-drag-region>
    <span class="titlebar-title">LeanReel</span>
    <div class="win-controls">
      <button onclick={() => appWindow.minimize()} aria-label="最小化">
        <svg width="10" height="1" viewBox="0 0 10 1"><rect width="10" height="1" fill="currentColor"/></svg>
      </button>
      <button onclick={() => appWindow.toggleMaximize()} aria-label="最大化">
        <svg width="10" height="10" viewBox="0 0 10 10"><rect x="1.5" y="1.5" width="7" height="7" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>
      </button>
      <button class="close-btn" onclick={() => appWindow.close()} aria-label="关闭">
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M 1 1 L 9 9 M 9 1 L 1 9" stroke="currentColor" stroke-width="1.2"/></svg>
      </button>
    </div>
  </div>

  <div class="app-layout">
    <aside class="sidebar">
      <LibraryPanel />
    </aside>

    <main class="content">
      <div class="toolbar">
        <input type="text" placeholder="文件夹路径..." bind:value={currentPath} />
        <button onclick={() => handleScan(currentPath)}>扫描</button>
        {#if $scanProgress}
          <div class="scan-progress">
            <div class="scan-progress-fill" style="width: {$scanProgress.total > 0 ? $scanProgress.done / $scanProgress.total * 100 : 0}%"></div>
          </div>
        {/if}
        <button class="primary" onclick={handleEncode} disabled={$selectedFilePaths.length === 0 || !$selectedStrategy}>
          开始编码
        </button>
        <button class="ghost" onclick={() => showHistory.set(true)}>历史</button>
        <span class="status-text">{$scanStatus}</span>
      </div>
      <div class="file-table-wrapper">
        <FileTable />
      </div>
    </main>

    <aside class="panel">
      <StrategyPanel />
    </aside>
  </div>

  <div class="queue-dock" class:visible={showQueue}>
    <QueuePanel />
  </div>
</div>

{#if $showHistory}
  <HistoryPanel />
{/if}

<style>
  .app-shell {
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: rgba(20, 28, 36, 0.50);
    overflow: hidden;
  }

  /* ── Titlebar ─────────────────────────────── */
  .titlebar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 32px;
    padding: 0 8px 0 12px;
    flex-shrink: 0;
    user-select: none;
  }
  .titlebar-title {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-disabled);
    letter-spacing: 0.02em;
  }

  /* ── Window controls — style A (Win11 native) ── */
  .win-controls {
    display: flex;
    gap: 0;
  }
  .win-controls button {
    width: 46px;
    height: 32px;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 0.1s;
  }
  .win-controls button:hover {
    background: rgba(255, 255, 255, 0.08);
  }
  .win-controls button:active {
    background: rgba(255, 255, 255, 0.12);
  }
  .win-controls .close-btn:hover {
    background: #e81123;
    color: #fff;
  }

  .app-layout {
    display: grid;
    grid-template-columns: 220px 1fr 300px;
    flex: 1;
    overflow: hidden;
  }

  .sidebar {
    background: rgba(255, 255, 255, 0.03);
    border-right: 1px solid var(--border-subtle);
    padding: var(--space-lg);
    overflow-y: auto;
    overflow-x: hidden;
  }

  .content {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .panel {
    background: rgba(255, 255, 255, 0.03);
    border-left: 1px solid var(--border-subtle);
    padding: var(--space-lg);
    overflow-y: auto;
    overflow-x: hidden;
  }

  /* ── Toolbar ──────────────────────────────── */
  .toolbar {
    display: flex;
    gap: var(--space-sm);
    align-items: center;
    padding: var(--space-md) var(--space-lg);
    border-bottom: 1px solid var(--border-subtle);
    flex-shrink: 0;
  }
  .toolbar input {
    flex: 1;
    max-width: 360px;
  }
  .status-text {
    flex: 1;
    text-align: right;
    font-size: var(--font-size-label);
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* ── File table ───────────────────────────── */
  .file-table-wrapper {
    flex: 1;
    overflow: hidden;
    padding: 0 var(--space-lg);
  }

  .scan-progress { width: 100px; height: 3px; background: var(--border-subtle); border-radius: 2px; overflow: hidden; flex-shrink: 0; }
  .scan-progress-fill { height: 100%; background: var(--accent); transition: width 0.3s var(--ease-expo); }

  /* ── Queue dock ───────────────────────────── */
  .queue-dock {
    height: 0;
    overflow: hidden;
    border-top: 1px solid transparent;
    background: rgba(20, 28, 36, 0.85);
    transition:
      height var(--duration-normal) var(--ease-expo),
      border-color var(--duration-normal) var(--ease-expo);
  }
  .queue-dock.visible {
    height: 200px;
    border-top-color: var(--border-subtle);
  }
</style>
