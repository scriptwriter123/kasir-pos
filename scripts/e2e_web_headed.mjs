import { chromium } from "playwright";
import { createHash, randomUUID } from "node:crypto";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8001";
const SLOW = Number(process.env.SLOW_MO || 400);
const stamp = Date.now();
const EMAIL = `e2e.headed.${stamp}@pos.test`;
const PASS = "E2eHeaded!2026";

function step(n, title) {
  console.log(`\n=== LANGKAH ${n}: ${title} ===`);
}
function ok(msg) {
  console.log(`  OK  ${msg}`);
}

const browser = await chromium.launch({ headless: false, slowMo: SLOW });
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
});
const page = await ctx.newPage();
page.on("console", (m) => {
  if (m.type() === "error") console.log("  [console.error]", m.text());
});

try {
  step(1, "Buka halaman landing");
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  ok(`title="${await page.title()}"`);

  step(2, `Daftar akun baru (${EMAIL})`);
  await page.goto(`${BASE}/register`, { waitUntil: "networkidle" });
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASS);
  await page.fill('input[name="store_name"]', "Toko E2E Headed");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard|\/login/, { timeout: 15000 });
  ok(`url=${page.url()}`);

  step(3, "Dashboard customer — lihat perangkat/lisensi/paket");
  if (!page.url().includes("/dashboard")) {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    await page.fill('input[name="email"]', EMAIL);
    await page.fill('input[name="password"]', PASS);
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/dashboard/, { timeout: 15000 });
  }
  await page.waitForTimeout(800);
  const dashText = await page.textContent("body");
  console.log(
    "  ada form .posreq:",
    dashText.includes("posreq") || (await page.$('input[type="file"]')) !== null
  );
  ok("dashboard terbuka");

  step(4, "Unggah .posreq untuk daftarkan perangkat");
  const fileInput = await page.$('input[type="file"]');
  if (!fileInput) throw new Error("Form .posreq tidak ditemukan");
  const installationId = randomUUID();
  const deviceId = createHash("sha256")
    .update(`POS Retail:e2e-headed-${stamp}`)
    .digest("hex");
  await fileInput.setInputFiles({
    name: "device.posreq",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify(
        {
          schema_version: 1,
          product: "POS Retail",
          installation_id: installationId,
          device_id: deviceId,
          store_name: "Toko E2E Headed",
          requested_at: new Date().toISOString(),
        },
        null,
        2
      )
    ),
  });
  await page.click('form[action="/devices"] button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 15000 });
  await page.waitForTimeout(800);
  ok("perangkat terdaftar");

  step(5, "Checkout paket — buat tagihan");
  const deviceSelect = await page.$('select[name="device_pk"]');
  const planSelect = await page.$('select[name="plan_code"]');
  if (!deviceSelect || !planSelect)
    throw new Error("Form checkout tidak muncul setelah unggah");
  await page.selectOption('select[name="device_pk"]', { index: 0 });
  await page.selectOption('select[name="plan_code"]', { index: 0 });
  await page.click('form[action="/checkout"] button[type="submit"]');
  await page.waitForURL(/\/orders\//, { timeout: 15000 });
  ok(`order page: ${page.url()}`);

  step(6, "Halaman order — panel VA ATM simulasi");
  await page.waitForTimeout(800);
  const orderText = await page.textContent("body");
  console.log("  VA tampil:", /Virtual Account/i.test(orderText));
  console.log("  tombol Sudah Bayar:", orderText.includes("Saya Sudah Bayar"));

  const payBtn = await page.$('form[action*="simulasi-bayar"] button');
  if (!payBtn) throw new Error("Tombol simulasi-bayar tidak ditemukan");
  step(7, "Klik 'Saya Sudah Bayar — Aktifkan Lisensi'");
  await payBtn.click();
  await page.waitForURL(/\/orders\//, { timeout: 15000 });
  await page.waitForTimeout(800);
  const after = await page.textContent("body");
  console.log(
    "  lisensi terbit:",
    after.includes("Pembayaran diterima") || after.includes("paid")
  );
  ok("pembayaran simulasi sukses");

  step(8, "Kembali ke dashboard — lihat lisensi aktif");
  const back = await page.$('a[href="/dashboard"]');
  if (back) {
    await back.click();
    await page.waitForURL(/\/dashboard/, { timeout: 15000 });
    await page.waitForTimeout(600);
    const dash2 = await page.textContent("body");
    console.log("  badge active:", dash2.includes("active"));
  }

  step(9, "Logout customer");
  const logout = await page.$('a[href="/logout"], form[action="/logout"] button');
  if (logout) {
    await logout.click();
    await page.waitForTimeout(600);
  } else {
    await page.goto(`${BASE}/logout`, { waitUntil: "networkidle" });
  }

  step(10, "Login admin");
  await page.goto(`${BASE}/admin/login`, { waitUntil: "networkidle" });
  await page.fill(
    'input[name="email"]',
    process.env.ADMIN_EMAIL || "admin@pos.local"
  );
  await page.fill(
    'input[name="password"]',
    process.env.ADMIN_PASSWORD || "admin12345"
  );
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/admin/, { timeout: 15000 });
  await page.waitForTimeout(800);
  const adminText = await page.textContent("body");
  console.log("  daftar customer tampil:", adminText.includes(EMAIL));
  console.log("  daftar admin tampil:", /admin/i.test(adminText));
  ok("admin dashboard terbuka");

  step(11, "Selesai — tahan browser 5 detik untuk inspeksi");
  await page.waitForTimeout(5000);
} catch (err) {
  console.error("\nGAGAL:", err.message);
  await page
    .screenshot({ path: "e2e-headed-failure.png", fullPage: true })
    .catch(() => {});
  console.error("screenshot: e2e-headed-failure.png");
  process.exitCode = 1;
} finally {
  await browser.close();
}
