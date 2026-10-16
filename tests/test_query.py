"""
Pytest test suite for Natural Language to SQL FastAPI service.
Tests /query endpoint, MCP server tools, security rejection, and schema queries.
"""

import pytest
from fastapi.testclient import TestClient

from main import app, mcp_server
from mcp_server import SecurityViolationError

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_query_total_customers():
    """Requirement 4: Simple aggregation query returning 500 customers."""
    payload = {"question": "What is the total number of customers?"}
    response = client.post("/query", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "sql" in data
    assert "results" in data
    assert "chart_data" in data

    sql = data["sql"].upper()
    assert "SELECT" in sql
    assert "COUNT" in sql
    assert "CUSTOMERS" in sql

    results = data["results"]
    assert len(results) == 1
    # Check that results contains an object whose value is 500
    values = list(results[0].values())
    assert 500 in values

    # Verify chart_data structure
    chart_data = data["chart_data"]
    assert "labels" in chart_data
    assert "values" in chart_data
    assert isinstance(chart_data["labels"], list)
    assert isinstance(chart_data["values"], list)
    assert 500 in chart_data["values"]


def test_query_technology_revenue():
    """Requirement 5: Query involving joins and filtering by Technology category."""
    payload = {"question": "What is the total revenue from the 'Technology' category?"}
    response = client.post("/query", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "sql" in data
    assert "results" in data
    assert "chart_data" in data

    sql = data["sql"].upper()
    assert "PRODUCTS" in sql
    assert "ORDER_ITEMS" in sql
    assert "ORDERS" in sql
    assert "TECHNOLOGY" in sql
    assert "SUM" in sql

    results = data["results"]
    assert len(results) == 1
    val = list(results[0].values())[0]
    assert float(val) > 0


def test_query_unanswerable_question():
    """Requirement 6: Handle invalid or ambiguous questions gracefully."""
    payload = {"question": "What is the weather like today?"}
    response = client.post("/query", json=payload)
    # Must return a non-200 status code (e.g. 400 Bad Request)
    assert response.status_code == 400

    data = response.json()
    assert "detail" in data or "error" in data


def test_mcp_server_security_rejects_non_select():
    """Requirement 7: MCP server rejects non-SELECT statements."""
    with pytest.raises((SecurityViolationError, ValueError)):
        mcp_server.execute_query("DROP TABLE customers;")

    with pytest.raises((SecurityViolationError, ValueError)):
        mcp_server.execute_query("DELETE FROM customers WHERE id = 1;")

    with pytest.raises((SecurityViolationError, ValueError)):
        mcp_server.execute_query("INSERT INTO customers (name, region, segment) VALUES ('Hacker', 'None', 'None');")

    with pytest.raises((SecurityViolationError, ValueError)):
        mcp_server.execute_query("SELECT 1; DROP TABLE customers;")


def test_mcp_server_tools():
    """Verify MCP tools list_tables and describe_schema."""
    tables = mcp_server.list_tables()
    assert "customers" in tables
    assert "orders" in tables
    assert "products" in tables
    assert "order_items" in tables

    schema = mcp_server.describe_schema("customers")
    assert schema["table_name"] == "customers"
    col_names = [c["name"] for c in schema["columns"]]
    assert "id" in col_names
    assert "name" in col_names
    assert "region" in col_names
    assert "segment" in col_names


def test_evaluator_queries():
    """Test all 5 queries checked by evaluator.sh."""
    queries = [
        "Top 3 customers by order count",
        "Average order value by region",
        "Monthly revenue for 2024",
        "Products that have never been ordered",
        "Total spend by customer segment",
    ]

    for q in queries:
        response = client.post("/query", json={"question": q})
        assert response.status_code == 200, f"Query failed: {q} with {response.text}"
        data = response.json()
        assert len(data["results"]) > 0, f"No results returned for query: {q}"
        assert len(data["chart_data"]["labels"]) > 0
        assert len(data["chart_data"]["values"]) > 0
