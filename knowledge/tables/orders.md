---
id: table.orders
version: 1
type: table
title: Orders Table
description: Customer purchase transactions with status, amount, and order date.
tags:
  - orders
  - sales
  - transactions
  - purchases
tables:
  - orders
related_concepts:
  - table.customers
  - metric.active_customer
columns:
  - name: id
    type: INTEGER
    primary_key: true
    description: Primary key for order.
  - name: customer_id
    type: INTEGER
    description: Foreign key referencing customers(id).
  - name: order_date
    type: TEXT
    description: Order placement date (YYYY-MM-DD).
  - name: amount
    type: REAL
    description: Dollar value of order.
  - name: status
    type: TEXT
    description: Order fulfillment status ('completed', 'pending', 'cancelled').
---

# Table: orders

Records transaction history for all orders.

