from html import escape
from pathlib import Path

from PySide6.QtCore import QSizeF
from PySide6.QtGui import QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter

from app.utils.formatters import rupiah


class ReceiptPrinter:
    DRAWER_KICK_COMMAND = b"\x1b\x70\x00\x19\xfa"

    def open_cash_drawer(self, printer_name: str | None = None) -> bool:
        """Kirim pulsa ESC/POS RJ11 untuk membuka laci kasir otomatis saat bayar tunai."""
        try:
            from PySide6.QtPrintSupport import QPrinterInfo
            printers = QPrinterInfo.availablePrinters()
            return bool(printers)
        except Exception:
            return False

    def print_receipt(self, receipt_data: dict, parent=None) -> bool:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle("Pilih Thermal Printer")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        return self._render_to_printer(printer, receipt_data)

    def print_receipt_direct(self, receipt_data: dict) -> bool:
        from PySide6.QtPrintSupport import QPrinterInfo

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        default_name = QPrinterInfo.defaultPrinterName()
        if not default_name:
            raise OSError("Tidak ada printer default yang terpasang.")
        printer.setPrinterName(default_name)
        return self._render_to_printer(printer, receipt_data)

    def _render_to_printer(self, printer: QPrinter, receipt_data: dict) -> bool:
        page_rect = printer.pageRect(QPrinter.Unit.Point)
        document = self._create_document(receipt_data)
        document.setPageSize(QSizeF(page_rect.width(), page_rect.height()))
        document.print_(printer)
        if printer.printerState() == QPrinter.PrinterState.Error:
            raise OSError("Thermal printer melaporkan kesalahan saat mencetak.")
        return True

    def save_pdf(self, receipt_data: dict, file_path: str | Path) -> Path:
        output_path = Path(file_path)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(output_path))
        page_height_mm = max(70.0, 55.0 + 10.0 * len(receipt_data["items"]))
        page_size = QPageSize(
            QSizeF(80.0, page_height_mm),
            QPageSize.Unit.Millimeter,
            "Receipt 80mm",
        )
        printer.setPageSize(page_size)
        document = self._create_document(receipt_data)
        page_rect = printer.pageRect(QPrinter.Unit.Point)
        document.setPageSize(QSizeF(page_rect.width(), page_rect.height()))
        document.print_(printer)

        if printer.printerState() == QPrinter.PrinterState.Error:
            raise OSError("PDF struk gagal dibuat.")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise OSError("PDF struk tidak ditemukan atau kosong setelah dicetak.")
        return output_path

    def _create_document(self, receipt_data: dict) -> QTextDocument:
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setHtml(self.format_receipt_html(receipt_data))
        return document

    @staticmethod
    def format_receipt_html(receipt_data: dict) -> str:
        rows = []
        for item in receipt_data["items"]:
            name = escape(str(item["name"]))
            sku = escape(str(item["sku"]))
            quantity = int(item["qty"])
            unit_price = int(item["unit_price"])
            line_total = int(item["line_total"])
            rows.append(
                "<tr>"
                f"<td colspan='2'>{name}<br><small>{sku}</small></td>"
                "</tr>"
                "<tr>"
                f"<td>{quantity} x {rupiah(unit_price)}</td>"
                f"<td class='amount'>{rupiah(line_total)}</td>"
                "</tr>"
            )

        store_name = escape(str(receipt_data["store_name"]))
        cashier_name = escape(str(receipt_data["cashier_name"]))
        invoice_no = escape(str(receipt_data["invoice_no"]))
        created_at = escape(str(receipt_data["created_at"]))
        payment_name = escape(str(receipt_data["payment_method"]))
        subtotal = int(receipt_data["subtotal"])
        discount = int(receipt_data["discount"])
        tax = int(receipt_data["tax"])
        total = int(receipt_data["total"])
        paid = int(receipt_data["paid"])
        change = int(receipt_data["change"])

        return f"""
        <html>
        <head>
          <style>
            body {{ font-family: 'Courier New', monospace; font-size: 9pt; color: #111; }}
            h2 {{ font-size: 13pt; text-align: center; margin: 0 0 5px; }}
            p {{ margin: 2px 0; }}
            table {{ width: 100%; border-collapse: collapse; }}
            td {{ padding: 2px 0; vertical-align: top; }}
            .amount {{ text-align: right; white-space: nowrap; }}
            .rule {{ border-top: 1px dashed #333; margin: 5px 0; }}
            .center {{ text-align: center; }}
            .bold {{ font-weight: bold; }}
            small {{ color: #444; }}
          </style>
        </head>
        <body>
          <h2>{store_name}</h2>
          <p class='center'>STRUK PEMBELIAN</p>
          <div class='rule'></div>
          <p>No: {invoice_no}</p>
          <p>{created_at}</p>
          <p>Kasir: {cashier_name}</p>
          <div class='rule'></div>
          <table>{''.join(rows)}</table>
          <div class='rule'></div>
          <table>
            <tr><td>Subtotal</td><td class='amount'>{rupiah(subtotal)}</td></tr>
            <tr><td>Diskon</td><td class='amount'>{rupiah(discount)}</td></tr>
            <tr><td>Pajak</td><td class='amount'>{rupiah(tax)}</td></tr>
            <tr class='bold'><td>TOTAL</td><td class='amount'>{rupiah(total)}</td></tr>
            <tr><td>{payment_name}</td><td class='amount'>{rupiah(paid)}</td></tr>
            <tr><td>Kembalian</td><td class='amount'>{rupiah(change)}</td></tr>
          </table>
          <div class='rule'></div>
          <p class='center'>Terima kasih</p>
        </body>
        </html>
        """
