<script lang="ts">
  import { onMount } from 'svelte';
  import Sortable from 'sortablejs';
  import { strategies, selectedStrategy } from '$lib/stores/strategy';
  import type { StrategyItem } from '$lib/stores/strategy';
  import { saveStrategy, saveStrategyOrder, deleteStrategy as delStrategy, getSettings, saveSettings, testTool, type AppSettings } from '$lib/api';
  import { loadStrategies } from '$lib/api';
  import { open } from '@tauri-apps/plugin-dialog';
  import Select from './Select.svelte';

  let { onEncode = () => {} } = $props();

  let deleteSource = $state(false);
  let workerCount = $state(2);
  let showManager = $state(false);
  let editingStrategy = $state<StrategyItem | null>(null);
  let sys = $state<AppSettings>({ ffprobe_custom: '', ffmpeg_custom: '', ffprobe_path: '', ffmpeg_path: '', ffprobe_ok: false, ffmpeg_ok: false, gpu_ok: false, gpu_info: '' });
  let toolPanel = $state<'ffprobe' | 'ffmpeg' | null>(null);
  let toolPath = $state('');
  let toolStatus = $state<'idle' | 'ok' | 'fail'>('idle');

  let strategyCount = $derived($strategies.length);

  onMount(async () => { sys = await getSettings(); });

  async function openToolPanel(tool: 'ffprobe' | 'ffmpeg') {
    toolPanel = tool;
    toolPath = tool === 'ffprobe' ? sys.ffprobe_path : sys.ffmpeg_path;
    toolStatus = 'idle';
  }

  async function detectAndSave() {
    if (!toolPath.trim()) { toolStatus = 'fail'; return; }
    const ok = await testTool(toolPath);
    toolStatus = ok ? 'ok' : 'fail';
    if (ok) {
      await saveSettings(
        toolPanel === 'ffprobe' ? toolPath : undefined,
        toolPanel === 'ffmpeg' ? toolPath : undefined,
      );
      sys = await getSettings();
    }
  }

  async function replaceAndDetect() {
    const selected = await open({ multiple: false, title: '选择可执行文件' });
    if (!selected) return;
    toolPath = selected;
    toolStatus = 'idle';
    await detectAndSave();
  }

  export function getEncodeSettings() {
    return { deleteSource, workerCount };
  }

  function sortable(node: HTMLElement) {
    Sortable.create(node, {
      handle: '.drag-handle',
      animation: 150,
      onEnd: () => {
        const items = node.querySelectorAll('.strategy-manager-row');
        const reordered: StrategyItem[] = [];
        items.forEach((el, i) => {
          const name = el.querySelector('.col-name')?.textContent?.trim();
          const existing = $strategies.find(s => s.name === name);
          if (existing) reordered.push({ ...existing, sort_order: i });
        });
        strategies.set(reordered);
        persistOrder(reordered.map(s => ({ name: s.name, sort_order: s.sort_order })));
      },
    });
  }

  async function persistOrder(order: { name: string; sort_order: number }[]) {
    try { await saveStrategyOrder(order); } catch (_) {}
    const result = await loadStrategies();
    strategies.set(result.strategies);
  }

  function openEdit(strategy: StrategyItem) {
    editingStrategy = { ...strategy };
  }

  async function saveEdit() {
    if (!editingStrategy) return;
    const s = editingStrategy;
    const data = {
      name: s.name,
      description: s.description,
      is_preset: false,
      video: { encoder: s.encoder, crf: s.crf, preset: s.preset, pix_fmt: 'yuv420p10le', gpu: s.gpu, nv_preset: '', rc: '', cq: s.cq },
      hdr: { mode: '', dv_handling: '' },
      audio: { mode: 'keep_original', preferred_languages: ['chi','zho','eng'] },
      subtitle: { mode: 'keep_all' },
      filters: { skip_x265: false, min_size_gb: null, only_remux: false },
      estimated_savings: s.savings,
      quality_impact: '',
      sort_order: s.sort_order,
    };
    const json = JSON.stringify(data, null, 2);
    try {
      await saveStrategy(s.name, json);
    } catch (e) {
      alert('保存失败: ' + (e as Error).message || String(e));
      return;
    }

    const result = await loadStrategies();
    strategies.set(result.strategies);
    editingStrategy = null;
  }

  async function deleteStrategy(index: number) {
    const s = $strategies[index];
    if (!s) return;
    try { await delStrategy(s.name); } catch (_) {}
    const result = await loadStrategies();
    strategies.set(result.strategies);
  }
