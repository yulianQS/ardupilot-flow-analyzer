from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
from gui.help_text import help_for, tooltip, HEADERS

def table(headers, rows=0):
    widget = QTableWidget(rows, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    for column,header in enumerate(headers):
        widget.horizontalHeaderItem(column).setToolTip(tooltip(HEADERS.get(header,help_for(header))))
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget

def cell(widget, row, column, value):
    text = 'N/A' if value is None else str(value)
    item = widget.item(row, column)
    if item is None:
        item = QTableWidgetItem(text)
        widget.setItem(row, column, item)
    elif item.text() != text:
        item.setText(text)
    first = widget.item(row,0)
    header = widget.horizontalHeaderItem(column)
    description = help_for(first.text()) if first else ''
    column_help = HEADERS.get(header.text(),'') if header else ''
    item.setToolTip(tooltip('\n'.join(part for part in (description,column_help) if part)))

def number(value, digits=3):
    return 'N/A' if value is None else f'{value:.{digits}f}'
