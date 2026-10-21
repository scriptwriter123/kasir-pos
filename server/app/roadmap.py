"""Roadmap pengembangan yang dikirim ke aplikasi POS.

Daftar ini adalah sumber kebenaran "fitur berikutnya" yang tampil pada
kartu Langganan di dashboard kasir, sehingga tim pengembang dapat
memperbarinya lewat server tanpa merilis ulang aplikasi POS.

Override tanpa menyentuh kode: taruh ``roadmap.json`` di folder kerja
server (biasanya folder ``server/``) berisi daftar objek
``{"title": ..., "description": ..., "eta": ...}``, bisa juga berupa
objek ``{"roadmap": [...]}``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROADMAP_FILE = Path(__file__).resolve().parents[2] / "roadmap.json"

DEFAULT_ROADMAP: list[dict[str, str]] = [
    {
        "title": "Aplikasi Kasir Mobile",
        "description": "Kasir Android & iOS memakai data toko yang sama, "
        "aman dipakai saat jaringan padam.",
        "eta": "Fase berikutnya",
    },
    {
        "title": "Sinkronisasi Awan Multi-Cabang",
        "description": "Gabungkan stok, harga, dan laporan antar cabang "
        "dari satu akun pemilik.",
        "eta": "Rencana kuartal depan",
    },
    {
        "title": "Laporan via WhatsApp",
        "description": "Rekap penjualan harian otomatis dikirim ke WhatsApp "
        "pemilik setiap tutup toko.",
        "eta": "Rencana kuartal depan",
    },
    {
        "title": "Pembayaran Digital Lengkap",
        "description": "QRIS, e-wallet, kartu, dan VA dalam satu alur "
        "kasir dengan rekonsiliasi otomatis.",
        "eta": "Rencana bertahap",
    },
    {
        "title": "Loyalitas & Promo",
        "description": "Poin pelanggan, kupon, dan harga spesial terjadwal "
        "langsung dari dashboard.",
        "eta": "Rencana bertahap",
    },
    {
        "title": "Role Teknisi & Audit Perangkat",
        "description": "Akses terbatas untuk teknisi perangkat beserta "
        "riwayat audit aktivitas.",
        "eta": "Rencana bertahap",
    },
]


def _normalize(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, str):
            title = entry.strip()
            if title:
                items.append({"title": title, "description": "", "eta": ""})
            continue
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title,
                "description": str(
                    entry.get("description") or entry.get("summary") or ""
                ).strip(),
                "eta": str(entry.get("eta") or entry.get("timeline") or "").strip(),
            }
        )
    return items


def load_roadmap() -> list[dict[str, str]]:
    """Daftar fitur berikutnya; file ``roadmap.json`` mengalahkan bawaan."""
    if ROADMAP_FILE.is_file():
        try:
            raw = json.loads(ROADMAP_FILE.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            raw = raw.get("roadmap")
        items = _normalize(raw)
        if items:
            return items
    return list(DEFAULT_ROADMAP)
