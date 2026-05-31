<script lang="ts">
  import { onMount } from 'svelte';
  import { listen } from '@tauri-apps/api/event';
  import { queue, type QueueStatus } from '$lib/stores/queue';
  import { pauseEncode, resumeEncode, cancelEncode } from '$lib/api';

  let paused = false;

  onMount(() => {
    listen<{job_id: string, stage: string, progress: number, status: string}>('encode-progress', (event) => {
      queue.update(items => items.map(item => {
        if (item.id === event.payload.job_id) {
          const stage = event.payload.stage;
          const pct = Math.round(event.payload.progress);
          const status = normalizeStatus(event.payload.status);
          return {
            ...item,
            progress: pct,
            status,
            statusText: stage === 'done'
              ? statusLabel(status)
              : `${stage}: ${pct}%`,
            stage: stage === 'done' ? undefined : stage,
          };
        }
        return item;
      }));
    });
  });

  function normalizeStatus(status: string): QueueStatus {
    if (status === 'completed') return 'done';
    if (status === 'discarded') return 'discarded';
    if (status === 'running' || status === 'failed' || status === 'cancelled') return status;
    return 'pending';
  }

  async function togglePause() {
    if (paused) { await resumeEncode(); paused = false; }
    else { await pauseEncode(); paused = true; }
  }

  async function handleCancel() { await cancelEncode(); }

  function clearFinished() {
    queue.update(items => items.filter(i => i.status !== 'done' && i.status !== 'failed' && i.status !== 'cancelled' && i.status !== 'discarded'));
  }

  function statusIcon(status: string): string {
    switch (status) {
      case 'running': return '⟳';
      case 'done': return '✓';
      case 'failed': return '✗';
      case 'cancelled': return '⊘';
      case 'discarded': return '⊘';
      default: return '○';
    }
  }

  function statusLabel(status: string): string {
    switch (status) {
      case 'running': return '运行中';
      case 'done': return '已完成';
      case 'failed': return '失败';
      case 'cancelled': return '已取消';
      case 'discarded': return '输出未节省空间';
      default: return '等待中';
    }
  }
</script>

<div class="queue-panel">
  <div class="queue-header">
    <h2>任务队列</h2>
    <div class="queue-controls">
      <button class="ghost" onclick={togglePause}>{paused ? '继续' : '暂停'}</button>
      <button class="ghost danger" onclick={handleCancel}>取消</button>
      <button class="ghost" onclick={clearFinished}>清除已完成</button>
    </div>
  </div>

  <div class="queue-list">
    {#each $queue as item (item.id)}
      <div
        class="queue-row"
        style={item.status === 'running' ? `--progress-pct: ${item.progress}%` : ''}
        class:running={item.status === 'running'}
        class:done={item.status === 'done'}
        class:failed={item.status === 'failed' || item.status === 'discarded'}
        class:cancelled={item.status === 'cancelled'}
      >
        <span class="status-icon" class:spin={item.status === 'running'}>
          {statusIcon(item.status)}
        </span>
        <div class="task-info">
          <span class="task-name" title={item.fileName}>{item.fileName}</span>
          <span class="task-strategy">{item.strategyName}</span>
        </div>
        <div class="task-progress">
          {#if item.status === 'running'}
            <div class="progress-track">
              <div class="progress-fill" style="width: {item.progress}%"></div>
            </div>
          {/if}
          <span
            class="task-status"
            class:success={item.status === 'done'}
            class:danger={item.status === 'failed' || item.status === 'discarded'}
            class:muted={item.status === 'pending' || item.status === 'cancelled'}
          >
            {item.statusText}
          </span>
        </div>
      </div>
    {/each}
  </div>
</div>

<style>
  .queue-panel {
    padding: var(--space-md) var(--space-lg);
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .queue-header {
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
  .queue-controls {
    display: flex;
    gap: var(--space-xs);
  }
  .queue-controls button {
    font-size: var(--font-size-label);
    padding: 2px 8px;
  }
  .queue-controls button.danger { color: var(--danger); }

  .queue-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .queue-row {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    padding: 6px 10px;
    border-radius: var(--radius-sm);
    background: var(--bg-surface);
    border: 1px solid transparent;
    transition: border-color var(--duration-fast) var(--ease-expo);
  }
  .queue-row.running { border-color: var(--accent); background: linear-gradient(to right, var(--accent-dimmed) var(--progress-pct, 0%), transparent var(--progress-pct, 0%)); }
  .queue-row.done { border-color: var(--success); opacity: 0.75; }
  .queue-row.failed { border-color: var(--danger); opacity: 0.75; }
  .queue-row.cancelled { opacity: 0.5; }

  .status-icon {
    font-size: 14px;
    width: 20px;
    text-align: center;
    flex-shrink: 0;
    font-weight: 700;
    color: var(--text-muted);
  }
  .queue-row.running .status-icon { color: var(--accent); }
  .queue-row.done .status-icon { color: var(--success); }
  .queue-row.failed .status-icon { color: var(--danger); }
  .queue-row.cancelled .status-icon { color: var(--text-muted); }

  .spin {
    display: inline-block;
    animation: spin 1.5s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .task-info {
    flex: 1;
    min-width: 0;
  }
  .task-name {
    display: block;
    font-size: var(--font-size-body);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .task-strategy {
    font-size: var(--font-size-sm);
    color: var(--text-secondary);
  }

  .task-progress {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
    flex-shrink: 0;
  }
  .progress-track {
    width: 100px;
    height: 3px;
    background: var(--border-subtle);
    border-radius: 2px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 2px;
    transition: width var(--duration-slow) var(--ease-expo);
  }
  .task-status {
    font-size: var(--font-size-sm);
    color: var(--text-secondary);
  }
  .task-status.success { color: var(--success); }
  .task-status.danger { color: var(--danger); }
  .task-status.muted { color: var(--text-muted); }
</style>
