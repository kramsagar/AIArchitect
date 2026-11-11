"""ShopSphere: a small multi-feature shop (auth, catalog, search, cart, checkout, orders) plus a separate
payments service, both from this image (SERVICE_ROLE=shop|payments). Built to be observed and broken."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from . import telemetry

ROLE = os.getenv("SERVICE_ROLE", "shop")
telemetry.setup(f"shopsphere-{ROLE}" if ROLE == "shop" else "payments-service")

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402
from fastapi import Depends, FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from opentelemetry import metrics, trace  # noqa: E402
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from . import db  # noqa: E402
from .chaos import SCENARIOS, SERVICES, ChaosConfig, ChaosStore, apply_request_faults  # noqa: E402
from .telemetry import log  # noqa: E402

logger = logging.getLogger(f"shopsphere.{ROLE}")
tracer = trace.get_tracer("shopsphere")
meter = metrics.get_meter("shopsphere")
ORDERS = meter.create_counter("shop.orders", unit="{order}", description="Checkout attempts by result")
ORDER_VALUE = meter.create_histogram("shop.order.value", unit="USD", description="Order value")
PAYMENTS = meter.create_counter("shop.payments", unit="{payment}", description="Payment attempts by result")
LOGINS = meter.create_counter("shop.logins", unit="{login}", description="Logins by result")
CHAOS_FAULTS = meter.create_counter("shop.chaos.injected", unit="{fault}", description="Injected faults")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://shop:shop@postgres:5432/shop")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
PAYMENTS_URL = os.getenv("PAYMENTS_URL", "http://payments:8000")
PAYMENT_TIMEOUT_S = float(os.getenv("PAYMENT_TIMEOUT_S", "2.0"))
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "shopsphere")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    app.state.chaos = ChaosStore(app.state.redis, ROLE)
    app.state.http = httpx.AsyncClient(timeout=PAYMENT_TIMEOUT_S)
    app.state.pool = None
    if ROLE == "shop":
        app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=int(os.getenv("DB_POOL", "20")))
        await db.init(app.state.pool)
    log(logger, logging.INFO, "service started", role=ROLE)
    yield
    await app.state.http.aclose()
    await app.state.redis.aclose()
    if app.state.pool:
        await app.state.pool.close()


async def chaos_fault(request: Request) -> None:
    """Global dependency (runs after routing, so failures keep their http.route in traces and metrics)."""
    path = request.url.path
    if not path.startswith("/api/") or path.startswith("/api/chaos"):
        return
    cfg = await request.app.state.chaos.get()
    if cfg.active() and cfg.applies_to(path):
        status = await apply_request_faults(cfg)
        if status:
            CHAOS_FAULTS.add(1, {"fault": "down" if status == 503 else "error", "service": ROLE})
            log(logger, logging.ERROR, "injected fault", path=path, status=status)
            raise HTTPException(status, "injected fault")


app = FastAPI(
    title=f"ShopSphere {ROLE}", version=telemetry.VERSION, lifespan=lifespan, dependencies=[Depends(chaos_fault)]
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("unhandled error", extra={"shop.path": request.url.path})
    return JSONResponse({"detail": "internal error"}, status_code=500)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "role": ROLE}


@app.get("/readyz")
async def readyz(request: Request):
    await request.app.state.redis.ping()
    if request.app.state.pool:
        await db.query(request.app.state.pool, "SELECT 1", fetch="val")
    return {"status": "ready"}


# --------------------------------------------------------------------------------------------- chaos
@app.get("/api/chaos")
async def chaos_get(request: Request):
    return {"services": await request.app.state.chaos.all(), "scenarios": sorted(SCENARIOS)}


@app.put("/api/chaos/{service}")
async def chaos_set(service: str, cfg: ChaosConfig, request: Request):
    if service not in SERVICES:
        raise HTTPException(404, f"unknown service; use one of {SERVICES}")
    await request.app.state.chaos.set(service, cfg)
    log(logger, logging.WARNING, "chaos updated", target=service, config=cfg.model_dump_json())
    return {"service": service, "config": cfg}


@app.post("/api/chaos/scenarios/{name}")
async def chaos_scenario(name: str, request: Request):
    if name not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario; use one of {sorted(SCENARIOS)}")
    store = request.app.state.chaos
    for service in SERVICES:
        await store.set(service, SCENARIOS[name].get(service, ChaosConfig()))
    log(logger, logging.WARNING, "chaos scenario applied", scenario=name)
    return await chaos_get(request)


# ------------------------------------------------------------------------------------------ payments
class ChargeRequest(BaseModel):
    order_ref: str
    amount_cents: int = Field(gt=0)
    username: str


if ROLE == "payments":

    @app.post("/api/payments/charge")
    async def charge(req: ChargeRequest):
        with tracer.start_as_current_span("payment-provider.authorize") as span:
            await asyncio.sleep(random.uniform(0.02, 0.08))  # external PSP call
            declined = random.random() < 0.02
            span.set_attribute("payment.declined", declined)
        if declined:
            PAYMENTS.add(1, {"result": "declined"})
            log(logger, logging.WARNING, "payment declined", order_ref=req.order_ref, amount_cents=req.amount_cents)
            raise HTTPException(402, "card declined")
        PAYMENTS.add(1, {"result": "approved"})
        return {"payment_ref": f"pay_{uuid.uuid4().hex[:12]}", "status": "approved"}


# ------------------------------------------------------------------------------------------- shop
class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str


class CartItem(BaseModel):
    product_id: int = Field(gt=0)
    qty: int = Field(1, ge=1, le=20)


async def current_user(request: Request, authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    user = await request.app.state.redis.get(f"session:{authorization[7:]}")
    if not user:
        raise HTTPException(401, "invalid or expired session")
    return user


def _slow(request: Request) -> int:
    return request.app.state.chaos._cached.slow_db_ms


if ROLE == "shop":

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.post("/api/auth/login")
    async def login(req: LoginRequest, request: Request):
        if req.password != DEMO_PASSWORD:
            LOGINS.add(1, {"result": "failure"})
            log(logger, logging.WARNING, "login failed", username=req.username)
            raise HTTPException(401, "bad credentials")
        token = secrets.token_urlsafe(24)
        await request.app.state.redis.set(f"session:{token}", req.username, ex=3600)
        LOGINS.add(1, {"result": "success"})
        return {"token": token, "username": req.username, "expires_in": 3600}

    @app.get("/api/auth/me")
    async def me(user: str = Depends(current_user)):
        return {"username": user}

    @app.get("/api/catalog/categories")
    async def categories(request: Request):
        rows = await db.query(
            request.app.state.pool,
            "SELECT category, count(*) AS n FROM products GROUP BY category ORDER BY category",
            slow_ms=_slow(request),
        )
        return [dict(r) for r in rows]

    @app.get("/api/catalog/products")
    async def products(request: Request, category: str | None = None, limit: int = 24, offset: int = 0):
        limit = max(1, min(limit, 100))
        rows = await db.query(
            request.app.state.pool,
            "SELECT id, sku, name, category, price_cents, stock FROM products "
            "WHERE ($1::text IS NULL OR category = $1) ORDER BY id LIMIT $2 OFFSET $3",
            category,
            limit,
            max(offset, 0),
            slow_ms=_slow(request),
        )
        return [dict(r) for r in rows]

    @app.get("/api/catalog/products/{product_id}")
    async def product(product_id: int, request: Request):
        r = request.app.state.redis
        if cached := await r.get(f"product:{product_id}"):
            trace.get_current_span().set_attribute("cache.hit", True)
            return json.loads(cached)
        row = await db.query(
            request.app.state.pool,
            "SELECT * FROM products WHERE id = $1",
            product_id,
            slow_ms=_slow(request),
            fetch="one",
        )
        if not row:
            raise HTTPException(404, "product not found")
        doc = dict(row)
        await r.set(f"product:{product_id}", json.dumps(doc), ex=30)
        return doc

    @app.get("/api/search")
    async def search(request: Request, q: str, limit: int = 20):
        q = q.strip()[:64]
        if len(q) < 2:
            raise HTTPException(422, "query too short")
        key = f"search:{q.lower()}:{limit}"
        if cached := await request.app.state.redis.get(key):
            return json.loads(cached)
        rows = await db.query(
            request.app.state.pool,
            "SELECT id, name, category, price_cents FROM products "
            "WHERE name ILIKE $1 OR category ILIKE $1 OR description ILIKE $1 ORDER BY id LIMIT $2",
            f"%{q}%",
            max(1, min(limit, 50)),
            slow_ms=_slow(request),
        )
        result = {"query": q, "results": [dict(r) for r in rows]}
        await request.app.state.redis.set(key, json.dumps(result), ex=15)
        return result

    @app.get("/api/cart")
    async def cart(request: Request, user: str = Depends(current_user)):
        items = await request.app.state.redis.hgetall(f"cart:{user}")
        return {"items": [{"product_id": int(k), "qty": int(v)} for k, v in items.items()]}

    @app.post("/api/cart/items")
    async def add_to_cart(item: CartItem, request: Request, user: str = Depends(current_user)):
        exists = await db.query(
            request.app.state.pool, "SELECT 1 FROM products WHERE id=$1", item.product_id, fetch="val"
        )
        if not exists:
            raise HTTPException(404, "product not found")
        await request.app.state.redis.hincrby(f"cart:{user}", str(item.product_id), item.qty)
        await request.app.state.redis.expire(f"cart:{user}", 3600)
        return await cart(request, user)

    @app.delete("/api/cart")
    async def clear_cart(request: Request, user: str = Depends(current_user)):
        await request.app.state.redis.delete(f"cart:{user}")
        return {"items": []}

    @app.post("/api/checkout")
    async def checkout(request: Request, user: str = Depends(current_user)):
        started = time.perf_counter()
        st = request.app.state
        items = {int(k): int(v) for k, v in (await st.redis.hgetall(f"cart:{user}")).items()}
        if not items:
            raise HTTPException(400, "cart is empty")
        with tracer.start_as_current_span("checkout.price_and_reserve") as span:
            rows = await db.query(
                st.pool,
                "UPDATE products SET stock = stock - c.qty FROM unnest($1::int[], $2::int[]) AS c(id, qty) "
                "WHERE products.id = c.id AND stock >= c.qty RETURNING products.id, price_cents",
                list(items),
                list(items.values()),
                slow_ms=_slow(request),
            )
            if len(rows) != len(items):
                ORDERS.add(1, {"result": "out_of_stock"})
                raise HTTPException(409, "insufficient stock")
            total = sum(r["price_cents"] * items[r["id"]] for r in rows)
            span.set_attribute("order.items", sum(items.values()))
            span.set_attribute("order.total_cents", total)
        order_ref = f"ord_{uuid.uuid4().hex[:12]}"
        try:
            resp = await st.http.post(
                f"{PAYMENTS_URL}/api/payments/charge",
                json={"order_ref": order_ref, "amount_cents": total, "username": user},
            )
        except httpx.HTTPError as exc:
            ORDERS.add(1, {"result": "payment_unavailable"})
            log(logger, logging.ERROR, "payment service unreachable", order_ref=order_ref, error=type(exc).__name__)
            raise HTTPException(502, "payment service unavailable") from exc
        if resp.status_code == 402:
            ORDERS.add(1, {"result": "declined"})
            raise HTTPException(402, "payment declined")
        if resp.status_code >= 500:
            ORDERS.add(1, {"result": "payment_error"})
            log(logger, logging.ERROR, "payment failed", order_ref=order_ref, upstream_status=resp.status_code)
            raise HTTPException(502, f"payment service error {resp.status_code}")
        payment_ref = resp.json()["payment_ref"]
        order_id = await db.query(
            st.pool,
            "INSERT INTO orders (username, total_cents, items, status, payment_ref) "
            "VALUES ($1, $2, $3, 'paid', $4) RETURNING id",
            user,
            total,
            sum(items.values()),
            payment_ref,
            fetch="val",
        )
        await st.redis.delete(f"cart:{user}")
        ORDERS.add(1, {"result": "success"})
        ORDER_VALUE.record(total / 100)
        log(
            logger,
            logging.INFO,
            "order placed",
            order_id=order_id,
            order_ref=order_ref,
            total_cents=total,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return {"order_id": order_id, "order_ref": order_ref, "total_cents": total, "payment_ref": payment_ref}

    @app.get("/api/orders")
    async def orders(request: Request, user: str = Depends(current_user)):
        rows = await db.query(
            request.app.state.pool,
            "SELECT id, total_cents, items, status, payment_ref, created_at FROM orders "
            "WHERE username = $1 ORDER BY created_at DESC LIMIT 20",
            user,
            slow_ms=_slow(request),
        )
        return [dict(r) | {"created_at": r["created_at"].isoformat()} for r in rows]


FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
