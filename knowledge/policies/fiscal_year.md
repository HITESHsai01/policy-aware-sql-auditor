---
id: policy.fiscal_year
version: 1
type: policy
title: Fiscal Year Accounting Boundaries
description: Company policy establishing that the fiscal year matches the calendar year from January 1 to December 31.
tags:
  - fiscal_year
  - accounting
  - dates
  - annual
tables:
  - budgets
  - expenses
related_concepts:
  - metric.departmental_spend
required_filters:
  - column: expenses.expense_date
    type: fiscal_year_range
    start_pattern: "{year}-01-01"
    end_pattern: "{year}-12-31"
---

# Policy: Fiscal Year Accounting Boundaries

## Purpose
Establishes standardized calendar boundaries for all fiscal year reporting.

## Rules
- The fiscal year $Y$ begins on `$Y-01-01` and ends on `$Y-12-31`.
- Any multi-year spend aggregation must partition or filter by fiscal year boundaries explicitly.

