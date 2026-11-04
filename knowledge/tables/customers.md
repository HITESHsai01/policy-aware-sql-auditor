---
id: table.customers
version: 1
type: table
title: Customers Table
description: Registered customer profiles and legacy activity flags.
tags:
  - customers
  - clients
  - accounts
  - buyers
tables:
  - customers
related_concepts:
  - table.orders
  - metric.active_customer
columns:
  - name: id
    type: INTEGER
    primary_key: true
    description: Unique customer account ID.
  - name: name
    type: TEXT
    description: Customer full name.
  - name: email
    type: TEXT
    description: Registered email address.
  - name: is_active
    type: INTEGER
    description: Legacy activity flag (do NOT use for active customer metric; see metric.active_customer).
  - name: created_at
    type: TEXT
    description: Account creation date (YYYY-MM-DD).
---

# Table: customers

Customer profile records. Warning: `is_active` column is unverified legacy data; see `metric.active_customer`.

