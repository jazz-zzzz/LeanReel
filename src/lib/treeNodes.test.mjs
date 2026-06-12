import test from 'node:test';
import assert from 'node:assert/strict';
import { getFolderNodeRefreshId } from './treeNodes.js';

test('folder refresh id comes from explicit folderId instead of encoded key shape', () => {
  const node = {
    key: 'folder:not-a-number:Movies',
    folderId: 42,
    isFolder: true,
  };

  assert.equal(getFolderNodeRefreshId(node), 42);
});

test('folder refresh id is unavailable when node has no folderId', () => {
  const node = {
    key: 'folder:42:Movies',
    isFolder: true,
  };

  assert.equal(getFolderNodeRefreshId(node), null);
});
