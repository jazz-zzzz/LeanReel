import { writable } from 'svelte/store';

export interface LibraryInfo {
  id: number;
  name: string;
  created_at: string;
  folders: FolderInfo[];
}

export interface FolderInfo {
  id: number;
  path: string;
}

export const libraries = writable<LibraryInfo[]>([]);
export const selectedLibraryId = writable<number | null>(null);
export const selectedFolderId = writable<number | null>(null);
