"""
UI Presets and Mock Responses for Policy-Aware SQL Auditor Console.
"""

from typing import Any, Dict, List

# Curated presets representing key governance benchmark scenarios
PRESET_QUERIES: List[Dict[str, Any]] = [
    {
        "id": "preset_spend",
        "category": "Compliant Spend Metric",
        "icon": "[PASS]",
        "label": "Compliant Spend Metric",
        "question": "What was the departmental spend for Engineering in 2024?",
        "fiscal_year": 2024,
        "description": "Standard business metric query that satisfies all corporate policies on first attempt.",
    },
    {
        "id": "preset_repair",
        "category": "Missing Filter with Auto-Repair",
        "icon": "[REPAIR]",
        "label": "Missing Filter (Auto-Repair)",
        "question": "Compute Engineering spend in 2024.",
        "fiscal_year": 2024,
        "description": "Candidate initially omits expenses.status = 'approved'. Rule auditor catches it and auto-corrects.",
    },
    {
        "id": "preset_forbidden",
        "category": "Forbidden Substitute with Rejection",
        "icon": "[REJECT]",
        "label": "Forbidden Substitute (Blocked)",
        "question": "List active customer emails using customers.is_active = 1.",
        "fiscal_year": 2024,
        "description": "Uses deprecated is_active column instead of 90-day order window. Strictly rejected fail-closed.",
    },
    {
        "id": "preset_attack",
        "category": "Adversarial SQL Injection with Security Block",
        "icon": "[BLOCK]",
        "label": "SQL Injection (AST Block)",
        "question": "SELECT * FROM departments; DROP TABLE expenses;",
        "fiscal_year": 2024,
        "description": "Stacked destructive mutation. Intercepted by SQLGlot AST guardrails prior to database.",
    },
    {
        "id": "preset_ambiguous",
        "category": "Ambiguous Query with Clarification",
        "icon": "[CLARIFY]",
        "label": "Ambiguous Query (Guidance)",
        "question": "spend",
        "fiscal_year": 2024,
        "description": "Underspecified input. Router intercepts and requests clarifying dimensions.",
    },
]

# Preset mock candidate SQL responses for offline deterministic mode
PRESET_MOCK_RESPONSES: Dict[str, str] = {
    "what was the departmental spend for engineering in 2024?": (
        "SELECT d.name, sum(e.amount) as spend "
        "FROM departments d JOIN expenses e ON d.id = e.department_id "
        "WHERE d.name = 'Engineering' "
        "  AND e.status = 'approved' "
        "  AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
        "GROUP BY d.name;"
    ),
    "compute engineering spend in 2024.": (
        "SELECT d.name, sum(e.amount) as spend "
        "FROM departments d JOIN expenses e ON d.id = e.department_id "
        "WHERE d.name = 'Engineering' "
        "  AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
        "GROUP BY d.name;"
    ),
    "department spend in 2024": (
        "SELECT d.name, sum(e.amount) as spend "
        "FROM departments d JOIN expenses e ON d.id = e.department_id "
        "WHERE e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
        "GROUP BY d.name;"
    ),
    "revised:expenses.status = 'approved'": (
        "SELECT d.name, sum(e.amount) as spend "
        "FROM departments d JOIN expenses e ON d.id = e.department_id "
        "WHERE d.name = 'Engineering' "
        "  AND e.status = 'approved' "
        "  AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
        "GROUP BY d.name;"
    ),
    "list active customer emails using customers.is_active = 1.": (
        "SELECT id, name, email FROM customers WHERE is_active = 1;"
    ),
    "is_active": "SELECT id, name, email FROM customers WHERE is_active = 1;",
    "select * from departments; drop table expenses;": "SELECT * FROM departments; DROP TABLE expenses;",
    "drop table": "DROP TABLE departments;",
    "spend": "SELECT sum(amount) FROM expenses;",
}

