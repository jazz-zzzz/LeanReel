# UI Responsiveness Contract

LeanReel keeps the Qt main thread reserved for UI event handling and light commits.

## Rules

1. Slow work runs in a worker thread.
   - File discovery
   - Cache loading
   - Cache resolution
   - ffprobe/probe callbacks
   - Hardware detection and strategy prioritization

2. Worker threads return data through `AppSignals`.
   - Workers may emit signals.
   - Workers must not mutate Qt widgets, Qt models, or `FileTableStore`.

3. UI commit slots run on the main thread.
   - `_on_scan_ready`
   - `_on_scan_resolved`
   - `_on_library_cache_loaded`
   - `_on_probe_result`
   - `_on_strategies_ready`

4. Large UI updates should be incremental when possible.
   - Per-row probe updates should emit `dataChanged`.
   - Avoid `layoutChanged` or model reset for visible-to-visible row updates.
   - Hidden views should be marked dirty and rebuilt only when shown.

## Tests To Add For New Slow Paths

When adding a UI-triggered operation that may touch disk, subprocesses, hardware, network paths, or many rows:

1. Add a fake slow dependency that sleeps for at least 150 ms.
2. Call the public UI handler.
3. Assert the handler returns in less than 50 ms.
4. Assert the slow dependency ran outside the captured main thread.
5. Assert the final store/model mutation happened on the main thread.
