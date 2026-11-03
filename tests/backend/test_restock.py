"""
Tests for restocking API endpoints.
"""
import json

import pytest

import mock_data


@pytest.fixture
def restock_store(tmp_path, monkeypatch):
    """Point restock persistence at a temp file and start with no orders."""
    path = tmp_path / "restock_orders.json"
    monkeypatch.setattr(mock_data, "RESTOCK_ORDERS_FILE", str(path))
    saved = list(mock_data.restock_orders)
    # Clear in place: main.py holds a reference to this same list
    mock_data.restock_orders.clear()
    yield path
    mock_data.restock_orders.clear()
    mock_data.restock_orders.extend(saved)


class TestRestockEndpoints:
    """Test suite for restocking-related endpoints."""

    def test_demand_forecasts_include_cost_and_lead_time(self, client):
        """Test that every forecast has a unit cost and lead time."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        for forecast in response.json():
            assert isinstance(forecast["unit_cost"], (int, float))
            assert forecast["unit_cost"] > 0
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["lead_time_days"] > 0

    def test_get_restock_orders_empty(self, client, restock_store):
        """Test getting restock orders when none have been submitted."""
        response = client.get("/api/restock-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restock_order(self, client, restock_store):
        """Test submitting a restock order computes totals and lead time."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        items = [
            {"item_sku": "WDG-001", "quantity": 10},
            {"item_sku": "MTR-304", "quantity": 2},
        ]
        expected_total = sum(forecasts[i["item_sku"]]["unit_cost"] * i["quantity"] for i in items)
        expected_lead = max(forecasts[i["item_sku"]]["lead_time_days"] for i in items)

        response = client.post("/api/restock-orders", json={"budget": 10000, "items": items})
        assert response.status_code == 201

        order = response.json()
        assert order["order_number"].startswith("RST-")
        assert order["status"] == "Submitted"
        assert abs(order["total_cost"] - expected_total) < 0.01
        assert order["lead_time_days"] == expected_lead
        assert len(order["items"]) == 2
        for line in order["items"]:
            assert abs(line["line_total"] - line["quantity"] * line["unit_cost"]) < 0.01
        assert "T" in order["submitted_date"]
        assert order["expected_delivery"] > order["submitted_date"]

    def test_create_restock_order_ignores_client_prices(self, client, restock_store):
        """Test that the server uses its own unit costs."""
        response = client.post(
            "/api/restock-orders",
            json={"budget": 10000, "items": [{"item_sku": "PSU-501", "quantity": 1, "unit_cost": 0.01}]},
        )
        assert response.status_code == 201
        assert response.json()["items"][0]["unit_cost"] == 18.99

    def test_create_restock_order_over_budget(self, client, restock_store):
        """Test that an order exceeding the budget is rejected."""
        response = client.post(
            "/api/restock-orders",
            json={"budget": 100, "items": [{"item_sku": "MTR-304", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()

    def test_create_restock_order_unknown_sku(self, client, restock_store):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restock-orders",
            json={"budget": 1000, "items": [{"item_sku": "NOPE-999", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    def test_create_restock_order_invalid_quantity(self, client, restock_store):
        """Test that zero or negative quantities are rejected."""
        response = client.post(
            "/api/restock-orders",
            json={"budget": 1000, "items": [{"item_sku": "WDG-001", "quantity": 0}]},
        )
        assert response.status_code == 400

    def test_create_restock_order_empty_items(self, client, restock_store):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restock-orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_restock_orders_persisted_and_listed(self, client, restock_store):
        """Test that submitted orders are saved to disk and listed newest first."""
        for qty in (1, 2):
            response = client.post(
                "/api/restock-orders",
                json={"budget": 1000, "items": [{"item_sku": "GSK-203", "quantity": qty}]},
            )
            assert response.status_code == 201

        data = client.get("/api/restock-orders").json()
        assert len(data) == 2
        assert data[0]["submitted_date"] >= data[1]["submitted_date"]

        saved = json.loads(restock_store.read_text())
        assert {o["order_number"] for o in saved} == {o["order_number"] for o in data}
