"""策略面板 — 紧凑单选式预设选择 + 可折叠自定义参数 + 编码设置"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QLabel, QSpinBox,
    QPushButton, QGroupBox, QFormLayout,
    QLineEdit, QFileDialog, QHBoxLayout, QToolButton,
    QButtonGroup, QSizePolicy
)
from PySide6.QtCore import Signal

from leanreel.core.strategy import Strategy

_GPU_ENCODERS = ["hevc_nvenc", "h264_nvenc"]
_ALL_ENCODERS = [*_GPU_ENCODERS, "copy"]
_NV_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]

_ROW_STYLE = """
QPushButton {
    background-color: #1c1a16;
    border: 1px solid #2e2b25;
    border-radius: 4px;
    padding: 3px 8px;
    text-align: left;
    min-height: 24px;
    font-size: 12px;
    color: #c8c0b8;
}
QPushButton:hover {
    border-color: #5c4a2e;
    background-color: #24221d;
}
QPushButton:checked {
    border: 1px solid #d4a853;
    background-color: #3d2e14;
    color: #f0e6d0;
}
QPushButton:checked:hover {
    border-color: #e0b85c;
    background-color: #45341a;
}
"""


class PresetCardPanel(QWidget):
    """预设策略选择面板 — 紧凑单选行 + 独立描述标签

    将原来的大卡片改为紧凑的单选按钮行，每行仅显示：
      ● 策略名  [CPU/GPU/COPY]  节省率
    描述文字独立显示在策略列表下方的 QLabel 中。
    """

    strategy_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self._strategies = []
        self._active_preset_index = 0
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        presets_label = QLabel("压缩策略")
        presets_label.setStyleSheet(
            "font-weight: bold; color: #8a857c; font-size: 11px; padding: 2px 4px;"
        )
        layout.addWidget(presets_label)

        # 按钮容器 — 每条策略一行紧凑按钮
        self.button_area = QWidget()
        self.button_layout = QVBoxLayout(self.button_area)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(2)
        layout.addWidget(self.button_area)

        # 描述标签 — 独立显示当前选中策略的描述
        self.description_label = QLabel("")
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet(
            "color: #a0988c; font-size: 11px; padding: 4px 8px;"
            "background: #1a1915; border-radius: 4px;"
            "border: 1px solid #2e2b25;"
        )
        self.description_label.hide()
        layout.addWidget(self.description_label)

        self.card_group = QButtonGroup(self)
        self.card_group.setExclusive(True)

    def _make_row_button(self, s: Strategy, index: int) -> QPushButton:
        tag = "GPU" if s.video.is_gpu else ("CPU" if s.video.encoder.startswith("lib")
                                             else "COPY")
        savings = getattr(s, "estimated_savings", "") or ""
        prefix = "●" if index == 0 else "○"
        text = f"{prefix}  {s.name}    [{tag}]  {savings}"

        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setStyleSheet(_ROW_STYLE)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.clicked.connect(lambda checked=False, i=index: self._on_card_clicked(i))
        return btn

    def set_strategies(self, strategies: list):
        self._strategies = strategies

        # 清除旧按钮
        for btn in self.card_group.buttons():
            self.card_group.removeButton(btn)

        while self.button_layout.count() > 0:
            item = self.button_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 创建新按钮
        for i, s in enumerate(strategies):
            btn = self._make_row_button(s, i)
            self.card_group.addButton(btn, i)
            self.button_layout.addWidget(btn)

        if strategies:
            self.card_group.buttons()[0].setChecked(True)
            self._active_preset_index = 0
            self._update_description()
        else:
            self.description_label.hide()

    def _on_card_clicked(self, index: int):
        self._active_preset_index = index
        self._update_indicators()
        self._update_description()
        self.strategy_changed.emit(index)

    def _update_indicators(self):
        """更新所有按钮的前缀指示器 (●/○) 和 checked 状态"""
        for i, btn in enumerate(self.card_group.buttons()):
            s = self._strategies[i]
            tag = "GPU" if s.video.is_gpu else ("CPU" if s.video.encoder.startswith("lib")
                                                 else "COPY")
            savings = getattr(s, "estimated_savings", "") or ""
            prefix = "●" if i == self._active_preset_index else "○"
            text = f"{prefix}  {s.name}    [{tag}]  {savings}"
            btn.setText(text)
            btn.setChecked(i == self._active_preset_index)

    def _update_description(self):
        """根据当前选中的策略更新描述标签"""
        idx = self._active_preset_index
        if 0 <= idx < len(self._strategies):
            desc = getattr(self._strategies[idx], "description", "") or ""
            if desc.strip():
                self.description_label.setText(f"  {desc}")
                self.description_label.show()
            else:
                self.description_label.hide()
        else:
            self.description_label.hide()

    @property
    def current_preset_strategy(self):
        idx = self._active_preset_index
        if 0 <= idx < len(self._strategies):
            return self._strategies[idx]
        return None


class CollapsibleGroup(QGroupBox):
    """可折叠的 QGroupBox — 点击标题栏复选框切换内容可见性"""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.setStyleSheet("""
            QGroupBox {
                padding-top: 16px;
                margin-top: 4px;
                font-weight: bold;
                color: #8a857c;
                border: 1px solid #2e2b25;
                border-radius: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QGroupBox::indicator {
                width: 12px;
                height: 12px;
            }
        """)

    def set_content_widget(self, widget: QWidget):
        """设置内容 widget，折叠时自动隐藏"""
        self._content = widget
        # 将 content widget 添加到 group box 的布局中
        if self.layout() is None:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(4, 4, 4, 4)
            main_layout.addWidget(widget)
        else:
            self.layout().addWidget(widget)
        widget.setVisible(False)
        self.toggled.connect(widget.setVisible)


class StrategyPanel(QWidget):
    """策略面板 — PresetCardPanel + 可折叠自定义参数 + 编码设置 + 开始按钮"""

    start_requested = Signal()
    strategy_changed = Signal(int)
    custom_strategy_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._temp_dir = str(Path.home() / "Temp" / "LeanReel")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── 预设选择（紧凑单选行）──
        self.preset_panel = PresetCardPanel()
        self.preset_panel.strategy_changed.connect(self.strategy_changed.emit)
        layout.addWidget(self.preset_panel)

        # ── 自定义参数（可折叠）──
        self.custom_group = CollapsibleGroup("自定义参数")

        custom_content = QWidget()
        custom_layout = QFormLayout(custom_content)
        custom_layout.setContentsMargins(4, 0, 4, 0)
        custom_layout.setVerticalSpacing(6)

        self.custom_encoder_combo = QComboBox()
        self.custom_encoder_combo.addItems(_ALL_ENCODERS)
        self.custom_encoder_combo.currentIndexChanged.connect(self._on_encoder_changed)

        self.custom_cq_spin = QSpinBox()
        self.custom_cq_spin.setRange(0, 51)
        self.custom_cq_spin.setValue(23)
        self.cq_label = QLabel("CQ")

        self.custom_nvpreset_combo = QComboBox()
        self.custom_nvpreset_combo.addItems([p.upper() for p in _NV_PRESETS])
        self.custom_nvpreset_combo.setCurrentText("P1")
        self.nvpreset_label = QLabel("NV 预设")

        self.custom_audio_combo = QComboBox()
        self.custom_audio_combo.addItems(["keep_original", "strip_commentary"])
        self.custom_subtitle_combo = QComboBox()
        self.custom_subtitle_combo.addItems(
            ["keep_chinese", "keep_chinese_english", "keep_all", "remove_all"]
        )
        self.custom_savings_label = QLabel("预计节省：35-50%")

        custom_layout.addRow("编码器", self.custom_encoder_combo)
        custom_layout.addRow(self.cq_label, self.custom_cq_spin)
        custom_layout.addRow(self.nvpreset_label, self.custom_nvpreset_combo)
        custom_layout.addRow("音轨", self.custom_audio_combo)
        custom_layout.addRow("字幕", self.custom_subtitle_combo)
        custom_layout.addRow(self.custom_savings_label)

        self.custom_group.set_content_widget(custom_content)
        layout.addWidget(self.custom_group)

        # 信号连接 — 自定义参数变化时重新计算策略
        for widget in (
            self.custom_encoder_combo,
            self.custom_cq_spin,
            self.custom_nvpreset_combo,
            self.custom_audio_combo, self.custom_subtitle_combo,
        ):
            if hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._emit_custom_strategy)
            else:
                widget.valueChanged.connect(self._emit_custom_strategy)

        # ── 编码设置 ──
        encode_group = QGroupBox("编码设置")
        encode_group.setStyleSheet("""
            QGroupBox {
                padding-top: 16px;
                margin-top: 4px;
                font-weight: bold;
                color: #8a857c;
                border: 1px solid #2e2b25;
                border-radius: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        encode_layout = QFormLayout(encode_group)
        encode_layout.setContentsMargins(8, 4, 8, 4)
        encode_layout.setVerticalSpacing(6)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(4)
        self.workers_spin.setSuffix(" 个")
        encode_layout.addRow("并行数", self.workers_spin)

        temp_row = QHBoxLayout()
        self.temp_dir_edit = QLineEdit(self._temp_dir)
        self.temp_dir_edit.setPlaceholderText("编码临时目录（本地 SSD 路径）")
        self.browse_btn = QToolButton()
        self.browse_btn.setText("...")
        self.browse_btn.clicked.connect(self._browse_temp_dir)
        temp_row.addWidget(self.temp_dir_edit)
        temp_row.addWidget(self.browse_btn)
        encode_layout.addRow("临时目录", temp_row)
        layout.addWidget(encode_group)

        # ── 开始按钮 ──
        self.start_btn = QPushButton("开始压缩")
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

    def set_strategies(self, strategies: list):
        self.preset_panel.set_strategies(strategies)
        self.custom_group.setChecked(False)

    def show_custom_strategy(self):
        self.custom_group.setChecked(True)
        self._emit_custom_strategy()

    def show_preset_strategy(self):
        self.custom_group.setChecked(False)

    def _on_encoder_changed(self):
        encoder = self.custom_encoder_combo.currentText()
        is_gpu = encoder in _GPU_ENCODERS
        is_copy = encoder == "copy"

        # GPU 默认始终显示 CQ/NV preset；copy 模式全隐藏
        self.cq_label.setVisible(is_gpu)
        self.custom_cq_spin.setVisible(is_gpu)
        self.nvpreset_label.setVisible(is_gpu)
        self.custom_nvpreset_combo.setVisible(is_gpu)

        self._emit_custom_strategy()

    def _browse_temp_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择编码临时目录", self.temp_dir_edit.text()
        )
        if d:
            self.temp_dir_edit.setText(d)
            self._temp_dir = d

    def _emit_custom_strategy(self):
        strategy = self.custom_strategy
        self.custom_savings_label.setText(
            f"预计节省：{strategy.estimated_savings}"
        )
        self.custom_strategy_changed.emit(strategy)

    @property
    def custom_strategy(self):
        encoder = self.custom_encoder_combo.currentText()

        if encoder == "copy":
            savings = "5-15%"
        else:
            cq_val = self.custom_cq_spin.value()
            if cq_val <= 20:
                savings = "20-35%"
            elif cq_val <= 23:
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
                "crf": 0,
                "preset": "",
                "pix_fmt": "yuv420p10le",
                "gpu": True,
                "nv_preset": nv_preset,
                "rc": "vbr",
                "cq": self.custom_cq_spin.value(),
            },
            "audio": {"mode": self.custom_audio_combo.currentText()},
            "subtitle": {"mode": self.custom_subtitle_combo.currentText()},
            "filters": {"skip_x265": False},
            "estimated_savings": savings,
            "quality_impact": "GPU 硬件编码",
        })

    @property
    def worker_count(self) -> int:
        return self.workers_spin.value()

    @property
    def temp_dir(self) -> str:
        return self.temp_dir_edit.text().strip() or self._temp_dir

    @property
    def current_strategy(self):
        if self.custom_group.isChecked():
            return self.custom_strategy
        return self.current_preset_strategy

    @property
    def current_preset_strategy(self):
        return self.preset_panel.current_preset_strategy
