"""
app.core — canonical business vocabulary shared by every layer.

Modules here define the SINGLE source of truth for cross-cutting constants:

  doc_types.py     — canonical document types + classifier alias resolution
  transactions.py  — canonical transaction-type codes + display labels

Nothing in app.core may import from app.pipeline / app.services / app.mappers
(one-way dependency: everything depends on core, core depends on nothing).
"""
