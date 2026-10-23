(function () {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Config
  // ─────────────────────────────────────────────────────────────────────────
  var POLL_INTERVAL_MS = 5000;   // cek status tiap 5 detik
  var POLL_MAX_TRIES   = 36;     // maksimal 3 menit polling (36 × 5 s)

  // ─────────────────────────────────────────────────────────────────────────
  // Snap Popup — tombol "Bayar Sekarang (Midtrans)"
  // ─────────────────────────────────────────────────────────────────────────
  var payButton = document.getElementById("pay-button");
  if (payButton && window.snap) {
    payButton.addEventListener("click", function () {
      var token = payButton.getAttribute("data-snap-token");
      window.snap.pay(token, {

        // Pembayaran berhasil dikonfirmasi Midtrans
        onSuccess: function (result) {
          console.log("[Snap] onSuccess", result);
          // Kirim ke endpoint /check agar server segera
          // memverifikasi dengan Midtrans API & tandai paid
          redirectToCheck("paid");
        },

        // Pembayaran diterima tapi masih menunggu konfirmasi
        // (mis. VA belum ditransfer, QRIS di-scan tapi pending)
        onPending: function (result) {
          console.log("[Snap] onPending", result);
          // Tetap cek ke server; webhook akan memperbarui status
          // secara otomatis saat Midtrans mengirim notifikasi
          redirectToCheck("pending");
        },

        // Transaksi ditolak / gagal
        onError: function (result) {
          console.log("[Snap] onError", result);
          showBanner("error",
            "Pembayaran gagal atau ditolak. Silakan coba lagi.");
        },

        // User menutup popup tanpa menyelesaikan pembayaran
        onClose: function () {
          console.log("[Snap] onClose");
          // Tidak redirect — user mungkin ingin memilih metode lain
          showBanner("info",
            "Popup ditutup. Klik 'Bayar Sekarang' untuk melanjutkan, " +
            "atau periksa status jika Anda sudah membayar.");
        }
      });
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Auto-polling — hanya aktif bila order masih "pending"
  // ─────────────────────────────────────────────────────────────────────────
  var pollTimer  = null;
  var pollTries  = 0;
  var cardEl     = document.querySelector(".card[data-order-code]");
  var orderCode  = cardEl ? cardEl.getAttribute("data-order-code") : null;
  var orderStatus = cardEl ? cardEl.getAttribute("data-order-status") : null;

  if (orderCode && orderStatus === "pending") {
    startPolling();
  }

  function startPolling() {
    showPollingIndicator(true);
    poll();
  }

  function poll() {
    if (pollTries >= POLL_MAX_TRIES) {
      showPollingIndicator(false);
      showBanner("info",
        "Waktu polling habis. Klik 'Periksa Status Pembayaran' untuk " +
        "memperbarui secara manual.");
      return;
    }
    pollTries++;

    fetch("/api/orders/" + orderCode + "/status", {
      method: "GET",
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    })
      .then(function (res) {
        if (!res.ok) { throw new Error("HTTP " + res.status); }
        return res.json();
      })
      .then(function (data) {
        var status = (data.status || "").toLowerCase();
        console.log("[poll]", pollTries, "→", status);

        if (status === "paid") {
          // Selesai! Muat ulang halaman agar UI menampilkan status paid
          window.location.reload();
          return;
        }
        if (status === "failed" || status === "cancelled" || status === "expired") {
          showPollingIndicator(false);
          showBanner("error",
            "Pembayaran " + status + ". Silakan buat order baru.");
          return;
        }
        // Masih pending — jadwalkan polling berikutnya
        pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
      })
      .catch(function (err) {
        console.warn("[poll] error:", err);
        // Jangan hentikan polling karena jaringan sesaat; coba lagi
        pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
      });
  }

  function showPollingIndicator(active) {
    var el = document.getElementById("poll-indicator");
    if (el) { el.style.display = active ? "" : "none"; }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Helper: redirect ke endpoint /check (POST form submit)
  // ─────────────────────────────────────────────────────────────────────────
  function redirectToCheck(hint) {
    if (!orderCode) { window.location.reload(); return; }
    // Kirim via form POST supaya auth cookie ikut terkirim
    var form = document.createElement("form");
    form.method = "post";
    form.action = "/orders/" + orderCode + "/check";
    if (hint) {
      var inp = document.createElement("input");
      inp.type  = "hidden";
      inp.name  = "hint";
      inp.value = hint;
      form.appendChild(inp);
    }
    document.body.appendChild(form);
    form.submit();
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Helper: tampilkan banner pesan di atas halaman
  // ─────────────────────────────────────────────────────────────────────────
  function showBanner(type, message) {
    var existing = document.getElementById("js-banner");
    if (existing) { existing.remove(); }

    var banner = document.createElement("div");
    banner.id = "js-banner";
    banner.className = "alert " + (type === "error" ? "error" : "ok");
    banner.style.cssText = "margin:12px 0;padding:12px 16px;border-radius:6px;" +
      "font-size:14px;animation:fadeIn .3s ease;";
    banner.textContent = message;

    var card = document.querySelector(".card");
    if (card) {
      card.insertBefore(banner, card.firstChild);
    }
    // Auto-hilang setelah 8 detik untuk pesan info
    if (type === "info") {
      setTimeout(function () {
        if (banner.parentNode) { banner.remove(); }
      }, 8000);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Tombol salin nomor Virtual Account
  // ─────────────────────────────────────────────────────────────────────────
  var copyButton = document.getElementById("copy-va");
  if (copyButton) {
    copyButton.addEventListener("click", function () {
      var va = copyButton.getAttribute("data-va") || "";
      function done() {
        copyButton.textContent = "Tersalin ✓";
        setTimeout(function () { copyButton.textContent = "Salin"; }, 2000);
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
