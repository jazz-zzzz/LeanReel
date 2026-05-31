<script lang="ts">
  import { onMount } from 'svelte';

  export let value: string = '';
  export let options: { value: string; label: string }[] = [];
  export let onChange: (value: string) => void = () => {};

  let open = false;
  let btnEl: HTMLElement;

  function select(opt: { value: string; label: string }) {
    value = opt.value;
    open = false;
    onChange(opt.value);
  }

  function handleClickOutside(e: MouseEvent) {
    if (btnEl && !btnEl.contains(e.target as Node)) {
      open = false;
    }
  }

  onMount(() => {
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  });
</script>

<span class="custom-select" bind:this={btnEl}>
  <button class="select-trigger" onclick={() => open = !open}>
    <span class="select-text">{options.find(o => o.value === value)?.label || value}</span>
    <span class="select-arrow" class:open>▾</span>
  </button>
  {#if open}
    <div class="select-dropdown">
      {#each options as opt (opt.value)}
        <button
          class="select-option"
          class:active={opt.value === value}
          onclick={() => select(opt)}
        >
          {opt.label}
        </button>
      {/each}
    </div>
  {/if}
</span>

<style>
  .custom-select { position: relative; display: inline-block; }
  .select-trigger {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    font-family: var(--font-body);
    font-size: var(--font-size-label);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    cursor: pointer;
    outline: none;
    min-width: 80px;
  }
  .select-trigger:hover { border-color: var(--border-focus); }
  .select-arrow { font-size: 8px; color: var(--text-muted); transition: transform 0.15s; }
  .select-arrow.open { transform: rotate(180deg); }
  .select-text { flex: 1; text-align: left; }

  .select-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    margin-top: 2px;
    min-width: 100%;
    background: rgba(20, 28, 36, 0.82);
    backdrop-filter: blur(40px) saturate(1.5);
    -webkit-backdrop-filter: blur(40px) saturate(1.5);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 4px;
    z-index: 100;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  }
  .select-option {
    display: block;
    width: 100%;
    padding: 5px 10px;
    text-align: left;
    font-size: var(--font-size-label);
    background: transparent;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    cursor: pointer;
    white-space: nowrap;
  }
  .select-option:hover { background: var(--bg-hover); }
  .select-option.active { color: var(--accent); }
</style>
