---
id: table.expenses
version: 1
type: table
title: Expenses Table
description: Itemized corporate expenses submitted by departments.
tags:
  - expenses
  - spend
  - transactions
  - costs
tables:
  - expenses
related_concepts:
  - table.departments
  - metric.departmental_spend
columns:
  - name: id
    type: INTEGER
    primary_key: true
    description: Primary key for expense entry.
  - name: department_id
    type: INTEGER
    description: Foreign key referencing departments(id).
  - name: amount
    type: REAL
    description: Cost in USD.
  - name: status
    type: TEXT
    description: Workflow status ('approved', 'pending', 'rejected').
  - name: expense_date
    type: TEXT
    description: Date incurred (YYYY-MM-DD).
---

# Table: expenses

Records departmental expense submissions and approval statuses.

