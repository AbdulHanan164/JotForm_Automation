"""
Business domain models for the מה זה קל arnona transfer service.

These dataclasses represent the operator-facing data model — clean, typed,
no JotForm field IDs, no technical metadata.  Every field maps directly to
a concept the business cares about (FHS-normalized view of the Google Sheet).

Source of truth: columns 74–92 of the arnona Google Sheet CSV export.

OPERATOR SUMMARY DESIGN PRINCIPLE (v0.7):
  The summary returned by to_summary_dict() is a FIXED TEMPLATE.
  Every section is ALWAYS present regardless of transaction type, client type,
  or which services were selected.  Empty fields show "לא סופק" (not provided)
  instead of being hidden.

  Reason: The operator cannot hide empty fields and needs a consistent layout
  that works for all flows — rental, sale, corporate, single/multi-service.
  Client-stated requirement: "I can't hide empty fields so I have all the
  important ones for all flows."

  Sections always present in every summary:
    1.  סוג_עסקה       — Transaction type and service package
    2.  פרטי_נכס       — Property details
    3.  תאריכים        — All relevant dates
    4.  דייר_נכנס      — Incoming tenant
    5.  שוכר_שני       — Second tenant / partner (לא סופק when absent)
    6.  דייר_יוצא      — Outgoing tenant  (לא סופק when absent)
    7.  בעל_הבית       — Landlord          (לא סופק when absent)
    8.  חשבון_ארנונה   — Arnona account numbers (לא סופק when absent)
    9.  חשבון_מים      — Water account numbers  (לא סופק when absent)
    10. חשבון_חשמל     — Electricity account    (לא סופק — no form fields yet)
    11. מסמכים         — All 6 document types, always with ✅/❌ status
    12. פרטי_תשלום     — Payment information
    13. מידע_פנימי     — Internal reference numbers
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Placeholder displayed for fields that are not provided / empty.
_N = "לא סופק"


# ── Supporting dataclasses ────────────────────────────────────────────────────

@dataclass
class Person:
    full_name:    str = ""
    first_name:   str = ""
    last_name:    str = ""
    id_number:    str = ""
    phone:        str = ""
    email:        str = ""
    is_company:   bool = False
    company_name: str = ""
    company_reg:  str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_name":    self.full_name,
            "first_name":   self.first_name,
            "last_name":    self.last_name,
            "id_number":    self.id_number,
            "phone":        self.phone,
            "email":        self.email,
            "is_company":   self.is_company,
            "company_name": self.company_name,
            "company_reg":  self.company_reg,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Person":
        return cls(
            full_name    = d.get("full_name", ""),
            first_name   = d.get("first_name", ""),
            last_name    = d.get("last_name", ""),
            id_number    = d.get("id_number", ""),
            phone        = d.get("phone", ""),
            email        = d.get("email", ""),
            is_company   = bool(d.get("is_company", False)),
            company_name = d.get("company_name", ""),
            company_reg  = d.get("company_reg", ""),
        )


@dataclass
class Dates:
    move_in:       str = ""
    move_out:      str = ""
    lease_end:     str = ""
    transfer_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "move_in":       self.move_in,
            "move_out":      self.move_out,
            "lease_end":     self.lease_end,
            "transfer_date": self.transfer_date,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Dates":
        return cls(
            move_in       = d.get("move_in", ""),
            move_out      = d.get("move_out", ""),
            lease_end     = d.get("lease_end", ""),
            transfer_date = d.get("transfer_date", ""),
        )


@dataclass
class Property:
    city:         str = ""
    street:       str = ""
    building:     str = ""
    apartment:    str = ""
    floor:        str = ""
    entrance:     str = ""
    full_address: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "city":         self.city,
            "street":       self.street,
            "building":     self.building,
            "apartment":    self.apartment,
            "floor":        self.floor,
            "entrance":     self.entrance,
            "full_address": self.full_address,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Property":
        return cls(
            city         = d.get("city", ""),
            street       = d.get("street", ""),
            building     = d.get("building", ""),
            apartment    = d.get("apartment", ""),
            floor        = d.get("floor", ""),
            entrance     = d.get("entrance", ""),
            full_address = d.get("full_address", ""),
        )


@dataclass
class ArnonaAccounts:
    property_number:       str = ""
    identification_number: str = ""
    payer_number:          str = ""
    resident_account:      str = ""
    customer_account:      str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_number":       self.property_number,
            "identification_number": self.identification_number,
            "payer_number":          self.payer_number,
            "resident_account":      self.resident_account,
            "customer_account":      self.customer_account,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArnonaAccounts":
        return cls(
            property_number       = d.get("property_number", ""),
            identification_number = d.get("identification_number", ""),
            payer_number          = d.get("payer_number", ""),
            resident_account      = d.get("resident_account", ""),
            customer_account      = d.get("customer_account", ""),
        )


@dataclass
class WaterAccounts:
    property_number: str = ""
    payer_number:    str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_number": self.property_number,
            "payer_number":    self.payer_number,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WaterAccounts":
        return cls(
            property_number = d.get("property_number", ""),
            payer_number    = d.get("payer_number", ""),
        )


@dataclass
class Documents:
    id_photo:       Any = None
    lease_contract: Any = None
    signature:      Any = None
    arnona_bill:    Any = None
    corp_cert:      Any = None
    tabu:           Any = None

    @staticmethod
    def _doc_present(doc: Any) -> str:
        """Return '✅' if present, '❌' if missing."""
        if doc is None:
            return "❌"
        if isinstance(doc, bool):
            return "✅" if doc else "❌"
        if isinstance(doc, dict):
            return "✅" if (doc.get("present") or doc.get("url") or doc.get("local_path")) else "❌"
        return "✅" if str(doc).strip() and str(doc).strip() != "❌" else "❌"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id_photo":       self._doc_present(self.id_photo),
            "lease_contract": self._doc_present(self.lease_contract),
            "signature":      self._doc_present(self.signature),
            "arnona_bill":    self._doc_present(self.arnona_bill),
            "corp_cert":      self._doc_present(self.corp_cert),
            "tabu":           self._doc_present(self.tabu),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Documents":
        # Stored as status strings — keep as-is for reconstruction
        return cls(
            id_photo       = d.get("id_photo"),
            lease_contract = d.get("lease_contract"),
            signature      = d.get("signature"),
            arnona_bill    = d.get("arnona_bill"),
            corp_cert      = d.get("corp_cert"),
            tabu           = d.get("tabu"),
        )


@dataclass
class SubmissionMeta:
    transaction_type:    str        = "rental_transfer"
    package_description: str        = ""
    services_selected:   list[str]  = field(default_factory=list)
    amount_paid:         float | None = None
    transfer_to:         str        = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_type":    self.transaction_type,
            "package_description": self.package_description,
            "services_selected":   self.services_selected,
            "amount_paid":         self.amount_paid,
            "transfer_to":         self.transfer_to,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SubmissionMeta":
        raw_services = d.get("services_selected", [])
        if isinstance(raw_services, str):
            raw_services = [s.strip() for s in raw_services.split(",") if s.strip()]
        return cls(
            transaction_type    = d.get("transaction_type", "rental_transfer"),
            package_description = d.get("package_description", ""),
            services_selected   = raw_services,
            amount_paid         = d.get("amount_paid"),
            transfer_to         = d.get("transfer_to", ""),
        )


# ── Main business model ───────────────────────────────────────────────────────

@dataclass
class BusinessSubmission:
    """
    Canonical operator-facing model for an arnona transfer submission.

    Built by app.mappers.business_mapper.build_from_parsed().
    Stored as parsed["_business"] (JSON dict) so it survives JSON serialization.
    Exposed via ReviewItem.business_data → GET /review/{id}.
    """
    submission:      SubmissionMeta = field(default_factory=SubmissionMeta)
    dates:           Dates          = field(default_factory=Dates)
    property:        Property       = field(default_factory=Property)
    arnona_accounts: ArnonaAccounts = field(default_factory=ArnonaAccounts)
    water_accounts:  WaterAccounts  = field(default_factory=WaterAccounts)
    incoming_tenant: Person         = field(default_factory=Person)
    outgoing_tenant: Person | None  = None
    partner:         Person | None  = None
    landlord:        Person | None  = None
    documents:       Documents      = field(default_factory=Documents)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict. Stored in parsed['_business']."""
        return {
            "submission":      self.submission.to_dict(),
            "dates":           self.dates.to_dict(),
            "property":        self.property.to_dict(),
            "arnona_accounts": self.arnona_accounts.to_dict(),
            "water_accounts":  self.water_accounts.to_dict(),
            "incoming_tenant": self.incoming_tenant.to_dict(),
            "outgoing_tenant": self.outgoing_tenant.to_dict() if self.outgoing_tenant else None,
            "partner":         self.partner.to_dict()         if self.partner         else None,
            "landlord":        self.landlord.to_dict()        if self.landlord         else None,
            "documents":       self.documents.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BusinessSubmission":
        """Reconstruct from JSON dict (e.g. loaded from review queue file)."""
        def _person(key: str) -> Person | None:
            raw = d.get(key)
            if raw is None:
                return None
            return Person.from_dict(raw)

        return cls(
            submission      = SubmissionMeta.from_dict(d.get("submission", {})),
            dates           = Dates.from_dict(d.get("dates", {})),
            property        = Property.from_dict(d.get("property", {})),
            arnona_accounts = ArnonaAccounts.from_dict(d.get("arnona_accounts", {})),
            water_accounts  = WaterAccounts.from_dict(d.get("water_accounts", {})),
            incoming_tenant = Person.from_dict(d.get("incoming_tenant", {})),
            outgoing_tenant = _person("outgoing_tenant"),
            partner         = _person("partner"),
            landlord        = _person("landlord"),
            documents       = Documents.from_dict(d.get("documents", {})),
        )

    # ── Fixed operator-facing summary ─────────────────────────────────────────

    def to_summary_dict(self) -> dict[str, Any]:
        """
        Fixed-template Hebrew summary for the operator review screen.

        EVERY section is ALWAYS present.  Missing data shows "לא סופק" instead
        of the section being hidden.  This matches the client's requirement that
        the operator sees the same layout for all transaction types.

        Consumer compatibility:
          queue.py       reads "דייר_נכנס"."שם", "פרטי_נכס"."כתובת", "סוג_עסקה"."שירות"
          email_templates reads "דייר_נכנס"."שם", "פרטי_נכס"."כתובת", "סוג_עסקה"."שירות"
          All existing consumers still work because those keys remain identical.
        """
        ds  = self.documents
        a   = self.arnona_accounts
        w   = self.water_accounts
        inc = self.incoming_tenant
        out = self.outgoing_tenant or Person()
        par = self.partner          or Person()
        ll  = self.landlord         or Person()

        def _v(val: str) -> str:
            """Return value or 'לא סופק' placeholder."""
            return val if val else _N

        def _doc(doc: Any) -> str:
            return Documents._doc_present(doc)

        # Services list: prefer multi-select field, fall back to package description
        services_list = self.submission.services_selected
        services_str  = ", ".join(services_list) if services_list else (
            self.submission.package_description or _N
        )

        # Payment
        amount_str  = f"{self.submission.amount_paid:.0f} ₪" if self.submission.amount_paid else _N
        paid_status = "שולם ✅" if self.submission.amount_paid else "לא שולם"

        summary: dict[str, Any] = {}

        # ── 1. Transaction type ───────────────────────────────────────────────
        summary["סוג_עסקה"] = {
            "סוג_עסקה":      _v(self.submission.transaction_type),
            "שירות":         _v(self.submission.package_description),
            "שירותים":       services_str,
            "עיר":           _v(self.property.city),
            "סוג_לקוח":      "חברה" if inc.is_company else "פרטי",
            "לאן_מעבירים":   _v(self.submission.transfer_to),
        }

        # ── 2. Property ───────────────────────────────────────────────────────
        summary["פרטי_נכס"] = {
            "כתובת":  _v(self.property.full_address),
            "עיר":    _v(self.property.city),
            "רחוב":   _v(self.property.street),
            "בניין":  _v(self.property.building),
            "דירה":   _v(self.property.apartment),
            "קומה":   _v(self.property.floor),
            "כניסה":  _v(self.property.entrance),
        }

        # ── 3. Dates ──────────────────────────────────────────────────────────
        summary["תאריכים"] = {
            "כניסה":         _v(self.dates.move_in),
            "יציאה":         _v(self.dates.move_out),
            "סיום_חוזה":     _v(self.dates.lease_end),
            "תאריך_העברה":   _v(self.dates.transfer_date),
        }

        # ── 4. Incoming tenant — always populated ──────────────────────────
        summary["דייר_נכנס"] = {
            "שם":          _v(inc.full_name),
            "טלפון":       _v(inc.phone),
            "אימייל":      _v(inc.email),
            "תעודת_זהות":  _v(inc.id_number),
        }
        if inc.is_company:
            summary["דייר_נכנס"]["שם_חברה"]    = _v(inc.company_name)
            summary["דייר_נכנס"]["מספר_חברה"]  = _v(inc.company_reg)

        # ── 5. Second tenant / partner — ALWAYS shown ─────────────────────
        summary["שוכר_שני"] = {
            "שם":          _v(par.full_name),
            "טלפון":       _v(par.phone),
            "אימייל":      _v(par.email),
            "תעודת_זהות":  _v(par.id_number),
        }

        # ── 6. Outgoing tenant — ALWAYS shown ─────────────────────────────
        summary["דייר_יוצא"] = {
            "שם":          _v(out.full_name),
            "טלפון":       _v(out.phone),
            "אימייל":      _v(out.email),
            "תעודת_זהות":  _v(out.id_number),
        }

        # ── 7. Landlord — ALWAYS shown ────────────────────────────────────
        summary["בעל_הבית"] = {
            "שם":          _v(ll.full_name),
            "טלפון":       _v(ll.phone),
            "אימייל":      _v(ll.email),
            "תעודת_זהות":  _v(ll.id_number),
        }

        # ── 8. Arnona account numbers — ALWAYS shown ──────────────────────
        summary["חשבון_ארנונה"] = {
            "מספר_נכס":           _v(a.property_number),
            "מספר_לקוח":          _v(a.payer_number),
            "מספר_זיהוי_נכס":     _v(a.identification_number),
            "מספר_חשבון_תושב":    _v(a.resident_account),
            "מספר_חשבון_לקוח":    _v(a.customer_account),
        }

        # ── 9. Water account numbers — ALWAYS shown ───────────────────────
        summary["חשבון_מים"] = {
            "מספר_נכס":   _v(w.property_number),
            "מספר_לקוח":  _v(w.payer_number),
        }

        # ── 10. Electricity — ALWAYS shown (no form fields yet) ───────────
        summary["חשבון_חשמל"] = {
            "מספר_נכס":   _N,
            "מספר_לקוח":  _N,
        }

        # ── 11. Documents — ALWAYS shown, all 6 types ─────────────────────
        summary["מסמכים"] = {
            "תעודת_זהות":       _doc(ds.id_photo),
            "חוזה_שכירות":      _doc(ds.lease_contract),
            "חתימה":             _doc(ds.signature),
            "חשבון_ארנונה":      _doc(ds.arnona_bill),
            "תעודת_התאגדות":     _doc(ds.corp_cert),
            "נסח_טאבו":          _doc(ds.tabu),
        }

        # ── 12. Payment — ALWAYS shown ────────────────────────────────────
        summary["פרטי_תשלום"] = {
            "שירות":          _v(self.submission.package_description),
            "סכום":           amount_str,
            "סטטוס_תשלום":    paid_status,
        }

        # ── 13. Internal reference — ALWAYS shown ─────────────────────────
        summary["מידע_פנימי"] = {
            "מספר_פנייה":  _N,
            "מזהה_החזר":   _N,
        }

        return summary
