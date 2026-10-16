# Sales Agent: Text-to-SQL with Model Context Protocol (MCP) & LangChain

A production-grade **FastAPI** service that securely translates natural language questions into SQL queries executed against a SQLite sales database. The architecture leverages the **Model Context Protocol (MCP)** pattern to decouple the AI agent from direct database access and credentials, enforcing strict read-only access controls, schema reflection, and parameterization.

---

## Architecture Overview

The system consists of three distinct layers:

```mermaid
flowchart TD
    Client["Client / Evaluator / Browser"] -->|POST /query| API["FastAPI Application (main.py)"]
    API -->|Question| Agent["SQL Agent (LangChain / agent.py)"]
    
    subgraph MCP ["MCP Server Layer (mcp_server.py)"]
        Tool1["list_tables()"]
        Tool2["describe_schema(table)"]
        Tool3["execute_query(sql) [Read-Only Guard]"]
    end
    
    Agent -->|1. Request Schema Context| Tool1
    Agent -->|2. Inspect Table Definitions| Tool2
    Tool1 --> DB[(sales.db)]
    Tool2 --> DB
    Agent -->|3. Generate SQL via LLM| Agent
    Agent -->|4. Safe Execution Request| Tool3
    Tool3 -->|5. Parameterized SELECT| DB
    Tool3 -->|Rows| Agent
    Agent -->|Structured Results & Chart Data| API
    API -->|JSON Response (sql, results, chart_data)| Client
```

### Key Components

1. **FastAPI Application (`main.py`)**:
   - Exposes `POST /query` for natural language questions.
   - Exposes `GET /health` and `GET /docs` (interactive Swagger UI).
   - Validates requests and shapes responses into `{sql, results, chart_data}` format.
   - Translates domain and security errors into clean HTTP error codes (e.g., 400 for unanswerable questions, 500 for execution violations).

2. **MCP Server (`mcp_server.py`)**:
   - Acts as a secure gatekeeper between AI agents and the underlying SQLite database.
   - **`list_tables()`**: Discovers active database tables dynamically without hardcoding.
   - **`describe_schema(table_name)`**: Reflects columns, types, primary keys, and foreign keys.
   - **`execute_query(sql, params)`**: Strictly enforces read-only access. Rejects non-`SELECT` statements, multi-statements, and mutating DDL/DML (`DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, etc.).

3. **SQL Agent (`agent.py`)**:
   - Orchestrates the Text-to-SQL workflow using LangChain.
   - Pulls dynamic schema context from the MCP server to construct few-shot prompts.
   - Supports **Anthropic Claude** (e.g. `claude-3-haiku-20240307`), **OpenAI**, local **Ollama** models, and a deterministic schema-aware fallback for isolated offline evaluation environments.
   - Transforms relational row sets into visualizable `chart_data` (labels and values).

---

## Database Schema

The database (`data/sales.db`) contains an e-commerce sales dataset with 500 customers and full 2024 order history:

* **`customers`** (`id`, `name`, `region`, `segment`)
* **`orders`** (`id`, `customer_id`, `amount`, `order_date`)
* **`products`** (`id`, `name`, `category`, `price`)
* **`order_items`** (`order_id`, `product_id`, `quantity`)

---

## API Specification

### `POST /query`

Translates a natural language question into SQL, executes it, and returns results.

#### Request Body
```json
{
  "question": "What is the total number of customers?"
}
```

#### Response (200 OK)
```json
{
  "sql": "SELECT COUNT(*) AS total_customers FROM customers",
  "results": [
    {
      "total_customers": 500
    }
  ],
  "chart_data": {
    "labels": ["total_customers"],
    "values": [500]
  }
}
```

#### Complex Query Example:
**Request:**
```json
{
  "question": "What is the total revenue from the 'Technology' category?"
}
```

**Response (200 OK):**
```json
{
  "sql": "SELECT ROUND(SUM(oi.quantity * p.price), 2) AS total_revenue FROM products p JOIN order_items oi ON p.id = oi.product_id JOIN orders o ON oi.order_id = o.id WHERE p.category = 'Technology'",
  "results": [
    {
      "total_revenue": 595295.33
    }
  ],
  "chart_data": {
    "labels": ["total_revenue"],
    "values": [595295.33]
  }
}
```

#### Error Handling (400 Bad Request):
When an unanswerable or ambiguous question is submitted:
```json
{
  "detail": "The question 'What is the weather like today?' cannot be answered using the sales database schema."
}
```

---

## Quickstart & Running

### 1. Environment Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Set `ANTHROPIC_API_KEY` if using Claude API, or leave blank to use local Ollama / offline schema engine:
```ini
ANTHROPIC_API_KEY=
DATABASE_URL=sqlite:///./data/sales.db
```

### 2. Run with Docker Compose (Recommended)

Build and run the containerized service:
```bash
docker compose up --build -d
```

The service will start, run health checks against `/docs`, and be ready on `http://localhost:8000`.

To view logs:
```bash
docker compose logs -f api
```

To stop:
```bash
docker compose down
```

### 3. Local Development Setup

If running locally without Docker:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run FastAPI with hot-reloading
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Automated Testing & Evaluation

### Run Unit and Integration Tests with Pytest

Run tests inside the running Docker container:
```bash
docker compose exec api pytest
```

Or run locally:
```bash
pytest
```

### Run End-to-End Evaluation Script

Execute `evaluator.sh` against the running service:
```bash
./evaluator.sh
```

The evaluator runs 5 test queries:
1. `Top 3 customers by order count`
2. `Average order value by region`
3. `Monthly revenue for 2024`
4. `Products that have never been ordered`
5. `Total spend by customer segment`

All queries must return non-empty result sets and exit with status code `0`.

---

## Security Model

1. **Protocol Decoupling (MCP)**: AI agents do not access connection strings, raw SQLite files, or database credentials.
2. **Read-Only Enforcement**: Query parser rejects any statements containing DDL or DML tokens (`DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `CREATE`, `TRUNCATE`, etc.).
3. **Multi-Statement Blocking**: Prevents SQL injection stacking attacks (e.g. `SELECT 1; DROP TABLE customers;`).
4. **SQLite Engine Guards**: Connections are opened in read-only mode (`mode=ro`) with SQLite `PRAGMA query_only = ON;`.
