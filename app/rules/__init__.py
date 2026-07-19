"""
app.rules — canonical deterministic business-rule engines (v0.7).

  requirements.py — THE Missing-Information and Missing-Documents engine.
  transaction.py  — THE transaction-type classifier.

These modules replaced the three divergent rule sources that existed before
v0.7 (app/mappers/missing_detector.py, app/services/arnona/rules.py,
app/services/arnona/field_map.REQUIRED_DOCS). All future code must call these
engines; do not add requirement logic anywhere else.
"""
