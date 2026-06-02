/**
 * Normalize new (process-level io_*) and legacy (share-level smb_*)
 * performance metrics into a uniform display shape.
 * @param {string} json
 * @returns {{ type: string, readBytesSec: number, writeBytesSec: number } | null}
 */
export function normalizeIoMetrics(json) {
  if (!json) return null;
  /** @type {Record<string, unknown>} */
  let parsed;
  try {
    parsed = JSON.parse(json);
  } catch {
    return null;
  }

  const ioType = typeof parsed.io_type === 'string' ? parsed.io_type : null;
  const ioRead = typeof parsed.io_read_bytes_sec === 'number' ? parsed.io_read_bytes_sec : undefined;
  const ioWrite =
    typeof parsed.io_write_bytes_sec === 'number' ? parsed.io_write_bytes_sec : undefined;

  if (ioType && ioRead !== undefined && ioWrite !== undefined) {
    const labels = { local: '本地', smb: 'SMB', mixed: '混合' };
    return { type: labels[ioType] || ioType, readBytesSec: ioRead, writeBytesSec: ioWrite };
  }

  // Fallback: legacy SMB-only records
  const smbRead = typeof parsed.smb_read_bytes_sec === 'number' ? parsed.smb_read_bytes_sec : undefined;
  const smbWrite =
    typeof parsed.smb_write_bytes_sec === 'number' ? parsed.smb_write_bytes_sec : undefined;
  if (smbRead !== undefined || smbWrite !== undefined) {
    return { type: 'SMB', readBytesSec: smbRead || 0, writeBytesSec: smbWrite || 0 };
  }

  return null;
}
