from PySide6.QtWidgets import QPlainTextEdit,QToolTip
from gui.help_text import signal_help,tooltip

class HelpTextEdit(QPlainTextEdit):
    """历史游标文本每行也可悬停解释，保持原 QPlainTextEdit API。"""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMouseTracking(True);self.viewport().setMouseTracking(True)

    def mouseMoveEvent(self,event):
        super().mouseMoveEvent(event)
        line=self.cursorForPosition(event.position().toPoint()).block().text()
        help_text=signal_help(line.split(':',1)[0])
        if help_text:QToolTip.showText(event.globalPosition().toPoint(),tooltip(help_text),self)
        else:QToolTip.hideText()
