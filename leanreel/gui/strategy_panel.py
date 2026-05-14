"""策略面板 — 卡片式预设选择 + 并行/输出设置，TMM 风格"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QLabel, QSpinBox,
    QCheckBox, QPushButton, QGroupBox, QFormLayout,
    QLineEdit, QFileDialog, QHBoxLayout, QToolButton,
    QButtonGroup, QScrollArea
)
from PySide6.QtCore import Signal, Qt

from leanreel.core.strategy import Strategy

_CPU_ENCODERS = ["libx265", "libx264"]
_GPU_ENCODERS = ["hevc_nvenc", "h264_nvenc"]
_ALL_ENCODERS = [*_CPU_ENCODERS, *_GPU_ENCODERS, "copy"]
_CPU_PRESETS = ["medium", "slow", "slower", "fast"]
_NV_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]

_CARD_STYLE = """
QPushButton {{
    background-color: #1c1a16;
    border: 2px solid #2e2b25;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    min-height: 56px;
}}
QPushButton:hover {{
    border-color: #5c4a2e;
    background-color: #24221d;
}}
QPushButton:checked {{
    border: 2px solid #d4a853;
    background-color: #3d2e14;
}}
QPushButton:checked:hover {{
    border-color: #e0b85c;
    background-color: #45341a;
}}
"""


class StrategyPanel(QWidget):
    start_requested = Signal()
    strategy_changed = Signal(int)
    custom_strategy_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._strategies = []
        self._temp_dir = str(Path.home() / "Temp" / "LeanReel")
        self._active_preset_index = 0
        self._resizing = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── 预设卡片 ──
        presets_label = QLabel("压缩策略")
        presets_label.setStyleSheet("font-weight: bold; color: #8a857c; font-size: 11px; padding: 2px 4px;")
        layout.addWidget(presets_label)

        self.card_area = QScrollArea()
        self.card_area.setWidgetResizable(True)
        self.card_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(4)
        self.card_layout.addStretch()
        self.card_area.setWidget(self.card_container)
        layout.addWidget(self.card_area)

        self.card_group = QButtonGroup(self)
        self.card_group.setExclusive(True)

        # ── 自定义区域 ──
        self.custom_group = QGroupBox("自定义参数")
        self.custom_group.setStyleSheet("QGroupBox { padding-top: 18px; margin-top: 8px; }")
        custom_layout = QFormLayout(self.custom_group)
        custom_layout.setContentsMargins(8, 4, 8, 4)
        custom_layout.setVerticalSpacing(6)

        self.custom_encoder_combo = QComboBox()
        self.custom_encoder_combo.addItems(_ALL_ENCODERS)
        self.custom_encoder_combo.currentIndexChanged.connect(self._on_encoder_changed)

        self.custom_crf_spin = QSpinBox()
        self.custom_crf_spin.setRange(0, 35)
        self.custom_crf_spin.setValue(20)
        self.crf_label = QLabel("CRF")

        self.custom_preset_combo = QComboBox()
        self.custom_preset_combo.addItems(_CPU_PRESETS)
        self.custom_preset_combo.setCurrentText("slow")
        self.preset_label = QLabel("预设")

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

        self.custom_audio_combo = QComboBox()
        self.custom_audio_combo.addItems(["keep_original", "strip_commentary"])
        self.custom_subtitle_combo = QComboBox()
        self.custom_subtitle_combo.addItems(["keep_chinese", "keep_chinese_english", "keep_all", "remove_all"])
        self.custom_savings_label = QLabel("预计节省：35-50%")

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

        # ── 并行 ──
        parallel_group = QGroupBox("并行设置")
        parallel_layout = QFormLayout(parallel_group)
        parallel_layout.setContentsMargins(8, 4, 8, 4)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(4)
        self.workers_spin.setSuffix(" 个")
        parallel_layout.addRow("同时编码", self.workers_spin)
        layout.addWidget(parallel_group)

        # ── 输出 ──
        output_group = QGroupBox("输出设置")
        output_layout = QVBoxLayout(output_group)
        output_layout.setContentsMargins(8, 4, 8, 4)
        output_layout.setSpacing(4)

        temp_layout = QHBoxLayout()
        self.temp_dir_edit = QLineEdit(self._temp_dir)
        self.temp_dir_edit.setPlaceholderText("编码临时目录（本地 SSD 路径）")
        self.browse_btn = QToolButton()
        self.browse_btn.setText("...")
        self.browse_btn.clicked.connect(self._browse_temp_dir)
        temp_layout.addWidget(self.temp_dir_edit)
        temp_layout.addWidget(self.browse_btn)
        output_layout.addLayout(temp_layout)
        output_layout.addWidget(QLabel("临时目录用于 I/O 分离加速"))
        layout.addWidget(output_group)

        # ── 开始 ──
        self.start_btn = QPushButton("开始压缩")
        self.start_btn.setProperty("class", "accent")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #c8963e; color: #12100e;
                border: none; border-radius: 6px;
                padding: 12px 24px; font-weight: bold; font-size: 15px;
            }
            QPushButton:hover { background-color: #d9a84c; }
            QPushButton:pressed { background-color: #b88730; }
        """)
        self.start_btn.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.start_btn)

    def _make_card(self, s: Strategy, index: int) -> QPushButton:
        tag = "GPU" if s.video.is_gpu else ("CPU" if s.video.encoder.startswith("lib") else "COPY")
        savings = getattr(s, "estimated_savings", "") or ""
        desc = getattr(s, "description", "") or ""
        if len(desc) > 52:
            desc = desc[:50] + "..."

        prefix = "●" if index == 0 else "○"
        plain = f"{prefix} {s.name}  [{tag}]  节省 {savings}"
        if desc:
            plain += f"\n    {desc}"

        btn = QPushButton(plain)
        btn.setCheckable(True)
        btn.setStyleSheet(_CARD_STYLE)
        btn.clicked.connect(lambda checked=False, i=index: self._on_card_clicked(i))
        return btn

    def set_strategies(self, strategies: list):
        self._strategies = strategies
        for btn in self.card_group.buttons():
            self.card_group.removeButton(btn)

        while self.card_layout.count() > 1:
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, s in enumerate(strategies):
            card = self._make_card(s, i)
            self.card_group.addButton(card, i)
            self.card_layout.insertWidget(self.card_layout.count() - 1, card)

        if strategies:
            self.card_group.buttons()[0].setChecked(True)
            self._active_preset_index = 0

        self.custom_group.hide()
        self._update_card_heights()

    def _update_card_heights(self):
        h = max(120, self.height() - 400)
        self.card_area.setMaximumHeight(h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._resizing:
            self._resizing = True
            self._update_card_heights()
            self._resizing = False

    def _on_card_clicked(self, index: int):
        self._active_preset_index = index
        self.custom_group.hide()
        self._update_card_indicators()
        self.strategy_changed.emit(index)

    def _update_card_indicators(self):
        for i, btn in enumerate(self.card_group.buttons()):
            s = self._strategies[i]
            tag = "GPU" if s.video.is_gpu else ("CPU" if s.video.encoder.startswith("lib") else "COPY")
            savings = getattr(s, "estimated_savings", "") or ""
            desc = getattr(s, "description", "") or ""
            if len(desc) > 52:
                desc = desc[:50] + "..."
            prefix = "●" if i == self._active_preset_index else "○"
            plain = f"{prefix} {s.name}  [{tag}]  节省 {savings}"
            if desc:
                plain += f"\n    {desc}"
            btn.setText(plain)
            btn.setChecked(i == self._active_preset_index)

    def show_custom_strategy(self):
        self.custom_group.show()
        self._emit_custom_strategy()

    def show_preset_strategy(self):
        self.custom_group.hide()

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

    def _emit_custom_strategy(self):
        strategy = self.custom_strategy
        self.custom_savings_label.setText(f"预计节省：{strategy.estimated_savings}")
        self.custom_strategy_changed.emit(strategy)

    @property
    def custom_strategy(self):
        encoder = self.custom_encoder_combo.currentText()
        is_gpu = encoder in _GPU_ENCODERS

        if encoder == "copy":
            savings = "5-15%"
        elif is_gpu:
            cq_val = self.custom_cq_spin.value()
            if cq_val <= 20:
                savings = "20-35%"
            elif cq_val <= 23:
                savings = "35-50%"
            else:
                savings = "50-70%"
        else:
            crf_val = self.custom_crf_spin.value()
            if crf_val <= 18:
                savings = "20-35%"
            elif crf_val <= 20:
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
            "quality_impact": "自定义参数",
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
        idx = self._active_preset_index
        if 0 <= idx < len(self._strategies):
            return self._strategies[idx]
        return None
