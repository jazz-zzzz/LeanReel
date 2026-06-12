/**
 * @param {{ folderId?: number | null }} node
 * @returns {number | null}
 */
export function getFolderNodeRefreshId(node) {
  return typeof node.folderId === 'number' ? node.folderId : null;
}
