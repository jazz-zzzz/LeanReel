"""策略面板 — 预设选择 + 并行设置 + 输出设置"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QLabel, QSpinBox,
    QCheckBox, QPushButton, QGroupBox, QFormLayout,
    QLineEdit, QFileDialog, QHBoxLayout, QToolButton
)
from PySide6.QtCore import Signal

from leanreel.core.strategy import Strategy

_CPU_ENCODERS = ["libx265", "libx264"]
_GPU_ENCODERS = ["hevc_nvenc", "h264_nvenc"]
_ALL_ENCODERS = [*_CPU_ENCODERS, *_GPU_ENCODERS, "copy"]

_CPU_PRESETS = ["medium", "slow", "slower", "fast"]
_NV_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]


class StrategyPanel(QWidget):
    start_requested = Signal()
    strategy_changed = Signal(int)  # strategy index
    custom_strategy_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._strategies = []
        self._temp_dir = str(Path.home() / "Temp" / "LeanReel")
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

        # 编码器
        self.custom_encoder_combo = QComboBox()
        self.custom_encoder_combo.addItems(_ALL_ENCODERS)
        self.custom_encoder_combo.currentIndexChanged.connect(self._on_encoder_changed)

        # CPU 参数
        self.custom_crf_spin = QSpinBox()
        self.custom_crf_spin.setRange(0, 35)
        self.custom_crf_spin.setValue(20)
        self.crf_label = QLabel("CRF")

        self.custom_preset_combo = QComboBox()
        self.custom_preset_combo.addItems(_CPU_PRESETS)
        self.custom_preset_combo.setCurrentText("slow")
        self.preset_label = QLabel("预设")

        # GPU 参数
        self.custom_cq_spin = QSpinBox()
        self.custom_cq_spin.setRange(0, 51)
        self.custom_cq_spin.setValue(23)
        self.custom_cq_spin.hide()
        self.cq_label = QLabel("CQ")
        self.cq_label.hide()

        self.custom_nvpreset_combo = QComboBox()
        self.custom_nvpreset_combo.addItems([p.upper() for p in _NV_PRESETS])
        self.custom_nvpreset_combo.setCurrentText("P1")
        self.custom_nvpreset_combo.hide()
        self.nvpreset_label = QLabel("NV 预设")
        self.nvpreset_label.hide()

        # 音轨 / 字幕
        self.custom_audio_combo = QComboBox()
        self.custom_audio_combo.addItems(["keep_original", "strip_commentary"])
        self.custom_subtitle_combo = QComboBox()
        self.custom_subtitle_combo.addItems(["keep_chinese", "keep_chinese_english", "keep_all", "remove_all"])
        self.custom_savings_label = QLabel("预计节省: 35-50%")

        custom_layout.addRow("编码器", self.custom_encoder_combo)
        custom_layout.addRow(self.crf_label, self.custom_crf_spin)
        custom_layout.addRow(self.preset_label, self.custom_preset_combo)
        custom_layout.addRow(self.cq_label, self.custom_cq_spin)
        custom_layout.addRow(self.nvpreset_label, self.custom_nvpreset_combo)
        custom_layout.addRow("音轨", self.custom_audio_combo)
        custom_layout.addRow("字幕", self.custom_subtitle_combo)
        custom_layout.addRow(self.custom_savings_label)
        self.custom_group.hide()
        layout.addWidget(self.custom_group)

        # 信号连接
        for widget in (
            self.custom_encoder_combo,
            self.custom_crf_spin, self.custom_cq_spin,
            self.custom_preset_combo, self.custom_nvpreset_combo,
            self.custom_audio_combo, self.custom_subtitle_combo,
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

        # 输出模式
        self.output_mode = QComboBox()
        self.output_mode.addItems(["移至备份目录", "仅输出新文件", "直接替换"])
        output_layout.addWidget(self.output_mode)

        # 临时目录 (I/O 分离)
        temp_layout = QHBoxLayout()
        self.temp_dir_edit = QLineEdit(self._temp_dir)
        self.temp_dir_edit.setPlaceholderText("编码临时目录（用于 I/O 分离加速）")
        self.browse_btn = QToolButton()
        self.browse_btn.setText("...")
        self.browse_btn.clicked.connect(self._browse_temp_dir)
        temp_layout.addWidget(self.temp_dir_edit)
        temp_layout.addWidget(self.browse_btn)
        output_layout.addLayout(temp_layout)

        self.auto_delete_cb = QCheckBox("确认后自动删除原文件")
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

    def _on_encoder_changed(self):
        encoder = self.custom_encoder_combo.currentText()
        is_gpu = encoder in _GPU_ENCODERS
        is_copy = encoder == "copy"

        self.crf_label.setVisible(not is_gpu and not is_copy)
        self.custom_crf_spin.setVisible(not is_gpu and not is_copy)
        self.preset_label.setVisible(not is_gpu and not is_copy)
        self.custom_preset_combo.setVisible(not is_gpu and not is_copy)

        self.cq_label.setVisible(is_gpu)
        self.custom_cq_spin.setVisible(is_gpu)
        self.nvpreset_label.setVisible(is_gpu)
        self.custom_nvpreset_combo.setVisible(is_gpu)

        self._emit_custom_strategy()

    def _browse_temp_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择编码临时目录", self.temp_dir_edit.text())
        if d:
            self.temp_dir_edit.setText(d)
            self._temp_dir = d

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
        encoder = self.custom_encoder_combo.currentText()
        is_gpu = encoder in _GPU_ENCODERS

        if encoder == "copy":
            savings = "5-15%"
        elif is_gpu:
            cq = self.custom_cq_spin.value()
            if cq <= 20:
                savings = "20-35%"
            elif cq <= 23:
                savings = "35-50%"
            else:
                savings = "50-70%"
        else:
            crf = self.custom_crf_spin.value()
            if crf <= 18:
                savings = "20-35%"
            elif crf <= 20:
                savings = "35-50%"
            else:
                savings = "50-70%"

        nv_preset = self.custom_nvpreset_combo.currentText().lower()

        return Strategy.from_dict({
            "name": "自定义",
            "description": "手动配置的压缩策略",
            "is_preset": False,
            "video": {
                "encoder": encoder,
                "crf": self.custom_crf_spin.value(),
                "preset": self.custom_preset_combo.currentText(),
                "pix_fmt": "yuv420p10le",
                "gpu": is_gpu,
                "nv_preset": nv_preset,
                "rc": "vbr",
                "cq": self.custom_cq_spin.value(),
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
    def temp_dir(self) -> str:
        return self.temp_dir_edit.text().strip() or self._temp_dir

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
