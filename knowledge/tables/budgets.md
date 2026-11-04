---
id: table.budgets
version: 1
type: table
title: Budgets Table
description: Approved annual monetary budgets allocated to departments per fiscal year.
tags:
  - budget
  - allocation
  - fiscal_year
  - finance
tables:
  - budgets
related_concepts:
  - table.departments
columns:
  - name: department_id
    type: INTEGER
    primary_key: true
    description: Foreign key referencing departments(id).
  - name: fiscal_year
    type: INTEGER
    primary_key: true
    description: Fiscal year (e.g. 2023, 2024, 2025).
  - name: approved_amount
    type: REAL
    description: Authorized dollar expenditure limit.
---

# Table: budgets

Stores approved budget ceilings per department and fiscal year.

