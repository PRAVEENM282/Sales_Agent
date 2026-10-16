import sqlite3
import random
from datetime import datetime, timedelta
import os

def create_database(db_path: str = "data/sales.db"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
    CREATE TABLE customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        region TEXT NOT NULL,
        segment TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        order_date TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers (id)
    );
    """)

    cursor.execute("""
    CREATE TABLE products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        price REAL NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE order_items (
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders (id),
        FOREIGN KEY (product_id) REFERENCES products (id)
    );
    """)

    # Seed customers (exactly 500 customers)
    random.seed(42)

    first_names = [
        "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
        "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
        "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
        "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
        "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
        "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker"
    ]
    regions = ["North", "South", "East", "West", "Central"]
    segments = ["Consumer", "Corporate", "Home Office"]

    customers_data = []
    for i in range(1, 501):
        fn = first_names[i % len(first_names)]
        ln = last_names[(i * 7) % len(last_names)]
        name = f"{fn} {ln}"
        region = regions[i % len(regions)]
        segment = segments[i % len(segments)]
        customers_data.append((name, region, segment))

    cursor.executemany("INSERT INTO customers (name, region, segment) VALUES (?, ?, ?)", customers_data)

    # Seed products
    products = [
        # Technology
        ("Pro Laptop 15", "Technology", 1299.99),
        ("Ultra Wireless Mouse", "Technology", 49.99),
        ("Mechanical Keyboard RGB", "Technology", 129.50),
        ("4K UltraHD Monitor 27in", "Technology", 399.00),
        ("USB-C Multiport Dock", "Technology", 89.99),
        ("Noise-Cancelling Headphones", "Technology", 249.99),
        ("Smart HD Webcam 1080p", "Technology", 79.99),
        ("Portable SSD 1TB", "Technology", 119.99),
        ("Smartwatch Active", "Technology", 199.99),
        ("Tablet Pro 11", "Technology", 649.99),
        ("LaserJet Network Printer", "Technology", 299.99),
        ("Bluetooth Conference Speaker", "Technology", 149.99),
        # Furniture
        ("Ergonomic Mesh Chair", "Furniture", 289.00),
        ("Electric Standing Desk", "Furniture", 499.00),
        ("Solid Oak Bookshelf", "Furniture", 199.50),
        ("3-Drawer Mobile File Cabinet", "Furniture", 149.00),
        ("Executive Leather Chair", "Furniture", 349.99),
        ("L-Shaped Corner Desk", "Furniture", 429.00),
        ("Conference Room Table", "Furniture", 799.00),
        ("Adjustable Monitor Arm", "Furniture", 69.99),
        ("LED Architect Desk Lamp", "Furniture", 45.00),
        ("Footrest Ergonomic Cushion", "Furniture", 35.00),
        # Office Supplies
        ("Premium Gel Pens Pack of 12", "Office Supplies", 14.99),
        ("Multipurpose Copy Paper 500 Sheets", "Office Supplies", 9.99),
        ("Heavy Duty Desktop Stapler", "Office Supplies", 22.50),
        ("Assorted Sticky Notes 24-Pack", "Office Supplies", 16.99),
        ("Metal Mesh Desk Organizer", "Office Supplies", 24.99),
        ("Dry Erase Whiteboard Markers", "Office Supplies", 12.49),
        ("Heavy Duty Hole Punch", "Office Supplies", 18.99),
        ("Manila File Folders 100-Pack", "Office Supplies", 21.00),
        ("Titanium Scissors 3-Pack", "Office Supplies", 15.99),
        ("Desk Tape Dispenser with Tape", "Office Supplies", 8.99),
        # Products never ordered:
        ("Vintage Mechanical Typewriter", "Office Supplies", 180.00),
        ("Legacy 3.5in Floppy Disk Pack", "Technology", 25.00),
        ("Antique Rolltop Wooden Desk", "Furniture", 1200.00)
    ]

    cursor.executemany("INSERT INTO products (name, category, price) VALUES (?, ?, ?)", products)

    # Let product IDs 33, 34, 35 be the never-ordered products
    orderable_product_ids = list(range(1, 33))

    # Seed orders across 2024
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 12, 31)
    total_days = (end_date - start_date).days

    orders_data = []
    order_items_data = []

    # Designate top 3 customers with high order volume
    # e.g., customer 1, customer 2, customer 3
    # Customer 1 -> 25 orders
    # Customer 2 -> 20 orders
    # Customer 3 -> 18 orders
    num_orders = 1000
    order_id = 1

    # Specific orders for top 3
    for cid, count in [(1, 25), (2, 20), (3, 18)]:
        for _ in range(count):
            random_day = random.randint(0, total_days)
            odate = (start_date + timedelta(days=random_day)).strftime("%Y-%m-%d")
            # Pick products and calculate amount
            num_items = random.randint(1, 3)
            chosen_pids = random.sample(orderable_product_ids, num_items)
            order_total = 0.0
            for pid in chosen_pids:
                price = products[pid - 1][2]
                qty = random.randint(1, 4)
                order_total += round(price * qty, 2)
                order_items_data.append((order_id, pid, qty))
            orders_data.append((order_id, cid, round(order_total, 2), odate))
            order_id += 1

    # Remaining orders for other customers (customers 4 to 500)
    remaining_orders_count = num_orders - (25 + 20 + 18)
    for _ in range(remaining_orders_count):
        cid = random.randint(4, 500)
        random_day = random.randint(0, total_days)
        odate = (start_date + timedelta(days=random_day)).strftime("%Y-%m-%d")
        num_items = random.randint(1, 3)
        chosen_pids = random.sample(orderable_product_ids, num_items)
        order_total = 0.0
        for pid in chosen_pids:
            price = products[pid - 1][2]
            qty = random.randint(1, 4)
            order_total += round(price * qty, 2)
            order_items_data.append((order_id, pid, qty))
        orders_data.append((order_id, cid, round(order_total, 2), odate))
        order_id += 1

    cursor.executemany("INSERT INTO orders (id, customer_id, amount, order_date) VALUES (?, ?, ?, ?)", orders_data)
    cursor.executemany("INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)", order_items_data)

    conn.commit()

    # Verification queries
    cursor.execute("SELECT COUNT(*) FROM customers")
    cust_count = cursor.fetchone()[0]

    cursor.execute("""
    SELECT SUM(oi.quantity * p.price)
    FROM products p
    JOIN order_items oi ON p.id = oi.product_id
    JOIN orders o ON oi.order_id = o.id
    WHERE p.category = 'Technology'
    """)
    tech_revenue = cursor.fetchone()[0]

    cursor.execute("""
    SELECT COUNT(*)
    FROM products p
    LEFT JOIN order_items oi ON p.id = oi.product_id
    WHERE oi.order_id IS NULL
    """)
    never_ordered_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT strftime('%Y-%m', order_date)) FROM orders WHERE order_date LIKE '2024%'")
    months_count = cursor.fetchone()[0]

    conn.close()

    print(f"Database created successfully at {db_path}")
    print(f"Total customers: {cust_count}")
    print(f"Total Technology revenue: {tech_revenue:.2f}")
    print(f"Never ordered products count: {never_ordered_count}")
    print(f"2024 Months with orders: {months_count}")

if __name__ == "__main__":
    create_database("data/sales.db")
