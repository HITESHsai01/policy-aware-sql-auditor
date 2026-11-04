"""
Usage:
    python data/seed_synthetic_data.py

Description:
    Seeds the SQLite database (data/auditor.db) with deterministic synthetic
    departments, budgets, expenses, customers, and orders data for the
    Policy-Aware SQL Auditor. Safe to rerun: resets only data/auditor.db.
"""

from pathlib import Path
import sqlite3

DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "auditor.db"


def seed_database(db_path: Path = DB_PATH) -> dict[str, int]:
    # Ensure data directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Reset only the generated database file if it exists
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # Enable SQLite foreign key constraint enforcement
        cur.execute("PRAGMA foreign_keys = ON;")

        # Create schema
        cur.executescript("""
            CREATE TABLE departments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE budgets (
                department_id INTEGER NOT NULL,
                fiscal_year INTEGER NOT NULL,
                approved_amount REAL NOT NULL CHECK (approved_amount >= 0),
                PRIMARY KEY (department_id, fiscal_year),
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
            );

            CREATE TABLE expenses (
                id INTEGER PRIMARY KEY,
                department_id INTEGER NOT NULL,
                amount REAL NOT NULL CHECK (amount >= 0),
                status TEXT NOT NULL CHECK (status IN ('approved', 'pending', 'rejected')),
                expense_date TEXT NOT NULL,
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
            );

            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount >= 0),
                status TEXT NOT NULL CHECK (status IN ('completed', 'pending', 'cancelled')),
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
            );

            CREATE INDEX idx_budgets_dept_year ON budgets(department_id, fiscal_year);
            CREATE INDEX idx_expenses_dept_status_date ON expenses(department_id, status, expense_date);
            CREATE INDEX idx_expenses_date ON expenses(expense_date);
            CREATE INDEX idx_orders_customer_date ON orders(customer_id, order_date);
            CREATE INDEX idx_orders_status ON orders(status);
        """)

        # Deterministic sample departments
        departments_data = [
            (1, "Engineering"),
            (2, "Marketing"),
            (3, "Human Resources"),
            (4, "Legal & Compliance"),
            (5, "Product Design"),
        ]
        cur.executemany(
            "INSERT INTO departments (id, name) VALUES (?, ?);",
            departments_data,
        )

        # Deterministic sample budgets across multiple fiscal years (2023, 2024, 2025)
        budgets_data = [
            (1, 2023, 500000.00),
            (1, 2024, 600000.00),
            (1, 2025, 750000.00),
            (2, 2023, 200000.00),
            (2, 2024, 250000.00),
            (2, 2025, 300000.00),
            (3, 2023, 100000.00),
            (3, 2024, 120000.00),
            (3, 2025, 140000.00),
            (4, 2023, 150000.00),
            (4, 2024, 160000.00),
            (4, 2025, 180000.00),
            (5, 2023, 80000.00),
            (5, 2024, 100000.00),
            (5, 2025, 120000.00),
        ]
        cur.executemany(
            "INSERT INTO budgets (department_id, fiscal_year, approved_amount) VALUES (?, ?, ?);",
            budgets_data,
        )

        # Deterministic sample expenses:
        # Mix of approved, pending, rejected across 2023, 2024, and 2025.
        expenses_data = [
            # Engineering (dept 1)
            (1, 1, 125000.00, "approved", "2023-04-12"),
            (2, 1, 45000.00, "rejected", "2023-06-20"),
            (3, 1, 85000.00, "approved", "2023-11-05"),
            (4, 1, 300000.00, "approved", "2024-02-15"),
            (5, 1, 75000.00, "pending", "2024-05-18"),
            (6, 1, 150000.00, "approved", "2024-09-30"),
            (7, 1, 50000.00, "rejected", "2024-10-12"),
            (8, 1, 200000.00, "approved", "2025-01-20"),
            (9, 1, 60000.00, "pending", "2025-03-01"),

            # Marketing (dept 2)
            (10, 2, 80000.00, "approved", "2023-03-14"),
            (11, 2, 30000.00, "rejected", "2023-08-22"),
            (12, 2, 110000.00, "approved", "2024-04-10"),
            (13, 2, 45000.00, "pending", "2024-07-15"),
            (14, 2, 60000.00, "approved", "2024-11-01"),
            (15, 2, 90000.00, "approved", "2025-02-14"),

            # Human Resources (dept 3)
            (16, 3, 40000.00, "approved", "2023-05-19"),
            (17, 3, 15000.00, "rejected", "2023-09-12"),
            (18, 3, 55000.00, "approved", "2024-03-04"),
            (19, 3, 20000.00, "pending", "2024-08-11"),
            (20, 3, 45000.00, "approved", "2025-01-25"),

            # Legal & Compliance (dept 4)
            (21, 4, 60000.00, "approved", "2023-07-21"),
            (22, 4, 70000.00, "approved", "2024-01-18"),
            (23, 4, 25000.00, "rejected", "2024-06-30"),
            (24, 4, 30000.00, "pending", "2024-10-05"),
            (25, 4, 50000.00, "approved", "2025-02-28"),

            # Product Design (dept 5)
            (26, 5, 35000.00, "approved", "2023-04-02"),
            (27, 5, 12000.00, "rejected", "2023-10-15"),
            (28, 5, 48000.00, "approved", "2024-06-12"),
            (29, 5, 18000.00, "pending", "2024-11-20"),
            (30, 5, 40000.00, "approved", "2025-03-10"),
        ]
        cur.executemany(
            "INSERT INTO expenses (id, department_id, amount, status, expense_date) "
            "VALUES (?, ?, ?, ?, ?);",
            expenses_data,
        )

        # Deterministic sample customers:
        # Includes trap columns (is_active=1 for users with no recent orders)
        customers_data = [
            (1, "Alice Smith", "alice@example.com", 1, "2023-01-10"),
            (2, "Bob Jones", "bob@example.com", 1, "2023-03-15"),      # Trap: is_active=1, but old order only
            (3, "Charlie Brown", "charlie@example.com", 1, "2024-01-20"), # Trap: is_active=1, only pending orders
            (4, "Diana Prince", "diana@example.com", 0, "2024-02-05"),   # Trap: is_active=0, but has recent completed order
            (5, "Evan Wright", "evan@example.com", 1, "2024-05-12"),    # Trap: is_active=1, only cancelled orders
            (6, "Fiona Gallagher", "fiona@example.com", 1, "2024-08-01") # Trap: is_active=1, 0 orders
        ]
        cur.executemany(
            "INSERT INTO customers (id, name, email, is_active, created_at) VALUES (?, ?, ?, ?, ?);",
            customers_data,
        )

        # Deterministic sample orders:
        # Reference snapshot date: 2025-03-31 (90-day window: 2025-01-01 to 2025-03-31)
        orders_data = [
            # Alice: genuinely active (completed in 90-day window)
            (1, 1, "2024-06-15", 150.00, "completed"),
            (2, 1, "2025-01-20", 320.00, "completed"),
            (3, 1, "2025-03-05", 210.00, "completed"),

            # Bob: completed order, but older than 90 days (2024-08-10) -> NOT active
            (4, 2, "2024-02-14", 85.00, "completed"),
            (5, 2, "2024-08-10", 120.00, "completed"),

            # Charlie: only pending orders in the window -> NOT active
            (6, 3, "2025-02-18", 450.00, "pending"),
            (7, 3, "2025-03-12", 200.00, "pending"),

            # Diana: is_active=0 in table, but completed order in 90-day window (2025-02-22) -> ACTIVE
            (8, 4, "2025-02-22", 500.00, "completed"),

            # Evan: cancelled orders only -> NOT active
            (9, 5, "2025-01-10", 300.00, "cancelled"),
        ]
        cur.executemany(
            "INSERT INTO orders (id, customer_id, order_date, amount, status) VALUES (?, ?, ?, ?, ?);",
            orders_data,
        )

        conn.commit()

        # Gather row counts
        counts = {}
        for table in ("departments", "budgets", "expenses", "customers", "orders"):
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            counts[table] = cur.fetchone()[0]

        return counts
    finally:
        conn.close()


if __name__ == "__main__":
    counts = seed_database()
    print("Database seeding completed successfully.")
    print(f"Database location: {DB_PATH}")
    for table, count in counts.items():
        print(f"Table '{table}': {count} rows")
