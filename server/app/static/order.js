(function () {
  "use strict";

  var payButton = document.getElementById("pay-button");
  if (payButton && window.snap) {
    payButton.addEventListener("click", function () {
      window.snap.pay(payButton.getAttribute("data-snap-token"), {
        onSuccess: function () {
          window.location.reload();
        },
        onPending: function () {
          window.location.reload();
        },
        onError: function () {
          alert("Pembayaran gagal. Silakan coba lagi.");
        },
        onClose: function () {
          window.location.reload();
        }
      });
    });
  }

  var copyButton = document.getElementById("copy-va");
  if (copyButton) {
    copyButton.addEventListener("click", function () {
      var va = copyButton.getAttribute("data-va") || "";
      var button = copyButton;
      function done() {
        button.textContent = "Tersalin ✓";
        setTimeout(function () {
          button.textContent = "Salin";
        }, 2000);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(va).then(done, done);
      } else {
        var area = document.createElement("textarea");
        area.value = va;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        document.body.removeChild(area);
        done();
      }
    });
  }
})();
