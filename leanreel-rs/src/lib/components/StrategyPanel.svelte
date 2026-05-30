<script lang="ts">
  import { strategies, selectedStrategy } from '$lib/stores/strategy';
  import type { StrategyItem } from '$lib/stores/strategy';

  let showCustom = false;

  let customEncoder = 'hevc_nvenc';
  let customCq = 34;
  let customCrf = 20;
  let customPreset = 'p7';
  let customAudio = 'strip_commentary';
  let customSub = 'keep_all';
  let workerCount = 2;
  let deleteSource = false;

  $: isGpu = ['hevc_nvenc', 'av1_nvenc', 'h264_nvenc'].includes(customEncoder);
  $: isCpu = customEncoder === 'libx265';

  $: strategyCount = $strategies.length;

  export function getEncodeSettings(): { workerCount: number; deleteSource: boolean; customStrategy?: { encoder: string; cq: number; crf: number; preset: string; audio: string; sub: string } } {
    if (showCustom) {
      return {
        workerCount,
        deleteSource,
        customStrategy: {
          encoder: customEncoder,
          cq: customCq,
          crf: customCrf,
          preset: customPreset,
          audio: customAudio,
          sub: customSub,
        }
      };
    }
    return { workerCount, deleteSource };
  }
</script>

<div class="strategy-panel">
  <div class="panel-top">
    <h2>策略</h2>
    {#if strategyCount > 0}
      <span class="count-badge">{strategyCount}</span>
    {/if}
  </div>

  {#if $strategies.length === 0}
    <div class="empty-state">
      <span class="empty-icon">+</span>
      <p>暂无策略</p>
      <p class="empty-sub">策略配置文件加载后将在此显示</p>
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

    <!-- Custom strategy toggle -->
    <button
      class="ghost custom-toggle"
      class:active={showCustom}
      onclick={() => showCustom = !showCustom}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      自定义参数
      <span class="toggle-arrow">{showCustom ? '▾' : '▸'}</span>
    </button>

    {#if showCustom}
      <div class="custom-section">
        <div class="custom-row">
          <label>编码器</label>
          <select bind:value={customEncoder}>
            <option value="libx265">libx265 (CPU)</option>
            <option value="hevc_nvenc">hevc_nvenc (GPU)</option>
            <option value="av1_nvenc">av1_nvenc (GPU)</option>
            <option value="h264_nvenc">h264_nvenc (GPU)</option>
            <option value="copy">流复制</option>
          </select>
        </div>

        {#if isCpu}
          <div class="custom-row">
            <label>CRF</label>
            <input type="number" min="0" max="51" bind:value={customCrf} />
          </div>
        {/if}

        {#if isGpu}
          <div class="custom-row">
            <label>CQ</label>
            <input type="number" min="0" max="63" bind:value={customCq} />
          </div>
          <div class="custom-row">
            <label>预设</label>
            <select bind:value={customPreset}>
              {#each ['p1','p2','p3','p4','p5','p6','p7'] as p}
                <option value={p}>{p.toUpperCase()}</option>
              {/each}
            </select>
          </div>
        {/if}

        <div class="custom-row">
          <label>音频</label>
          <select bind:value={customAudio}>
            <option value="keep_original">保留原始</option>
            <option value="strip_commentary">去除评论音轨</option>
          </select>
        </div>

        <div class="custom-row">
          <label>字幕</label>
          <select bind:value={customSub}>
            <option value="keep_all">保留全部</option>
            <option value="keep_chinese">仅保留中文</option>
            <option value="keep_chinese_english">保留中英</option>
            <option value="remove_all">移除全部</option>
          </select>
        </div>

        <div class="custom-row">
          <label>并发数</label>
          <input type="number" min="1" max="16" bind:value={workerCount} />
        </div>

        <div class="custom-row checkbox-row">
          <input type="checkbox" id="deleteSource" bind:checked={deleteSource} />
          <label for="deleteSource">编码后删除源文件</label>
        </div>
      </div>
    {/if}
  {/if}
</div>

<style>
  .strategy-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    gap: var(--space-sm);
  }

  .panel-top {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-xs);
  }
  h2 {
    font-size: var(--font-size-label);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
  }
  .count-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px; height: 16px;
    padding: 0 5px;
    border-radius: 8px;
    font-size: var(--font-size-sm);
    font-weight: 700;
    background: var(--accent-dimmed);
    color: var(--accent);
  }

  /* ── Empty state ──────────────────────────── */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: var(--space-2xl) var(--space-lg);
    color: var(--text-muted);
    gap: var(--space-sm);
  }
  .empty-icon { font-size: 22px; opacity: 0.3; }
  .empty-sub { font-size: var(--font-size-label); opacity: 0.6; }

  /* ── Strategy rows ────────────────────────── */
  .strategy-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    overflow-y: auto;
  }
  .strategy-row {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
    text-align: left;
    padding: 8px 10px;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    background: transparent;
    cursor: pointer;
    transition:
      background var(--duration-fast) var(--ease-expo),
      border-color var(--duration-fast) var(--ease-expo);
  }
  .strategy-row:hover { background: var(--bg-hover); border-color: var(--border-subtle); }
  .strategy-row.selected {
    background: var(--bg-selected);
    border-color: rgba(91, 155, 213, 0.25);
  }

  .strategy-name { font-size: var(--font-size-body); font-weight: 600; }
  .strategy-row.selected .strategy-name { color: var(--accent); }

  .strategy-meta {
    display: flex;
    gap: 4px;
    align-items: center;
    flex-wrap: wrap;
  }

  .tag {
    padding: 0 5px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
    font-weight: 600;
    text-transform: uppercase;
    line-height: 1.6;
  }
  .tag.gpu { background: var(--tag-hevc-bg); color: var(--tag-hevc-text); }
  .tag.cpu { background: var(--tag-av1-bg); color: var(--tag-av1-text); }
  .tag.encoder { color: var(--text-secondary); background: var(--bg-surface); }
  .tag.cq {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    background: var(--bg-surface);
    color: var(--text-secondary);
  }

  .savings-text {
    font-size: var(--font-size-sm);
    color: var(--success);
    font-weight: 600;
    margin-left: auto;
  }

  /* ── Detail ───────────────────────────────── */
  .strategy-detail {
    padding: var(--space-sm) var(--space-md);
    border-top: 1px solid var(--border-subtle);
  }
  .detail-desc {
    font-size: var(--font-size-label);
    color: var(--text-secondary);
    line-height: 1.5;
  }

  /* ── Custom toggle ────────────────────────── */
  .custom-toggle {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    width: 100%;
    padding: 6px 10px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--font-size-label);
    cursor: pointer;
    border-radius: var(--radius-sm);
    transition: color var(--duration-fast) var(--ease-expo);
  }
  .custom-toggle:hover { color: var(--text-primary); background: var(--bg-hover); }
  .custom-toggle.active { color: var(--accent); }
  .toggle-arrow { margin-left: auto; font-size: 10px; }

  /* ── Custom section ───────────────────────── */
  .custom-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    border-top: 1px solid var(--border-subtle);
    animation: fadeIn var(--duration-fast) var(--ease-expo);
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .custom-row {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }
  .custom-row label {
    flex-shrink: 0;
    width: 48px;
    font-size: var(--font-size-label);
    color: var(--text-secondary);
    text-align: right;
  }
  .custom-row select,
  .custom-row input[type="number"] {
    flex: 1;
    font-size: var(--font-size-label);
    min-width: 0;
  }
  .custom-row input[type="number"] {
    width: 100%;
    padding: 4px 8px;
  }
  .checkbox-row { padding-left: 48px; }
  .checkbox-row label {
    width: auto;
    text-align: left;
    font-size: var(--font-size-label);
    color: var(--text-secondary);
    cursor: pointer;
  }
</style>
