# 持久化层重构：domain/ + infrastructure/ 拆分

> 渐进式重构第一步。从底向上：先建零依赖 domain，再建 infrastructure 实现接口。
> 每一步 386 测试必须通过。不修改任何业务逻辑。

## 目标

- `domain/` — 纯数据 + 抽象接口，**零 import 依赖**（不依赖 Qt、threading、sqlite3、项目内其他层）
- `infrastructure/` — 实现 domain 接口，只依赖 domain + stdlib + sqlite3
- 其余文件逻辑不变，只更新 import 路径

## 不改的内容

- `data/file_store.py` — 不动（后续 State 层重构时拆）
- `core/` 下所有业务逻辑 — 不动
- `gui/` 下所有 UI 代码 — 不动
- `executor/` 下所有执行器 — 不动
- 测试文件除了 import 路径外不动

---

## 新目录结构

```
leanreel/
  domain/                        ← 新建，零依赖
    __init__.py
    models.py                    ← 从 data/models.py 移入，代码不变
    interfaces.py                ← 新建，SnapshotStore + ProbeRunner ABC

  infrastructure/                ← 新建，依赖 domain + stdlib + sqlite3
    __init__.py
    database.py                  ← 从 data/database.py 移入，改 import
    repository.py                ← 从 core/repository.py 移入，实现 SnapshotStore

  data/                          ← 保留，只剩 file_store.py（后续拆）
    __init__.py
    file_store.py                ← 不动

  core/                          ← 保留，只改 import 路径
    ...
  gui/                           ← 保留，只改 import 路径
    ...
  executor/                      ← 保留，只改 import 路径
    ...
```

## domain/models.py

从 `data/models.py` 完整移入，代码不变。内容：

- `HDRType` (enum)
- `TaskStatus` (enum)
- `Library` (dataclass)
- `LibraryFolder` (dataclass)
- `FileSnapshot` (dataclass)
- `AudioTrack` (dataclass)
- `SubtitleTrack` (dataclass)
- `CompressionRecord` (dataclass)

## domain/interfaces.py

新建文件，定义两个抽象接口：

```python
from abc import ABC, abstractmethod
from typing import Optional
from leanreel.domain.models import FileSnapshot

class SnapshotStore(ABC):
    @abstractmethod
    def load_all(self, library_folder_id: int) -> list[FileSnapshot]: ...
    @abstractmethod
    def get_cached(self, folder_id: int, rel_path: str) -> Optional[FileSnapshot]: ...
    @abstractmethod
    def save(self, snap: FileSnapshot) -> None: ...
    @abstractmethod
    def delete_orphans(self, folder_id: int, keep_paths: set[str]) -> None: ...

class ProbeRunner(ABC):
    @abstractmethod
    def probe(self, file_path: str, library_folder_id: int = 0) -> FileSnapshot: ...
```

## infrastructure/database.py

从 `data/database.py` 移入。改动：
- `from leanreel.data.models` → `from leanreel.domain.models`
- 代码逻辑不变

## infrastructure/repository.py

从 `core/repository.py` 移入。改动：
- 类签名改为 `class SnapshotRepository(SnapshotStore):`
- `from leanreel.data.database` → `from leanreel.infrastructure.database`
- `from leanreel.data.models` → `from leanreel.domain.models`
- 代码逻辑不变

## Import 路径变更清单

每个受影响的文件，只改 import 语句的模块路径，不改业务代码：

| 文件 | 旧 import | 新 import |
|------|----------|----------|
| `infrastructure/database.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `infrastructure/repository.py` | `leanreel.data.database` | `leanreel.infrastructure.database` |
| `infrastructure/repository.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `core/scanner.py` | `leanreel.data.database` | `leanreel.infrastructure.database` |
| `core/scanner.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `core/scanner.py` | `leanreel.core.repository` | `leanreel.infrastructure.repository` |
| `core/library.py` | `leanreel.data.database` | `leanreel.infrastructure.database` |
| `core/library.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `core/matcher.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `core/pipeline.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `core/strategy.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `gui/file_list.py` | `leanreel.data.file_store` | 不变（file_store 仍在 data/） |
| `gui/file_list.py` | `leanreel.core.matcher` | 不变（后续拆） |
| `gui/file_list.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `gui/strategy_panel.py` | `leanreel.core.strategy` | 不变（后续拆） |
| `gui/queue_panel.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `gui/adapters/file_table_model.py` | `leanreel.gui.file_list` | 不变（后续拆） |
| `gui/adapters/strategy_delegate.py` | — | 不变 |
| `gui/adapters/tree_adapter.py` | `leanreel.gui.file_list` | 不变（后续拆） |
| `executor/ffmpeg.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `executor/ffmpeg_builder.py` | — | 不变 |
| `executor/worker.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `executor/probe.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `controllers/signals.py` | — | 不变 |
| `main.py` | `leanreel.data.database` | `leanreel.infrastructure.database` |
| `main.py` | `leanreel.data.models` | `leanreel.domain.models` |
| `main.py` | `leanreel.core.repository` | 不变（通过 scanner 间接使用） |

## 测试文件 Import 变更

所有测试文件中：
- `from leanreel.data.models` → `from leanreel.domain.models`
- `from leanreel.data.database` → `from leanreel.infrastructure.database`
- `from leanreel.core.repository` → `from leanreel.infrastructure.repository`
- 新增 `from leanreel.domain.interfaces import SnapshotStore` 按需

## 验证标准

- [ ] `py -m pytest -q` 386 passed
- [ ] `python -m leanreel.main` 可启动 GUI
- [ ] 库切换、重建缓存、复选框勾选功能正常

## 不在范围内

- `data/file_store.py` 的拆分（下步 State 层重构）
- `core/` 业务逻辑重构（下步 Services 层重构）
- `gui/` 跨层 import 清理（下步 UI 层重构）
- Scanner 从 core 拆出（下步 Job 层重构）
- 颜色常量归一化
