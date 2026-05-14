"""策略面板 — 预设选择 + 并行设置 + 输出设置"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QLabel, QSpinBox,
    QCheckBox, QPushButton, QGroupBox, QFormLayout
)
from PySide6.QtCore import Signal

from leanreel.core.strategy import Strategy


class StrategyPanel(QWidget):
    start_requested = Signal()
    strategy_changed = Signal(int)  # strategy index
    custom_strategy_changed = Signal(object)

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

        self.custom_group = QGroupBox("自定义参数")
        custom_layout = QFormLayout(self.custom_group)
        self.custom_encoder_combo = QComboBox()
        self.custom_encoder_combo.addItems(["libx265", "libx264", "copy"])
        self.custom_crf_spin = QSpinBox()
        self.custom_crf_spin.setRange(0, 35)
        self.custom_crf_spin.setValue(20)
        self.custom_preset_combo = QComboBox()
        self.custom_preset_combo.addItems(["medium", "slow", "slower", "fast"])
        self.custom_audio_combo = QComboBox()
        self.custom_audio_combo.addItems(["keep_original", "strip_commentary"])
        self.custom_subtitle_combo = QComboBox()
        self.custom_subtitle_combo.addItems(["keep_chinese", "keep_chinese_english", "keep_all", "remove_all"])
        self.custom_savings_label = QLabel("预计节省: 35-50%")
        custom_layout.addRow("编码器", self.custom_encoder_combo)
        custom_layout.addRow("CRF", self.custom_crf_spin)
        custom_layout.addRow("预设", self.custom_preset_combo)
        custom_layout.addRow("音轨", self.custom_audio_combo)
        custom_layout.addRow("字幕", self.custom_subtitle_combo)
        custom_layout.addRow(self.custom_savings_label)
        self.custom_group.hide()
        layout.addWidget(self.custom_group)

        for widget in (
            self.custom_encoder_combo,
            self.custom_crf_spin,
            self.custom_preset_combo,
            self.custom_audio_combo,
            self.custom_subtitle_combo,
        ):
            if hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._emit_custom_strategy)
            else:
                widget.valueChanged.connect(self._emit_custom_strategy)

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

    def show_custom_strategy(self):
        self.custom_group.show()
        self.strategy_desc.setText("正在编辑自定义策略，参数变化会实时刷新列表中的预计节省。")
        self._emit_custom_strategy()

    def show_preset_strategy(self):
        self.custom_group.hide()
        strategy = self.current_strategy
        if strategy is not None:
            self._update_desc(strategy)

    def _emit_custom_strategy(self):
        strategy = self.custom_strategy
        self.custom_savings_label.setText(f"预计节省: {strategy.estimated_savings}")
        self.custom_strategy_changed.emit(strategy)

    @property
    def custom_strategy(self):
        crf = self.custom_crf_spin.value()
        if self.custom_encoder_combo.currentText() == "copy":
            savings = "5-15%"
        elif crf <= 18:
            savings = "20-35%"
        elif crf <= 20:
            savings = "35-50%"
        else:
            savings = "50-70%"
        return Strategy.from_dict({
            "name": "自定义",
            "description": "手动配置的压缩策略",
            "is_preset": False,
            "video": {
                "encoder": self.custom_encoder_combo.currentText(),
                "crf": crf,
                "preset": self.custom_preset_combo.currentText(),
                "pix_fmt": "yuv420p10le",
            },
            "audio": {"mode": self.custom_audio_combo.currentText()},
            "subtitle": {"mode": self.custom_subtitle_combo.currentText()},
            "filters": {"skip_x265": False},
            "estimated_savings": savings,
            "quality_impact": "自定义参数，节省空间为粗略估算",
        })

    @property
    def worker_count(self) -> int:
        return self.workers_spin.value()

    @property
    def current_strategy(self):
        if self.custom_group.isVisibleTo(self):
            return self.custom_strategy
        return self.current_preset_strategy

    @property
    def current_preset_strategy(self):
        idx = self.strategy_combo.currentIndex()
        if 0 <= idx < len(self._strategies):
            return self._strategies[idx]
        return None
