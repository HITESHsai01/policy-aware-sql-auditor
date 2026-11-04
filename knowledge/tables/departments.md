---
id: table.departments
version: 1
type: table
title: Departments Table
description: Master record of company organizational departments.
tags:
  - department
  - org
  - division
tables:
  - departments
related_concepts:
  - table.budgets
  - table.expenses
columns:
  - name: id
    type: INTEGER
    primary_key: true
    description: Primary key for department.
  - name: name
    type: TEXT
    description: Unique department title (e.g., Engineering, Marketing).
---

# Table: departments

Contains internal corporate organizational units.

