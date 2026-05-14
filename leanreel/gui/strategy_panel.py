"""策略面板 — 预设选择 + 并行设置 + 输出设置"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QLabel, QSpinBox,
    QCheckBox, QPushButton, QGroupBox, QFormLayout
)
from PySide6.QtCore import Signal


class StrategyPanel(QWidget):
    start_requested = Signal()
    strategy_changed = Signal(int)  # strategy index

    def __init__(self):
        super().__init__()
        self._strategies = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 策略组
        strat_group = QGroupBox("压缩策略")
        strat_layout = QVBoxLayout(strat_group)
        self.strategy_combo = QComboBox()
        self.strategy_combo.currentIndexChanged.connect(
            lambda i: self.strategy_changed.emit(i)
        )
        self.strategy_desc = QLabel("选择策略查看详情")
        self.strategy_desc.setWordWrap(True)
        self.strategy_desc.setStyleSheet("color: #888; font-size: 11px;")
        strat_layout.addWidget(self.strategy_combo)
        strat_layout.addWidget(self.strategy_desc)
        layout.addWidget(strat_group)

        # 并行组
        parallel_group = QGroupBox("并行设置")
        parallel_layout = QFormLayout(parallel_group)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(4)
        self.workers_spin.setSuffix(" 个")
        parallel_layout.addRow("同时编码", self.workers_spin)
        layout.addWidget(parallel_group)

        # 输出组
        output_group = QGroupBox("输出设置")
        output_layout = QVBoxLayout(output_group)
        self.output_mode = QComboBox()
        self.output_mode.addItems(["移至备份目录", "仅输出新文件", "直接替换"])
        self.auto_delete_cb = QCheckBox("确认后自动删除原文件")
        output_layout.addWidget(self.output_mode)
        output_layout.addWidget(self.auto_delete_cb)
        layout.addWidget(output_group)

        # 开始按钮
        self.start_btn = QPushButton("▶ 开始压缩")
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #059669; color: white; "
            "padding: 8px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #047857; }"
        )
        self.start_btn.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.start_btn)
        layout.addStretch()

    def set_strategies(self, strategies: list):
        self._strategies = strategies
        self.strategy_combo.clear()
        for s in strategies:
            self.strategy_combo.addItem(f"{s.name} ⭐" if s.is_preset else s.name)
        if strategies:
            self._update_desc(strategies[0])

    def _update_desc(self, s):
        self.strategy_desc.setText(
            f"{s.description}\n预计节省: {s.estimated_savings}\n{s.quality_impact}"
        )

    @property
    def worker_count(self) -> int:
        return self.workers_spin.value()

    @property
    def current_strategy(self):
        idx = self.strategy_combo.currentIndex()
        if 0 <= idx < len(self._strategies):
            return self._strategies[idx]
        return None
