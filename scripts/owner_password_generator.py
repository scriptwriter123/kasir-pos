import secrets
import string
import tkinter as tk
from tkinter import messagebox


PASSWORD_LENGTH = 20
LOWERCASE = string.ascii_lowercase.replace("l", "")
UPPERCASE = string.ascii_uppercase.replace("I", "").replace("O", "")
DIGITS = "23456789"
SYMBOLS = "!@#$%+-_"
CHARACTER_GROUPS = (LOWERCASE, UPPERCASE, DIGITS, SYMBOLS)
PASSWORD_CHARACTERS = "".join(CHARACTER_GROUPS)


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    if length < len(CHARACTER_GROUPS):
        raise ValueError(
            f"Panjang password minimal {len(CHARACTER_GROUPS)} karakter."
        )

    characters = [secrets.choice(group) for group in CHARACTER_GROUPS]
    characters.extend(
        secrets.choice(PASSWORD_CHARACTERS)
        for _ in range(length - len(characters))
    )
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


class OwnerPasswordGenerator:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Generator Password OWNER")
        root.geometry("440x190")
        root.resizable(False, False)

        frame = tk.Frame(root, padx=20, pady=18)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Password ini tidak disimpan oleh aplikasi POS.",
            wraplength=400,
        ).pack(anchor="w", pady=(0, 10))

        self.password = tk.StringVar()
        self.password_input = tk.Entry(
            frame,
            textvariable=self.password,
            font=("Consolas", 15),
            justify="center",
            state="readonly",
            readonlybackground="white",
        )
        self.password_input.pack(fill="x", pady=(0, 12))

        buttons = tk.Frame(frame)
        buttons.pack(fill="x")
        tk.Button(
            buttons,
            text="Generate Password",
            command=self.generate,
        ).pack(side="left")
        tk.Button(
            buttons,
            text="Salin",
            command=self.copy_password,
        ).pack(side="right")

        tk.Label(
            frame,
            text="Berikan password ini kepada OWNER untuk setup pertama POS.",
            wraplength=400,
        ).pack(anchor="w", pady=(12, 0))

        self.generate()

    def generate(self) -> None:
        self.password.set(generate_password())

    def copy_password(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.password.get())
        messagebox.showinfo(
            "Password disalin",
            "Password tersalin ke clipboard. Berikan dengan aman kepada OWNER.",
            parent=self.root,
        )


def main() -> None:
    root = tk.Tk()
    OwnerPasswordGenerator(root)
    root.mainloop()


if __name__ == "__main__":
    main()
