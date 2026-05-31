import { writable } from 'svelte/store';

export interface FileEntry {
  key: string;
  folder_id: number;
  path: string;
  name: string;
  size: number;
  codec: string;
  hdr: string;
  size_display: string;
  width: number;
  height: number;
  bitrate_bps: number;
  decision_status: string;
  decision_text: string;
}

export const files = writable<FileEntry[]>([]);
export const scanStatus = writable<string>('');
export const selectedFilePaths = writable<string[]>([]);
export const scanProgress = writable<{ done: number; total: number } | null>(null);
