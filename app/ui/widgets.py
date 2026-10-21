from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolTip,
    QWidget,
)


COPYRIGHT_CAPTION = "ANJAY Solution Software Dev. 2026"
PRIMARY_BUTTON_STYLE = (
    "QPushButton { background: #007acc; color: white; border: none; "
    "border-radius: 8px; padding: 9px 14px; font-weight: 600; }"
    "QPushButton:hover { background: #0098ff; }"
)
DASHBOARD_BACK_BUTTON_STYLE = (
    "QPushButton { background: #007acc; color: white; border: none; "
    "border-radius: 8px; padding: 9px 14px; font-weight: 600; }"
    "QPushButton:hover { background: #0098ff; }"
    "QPushButton:pressed { background: #005995; }"
)


def create_dashboard_back_button(parent=None) -> QPushButton:
    button = QPushButton("Dashboard", parent)
    button.setObjectName("dashboardBackButton")
    pixmap = QPixmap(QSize(20, 20))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(
        QPen(
            QColor("#ffffff"),
            2.2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.drawLine(QPointF(16, 10), QPointF(4, 10))
    painter.drawLine(QPointF(4, 10), QPointF(10, 4))
    painter.drawLine(QPointF(4, 10), QPointF(10, 16))
    painter.end()
    button.setIcon(QIcon(pixmap))
    button.setIconSize(QSize(18, 18))
    button.setStyleSheet(DASHBOARD_BACK_BUTTON_STYLE)
    return button


def create_copyright_label(parent=None) -> QLabel:
    label = QLabel(COPYRIGHT_CAPTION, parent)
    label.setObjectName("copyrightCredit")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setStyleSheet(
        "color: #89b4fa; font-size: 10px; font-weight: 600; padding: 3px 8px;"
    )
    return label


class TableSearchBar(QWidget):
    """Input teks + tombol Cari untuk menyaring baris tabel record.

    Kata kunci dipasang otomatis ulang setiap isi tabel berubah
    (mis. saat refresh memuat ulang data), sehingga hasil saringan
    tidak hilang ketika tabel diperbarui.
    """

    def __init__(self, table, placeholder: str = "Cari data...", parent=None):
        super().__init__(parent)
        self.table = table
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.setClearButtonEnabled(True)
        self.button = QPushButton("Cari")
        row.addWidget(self.input, 1)
        row.addWidget(self.button)

        self.button.clicked.connect(self.apply)
        self.input.returnPressed.connect(self.apply)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.apply)
        model = table.model()
        model.rowsInserted.connect(self._queue)
        model.rowsRemoved.connect(self._queue)
        model.layoutChanged.connect(self._queue)
        model.modelReset.connect(self._queue)

    def _queue(self, *_args):
        self._timer.start()

    def apply(self, *_args):
        query = self.input.text().strip().casefold()
        table = self.table
        table.setUpdatesEnabled(False)
        try:
            for row in range(table.rowCount()):
                if not query:
                    table.setRowHidden(row, False)
                    continue
                texts = []
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item is not None:
                        texts.append(item.text())
                table.setRowHidden(
                    row, query not in " ".join(texts).casefold()
                )
        finally:
            table.setUpdatesEnabled(True)


def attach_status_focus_hint(table) -> None:
    """Tampilkan tooltip sel status (mis. jumlah DP) saat baris difokuskan.

    Tooltip sel tampil otomatis saat hover; fungsi ini melengkapinya
    agar juga muncul saat sel dipilih lewat klik maupun keyboard.
    """

    def _show_hint():
        item = table.currentItem()
        if item is None or not item.toolTip():
            return
        rect = table.visualItemRect(item)
        if not rect.isValid():
            return
        QToolTip.showText(
            table.viewport().mapToGlobal(rect.topLeft()),
            item.toolTip(),
            table,
        )

    table.itemSelectionChanged.connect(_show_hint)
