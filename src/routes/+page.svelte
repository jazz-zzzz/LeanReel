<script lang="ts">
  import { onMount } from 'svelte';
  import { files, scanStatus, scanProgress, selectedFilePaths } from '$lib/stores/files';
  import { strategies, selectedStrategy } from '$lib/stores/strategy';
  import { showHistory } from '$lib/stores/history';
  import { selectedLibraryId, selectedFolderId, libraries } from '$lib/stores/library';
  import { queue } from '$lib/stores/queue';
  import { applyEncodeProgress } from '$lib/queueProgress.js';
  import { getLibraryFiles, getFolderFiles, scanDirectory, loadStrategies, startEncode, listLibraries, getSettings, saveSettings, type AppSettings, type FileEntry } from '$lib/api';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { listen } from '@tauri-apps/api/event';
  import { open } from '@tauri-apps/plugin-dialog';
  import LibraryPanel from '$lib/components/LibraryPanel.svelte';
  import FileTable from '$lib/components/FileTable.svelte';
  import TreeView from '$lib/components/TreeView.svelte';
  import StrategyPanel from '$lib/components/StrategyPanel.svelte';
  import HistoryPanel from '$lib/components/HistoryPanel.svelte';

  const appWindow = getCurrentWindow();

  let viewModes = $state<Record<number, 'flat' | 'tree'>>({});
  let viewMode = $derived($selectedLibraryId ? (viewModes[$selectedLibraryId] || 'flat') : 'flat');
  let showSettings = $state(false);
  let appSettings = $state<AppSettings>({ ffprobe_custom: '', ffmpeg_custom: '', ffprobe_path: '', ffmpeg_path: '', ffprobe_ok: false, ffmpeg_ok: false, gpu_ok: false, gpu_info: '' });
  let toolWarning = $state('');
  let strategyPanel: any;

  // Reset filter and progress when switching libraries
  let filterKey = $state('all');
  $effect(() => {
    if ($selectedLibraryId) {
      filterKey = 'all';
      scanProgress.set(null);
    }
  });

  let totalTasks = $derived($queue.length);
  let doneTasks = $derived($queue.filter(t => t.status === 'done').length);
  let failedTasks = $derived($queue.filter(t => t.status === 'failed' || t.status === 'cancelled').length);
  let runningTasks = $derived($queue.filter(t => t.status === 'running'));
  let overallPct = $derived(totalTasks > 0 ? Math.round($queue.reduce((s, t) => s + (t.progress || 0), 0) / totalTasks) : 0);

  // Rotate through running tasks display
  let rotateIdx = $state(0);
  $effect(() => {
    if (runningTasks.length <= 1) return;
    const timer = setInterval(() => rotateIdx = (rotateIdx + 1) % runningTasks.length, 1500);
    return () => clearInterval(timer);
  });
  let displayTask = $derived(runningTasks.length > 0 ? runningTasks[rotateIdx % runningTasks.length] : null);

  onMount(async () => {
    listen<{done: number, total: number}>('scan-progress', (event) => {
      scanProgress.set({ done: event.payload.done, total: event.payload.total });
      if (event.payload.done >= event.payload.total && event.payload.total > 0) {
        setTimeout(() => scanProgress.set(null), 1500);
      }
    });
    listen<FileEntry>('scan-result', (event) => {
      const entry = event.payload;
      const selectedLibrary = $libraries.find(library => library.id === $selectedLibraryId);
      const visible = $selectedFolderId
        ? entry.folder_id === $selectedFolderId
        : !!selectedLibrary?.folders.some(folder => folder.id === entry.folder_id);
      if (!visible) return;
      files.update(current => {
        const index = current.findIndex(file => file.key === entry.key);
        if (index === -1) return [...current, entry];
        const next = [...current];
        next[index] = entry;
        return next;
      });
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
      appSettings = await getSettings();
    } catch (_) {}
    listen<string>('tool-status', (e) => { toolWarning = e.payload; });
    const unlisten = listen<{job_id: string, stage: string, progress: number, status: string}>('encode-progress', (event) => {
      scanStatus.set(`${event.payload.stage}: ${Math.round(event.payload.progress)}%`);
      queue.update(items => applyEncodeProgress(items, event.payload));
    });
  });

  async function browseFile(tool: 'ffprobe' | 'ffmpeg') {
    const selected = await open({ multiple: false, title: `选择 ${tool}.exe` });
    if (!selected) return;
    await saveSettings(
      tool === 'ffprobe' ? selected : undefined,
      tool === 'ffmpeg' ? selected : undefined,
    );
    appSettings = await getSettings();
    toolWarning = '';
  }

  $effect(() => {
    if (!$selectedLibraryId && !$selectedFolderId) {
      files.set([]);
      scanStatus.set('请选择库查看');
    }
  });
  $effect(() => { if ($selectedFolderId) loadFolderFiles($selectedFolderId); });
  $effect(() => { if ($selectedLibraryId && !$selectedFolderId) loadLibraryFiles($selectedLibraryId); });
  $effect(() => {
    const visibleKeys = new Set($files.map(file => file.key));
    const next = $selectedFilePaths.filter(key => visibleKeys.has(key));
    if (next.length !== $selectedFilePaths.length) selectedFilePaths.set(next);
  });

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

  async function handleScan() {
    // Scan a specific folder if one is selected
    if ($selectedFolderId) {
      const path = getSelectedFolderPath();
      if (!path) { scanStatus.set('未找到文件夹路径'); return; }
      scanStatus.set('扫描中...');
      try {
        const result = await scanDirectory(path, $selectedFolderId);
        files.set(result.files);
        scanStatus.set(`扫描完成: ${result.total_files} 文件, ${result.probe_ok} 成功`);
        const libs = await listLibraries(); libraries.set(libs);
      } catch (e) { scanStatus.set(`错误: ${e}`); }
      return;
    }

    // Scan all folders in the selected library
    if ($selectedLibraryId) {
      const lib = $libraries.find(l => l.id === $selectedLibraryId);
      if (!lib || lib.folders.length === 0) { scanStatus.set('请先在库中添加文件夹'); return; }
      scanStatus.set(`扫描中 (${lib.folders.length} 个文件夹)...`);
      let totalFiles = 0, totalOk = 0;
      let idx = 0;
      for (const folder of lib.folders) {
        idx++;
        scanStatus.set(`扫描 ${idx}/${lib.folders.length}: ${folder.path.split(/[/\\]/).pop() || folder.path}...`);
        try {
          const result = await scanDirectory(folder.path, folder.id);
          totalFiles += result.total_files;
          totalOk += result.probe_ok;
        } catch (_) {}
      }
      try {
        const result = await getLibraryFiles($selectedLibraryId);
        files.set(result.files);
      } catch (_) {}
      scanStatus.set(`扫描完成: ${totalFiles} 文件, ${totalOk} 成功`);
      const libs = await listLibraries(); libraries.set(libs);
      return;
    }

    scanStatus.set('请先在左侧选择一个库');
  }

  function getSelectedFolderPath(): string | null {
    for (const lib of $libraries) {
      const f = lib.folders.find(f => f.id === $selectedFolderId);
      if (f) return f.path;
    }
    return null;
  }

  async function handleEncode() {
    const selected = $selectedFilePaths;
    const strategy = $selectedStrategy;
    if (selected.length === 0) { scanStatus.set('请先选择要编码的文件'); return; }
    if (!strategy) { scanStatus.set('请先选择一个压缩策略'); return; }

    // Dedup: skip files that already have a pending/running task
    const activeFileNames = new Set($queue.filter(q => q.status === 'pending' || q.status === 'running').map(q => q.fileName));
    const files = selected.filter(f => {
      const name = f.split(/[/\\]/).pop() || f;
      return !activeFileNames.has(name);
    });
    if (files.length === 0) { scanStatus.set('所选文件已有活跃任务'); return; }

    scanStatus.set('正在提交编码任务...');
    try {
      const settings = strategyPanel?.getEncodeSettings?.() ?? { deleteSource: false, workerCount: 2 };
      const result = await startEncode(files, strategy.name, settings.deleteSource, settings.workerCount, settings.customStrategy);
      queue.update(current => {
        // Remove old entries for the same files
        const newNames = new Set(result.jobs.map(j => j.file_name));
        const now = current.filter(i => !newNames.has(i.fileName));
        for (const job of result.jobs) {
          now.push({
            id: job.id,
            fileName: job.file_name,
            strategyName: job.strategy_name,
            progress: 0,
            status: 'pending',
            statusText: '排队中'
          });
        }
        return now;
      });
      scanStatus.set(result.message);
    } catch (e) { scanStatus.set(`错误: ${e}`); }
  }
</script>

<div class="app-shell" oncontextmenu={(e) => e.preventDefault()}>
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
        <button onclick={handleScan}>扫描</button>
        {#if $scanProgress}
          <div class="scan-progress">
            <div class="scan-progress-fill" style="width: {$scanProgress.total > 0 ? $scanProgress.done / $scanProgress.total * 100 : 0}%"></div>
          </div>
        {/if}
        <button class="primary tasks-btn" class:pulse={totalTasks > 0 && doneTasks + failedTasks < totalTasks} onclick={() => showHistory.set(true)}>查看任务</button>
        {#if totalTasks > 0 && doneTasks + failedTasks < totalTasks}
          <div class="encode-progress">
            <div class="encode-progress-bar">
              <div class="encode-progress-fill" style="width: {overallPct}%"></div>
            </div>
            <span class="encode-progress-text">
              {overallPct}% {doneTasks}/{totalTasks}
              {#if displayTask}· {displayTask.fileName} {displayTask.progress}%{/if}{#if runningTasks.length > 1} +{runningTasks.length - 1}更多{/if}
            </span>
          </div>
        {/if}
        <span class="status-text">{$scanStatus}</span>
      </div>

      <div class="file-table-wrapper">
        {#if viewMode === 'flat'}
          <FileTable viewMode={viewMode} filterKey={filterKey} onViewChange={(v: 'flat' | 'tree') => { if ($selectedLibraryId) { viewModes[$selectedLibraryId] = v; viewModes = viewModes; } }} onFilterChange={(v: string) => filterKey = v} />
        {:else}
          <TreeView files={$files} viewMode={viewMode} filterKey={filterKey} onViewChange={(v: 'flat' | 'tree') => { if ($selectedLibraryId) { viewModes[$selectedLibraryId] = v; viewModes = viewModes; } }} onFilterChange={(v: string) => filterKey = v} />
        {/if}
      </div>
    </main>

    <aside class="panel">
      <StrategyPanel bind:this={strategyPanel} onEncode={handleEncode} />
    </aside>
  </div>

</div>

{#if $showHistory}
  <HistoryPanel />
{/if}

{#if showSettings}
  <div class="dialog-overlay" onclick={() => showSettings = false} onkeydown={(e) => e.key === 'Escape' && (showSettings = false)}>
    <div class="dialog-box" onclick={(e) => e.stopPropagation()} style="min-width: 460px">
      <h3>设置</h3>

      <label class="setting-label">ffprobe</label>
      <div class="setting-row">
        <span class="setting-path">{appSettings.ffprobe_path || '未找到'}</span>
        <span class="setting-dot" class:green={appSettings.ffprobe_ok} class:red={!appSettings.ffprobe_ok}></span>
        <button class="ghost setting-btn" onclick={() => browseFile('ffprobe')}>替换</button>
      </div>

      <label class="setting-label">ffmpeg</label>
      <div class="setting-row">
        <span class="setting-path">{appSettings.ffmpeg_path || '未找到'}</span>
        <span class="setting-dot" class:green={appSettings.ffmpeg_ok} class:red={!appSettings.ffmpeg_ok}></span>
        <button class="ghost setting-btn" onclick={() => browseFile('ffmpeg')}>替换</button>
      </div>

      {#if toolWarning}
        <p class="setting-warning">{toolWarning}</p>
      {/if}

      <div class="dialog-actions">
        <button class="ghost" onclick={() => showSettings = false}>关闭</button>
      </div>
    </div>
  </div>
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

  .encode-progress { display: flex; align-items: center; gap: var(--space-sm); flex: 1; }
  .encode-progress-bar { flex: 1; height: 3px; background: var(--border-subtle); border-radius: 2px; overflow: hidden; max-width: 200px; }
  .encode-progress-fill { height: 100%; background: var(--success); transition: width 0.5s var(--ease-expo); }
  .encode-progress-text { font-size: var(--font-size-label); color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 280px; }
  .tasks-btn { flex-shrink: 0; }

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
  .dialog-overlay { position: fixed; inset: 0; z-index: 10000; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; }
  .dialog-box { background: rgba(20,28,36,0.94); backdrop-filter: blur(40px); border: 1px solid var(--border-default); border-radius: var(--radius-lg); padding: var(--space-xl); display: flex; flex-direction: column; gap: var(--space-md); }
  .dialog-box h3 { font-size: var(--font-size-body); font-weight: 600; }
  .dialog-box input { width: 100%; }
  .dialog-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); }
  .setting-label { font-size: var(--font-size-label); color: var(--text-secondary); }
  .setting-row { display: flex; align-items: center; gap: var(--space-sm); }
  .setting-row input { flex: 1; }
  .setting-status { font-size: 14px; font-weight: 700; }
  .setting-status.ok { color: var(--success); }
  .setting-status.fail { color: var(--danger); }
  .setting-warning { font-size: var(--font-size-label); color: var(--warning); }
  .setting-path { flex: 1; font-size: var(--font-size-label); color: var(--text-secondary); word-break: break-all; }
  .setting-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .setting-dot.green { background: var(--success); }
  .setting-dot.red { background: var(--danger); }
  .setting-btn { font-size: var(--font-size-label); flex-shrink: 0; }

  .tasks-btn.pulse {
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(91, 155, 213, 0.5); }
    50% { box-shadow: 0 0 0 6px rgba(91, 155, 213, 0); }
  }

</style>
