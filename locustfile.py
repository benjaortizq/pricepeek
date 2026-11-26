import random
import re

from locust import HttpUser, between, task

BUSQUEDAS = ["leche", "arroz", "cafe", "aceite", "pan", "atun"]


class Visitante(HttpUser):
    wait_time = between(1, 3)  # pausa entre clics, como una persona real
    productos = []  # ids sacados de los resultados de búsqueda

    @task(3)
    def buscar(self):
        r = self.client.get(
            "/products/buscar/",
            params={"q": random.choice(BUSQUEDAS)},
            name="/products/buscar/",
        )
        ids = re.findall(r'href="/products/(\d+)/', r.text)
        if ids:
            Visitante.productos = ids

    @task(2)
    def detalle(self):
        if self.productos:
            pk = random.choice(self.productos)
            self.client.get(f"/products/{pk}/", name="/products/[id]/")

    @task(1)
    def login(self):
        self.client.get("/accounts/login/")