"""Realistic shopper traffic: browse-heavy, some search, fewer checkouts (like real e-commerce funnels)."""

import random

from locust import HttpUser, between, task


class Shopper(HttpUser):
    wait_time = between(0.2, 1.5)

    def on_start(self):
        user = f"user{random.randint(1, 500)}"
        r = self.client.post("/api/auth/login", json={"username": user, "password": "shopsphere"})
        self.headers = {"Authorization": f"Bearer {r.json().get('token', '')}"} if r.ok else {}

    @task(6)
    def browse(self):
        cat = random.choice(["laptops", "phones", "audio", "monitors", "storage", "networking", "wearables", "gaming"])
        self.client.get(f"/api/catalog/products?category={cat}", name="/api/catalog/products")

    @task(4)
    def product(self):
        self.client.get(f"/api/catalog/products/{random.randint(1, 240)}", name="/api/catalog/products/{id}")

    @task(3)
    def search(self):
        q = random.choice(["laptop", "pro", "ultra", "phone", "audio", "nova", "gaming", "zen", "mini", "edge"])
        self.client.get(f"/api/search?q={q}", name="/api/search")

    @task(2)
    def add_to_cart(self):
        self.client.post("/api/cart/items", json={"product_id": random.randint(1, 240), "qty": random.randint(1, 3)},
                         headers=self.headers, name="/api/cart/items")

    @task(1)
    def checkout(self):
        self.client.post("/api/cart/items", json={"product_id": random.randint(1, 240), "qty": 1},
                         headers=self.headers, name="/api/cart/items")
        with self.client.post("/api/checkout", headers=self.headers, catch_response=True, name="/api/checkout") as r:
            if r.status_code in (402, 409):  # business outcomes, not errors
                r.success()

    @task(1)
    def orders(self):
        self.client.get("/api/orders", headers=self.headers, name="/api/orders")