</script>

<div class="strategy-panel">
  <div class="panel-top">
    <h2>策略</h2>
    <span class="top-right">
      {#if strategyCount > 0}
        <span class="count-badge">{strategyCount}</span>
      {/if}
      <button class="ghost icon-btn" onclick={() => showManager = true} title="管理策略" aria-label="管理策略">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      </button>
    </span>
  </div>

  {#if $strategies.length === 0}
    <div class="empty-state">
      <span class="empty-icon">+</span>
      <p>暂无策略</p>
      <p class="empty-sub">点击 ⚙ 创建第一个策略</p>
    </div>
  {:else}
    <div class="strategy-list">
      {#each $strategies as strategy (strategy.name)}
        <button
          class="strategy-row"
          class:selected={$selectedStrategy?.name === strategy.name}
          onclick={() => selectedStrategy.set(strategy)}
          aria-pressed={$selectedStrategy?.name === strategy.name}
        >
          <span class="strategy-name">{strategy.name}</span>
          <span class="strategy-meta">
            <span class="tag" class:gpu={strategy.gpu} class:cpu={!strategy.gpu}>
              {strategy.gpu ? 'GPU' : 'CPU'}
            </span>
            <span class="tag encoder">{strategy.encoder}</span>
            {#if strategy.cq > 0}
              <span class="tag cq">CQ {strategy.cq}</span>
            {/if}
            {#if strategy.savings}
              <span class="savings-text">{strategy.savings}</span>
            {/if}
          </span>
        </button>
      {/each}
    </div>

    {#if $selectedStrategy}
      <div class="strategy-detail">
        <p class="detail-desc">{$selectedStrategy.description}</p>
      </div>
    {/if}
  {/if}

  <div class="sys-status">
    <div class="sys-row clickable" onclick={() => openToolPanel('ffprobe')} onkeydown={(e) => e.key === 'Enter' && openToolPanel('ffprobe')} role="button" tabindex="0">
      <span class="sys-dot" class:green={sys.ffprobe_ok} class:red={!sys.ffprobe_ok}></span> ffprobe
      <span class="sys-val">{sys.ffprobe_ok ? sys.ffprobe_path.split(/[/\\]/).pop() || 'OK' : '未找到'}</span>
    </div>
    {#if toolPanel === 'ffprobe'}
      <div class="tool-popup">
        <div class="tool-popup-row">
          <input type="text" bind:value={toolPath} placeholder="未设置" />
          <button class="primary" onclick={replaceAndDetect}>选择</button>
        </div>
        <div class="tool-popup-actions">
          <button class="ghost" onclick={detectAndSave}>检测</button>
          <button class="ghost" onclick={() => toolPanel = null}>关闭</button>
          {#if toolStatus === 'ok'}<span class="tool-indicator ok">✓ 可用</span>
          {:else if toolStatus === 'fail'}<span class="tool-indicator fail">✗ 无效</span>
          {/if}
        </div>
      </div>
    {/if}
    <div class="sys-row clickable" onclick={() => openToolPanel('ffmpeg')} onkeydown={(e) => e.key === 'Enter' && openToolPanel('ffmpeg')} role="button" tabindex="0">
      <span class="sys-dot" class:green={sys.ffmpeg_ok} class:red={!sys.ffmpeg_ok}></span> ffmpeg
      <span class="sys-val">{sys.ffmpeg_ok ? sys.ffmpeg_path.split(/[/\\]/).pop() || 'OK' : '未找到'}</span>
    </div>
    {#if toolPanel === 'ffmpeg'}
      <div class="tool-popup">
        <div class="tool-popup-row">
          <input type="text" bind:value={toolPath} placeholder="未设置" />
          <button class="primary" onclick={replaceAndDetect}>选择</button>
        </div>
        <div class="tool-popup-actions">
          <button class="ghost" onclick={detectAndSave}>检测</button>
          <button class="ghost" onclick={() => toolPanel = null}>关闭</button>
          {#if toolStatus === 'ok'}<span class="tool-indicator ok">✓ 可用</span>
          {:else if toolStatus === 'fail'}<span class="tool-indicator fail">✗ 无效</span>
          {/if}
        </div>
      </div>
    {/if}
    <div class="sys-row"><span class="sys-dot" class:green={sys.gpu_ok} class:red={!sys.gpu_ok}></span> GPU <span class="sys-val">{sys.gpu_ok ? sys.gpu_info : '未检测到'}</span></div>
  </div>

  <div class="encode-settings">
    <div class="setting-row">
      <label>并发数</label>
      <input type="number" min="1" max="16" bind:value={workerCount} />
    </div>
    <div class="setting-row checkbox-row">
      <input type="checkbox" id="deleteSource" bind:checked={deleteSource} />
      <label for="deleteSource">编码后删除源文件</label>
    </div>
    <button class="primary" style="width:100%;margin-top:var(--space-sm)" onclick={onEncode} disabled={!$selectedStrategy}>
      开始编码
    </button>
  </div>
</div>

{#if toolPanel}
  <div class="tool-popup">
    <div class="tool-popup-row">
      <input type="text" bind:value={toolPath} placeholder="未设置" />
      <button class="primary" onclick={replaceAndDetect}>选择</button>
    </div>
    <div class="tool-popup-actions">
      <button class="ghost" onclick={async () => { await saveSettings(toolPanel === 'ffprobe' ? toolPath : undefined, toolPanel === 'ffmpeg' ? toolPath : undefined); sys = await getSettings(); }}>检测</button>
      <button class="ghost" onclick={() => toolPanel = null}>关闭</button>
    </div>
  </div>
{/if}

{#if showManager}
  <div class="overlay-full" onclick={() => showManager = false} onkeydown={(e) => e.key === 'Escape' && (showManager = false)}>
    <div class="manager-panel" onclick={(e) => e.stopPropagation()}>
      <div class="manager-header">
        <button class="ghost" onclick={() => showManager = false}><span class="back-arrow">←</span> 返回</button>
        <h2>策略管理</h2>
        <button class="primary" onclick={() => editingStrategy = { name: '', encoder: 'hevc_nvenc', cq: 28, crf: 20, description: '', savings: '', gpu: true, preset: 'p7', sort_order: $strategies.length, is_preset: false }}>新建策略</button>
      </div>

      <div class="manager-table" use:sortable>
        {#each $strategies as strategy, i (strategy.name)}
          <div class="strategy-manager-row">
            <span class="drag-handle">☰</span>
            <span class="col-name">{strategy.name}</span>
            <span class="col-encoder">{strategy.encoder}</span>
            <span class="col-cq">{strategy.cq > 0 ? `CQ ${strategy.cq}` : `CRF ${strategy.crf}`}</span>
            <span class="col-savings">{strategy.savings}</span>
            <button class="ghost edit-btn" onclick={() => openEdit(strategy)}>✎</button>
            <button class="ghost danger-btn" onclick={() => deleteStrategy(i)}>✕</button>
          </div>
        {/each}
      </div>

      {#if editingStrategy}
        <div class="edit-overlay" onclick={() => editingStrategy = null}>
          <div class="edit-form" onclick={(e) => e.stopPropagation()}>
            <h3>{editingStrategy.name ? '编辑策略' : '新建策略'}</h3>
            <label>名称</label>
            <input type="text" bind:value={editingStrategy.name} />
            <label>编码器</label>
            <Select value={editingStrategy.encoder}
              options={[
                { value: 'libx265', label: 'libx265 (CPU)' },
                { value: 'hevc_nvenc', label: 'hevc_nvenc (GPU)' },
                { value: 'av1_nvenc', label: 'av1_nvenc (GPU)' },
                { value: 'h264_nvenc', label: 'h264_nvenc (GPU)' },
                { value: 'copy', label: '流复制' },
              ]}
              onChange={(v) => editingStrategy!.encoder = v}
            />
            <label>CQ / CRF</label>
            <input type="number" min="0" max="63" bind:value={editingStrategy.cq} />
            <label>描述</label>
            <input type="text" bind:value={editingStrategy.description} />
            <label>节省估算</label>
            <input type="text" placeholder="如 30-60%" bind:value={editingStrategy.savings} />
            <div class="dialog-actions">
              <button class="ghost" onclick={() => editingStrategy = null}>取消</button>
              <button class="primary" onclick={saveEdit}>保存</button>
            </div>
          </div>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .strategy-panel { display: flex; flex-direction: column; height: 100%; gap: var(--space-sm); }

  .panel-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-xs); }
  h2 { font-size: var(--font-size-label); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-secondary); }
  .top-right { display: flex; align-items: center; gap: var(--space-sm); }
  .count-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 16px; padding: 0 5px; border-radius: 8px; font-size: var(--font-size-sm); font-weight: 700; background: var(--accent-dimmed); color: var(--accent); }
  .icon-btn { width: 24px; height: 24px; padding: 0; display: inline-flex; align-items: center; justify-content: center; border: none; color: var(--text-secondary); }
  .icon-btn:hover { color: var(--text-primary); background: var(--bg-hover); }

  .empty-state { display: flex; flex-direction: column; align-items: center; padding: var(--space-2xl); color: var(--text-muted); gap: var(--space-sm); }
  .empty-icon { font-size: 22px; opacity: 0.3; }
  .empty-sub { font-size: var(--font-size-label); opacity: 0.6; }

  .strategy-list { display: flex; flex-direction: column; gap: 2px; flex: 1; overflow-y: auto; }
  .strategy-row { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; padding: 6px 8px; border: 1px solid transparent; border-radius: var(--radius-md); background: transparent; cursor: pointer; transition: background var(--duration-fast) var(--ease-expo), border-color var(--duration-fast) var(--ease-expo); }
  .strategy-row:hover { background: var(--bg-hover); border-color: var(--border-subtle); }
  .strategy-row.selected { background: var(--bg-selected); border-color: rgba(91,155,213,0.25); }
  .strategy-name { font-size: var(--font-size-body); font-weight: 600; }
  .strategy-row.selected .strategy-name { color: var(--accent); }
  .strategy-meta { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
  .tag { padding: 0 5px; border-radius: var(--radius-sm); font-size: var(--font-size-sm); font-weight: 600; text-transform: uppercase; line-height: 1.6; }
  .tag.gpu { background: var(--tag-hevc-bg); color: var(--tag-hevc-text); }
  .tag.cpu { background: var(--tag-av1-bg); color: var(--tag-av1-text); }
  .tag.encoder { color: var(--text-secondary); background: var(--bg-surface); }
  .tag.cq { font-family: var(--font-mono); font-size: var(--font-size-sm); background: var(--bg-surface); color: var(--text-secondary); }
  .savings-text { font-size: var(--font-size-sm); color: var(--success); font-weight: 600; margin-left: auto; }
  .strategy-detail { padding: var(--space-sm) var(--space-md); border-top: 1px solid var(--border-subtle); }
  .detail-desc { font-size: var(--font-size-label); color: var(--text-secondary); line-height: 1.5; }

  .sys-status { position: relative; display: flex; flex-direction: column; gap: 2px; padding: var(--space-sm) var(--space-md); border-top: 1px solid var(--border-subtle); margin-top: var(--space-sm); }
  .sys-row { display: flex; align-items: center; gap: var(--space-sm); font-size: var(--font-size-label); color: var(--text-secondary); }
  .sys-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .sys-dot.green { background: var(--success); }
  .sys-dot.red { background: var(--danger); }
  .sys-val { margin-left: auto; color: var(--text-muted); font-size: var(--font-size-sm); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sys-row.clickable { cursor: pointer; }
  .sys-row.clickable:hover .sys-val { text-decoration: underline; color: var(--accent); }

  .encode-settings { display: flex; flex-direction: column; gap: var(--space-sm); padding: var(--space-sm) var(--space-md); border-top: 1px solid var(--border-subtle); margin-top: var(--space-sm); }
  .setting-row { display: flex; align-items: center; gap: var(--space-sm); }
  .setting-row label { flex-shrink: 0; width: 48px; font-size: var(--font-size-label); color: var(--text-secondary); text-align: right; }
  .setting-row input[type="number"] { flex: 1; font-size: var(--font-size-label); padding: 4px 8px; min-width: 0; }
  .tool-popup { padding: var(--space-sm); background: rgba(20,28,36,0.92); border: 1px solid var(--border-default); border-radius: var(--radius-md); display: flex; flex-direction: column; gap: var(--space-sm); margin: 2px 0; }
  .tool-popup input { font-size: var(--font-size-label); }
  .tool-popup-row { display: flex; align-items: center; gap: var(--space-sm); }
  .tool-popup-row input { flex: 1; font-size: var(--font-size-label); }
  .tool-popup-actions { display: flex; align-items: center; gap: var(--space-sm); }
  .tool-popup-actions button { font-size: var(--font-size-label); }
  .tool-indicator { font-size: var(--font-size-label); font-weight: 600; }
  .tool-indicator.ok { color: var(--success); }
  .tool-indicator.fail { color: var(--danger); }
  .checkbox-row { padding-left: 48px; }
  .checkbox-row label { width: auto; text-align: left; font-size: var(--font-size-label); color: var(--text-secondary); cursor: pointer; }

  /* ── Manager ────────────────────────── */
  .overlay-full { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,0.45); backdrop-filter: blur(4px); display: flex; }
  .manager-panel { width: 100%; height: 100%; background: var(--bg-window); display: flex; flex-direction: column; padding: var(--space-xl) var(--space-2xl); overflow-y: auto; }
  .manager-header { display: flex; align-items: center; gap: var(--space-xl); margin-bottom: var(--space-xl); flex-shrink: 0; }
  .manager-header h2 { font-size: var(--font-size-body); font-weight: 600; color: var(--text-primary); flex: 1; }
  .back-arrow { font-size: 14px; margin-right: 4px; }
  .manager-table { flex: 1; overflow-y: auto; }
  .strategy-manager-row { display: flex; align-items: center; gap: var(--space-sm); padding: 6px 8px; border-bottom: 1px solid var(--border-subtle); font-size: var(--font-size-body); }
  .strategy-manager-row:hover { background: var(--bg-hover); }
  .drag-handle { cursor: grab; color: var(--text-muted); user-select: none; flex-shrink: 0; }
  .col-name { flex: 1; font-weight: 500; }
  .col-encoder { width: 100px; color: var(--text-secondary); }
  .col-cq { width: 60px; font-family: var(--font-mono); font-size: var(--font-size-mono); color: var(--text-secondary); }
  .col-savings { width: 70px; color: var(--success); }
  .edit-btn, .danger-btn { flex-shrink: 0; }
  .danger-btn:hover { color: var(--danger); }

  .edit-overlay { position: fixed; inset: 0; z-index: 2000; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; }
  .edit-form { background: rgba(20,28,36,0.96); backdrop-filter: blur(40px); border: 1px solid var(--border-default); border-radius: var(--radius-lg); padding: var(--space-xl); display: flex; flex-direction: column; gap: var(--space-sm); min-width: 360px; }
  .edit-form h3 { font-size: var(--font-size-body); font-weight: 600; }
  .edit-form label { font-size: var(--font-size-label); color: var(--text-secondary); }
  .edit-form input, .edit-form select { width: 100%; }
  .dialog-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); margin-top: var(--space-sm); }
</style>
