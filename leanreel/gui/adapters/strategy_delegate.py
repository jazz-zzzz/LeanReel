"""策略列 QComboBox 委托"""
from PySide6.QtWidgets import QStyledItemDelegate, QComboBox
from PySide6.QtCore import Qt

from leanreel.ui_text import UI_TEXT


class StrategyDelegate(QStyledItemDelegate):
    """列 5（处理策略）的 QComboBox 编辑器委托。"""

    def __init__(self, strategy_lookup: dict, combo_factory, parent=None):
        super().__init__(parent)
        self._lookup = strategy_lookup
        self._factory = combo_factory

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setMinimumWidth(140)
        combo.setMaximumHeight(28)
        names = list(self._lookup)
        if UI_TEXT.FILE_CUSTOM_STRATEGY not in names:
            names.append(UI_TEXT.FILE_CUSTOM_STRATEGY)
        combo.addItems(names)
        combo.wheelEvent = lambda event: event.ignore()
        if parent is not None:
            combo.activated.connect(lambda _idx, editor=combo: self.commitData.emit(editor))
        return combo

    def setEditorData(self, editor, index):
        current = index.data(Qt.DisplayRole) or ""
        if editor.findText(current) >= 0:
            editor.setCurrentText(current)
        elif current and current not in ("未匹配", "—"):
            editor.insertItem(0, current)
            editor.setCurrentText(current)

    def setModelData(self, editor, model, index):
        text = editor.currentText()
        model.setData(index, text, Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)
