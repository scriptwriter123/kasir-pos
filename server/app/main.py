import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from server.app import roadmap as roadmap_content
from server.app.config import Settings, settings as default_settings
from server.app.database import init_db, make_session_factory, seed_admin, seed_plans
from server.app.licensing import SigningError
from server.app.models import Customer, Plan
from server.app.security import hash_password
from server.app.services import auth_service, license_service, payment_service
from server.app.services.auth_service import AuthError
from server.app.services.license_service import LicenseServiceError
from server.app.services.payment_service import (
    PaymentError,
    format_va_display,
    simulated_va_number,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _warn_midtrans_key_config(app_settings: Settings) -> None:
    """Peringatan keras bila kolom Client Key ternyata diisi Server Key.

    Kombinasi ini membuat popup Snap gagal diam-diam; lebih baik
    ketahuan saat startup daripada saat user mencoba membayar.
    """
    if not app_settings.midtrans_snap_client_key_is_suspect:
        return
    logging.getLogger(__name__).warning(
        "MIDTRANS_SNAP_CLIENT_KEY berisi Server Key (%s...). Yang diperlukan "
        "Snap.js adalah Client Key — ambil dari Midtrans MAP → Settings → "
        "Access Keys → baris 'Client Key'.",
        (app_settings.midtrans_snap_client_key or "")[:16] + "...",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or default_settings
    session_factory = make_session_factory(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _warn_midtrans_key_config(app_settings)
        init_db(session_factory)
        seed_plans(session_factory)
        seed_admin(
            session_factory,
            email=app_settings.admin_email,
            password=app_settings.admin_password,
        )
        yield

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.state.settings = app_settings
    app.state.session_factory = session_factory
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def get_token(request: Request) -> str | None:
        return request.cookies.get(app_settings.session_cookie_name)

    def get_customer(
        request: Request,
        session: Session = Depends(get_session),
        token: str | None = Depends(get_token),
    ) -> Customer:
        customer = auth_service.customer_for_token(session, token)
        if customer is None:
            if request.url.path.startswith("/api/"):
                raise HTTPException(status_code=401, detail="Silakan masuk terlebih dahulu.")
            raise RedirectToLogin()
        return customer

    def get_admin(
        request: Request,
        session: Session = Depends(get_session),
        token: str | None = Depends(get_token),
    ) -> Customer:
        customer = auth_service.customer_for_token(session, token)
        if customer is None:
            if request.url.path.startswith("/api/"):
                raise HTTPException(status_code=401, detail="Silakan masuk terlebih dahulu.")
            raise RedirectToAdminLogin()
        if not customer.is_admin:
            if request.url.path.startswith("/api/"):
                raise HTTPException(status_code=403, detail="Khusus admin.")
            raise RedirectToAdminLogin()
        return customer

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            app_settings.session_cookie_name,
            token,
            max_age=app_settings.session_ttl_days * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=app_settings.app_env == "production",
        )

    def clear_session_cookie(response: Response) -> None:
        response.delete_cookie(app_settings.session_cookie_name)

    class RedirectToLogin(Exception):
        pass

    class RedirectToAdminLogin(Exception):
        pass

    @app.exception_handler(RedirectToLogin)
    async def _redirect_to_login(_: Request, __: RedirectToLogin):
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(RedirectToAdminLogin)
    async def _redirect_to_admin_login(_: Request, __: RedirectToAdminLogin):
        return RedirectResponse("/admin/login", status_code=303)

    # ------------------------------------------------------------------ pages

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, session: Session = Depends(get_session)):
        plans = session.query(Plan).order_by(Plan.price_idr).all()
        customer = auth_service.customer_for_token(session, get_token(request))
        return templates.TemplateResponse(
            request,
            "index.html",
            {"plans": plans, "customer": customer},
        )

    @app.get("/register", response_class=HTMLResponse)
    def register_form(request: Request):
        return templates.TemplateResponse(request, "register.html", {"error": None})

    @app.post("/register", response_class=HTMLResponse)
    def register_submit(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        store_name: str = Form(""),
        session: Session = Depends(get_session),
    ):
        try:
            auth_service.register_customer(
                session, email=email, password=password, store_name=store_name
            )
        except AuthError as exc:
            return templates.TemplateResponse(
                request,
                "register.html",
                {"error": str(exc), "email": email},
                status_code=400,
            )
        try:
            customer, token = auth_service.login_customer(
                session,
                email=email,
                password=password,
                ttl_days=app_settings.session_ttl_days,
            )
        except AuthError as exc:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": str(exc), "email": email},
                status_code=400,
            )
        response = RedirectResponse("/dashboard", status_code=303)
        set_session_cookie(response, token)
        return response

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login", response_class=HTMLResponse)
    def login_submit(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        session: Session = Depends(get_session),
    ):
        try:
            _, token = auth_service.login_customer(
                session,
                email=email,
                password=password,
                ttl_days=app_settings.session_ttl_days,
            )
        except AuthError as exc:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": str(exc), "email": email},
                status_code=401,
            )
        response = RedirectResponse("/dashboard", status_code=303)
        set_session_cookie(response, token)
        return response

    @app.post("/logout")
    def logout(
        response: Response,
        session: Session = Depends(get_session),
        token: str | None = Depends(get_token),
    ):
        auth_service.logout_token(session, token)
        out = RedirectResponse("/", status_code=303)
        clear_session_cookie(out)
        return out

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        devices = license_service.list_devices(session, customer)
        licenses = license_service.list_licenses(session, customer)
        orders = license_service.list_orders(session, customer)
        plans = session.query(Plan).order_by(Plan.price_idr).all()
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "customer": customer,
                "devices": devices,
                "licenses": licenses,
                "orders": orders,
                "plans": plans,
                "notice": request.query_params.get("notice"),
                "error": request.query_params.get("error"),
                "status_label": license_service.license_effective_status,
            },
        )

    @app.post("/devices")
    def upload_device(
        request: Request,
        posreq: UploadFile = File(...),
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        content = (posreq.file.read()).decode("utf-8", errors="replace")
        try:
            device = license_service.register_device(session, customer, content)
        except LicenseServiceError as exc:
            return RedirectResponse(
                f"/dashboard?error={exc}", status_code=303
            )
        return RedirectResponse(
            f"/dashboard?notice=Perangkat {device.store_name} terdaftar.",
            status_code=303,
        )

    @app.post("/checkout")
    def checkout(
        device_pk: int = Form(...),
        plan_code: str = Form(...),
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        try:
            order, _ = license_service.create_checkout(
                session, customer, device_pk=device_pk, plan_code=plan_code,
                settings=app_settings,
            )
        except LicenseServiceError as exc:
            return RedirectResponse(f"/dashboard?error={exc}", status_code=303)
        return RedirectResponse(f"/orders/{order.order_code}", status_code=303)

    @app.get("/orders/{order_code}", response_class=HTMLResponse)
    def order_page(
        request: Request,
        order_code: str,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        order = license_service.get_order(session, customer, order_code)
        if order is None:
            raise HTTPException(status_code=404, detail="Order tidak ditemukan.")
        va_number = simulated_va_number(order.order_code)
        return templates.TemplateResponse(
            request,
            "order.html",
            {
                "customer": customer,
                "order": order,
                "snap_client_key": app_settings.midtrans_snap_client_key or "",
                "snap_js_url": app_settings.midtrans_snap_js_url,
                "flash_status": request.query_params.get("status"),
                "flash_message": request.query_params.get("message"),
                "va_number": va_number,
                "va_number_display": format_va_display(va_number),
                "simulated_va_bank": app_settings.simulated_va_bank,
            },
        )

    @app.post("/orders/{order_code}/check")
    def order_check(
        order_code: str,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        order = license_service.get_order(session, customer, order_code)
        if order is None:
            raise HTTPException(status_code=404, detail="Order tidak ditemukan.")
        # Aktivasi bisa melempar SigningError (kunci privat) dan
        # PaymentError (nominal tidak cocok); tanpa cabang ini error
        # lolos menjadi HTTP 500 dan user tidak pernah tahu penyebabnya.
        try:
            result = license_service.refresh_order_status(
                session, app_settings, order
            )
        except (LicenseServiceError, PaymentError, SigningError) as exc:
            return RedirectResponse(
                "/orders/{}?status=error&message={}".format(
                    order_code, quote(str(exc), safe="")
                ),
                status_code=303,
            )
        return RedirectResponse(
            f"/orders/{order_code}?status={quote(str(result['status']), safe='')}",
            status_code=303,
        )

    @app.post("/orders/{order_code}/simulasi-bayar")
    def order_simulate_atm(
        order_code: str,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        """Simulasi ATM: customer transfer manual lalu konfirmasi di sini.

        Menandai order lunas dan menerbitkan lisensi — pengganti webhook
        gateway untuk pembayaran virtual account sederhana.
        """
        order = license_service.get_order(session, customer, order_code)
        if order is None:
            raise HTTPException(status_code=404, detail="Order tidak ditemukan.")
        try:
            result = payment_service.simulate_atm_payment(
                session, app_settings, order
            )
        except PaymentError as exc:
            return RedirectResponse(
                "/orders/{}?status=error&message={}".format(
                    order_code, quote(str(exc), safe="")
                ),
                status_code=303,
            )
        return RedirectResponse(
            f"/orders/{order_code}?status={quote(str(result['status']), safe='')}",
            status_code=303,
        )

    @app.post("/licenses/{license_pk}/deactivate")
    def deactivate_license_page(
        license_pk: int,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        try:
            license_service.deactivate_license(session, customer, license_pk)
        except LicenseServiceError as exc:
            return RedirectResponse(f"/dashboard?error={exc}", status_code=303)
        return RedirectResponse(
            "/dashboard?notice=Lisensi dinonaktifkan. Perangkat dapat diaktifkan "
            "kembali dengan lisensi baru.",
            status_code=303,
        )

    @app.get("/licenses/{license_pk}/download")
    def download_license(
        license_pk: int,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        try:
            document = license_service.get_license_document(
                session, customer, license_pk
            )
        except LicenseServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        import json as _json

        content = _json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{document["payload"]["license_id"]}.poslic"'
                )
            },
        )

    # ------------------------------------------------------- admin dashboard

    @app.get("/admin/login", response_class=HTMLResponse)
    def admin_login_form(request: Request):
        return templates.TemplateResponse(
            request, "admin_login.html", {"error": None}
        )

    @app.post("/admin/login", response_class=HTMLResponse)
    def admin_login_submit(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        session: Session = Depends(get_session),
    ):
        try:
            customer, token = auth_service.login_customer(
                session,
                email=email,
                password=password,
                ttl_days=app_settings.session_ttl_days,
            )
        except AuthError:
            return templates.TemplateResponse(
                request,
                "admin_login.html",
                {"error": "Email atau password salah.", "email": email},
                status_code=401,
            )
        if not customer.is_admin:
            auth_service.logout_token(session, token)
            return templates.TemplateResponse(
                request,
                "admin_login.html",
                {"error": "Akun ini bukan admin.", "email": email},
                status_code=403,
            )
        response = RedirectResponse("/admin", status_code=303)
        set_session_cookie(response, token)
        return response

    @app.post("/admin/logout")
    def admin_logout(
        session: Session = Depends(get_session),
        token: str | None = Depends(get_token),
    ):
        auth_service.logout_token(session, token)
        out = RedirectResponse("/admin/login", status_code=303)
        clear_session_cookie(out)
        return out

    @app.get("/admin", response_class=HTMLResponse)
    def admin_dashboard(
        request: Request,
        session: Session = Depends(get_session),
        admin: Customer = Depends(get_admin),
    ):
        customers = (
            session.query(Customer).order_by(Customer.created_at.desc()).all()
        )
        admins = [c for c in customers if c.is_admin]
        rows = []
        active_subs = 0
        pending_subs = 0
        revenue_idr = 0
        for item in customers:
            if item.is_admin:
                continue
            licenses = license_service.list_licenses(session, item)
            devices = license_service.list_devices(session, item)
            orders = license_service.list_orders(session, item)
            paid_total = sum(o.amount_idr for o in orders if o.status == "paid")
            revenue_idr += paid_total
            statuses = {
                license_service.license_effective_status(r) for r in licenses
            }
            best = next(
                (r for r in licenses
                 if license_service.license_effective_status(r) == "active"),
                None,
            ) or next(
                (r for r in licenses
                 if license_service.license_effective_status(r) == "pending"),
                None,
            ) or next(iter(licenses), None)
            if not item.is_active:
                sub_status, sub_detail = "revoked", "Akun dinonaktifkan"
            elif best is None:
                sub_status, sub_detail = "none", "Belum berlangganan"
            else:
                sub_status = license_service.license_effective_status(best)
                expiry = (
                    best.expires_at.strftime("%d %b %Y")
                    if best.expires_at
                    else "Selamanya"
                )
                sub_detail = f"{best.plan_code} · s/d {expiry}"
            if item.is_active:
                if "active" in statuses:
                    active_subs += 1
                elif "pending" in statuses:
                    pending_subs += 1
            rows.append(
                {
                    "customer": item,
                    "licenses": licenses,
                    "device_count": len(devices),
                    "order_count": len(orders),
                    "paid_total": paid_total,
                    "sub_status": sub_status,
                    "sub_detail": sub_detail,
                }
            )
        return templates.TemplateResponse(
            request,
            "admin_dashboard.html",
            {
                "customer": admin,
                "admins": admins,
                "rows": rows,
                "total_admins": len(admins),
                "total_customers": len(rows),
                "active_subs": active_subs,
                "pending_subs": pending_subs,
                "revenue_idr": revenue_idr,
                "notice": request.query_params.get("notice"),
                "error": request.query_params.get("error"),
            },
        )

    @app.post("/admin/customers/{customer_id}/toggle")
    def admin_toggle_customer(
        customer_id: int,
        session: Session = Depends(get_session),
        admin: Customer = Depends(get_admin),
    ):
        target = session.get(Customer, customer_id)
        if target is None:
            return RedirectResponse(
                "/admin?error=Customer tidak ditemukan.", status_code=303
            )
        if target.id == admin.id or target.is_admin:
            return RedirectResponse(
                "/admin?error=Akun admin tidak dapat dinonaktifkan.",
                status_code=303,
            )
        target.is_active = not target.is_active
        session.commit()
        state = "diaktifkan" if target.is_active else "dinonaktifkan"
        return RedirectResponse(
            f"/admin?notice=Akun {target.email} {state}.", status_code=303
        )

    @app.post("/admin/admins/create")
    def admin_create_admin(
        email: str = Form(...),
        password: str = Form(...),
        session: Session = Depends(get_session),
        admin: Customer = Depends(get_admin),
    ):
        normalized = email.strip().lower()
        if "@" not in normalized or len(password) < 8:
            return RedirectResponse(
                "/admin?error=Email tidak valid atau password minimal 8 karakter.",
                status_code=303,
            )
        if session.query(Customer).filter(Customer.email == normalized).first():
            return RedirectResponse(
                f"/admin?error=Email {normalized} sudah terdaftar.",
                status_code=303,
            )
        session.add(
            Customer(
                email=normalized,
                password_hash=hash_password(password),
                store_name="Administrator",
                is_active=True,
                is_admin=True,
            )
        )
        session.commit()
        return RedirectResponse(
            f"/admin?notice=Admin {normalized} ditambahkan.", status_code=303
        )

    @app.post("/admin/admins/{admin_id}/delete")
    def admin_delete_admin(
        admin_id: int,
        session: Session = Depends(get_session),
        admin: Customer = Depends(get_admin),
    ):
        target = session.get(Customer, admin_id)
        if target is None or not target.is_admin:
            return RedirectResponse(
                "/admin?error=Akun admin tidak ditemukan.", status_code=303
            )
        if target.id == admin.id:
            return RedirectResponse(
                "/admin?error=Tidak dapat menghapus akun sendiri.",
                status_code=303,
            )
        session.delete(target)
        session.commit()
        return RedirectResponse(
            f"/admin?notice=Admin {target.email} dihapus.", status_code=303
        )

    @app.post("/admin/customers/create")
    def admin_create_customer(
        email: str = Form(...),
        password: str = Form(...),
        store_name: str = Form(""),
        session: Session = Depends(get_session),
        admin: Customer = Depends(get_admin),
    ):
        try:
            customer = auth_service.register_customer(
                session,
                email=email,
                password=password,
                store_name=store_name,
            )
        except AuthError as exc:
            return RedirectResponse(f"/admin?error={exc}", status_code=303)
        return RedirectResponse(
            f"/admin?notice=Customer {customer.email} ditambahkan.",
            status_code=303,
        )

    @app.post("/admin/customers/{customer_id}/delete")
    def admin_delete_customer(
        customer_id: int,
        session: Session = Depends(get_session),
        admin: Customer = Depends(get_admin),
    ):
        target = session.get(Customer, customer_id)
        if target is None or target.is_admin:
            return RedirectResponse(
                "/admin?error=Customer tidak ditemukan.", status_code=303
            )
        email = target.email
        session.delete(target)
        session.commit()
        return RedirectResponse(
            f"/admin?notice=Customer {email} beserta datanya dihapus.",
            status_code=303,
        )

    # -------------------------------------------------------------------- api

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": app_settings.app_env}

    # ------------------------------------------------------ installer download

    @app.get("/download/installer")
    def download_installer():
        installer = app_settings.resolved_installer_path
        if not installer.is_file():
            raise HTTPException(
                status_code=404, detail="File instalator belum tersedia."
            )
        return FileResponse(
            installer,
            media_type="application/octet-stream",
            filename=installer.name,
        )

    # ------------------------------------------------- pos machine endpoints

    def _bearer_token(request: Request) -> str | None:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return authorization[len("Bearer ") :].strip()
        return None

    def get_customer_bearer(
        request: Request,
        session: Session = Depends(get_session),
    ) -> Customer:
        token = _bearer_token(request)
        customer = auth_service.customer_for_token(session, token)
        if customer is None:
            raise HTTPException(
                status_code=401, detail="Silakan masuk terlebih dahulu."
            )
        return customer

    @app.post("/api/pos/register")
    def pos_register(
        payload: dict,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer_bearer),
    ):
        """POS mendaftarkan perangkatnya dan menerima device_token."""
        posreq_content = str(payload.get("posreq", ""))
        try:
            device = license_service.register_device(
                session, customer, posreq_content
            )
        except LicenseServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        device_token = license_service.issue_device_token(session, device)
        return {
            "device_pk": device.id,
            "installation_id": device.installation_id,
            "store_name": device.store_name,
            "device_token": device_token,
        }

    @app.get("/api/pos/license")
    def pos_license(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """POS memeriksa lisensi; mengembalikan dokumen saat sudah aktif."""
        device = license_service.device_for_token(
            session, _bearer_token(request)
        )
        if device is None:
            raise HTTPException(
                status_code=401, detail="Token perangkat tidak valid."
            )
        # Pengganti webhook: polling POS sekaligus memverifikasi pembayaran
        # bila lisensi instalasi ini masih menunggu. Lisensi terbit otomatis
        # begitu gateway melunasi, tanpa URL publik atau tombol manual.
        license_service.verify_pending_for_device(
            session, app_settings, device
        )
        document = license_service.active_license_document_for_device(
            session, device
        )
        if document is None:
            license_record = license_service.license_for_installation(
                session, device.installation_id, device.device_id
            )
            status = (
                license_service.license_effective_status(license_record)
                if license_record is not None
                else "none"
            )
            return {"status": status, "document": None}
        return {"status": "active", "document": document}

    @app.get("/api/pos/status")
    def pos_status(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Roadmap pengembangan + status langganan untuk kartu dashboard POS.

        Tanpa token perangkat POS tetap menerima roadmap dan daftar paket
        (info publik yang sama dengan halaman website). Dengan token device
        yang sah, blok ``subscription`` berisi paket dipakai beserta sisa
        masa berlakunya — baik paket bulanan maupun tahunan.
        """
        device = license_service.device_for_token(
            session, _bearer_token(request)
        )
        subscription = None
        if device is not None:
            # Pengganti webhook: sekalian verifikasi pembayaran bila lisensi
            # perangkat ini masih menunggu (throttle di license_service).
            license_service.verify_pending_for_device(
                session, app_settings, device
            )
            subscription = license_service.subscription_for_device(session, device)
        return {
            "server_time": datetime.now(timezone.utc).isoformat(),
            "roadmap": roadmap_content.load_roadmap(),
            "plans": license_service.plan_catalog(session),
            "subscription": subscription,
        }

    @app.post("/api/auth/register")
    def api_register(payload: dict, session: Session = Depends(get_session)):
        try:
            customer = auth_service.register_customer(
                session,
                email=str(payload.get("email", "")),
                password=str(payload.get("password", "")),
                store_name=str(payload.get("store_name", "")),
            )
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": customer.id, "email": customer.email}

    @app.post("/api/auth/login")
    def api_login(payload: dict, session: Session = Depends(get_session)):
        try:
            customer, token = auth_service.login_customer(
                session,
                email=str(payload.get("email", "")),
                password=str(payload.get("password", "")),
                ttl_days=app_settings.session_ttl_days,
            )
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"token": token, "email": customer.email}

    @app.get("/api/licenses/me")
    def api_licenses_me(
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        licenses = license_service.list_licenses(session, customer)
        return [
            {
                "license_id": record.license_id,
                "installation_id": record.installation_id,
                "store_name": record.store_name,
                "plan_code": record.plan_code,
                "status": license_service.license_effective_status(record),
                "starts_at": record.starts_at.isoformat() if record.starts_at else None,
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            }
            for record in licenses
        ]

    @app.post("/api/licenses/{license_pk}/renew")
    def api_renew(
        license_pk: int,
        payload: dict,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        try:
            order = license_service.create_renewal(
                session,
                customer,
                license_pk=license_pk,
                plan_code=str(payload.get("plan_code", "")),
            )
        except LicenseServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"order_code": order.order_code, "amount_idr": order.amount_idr}

    @app.post("/api/licenses/{license_pk}/deactivate")
    def api_deactivate(
        license_pk: int,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        try:
            license_service.deactivate_license(session, customer, license_pk)
        except LicenseServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "revoked"}

    @app.post("/api/checkout/create")
    def api_checkout(
        payload: dict,
        session: Session = Depends(get_session),
        customer: Customer = Depends(get_customer),
    ):
        try:
            order, _ = license_service.create_checkout(
                session,
                customer,
                device_pk=int(payload.get("device_pk", 0)),
                plan_code=str(payload.get("plan_code", "")),
                settings=app_settings,
            )
        except (LicenseServiceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "order_code": order.order_code,
            "amount_idr": order.amount_idr,
            "status": order.status,
            "snap_token": order.snap_token,
        }

    @app.post("/webhooks/payment/{provider}")
    def payment_webhook(
        provider: str,
        payload: dict,
        session: Session = Depends(get_session),
    ):
        if provider != "midtrans":
            raise HTTPException(status_code=404, detail="Provider tidak dikenal.")
        try:
            return payment_service.apply_midtrans_notification(
                session, app_settings, payload
            )
        except PaymentError as exc:
            message = str(exc)
            if "Signature" in message:
                raise HTTPException(status_code=401, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        except SigningError as exc:
            # Kunci privat belum terpasang; notifikasi tetap ditolak
            # dengan kode jelas alih-alih traceback tak tertangani.
            raise HTTPException(
                status_code=500,
                detail=f"Gagal memvalidasi notifikasi: {exc}",
            ) from exc

    @app.post("/admin/licenses/issue")
    def admin_issue(
        payload: dict,
        session: Session = Depends(get_session),
    ):
        """Development helper: issue a license without payment (admin key required)."""
        key = payload.get("admin_key")
        if not app_settings.admin_api_key or key != app_settings.admin_api_key:
            raise HTTPException(status_code=403, detail="Admin key tidak valid.")
        try:
            device = license_service.register_device(
                session,
                _admin_customer(session, app_settings, payload),
                str(payload.get("posreq", "")),
            )
            order, _ = license_service.create_checkout(
                session,
                device.customer,
                device_pk=device.id,
                plan_code=str(payload.get("plan_code", "monthly")),
            )
            license_record = license_service.force_pay(
                session, app_settings, order
            )
        except (LicenseServiceError, PaymentError, SigningError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "license_id": license_record.license_id,
            "status": license_record.status,
            "expires_at": (
                license_record.expires_at.isoformat()
                if license_record.expires_at
                else None
            ),
        }

    def _admin_customer(session: Session, settings: Settings, payload: dict) -> Customer:
        email = str(payload.get("email", "")).strip().lower()
        customer = session.query(Customer).filter(Customer.email == email).first()
        if customer is None:
            customer = auth_service.register_customer(
                session,
                email=email,
                password=str(payload.get("password", "admin-default-1")),
                store_name=str(payload.get("store_name", "")),
            )
        return customer

    return app


app = create_app()
