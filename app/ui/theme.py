from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

PALETTE = {
    "window": "#121214",
    "panel": "#1a1a1e",
    "panel_alt": "#222226",
    "panel_hover": "#2a2a30",
    "panel_row": "#1e1e24",
    "text": "#ffffff",
    "text_soft": "#e4e4e7",
    "text_muted": "#a1a1aa",
    "text_disabled": "#71717a",
    "accent": "#007acc",
    "accent_hover": "#0098ff",
    "accent_pressed": "#005995",
    "accent_soft": "#89b4fa",
    "border": "#2d2d34",
    "border_hover": "#3f3f4a",
    "danger": "#dc2626",
    "danger_hover": "#ef4444",
    "success": "#16a34a",
    "success_hover": "#15803d",
    "warning": "#facc15",
    "scrollbar": "#474752",
    "scrollbar_hover": "#60606e",
}

FONT_STACK = "'Segoe UI', 'SF Pro Display', 'Inter', sans-serif"

STYLE_SHEET = f"""
QWidget {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {PALETTE['text']};
}}

QMainWindow {{
    background-color: {PALETTE['window']};
}}

QDialog {{
    background-color: {PALETTE['window']};
}}

QWidget#loginRoot, QWidget#licenseRoot {{
    background-color: {PALETTE['window']};
}}

QWidget#headerPanel, QWidget#cardPanel, QFrame#cardPanel {{
    background-color: {PALETTE['panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
}}

QPushButton {{
    background-color: {PALETTE['accent']};
    color: {PALETTE['text']};
    font-weight: 600;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
}}

QPushButton:hover {{
    background-color: {PALETTE['accent_hover']};
}}

QPushButton:pressed {{
    background-color: {PALETTE['accent_pressed']};
}}

QPushButton:disabled {{
    background-color: {PALETTE['border']};
    color: {PALETTE['text_disabled']};
}}

QPushButton#secondaryBtn {{
    background-color: transparent;
    color: {PALETTE['text_muted']};
    border: 1px solid {PALETTE['border']};
}}

QPushButton#secondaryBtn:hover {{
    background-color: {PALETTE['panel_alt']};
    color: {PALETTE['text']};
}}

QToolButton {{
    background-color: transparent;
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 6px 10px;
}}

QToolButton:hover {{
    background-color: {PALETTE['panel_alt']};
    border: 1px solid {PALETTE['border_hover']};
}}

QToolButton:pressed {{
    background-color: {PALETTE['accent_pressed']};
}}

QToolButton::menu-indicator {{
    subcontrol-origin: padding;
    subcontrol-position: right center;
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {PALETTE['panel_alt']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 9px 10px;
    color: {PALETTE['text']};
    selection-background-color: {PALETTE['accent']};
    selection-color: {PALETTE['text']};
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border: 1px solid {PALETTE['border_hover']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {PALETTE['accent']};
    background-color: {PALETTE['panel_hover']};
}}

QLineEdit:read-only {{
    color: {PALETTE['text_muted']};
}}

QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {{
    background-color: {PALETTE['panel_alt']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 7px 10px;
    color: {PALETTE['text']};
    selection-background-color: {PALETTE['accent']};
}}

QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QDateEdit:hover, QTimeEdit:hover, QDateTimeEdit:hover {{
    border: 1px solid {PALETTE['border_hover']};
}}

QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {{
    border: 1px solid {PALETTE['accent']};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 22px;
    background: transparent;
}}

QComboBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PALETTE['text_muted']};
    width: 0px;
    height: 0px;
}}

QComboBox QAbstractItemView {{
    background-color: {PALETTE['panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    color: {PALETTE['text']};
    selection-background-color: {PALETTE['accent']};
    selection-color: {PALETTE['text']};
    outline: 0;
    padding: 4px;
}}

QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 18px;
}}

QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{
    width: 8px;
    height: 8px;
    background-color: {PALETTE['text_muted']};
}}

QAbstractSpinBox::line-edit {{
    background-color: {PALETTE['panel_alt']};
    border: none;
    color: {PALETTE['text']};
    padding: 7px 10px;
    selection-background-color: {PALETTE['accent']};
    selection-color: {PALETTE['text']};
}}

QAbstractSpinBox::line-edit:focus {{
    background-color: {PALETTE['panel_hover']};
}}

QCheckBox, QRadioButton {{
    spacing: 8px;
    color: {PALETTE['text']};
    background-color: transparent;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {PALETTE['border_hover']};
    background-color: {PALETTE['panel_alt']};
}}

QCheckBox::indicator {{
    border-radius: 4px;
}}

QRadioButton::indicator {{
    border-radius: 9px;
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {PALETTE['accent']};
    border: 1px solid {PALETTE['accent']};
}}

QCheckBox:disabled, QRadioButton:disabled {{
    color: {PALETTE['text_disabled']};
}}

QTableWidget, QTableView {{
    background-color: {PALETTE['panel']};
    alternate-background-color: {PALETTE['panel_row']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    gridline-color: {PALETTE['border']};
    color: {PALETTE['text']};
    selection-background-color: {PALETTE['accent']};
    selection-color: {PALETTE['text']};
    padding: 4px;
}}

QTableWidget::viewport, QTableView::viewport {{
    background-color: {PALETTE['panel']};
    border: none;
}}

QAbstractScrollArea {{
    background-color: {PALETTE['panel']};
}}

QAbstractScrollArea::viewport {{
    background-color: {PALETTE['panel']};
    border: none;
}}

QTableView QHeaderView::vertical, QTableWidget QHeaderView::vertical {{
    background-color: {PALETTE['panel_alt']};
}}

QTableView QHeaderView::vertical::section, QTableWidget QHeaderView::vertical::section {{
    background-color: {PALETTE['panel_alt']};
    color: {PALETTE['text_muted']};
    border: none;
    border-right: 1px solid {PALETTE['border']};
    padding: 6px;
}}

QListView::viewport, QTreeView::viewport, QListWidget::viewport {{
    background-color: {PALETTE['panel']};
    border: none;
}}

QTableWidget::item, QTableView::item {{
    background-color: transparent;
    padding: 6px;
    border: none;
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {PALETTE['accent']};
    color: {PALETTE['text']};
}}

QTableWidget::item:hover, QTableView::item:hover {{
    background-color: {PALETTE['panel_alt']};
}}

QHeaderView::section {{
    background-color: {PALETTE['panel_alt']};
    color: {PALETTE['text_muted']};
    border: none;
    border-right: 1px solid {PALETTE['border']};
    border-bottom: 1px solid {PALETTE['border']};
    padding: 8px;
    font-weight: 600;
}}

QHeaderView::section:hover {{
    background-color: {PALETTE['panel_hover']};
    color: {PALETTE['text']};
}}

QTableCornerButton::section {{
    background-color: {PALETTE['panel_alt']};
    border: none;
}}

QTabWidget::pane {{
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    background-color: {PALETTE['panel']};
    top: -1px;
}}

QTabBar::tab {{
    background-color: {PALETTE['panel_alt']};
    color: {PALETTE['text_muted']};
    border: 1px solid {PALETTE['border']};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 16px;
    margin-right: 4px;
}}

QTabBar::tab:selected {{
    background-color: {PALETTE['panel']};
    color: {PALETTE['text']};
    border-color: {PALETTE['accent']};
}}

QTabBar::tab:hover:!selected {{
    color: {PALETTE['text']};
    background-color: {PALETTE['panel_hover']};
}}

QGroupBox {{
    background-color: transparent;
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 16px;
    font-weight: 600;
    color: {PALETTE['text_muted']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: {PALETTE['text_muted']};
}}

QMenuBar {{
    background-color: {PALETTE['panel']};
    color: {PALETTE['text']};
    border-bottom: 1px solid {PALETTE['border']};
    padding: 4px;
}}

QMenuBar::item {{
    background-color: transparent;
    padding: 7px 12px;
    border-radius: 6px;
}}

QMenuBar::item:selected {{
    background-color: {PALETTE['accent']};
}}

QMenu {{
    background-color: {PALETTE['panel']};
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 6px;
}}

QMenu::item {{
    background-color: transparent;
    padding: 8px 26px 8px 16px;
    border-radius: 6px;
    margin: 2px 4px;
}}

QMenu::item:selected {{
    background-color: {PALETTE['accent']};
    color: {PALETTE['text']};
}}

QMenu::item:disabled {{
    color: {PALETTE['text_disabled']};
}}

QMenu::separator {{
    height: 1px;
    background-color: {PALETTE['border']};
    margin: 5px 10px;
}}

QMenu::indicator {{
    width: 14px;
    height: 14px;
}}

QProgressBar {{
    background-color: {PALETTE['panel_alt']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    color: {PALETTE['text']};
    text-align: center;
    min-height: 16px;
}}

QProgressBar::chunk {{
    background-color: {PALETTE['accent']};
    border-radius: 7px;
}}

QSplitter::handle {{
    background-color: {PALETTE['border']};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

QSplitter::handle:hover {{
    background-color: {PALETTE['accent']};
}}

QStatusBar {{
    background-color: transparent;
    color: {PALETTE['text_muted']};
    border-top: 1px solid {PALETTE['border']};
}}

QStatusBar::item {{
    border: none;
}}

QDialogButtonBox {{
    background-color: transparent;
}}

QMessageBox {{
    background-color: {PALETTE['panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
}}

QMessageBox QLabel {{
    color: {PALETTE['text']};
    background-color: transparent;
    min-width: 260px;
}}

QMessageBox QPushButton {{
    min-width: 90px;
}}

QToolTip {{
    background-color: {PALETTE['panel']};
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border']};
    padding: 6px 8px;
}}

QWidget:disabled {{
    color: {PALETTE['text_disabled']};
}}

QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 8px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: {PALETTE['scrollbar']};
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {PALETTE['scrollbar_hover']};
}}

QScrollBar:horizontal {{
    border: none;
    background: transparent;
    height: 8px;
    margin: 0px;
}}

QScrollBar::handle:horizontal {{
    background: {PALETTE['scrollbar']};
    min-width: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {PALETTE['scrollbar_hover']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QScrollBar::add-corner, QScrollBar::sub-corner {{
    width: 0px;
    height: 0px;
    background: transparent;
}}
"""

MUTED_LABEL_STYLE = (
    f"color: {PALETTE['text_muted']}; font-size: 14px; background: transparent;"
)


def apply_theme(widget: QWidget) -> None:
    widget.setStyleSheet(STYLE_SHEET)


def add_card_shadow(widget: QWidget, offset: int = 8, blur: int = 28) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, offset)
    shadow.setColor(QColor(0, 0, 0, 150))
    widget.setGraphicsEffect(shadow)
