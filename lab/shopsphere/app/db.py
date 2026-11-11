"""Postgres schema, seed data and queries. Every query passes through `query()` so slow-DB chaos applies."""

from __future__ import annotations

import random

import asyncpg

CATEGORIES = ["laptops", "phones", "audio", "monitors", "storage", "networking", "wearables", "gaming"]
ADJ = ["Pro", "Max", "Air", "Lite", "Ultra", "Mini", "Plus", "Edge"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  id SERIAL PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
  description TEXT NOT NULL, price_cents INT NOT NULL, stock INT NOT NULL
);
CREATE INDEX IF NOT EXISTS products_category_idx ON products (category);
CREATE TABLE IF NOT EXISTS orders (
  id SERIAL PRIMARY KEY, username TEXT NOT NULL, total_cents INT NOT NULL, items INT NOT NULL,
  status TEXT NOT NULL, payment_ref TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orders_username_idx ON orders (username, created_at DESC);
"""


async def init(pool: asyncpg.Pool, n_products: int = 240) -> None:
    async with pool.acquire() as conn:
        # Several replicas may start together; serialise schema + seed with an advisory lock.
        await conn.execute("SELECT pg_advisory_lock(4242)")
        try:
            await conn.execute(SCHEMA)
            if await conn.fetchval("SELECT count(*) FROM products") == 0:
                rng = random.Random(7)
                rows = []
                for i in range(1, n_products + 1):
                    cat = CATEGORIES[i % len(CATEGORIES)]
                    brand = rng.choice(["Nova", "Orbit", "Pulse", "Vertex", "Zen", "Flux"])
                    name = f"{brand} {cat[:-1].title()} {rng.choice(ADJ)}"
                    desc = f"{name}: {cat} for high-performance teams. Model {i:04d}."
                    rows.append((f"SKU-{i:05d}", name, cat, desc, rng.randint(1_999, 249_999), rng.randint(50, 5_000)))
                await conn.executemany(
                    "INSERT INTO products (sku, name, category, description, price_cents, stock) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    rows,
                )
        finally:
            await conn.execute("SELECT pg_advisory_unlock(4242)")


async def query(pool: asyncpg.Pool, sql: str, *args, slow_ms: int = 0, fetch: str = "all"):
    async with pool.acquire() as conn:
        if slow_ms:
            await conn.execute("SELECT pg_sleep($1)", slow_ms / 1000)
        if fetch == "one":
            return await conn.fetchrow(sql, *args)
        if fetch == "val":
            return await conn.fetchval(sql, *args)
        if fetch == "none":
            return await conn.execute(sql, *args)
        return await conn.fetch(sql, *args)
