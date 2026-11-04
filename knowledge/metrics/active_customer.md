---
id: metric.active_customer
version: 1
type: metric
title: Active Customer
description: A customer who has placed at least one completed order within the trailing 90 days.
tags:
  - customer
  - active
  - orders
  - retention
  - buyers
tables:
  - customers
  - orders
related_concepts: []
required_filters:
  - column: orders.status
    operator: "="
    value: "completed"
  - column: orders.order_date
    type: relative_date_range
    window_days: 90
forbidden_substitutes:
  - column: customers.is_active
    reason: "customers.is_active is an unverified legacy flag; active customers must be verified via completed orders in the last 90 days."
required_joins:
  - from_table: customers
    to_table: orders
    'on': "customers.id = orders.customer_id"
---

# Metric: Active Customer

## Business Definition
An active customer is defined as any customer who has placed at least one completed order in the trailing 90 days.

## Compliance Constraints
1. **Completion Requirement**: Only orders where `status = 'completed'` count toward customer activity. Pending or cancelled orders do not qualify.
2. **Forbidden Substitute**: Do not filter on `customers.is_active = 1`. That column is a legacy placeholder that does not accurately reflect business activity.
3. **Table Relationships**: Must join `customers` and `orders` via `customers.id = orders.customer_id`.

