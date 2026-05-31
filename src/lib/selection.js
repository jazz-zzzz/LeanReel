/**
 * Add a visible file range to the current selection.
 *
 * When the anchor is no longer visible, fall back to toggling the target.
 *
 * @param {{ key: string, decision_status: string }[]} files
 * @param {string[]} selectedKeys
 * @param {string} anchorKey
 * @param {string} targetKey
 * @returns {string[]}
 */
export function addSelectionRange(files, selectedKeys, anchorKey, targetKey) {
  const next = new Set(selectedKeys);
  const anchorIndex = files.findIndex((file) => file.key === anchorKey);
  const targetIndex = files.findIndex((file) => file.key === targetKey);

  if (anchorIndex === -1 || targetIndex === -1) {
    const target = files[targetIndex];
    if (!target || target.decision_status !== 'processable') return [...next];
    if (next.has(targetKey)) next.delete(targetKey);
    else next.add(targetKey);
    return [...next];
  }

  const start = Math.min(anchorIndex, targetIndex);
  const end = Math.max(anchorIndex, targetIndex);
  for (let index = start; index <= end; index += 1) {
    const file = files[index];
    if (file.decision_status === 'processable') next.add(file.key);
  }
  return [...next];
}
