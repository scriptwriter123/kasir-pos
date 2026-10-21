import pytest
from fastapi.testclient import TestClient

from server.app.config import Settings
from server.app.main import create_app


@pytest.fixture
def admin_client(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'billing.db'}",
        admin_email="admin@example.com",
        admin_password="adminrahasia123",
    )
    app = create_app(settings)
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def test_admin_seeded_on_startup(admin_client):
    response = admin_client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "adminrahasia123"},
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/admin"


def test_admin_dashboard_requires_login(admin_client):
    response = admin_client.get("/admin")
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def _login_admin(admin_client):
    response = admin_client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "adminrahasia123"},
    )
    assert response.status_code == 303, response.text


def test_admin_dashboard_lists_customers(admin_client):
    # customer biasa
    response = admin_client.post(
        "/api/auth/register",
        json={
            "email": "toko@example.com",
            "password": "rahasia123",
            "store_name": "Toko Contoh",
        },
    )
    assert response.status_code == 200, response.text

    # customer biasa tidak boleh masuk area admin
    response = admin_client.post(
        "/admin/login",
        data={"email": "toko@example.com", "password": "rahasia123"},
    )
    assert response.status_code == 403

    # login admin lalu buka dashboard
    response = admin_client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "adminrahasia123"},
    )
    assert response.status_code == 303
    cookie = response.headers.get("set-cookie", "")
    assert "billing_session" in cookie

    response = admin_client.get("/admin")
    assert response.status_code == 200, response.text
    assert "Dashboard Admin" in response.text
    assert "toko@example.com" in response.text
    assert "Belum berlangganan" in response.text


def test_admin_create_and_delete_admin(admin_client):
    _login_admin(admin_client)

    response = admin_client.post(
        "/admin/admins/create",
        data={"email": "baru@example.com", "password": "barurahasia123"},
    )
    assert response.status_code == 303, response.text

    response = admin_client.get("/admin")
    assert response.status_code == 200
    assert "baru@example.com" in response.text
    assert "Tambah Admin" in response.text

    # login dengan admin baru
    response = admin_client.post(
        "/admin/login",
        data={"email": "baru@example.com", "password": "barurahasia123"},
    )
    assert response.status_code == 303

    # email duplikat ditolak
    _login_admin(admin_client)
    response = admin_client.post(
        "/admin/admins/create",
        data={"email": "baru@example.com", "password": "barurahasia123"},
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    # hapus admin baru via id yang terlihat di dashboard
    import re

    page = admin_client.get("/admin").text
    match = re.search(r'/admin/admins/(\d+)/delete', page)
    assert match, "tombol hapus admin harus ada"
    # jangan hapus akun sendiri: hapus id selain admin utama
    for candidate in re.findall(r'/admin/admins/(\d+)/delete', page):
        response = admin_client.post(f"/admin/admins/{candidate}/delete")
        assert response.status_code == 303
        break
    assert "baru@example.com" not in admin_client.get("/admin").text


def test_admin_cannot_delete_self(admin_client):
    _login_admin(admin_client)
    page = admin_client.get("/admin").text
    # akun sendiri tidak punya tombol hapus (hanya penanda "Anda")
    assert "Anda" in page
    # id 1 adalah admin utama hasil seed (= akun yang sedang login),
    # penghapusan diri sendiri harus ditolak dan akun tetap ada
    response = admin_client.post("/admin/admins/1/delete")
    assert response.status_code == 303
    # admin utama tetap bisa login
    response = admin_client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "adminrahasia123"},
    )
    assert response.status_code == 303


def test_admin_create_and_delete_customer(admin_client):
    _login_admin(admin_client)

    response = admin_client.post(
        "/admin/customers/create",
        data={
            "email": "pelanggan@example.com",
            "password": "pelanggan123",
            "store_name": "Toko Pelanggan",
        },
    )
    assert response.status_code == 303, response.text
    assert "notice=" in response.headers["location"]

    page = admin_client.get("/admin").text
    assert "pelanggan@example.com" in page
    assert "Tambah Customer" in page

    import re

    match = re.search(r'/admin/customers/(\d+)/delete', page)
    assert match, "tombol hapus customer harus ada"
    response = admin_client.post(f"/admin/customers/{match.group(1)}/delete")
    assert response.status_code == 303
    assert "pelanggan@example.com" not in admin_client.get("/admin").text
