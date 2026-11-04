---
id: policy.expense_reimbursement
version: 1
type: policy
title: Expense Reimbursement Policy
description: Corporate policy dictating that only approved expenses constitute recognized expenditures.
tags:
  - expense
  - reimbursement
  - approval
  - compliance
tables:
  - expenses
related_concepts:
  - metric.departmental_spend
required_filters:
  - column: expenses.status
    operator: "="
    value: "approved"
---

# Policy: Expense Reimbursement

## Purpose
Ensures that calculations of expenditures, reimbursements, and cost allocations only include verified and approved company expenses.

## Requirements
- Queries calculating spent amounts must explicitly filter by `expenses.status = 'approved'`.
- Pending expenses (under review) and rejected expenses (denied claims) must never be added to totals.

