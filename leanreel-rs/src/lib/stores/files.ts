import { writable } from 'svelte/store';

export interface FileEntry {
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
