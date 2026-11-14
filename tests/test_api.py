import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import sys
import os

# API folder ko Python path me add karo
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api")))
from main import app

client = TestClient(app)

# 1. Test Root Endpoint
def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "ticketpulse-api"
    assert response.json()["status"] == "online"

# 2. Test Tickets Inventory Endpoint (Mocking Redis)
@patch("main.r")
def test_get_tickets(mock_redis):
    mock_redis.get.side_effect = lambda key: "85" if key == "tickets_inventory" else "15"
    response = client.get("/tickets")
    assert response.status_code == 200
    data = response.json()
    assert data["available_tickets"] == 85
    assert data["total_sold"] == 15
    assert data["status"] == "in_stock"

# 3. Test Successful Booking Flow
@patch("main.r")
def test_book_ticket_success(mock_redis):
    mock_lua = MagicMock(return_value=[1, 83])
    mock_redis.register_script.return_value = mock_lua

    payload = {"quantity": 2}
    response = client.post("/book", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["tickets_remaining"] == 83
    assert "BK-" in data["booking_id"]

# 4. Test Sold Out Scenario (Expect HTTP 409 Conflict)
@patch("main.r")
def test_book_ticket_sold_out(mock_redis):
    mock_lua = MagicMock(return_value=[0, 0])
    mock_redis.register_script.return_value = mock_lua

    payload = {"quantity": 1}
    response = client.post("/book", json=payload)
    assert response.status_code == 409
