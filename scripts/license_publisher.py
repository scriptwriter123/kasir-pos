import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from app.services.license_service import (
    PRIVATE_KEY_PATH,
    LicenseError,
    issue_license,
)


class LicensePublisher:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Penerbit Lisensi POS Retail")
        root.geometry("520x250")
        root.resizable(False, False)

        frame = tk.Frame(root, padx=20, pady=18)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Penerbitan lisensi offline — satu komputer per lisensi.",
            wraplength=470,
        ).pack(anchor="w", pady=(0, 10))
        tk.Label(
            frame,
            text=f"Kunci penandatanganan: {PRIVATE_KEY_PATH}",
            wraplength=470,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))
        tk.Button(
            frame,
            text="Pilih Permintaan dan Terbitkan Lisensi",
            command=self.issue,
        ).pack(anchor="w")
        tk.Label(
            frame,
            text=(
                "Kunci privat tidak disertakan dalam tool ini. Jaga file kunci "
                "di komputer penerbit dan buat cadangan yang aman."
            ),
            wraplength=470,
            justify="left",
        ).pack(anchor="w", pady=(16, 0))

    def issue(self) -> None:
        request_path = filedialog.askopenfilename(
            parent=self.root,
            title="Pilih Permintaan Lisensi",
            filetypes=[("Permintaan lisensi POS", "*.posreq")],
        )
        if not request_path:
            return
        output_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Simpan Lisensi POS",
            defaultextension=".poslic",
            initialfile="lisensi.poslic",
            filetypes=[("Lisensi POS", "*.poslic")],
        )
        if not output_path:
            return
        store_name = simpledialog.askstring(
            "Nama toko",
            "Masukkan nama toko yang akan menerima lisensi:",
            parent=self.root,
        )
        if store_name is None:
            return
        passphrase = simpledialog.askstring(
            "Kata sandi kunci privat",
            "Masukkan kata sandi kunci penandatangan lisensi:",
            show="*",
            parent=self.root,
        )
        if passphrase is None:
            return

        try:
            issue_license(
                Path(request_path),
                Path(output_path),
                store_name=store_name,
                private_key_path=PRIVATE_KEY_PATH,
                passphrase=passphrase,
            )
        except (LicenseError, OSError) as exc:
            messagebox.showerror(
                "Lisensi tidak dapat diterbitkan",
                str(exc),
                parent=self.root,
            )
            return
        messagebox.showinfo(
            "Lisensi diterbitkan",
            "File lisensi berhasil dibuat. Kirim file tersebut kepada "
            "pemilik toko untuk diimpor pada POS.",
            parent=self.root,
        )


def main() -> None:
    root = tk.Tk()
    LicensePublisher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
