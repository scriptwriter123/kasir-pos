def rupiah(value: int) -> str:
    return f"Rp {int(value):,}".replace(",", ".") + ",00"


def money_to_int(value: str) -> int:
    return int("".join(c for c in value if c.isdigit()) or 0)
