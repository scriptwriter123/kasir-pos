class PaymentProvider:
    def pay(self, amount: int, reference=None):
        raise NotImplementedError


class CashPayment(PaymentProvider):
    def pay(self, amount: int, reference=None):
        return {"method": "CASH", "amount": amount, "reference": reference}


class ManualQRISPayment(PaymentProvider):
    def pay(self, amount: int, reference=None):
        return {"method": "QRIS", "amount": amount, "reference": reference}
