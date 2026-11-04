---
id: metric.departmental_spend
version: 1
type: metric
title: Departmental Spend
description: Total sum of approved departmental expenditures within a designated fiscal year.
tags:
  - spend
  - expense
  - budget
  - department
  - cost
tables:
  - expenses
  - departments
related_concepts:
  - policy.fiscal_year
  - policy.expense_reimbursement
required_filters:
  - column: expenses.status
    operator: "="
    value: "approved"
  - column: expenses.expense_date
    type: fiscal_year_range
required_joins:
  - from_table: departments
    to_table: expenses
    'on': "departments.id = expenses.department_id"
---

# Metric: Departmental Spend

## Business Definition
Departmental spend measures recognized corporate expenditure for an organization's departments.

## Compliance Constraints
1. **Approval Requirement**: Only expenses with `status = 'approved'` count toward departmental spend. Pending and rejected expenses must be excluded.
2. **Fiscal Year Alignment**: Expenses must fall strictly within the January 1 to December 31 boundary of the target fiscal year.
3. **Table Relationships**: Must join `departments` and `expenses` via `departments.id = expenses.department_id`.

