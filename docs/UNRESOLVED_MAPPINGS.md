# Unresolved JotForm Field Mappings

Source of truth: `config/field_maps/arnona.yaml` (form **250201745267957**).
Loaded by `app/services/arnona/field_map.py`; live status at
`GET /admin/fieldmap/arnona/status`.

Two classes of unresolved entries (24 total as of v0.7):

- **Guessed numeric IDs** (`verified: false`, plausible `qNN_*` shape) — kept
  ACTIVE in `FIELD_MAP`: if the guess is right they parse; if wrong they match
  nothing. Verify against a real submission (`GET /discover/{submission_id}`)
  and set `verified: true`.
- **Fabricated IDs** (`fhs_*_placeholder`) — QUARANTINED at load time (v0.7):
  they can never match a webhook field and previously polluted the evaluator's
  label-visibility algorithm as permanently-visible passive QIDs.

## How to resolve (requires JOTFORM_API_KEY / a real submission — see docs/INTEGRATION_TODO.md)

1. Trigger or locate a real submission exercising the field's flow.
2. `GET /discover/{submission_id}` (operator key required) → raw field IDs.
3. Update `jotform_id` in the YAML, set `verified: true`, restart.

## Guessed numeric IDs (active, unverified)

| YAML id | Label | Section | Impact while unverified |
|---|---|---|---|
| `q9_transferDate9` | תאריך_העברה | basic | Transfer date may come only from FHS/raw fallback |
| `q105_email105` | אימייל | partner | **Second-tenant email missing on dashboard** (production bug #2) — verify FIRST |
| `q53_floor53` | קומה | property | Floor absent from address |
| `q54_entrance54` | כניסה | property | Entrance absent from address |
| `q63_arnonaTenant63` | מספר_חשבון_תושב | arnona | Ramat-Gan resident account never parsed |
| `q64_arnonaCustomer64` | מספר_חשבון_לקוח | arnona | Ramat-Gan customer account never parsed |
| `q70_waterProperty70` | מספר_נכס | water | Water property number never parsed |

Also verify: partner **phone** exists only for the "בעל בית" flow
(`q213_input213`); the "מתחיל שכירות" couple/roommate flow has NO mapped
partner-phone field — the second production complaint. Discover the QID from a
real couple submission and add it with `section: partner`.

## Fabricated IDs (quarantined, 17)

All `fhs_*_placeholder` entries: incoming name/id/email/phone, outgoing
id/email/phone, landlord name/id/email/phone, partner name/id/email/phone,
transfer_date, package. They describe the FHS Google-Sheet normalization
columns (sheet columns 74–92). Until the JotForm computed-field QIDs are
known, `business_mapper` serves every FHS value from the raw sections — which
is why quarantining them changes no behavior.

## Supplemental services

No verified field carries add-on services (e.g. עדכון כתובת). The parser
(`app/mappers/supplemental_services.py`) scans `_unmapped` as a stopgap; once
the QID is known, map it with label `שירותים_נוספים`, section `basic`.
