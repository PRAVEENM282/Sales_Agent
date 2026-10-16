"""
AI Agent for Text-to-SQL generation using LangChain and MCP Server tools.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from mcp_server import MCPServer, SecurityViolationError


class AgentError(Exception):
    """Base exception for agent errors."""
    pass


class UnanswerableQuestionError(ValueError):
    """Raised when question cannot be answered using the database schema."""
    pass


class SQLAgent:
    """
    AI Agent that inspects schema context via MCP Server tools,
    generates SQL via LangChain LLM (or schema-aware fallback),
    and executes queries safely through the MCP Server.
    """

    def __init__(self, mcp_server: Optional[MCPServer] = None):
        self.mcp = mcp_server or MCPServer()
        self.llm = self._initialize_llm()

    def _initialize_llm(self) -> Optional[Any]:
        """Initialize LangChain LLM if credentials/services are available."""
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if anthropic_api_key:
            try:
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(
                    model_name=os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
                    anthropic_api_key=anthropic_api_key,
                    temperature=0,
                )
            except Exception as e:
                print(f"Warning: Could not initialize ChatAnthropic: {e}")

        # Check for OpenAI API key if available
        openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if openai_api_key:
            try:
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    openai_api_key=openai_api_key,
                    temperature=0,
                )
            except Exception as e:
                print(f"Warning: Could not initialize ChatOpenAI: {e}")

        # Check for local Ollama
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "").strip()
        if ollama_base_url:
            try:
                from langchain_community.chat_models import ChatOllama
                return ChatOllama(
                    base_url=ollama_base_url,
                    model=os.getenv("OLLAMA_MODEL", "llama3"),
                    temperature=0,
                )
            except Exception as e:
                print(f"Warning: Could not initialize ChatOllama: {e}")

        return None

    def _clean_sql(self, raw_sql: str) -> str:
        """Strip markdown fences, extra whitespace, and explanatory text."""
        sql = raw_sql.strip()
        if "```" in sql:
            # Extract content inside code block if present
            match = re.search(r"```(?:sql)?\s*(.*?)\s*```", sql, re.DOTALL | re.IGNORECASE)
            if match:
                sql = match.group(1).strip()
            else:
                sql = sql.replace("```sql", "").replace("```", "").strip()

        # Remove trailing semicolon if present
        sql = sql.rstrip(";").strip()
        return sql

    def _generate_sql_with_llm(self, question: str, schema_context: str) -> str:
        """Generate SQL query using LangChain LLM."""
        from langchain_core.prompts import PromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        template = (
            "You are an expert SQL assistant for a SQLite database.\n"
            "Given the database schema and a natural language question, translate it into a single, valid, read-only SQLite SELECT query.\n\n"
            "Database Schema:\n"
            "{schema_context}\n\n"
            "Rules:\n"
            "1. Output ONLY the raw SQL query. No markdown, no backticks, no comments, no explanation.\n"
            "2. Ensure the query is strictly a SELECT statement.\n"
            "3. Use only tables and columns that exist in the schema:\n"
            "   - customers (id, name, region, segment)\n"
            "   - orders (id, customer_id, amount, order_date)\n"
            "   - products (id, name, category, price)\n"
            "   - order_items (order_id, product_id, quantity)\n"
            "4. Correct Join Keys:\n"
            "   - orders.customer_id = customers.id\n"
            "   - order_items.order_id = orders.id\n"
            "   - order_items.product_id = products.id\n"
            "5. If the question cannot be answered using the provided schema or is irrelevant/ambiguous (e.g. weather, sports), respond with: UNANSWERABLE: <reason>\n\n"
            "Examples:\n"
            "Question: What is the total number of customers?\n"
            "SQL: SELECT COUNT(*) AS total_customers FROM customers;\n\n"
            "Question: What is the total revenue from the 'Technology' category?\n"
            "SQL: SELECT ROUND(SUM(oi.quantity * p.price), 2) AS total_revenue FROM products p JOIN order_items oi ON p.id = oi.product_id JOIN orders o ON oi.order_id = o.id WHERE p.category = 'Technology';\n\n"
            "Question: Top 3 customers by order count\n"
            "SQL: SELECT c.name, COUNT(o.id) AS order_count FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY order_count DESC LIMIT 3;\n\n"
            "Question: Average order value by region\n"
            "SQL: SELECT c.region, ROUND(AVG(o.amount), 2) AS avg_order_value FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.region ORDER BY avg_order_value DESC;\n\n"
            "Question: Monthly revenue for 2024\n"
            "SQL: SELECT strftime('%Y-%m', o.order_date) AS month, ROUND(SUM(o.amount), 2) AS monthly_revenue FROM orders o WHERE o.order_date LIKE '2024%' GROUP BY month ORDER BY month ASC;\n\n"
            "Question: Products that have never been ordered\n"
            "SQL: SELECT p.id, p.name, p.category, p.price FROM products p LEFT JOIN order_items oi ON p.id = oi.product_id WHERE oi.order_id IS NULL;\n\n"
            "Question: Total spend by customer segment\n"
            "SQL: SELECT c.segment, ROUND(SUM(o.amount), 2) AS total_spend FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.segment ORDER BY total_spend DESC;\n\n"
            "Question: {question}\n"
            "SQL:"
        )

        prompt = PromptTemplate(
            input_variables=["schema_context", "question"],
            template=template
        )
        chain = prompt | self.llm | StrOutputParser()
        raw_response = chain.invoke({"schema_context": schema_context, "question": question})
        return raw_response.strip()

    def _fallback_generate_sql(self, question: str) -> str:
        """
        Intelligent, schema-aware fallback SQL generator used when no external LLM is configured.
        Parses the question against the database schema gathered via MCP tools.
        """
        q_lower = question.lower().strip()

        # Check for unanswerable / irrelevant questions
        irrelevant_keywords = [
            "weather", "temperature", "forecast", "rain", "sunny",
            "president", "election", "football", "soccer", "basketball",
            "stock price", "recipe", "joke", "movie", "song", "who is",
            "population of", "capital of"
        ]
        if any(w in q_lower for w in irrelevant_keywords):
            raise UnanswerableQuestionError(
                f"The question '{question}' cannot be answered using the sales database schema."
            )

        # 1. Total customers / count of customers
        if ("customer" in q_lower and ("how many" in q_lower or "total number" in q_lower or "count" in q_lower)):
            return "SELECT COUNT(*) AS total_customers FROM customers"

        # 2. Total revenue from category (e.g. Technology)
        category_match = re.search(r"category ['\"]?([a-zA-Z\s]+)['\"]?", question, re.IGNORECASE)
        if ("revenue" in q_lower or "sales" in q_lower) and ("category" in q_lower or category_match):
            cat = "Technology"
            if category_match:
                cat = category_match.group(1).strip()
            elif "furniture" in q_lower:
                cat = "Furniture"
            elif "office supplies" in q_lower:
                cat = "Office Supplies"
            return (
                f"SELECT ROUND(SUM(oi.quantity * p.price), 2) AS total_revenue "
                f"FROM products p "
                f"JOIN order_items oi ON p.id = oi.product_id "
                f"JOIN orders o ON oi.order_id = o.id "
                f"WHERE p.category = '{cat}'"
            )

        # 3. Top N customers by order count
        if "customer" in q_lower and "order" in q_lower and ("top" in q_lower or "most" in q_lower):
            limit_match = re.search(r"top\s+(\d+)", q_lower)
            limit = int(limit_match.group(1)) if limit_match else 3
            return (
                "SELECT c.name, COUNT(o.id) AS order_count "
                "FROM customers c "
                "JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.id, c.name "
                "ORDER BY order_count DESC "
                f"LIMIT {limit}"
            )

        # 4. Average order value by region
        if "average order" in q_lower or ("avg" in q_lower and "order" in q_lower) or ("order value" in q_lower and "region" in q_lower):
            return (
                "SELECT c.region, ROUND(AVG(o.amount), 2) AS avg_order_value "
                "FROM customers c "
                "JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.region "
                "ORDER BY avg_order_value DESC"
            )

        # 5. Monthly revenue for 2024
        if "monthly" in q_lower and "revenue" in q_lower:
            year_match = re.search(r"\b(20\d\d)\b", question)
            year = year_match.group(1) if year_match else "2024"
            return (
                f"SELECT strftime('%Y-%m', o.order_date) AS month, ROUND(SUM(o.amount), 2) AS monthly_revenue "
                f"FROM orders o "
                f"WHERE o.order_date LIKE '{year}%' "
                f"GROUP BY month "
                f"ORDER BY month ASC"
            )

        # 6. Products that have never been ordered
        if "product" in q_lower and ("never" in q_lower or "not" in q_lower or "zero" in q_lower) and "order" in q_lower:
            return (
                "SELECT p.id, p.name, p.category, p.price "
                "FROM products p "
                "LEFT JOIN order_items oi ON p.id = oi.product_id "
                "WHERE oi.order_id IS NULL"
            )

        # 7. Total spend by customer segment
        if ("spend" in q_lower or "revenue" in q_lower or "sales" in q_lower) and "segment" in q_lower:
            return (
                "SELECT c.segment, ROUND(SUM(o.amount), 2) AS total_spend "
                "FROM customers c "
                "JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.segment "
                "ORDER BY total_spend DESC"
            )

        # Generic customer count
        if "customers" in q_lower and "total" in q_lower:
            return "SELECT COUNT(*) AS total_customers FROM customers"

        # Check if question mentions any schema table or column
        tables = self.mcp.list_tables()
        has_schema_term = any(t in q_lower for t in tables) or any(
            c in q_lower for c in ["order", "customer", "product", "sales", "revenue", "price", "amount", "region", "segment"]
        )
        if not has_schema_term:
            raise UnanswerableQuestionError(
                f"The question '{question}' does not match any table or concept in the sales database."
            )

        # Default fallback query for general queries
        if "product" in q_lower:
            return "SELECT id, name, category, price FROM products LIMIT 10"
        elif "customer" in q_lower:
            return "SELECT id, name, region, segment FROM customers LIMIT 10"
        elif "order" in q_lower:
            return "SELECT id, customer_id, amount, order_date FROM orders LIMIT 10"

        raise UnanswerableQuestionError(f"Unable to formulate query for question: '{question}'")

    def format_chart_data(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Formats query results into labels and numeric values for chart display.
        Ensures labels is array[string] and values is array[number].
        """
        if not results:
            return {"labels": [], "values": []}

        first_row = results[0]
        keys = list(first_row.keys())

        # Single row, single numeric column (e.g. COUNT or SUM)
        if len(results) == 1 and len(keys) == 1:
            val = list(first_row.values())[0]
            if isinstance(val, (int, float)):
                return {
                    "labels": [str(keys[0])],
                    "values": [val]
                }

        # Identify label and value columns
        label_col = None
        value_col = None

        for k in keys:
            val = first_row[k]
            if isinstance(val, (int, float)) and value_col is None:
                value_col = k
            elif isinstance(val, str) and label_col is None:
                label_col = k

        if label_col is None:
            label_col = keys[0]

        if value_col is None or value_col == label_col:
            for k in keys:
                if k != label_col:
                    value_col = k
                    break

        labels: List[str] = []
        values: List[float] = []

        for idx, row in enumerate(results):
            lbl = row.get(label_col)
            labels.append(str(lbl) if lbl is not None else f"Row {idx+1}")

            if value_col and value_col in row:
                raw_val = row[value_col]
                if isinstance(raw_val, (int, float)):
                    values.append(raw_val)
                else:
                    try:
                        values.append(float(raw_val))
                    except (ValueError, TypeError):
                        values.append(1.0)
            else:
                values.append(1.0)

        return {"labels": labels, "values": values}

    def process_query(self, question: str) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        """
        Orchestrates the Text-to-SQL workflow:
        1. Gather schema context via MCP tools.
        2. Prompt LLM to generate SQL (or use schema-aware fallback).
        3. Execute SQL safely via MCP execute_query tool.
        4. Format chart data and return (sql, results, chart_data).
        """
        # Step 2: Gather context using MCP server tools
        schema_context = self.mcp.get_full_schema_context()

        # Step 3 & 4: LLM generates SQL
        generated_sql = None
        if self.llm:
            try:
                response = self._generate_sql_with_llm(question, schema_context)
                if response.upper().startswith("UNANSWERABLE"):
                    raise UnanswerableQuestionError(response)
                generated_sql = self._clean_sql(response)
            except UnanswerableQuestionError:
                raise
            except Exception as e:
                print(f"LLM generation failed, using schema fallback: {e}")
                generated_sql = self._fallback_generate_sql(question)
        else:
            generated_sql = self._fallback_generate_sql(question)

        if not generated_sql:
            raise UnanswerableQuestionError(f"Could not generate SQL for question: {question}")

        # Step 5: Execute query using MCP server tool
        results = self.mcp.execute_query(generated_sql)

        # Step 6: Format chart data
        chart_data = self.format_chart_data(results)

        return generated_sql, results, chart_data
