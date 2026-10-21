from app.utils.formatters import money_to_int, rupiah


def test_integer_rupiah():
    assert money_to_int("Rp 25.000") == 25000
    assert rupiah(25000) == "Rp 25.000,00"
