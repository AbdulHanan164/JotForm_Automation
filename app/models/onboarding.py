"""
Onboarding summary builder.

Takes a ParsedSubmission + DocumentReport and builds the final clean JSON
that represents a complete onboarding record — ready for HubSpot, AI, or storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.parsers.jotform_parser import ParsedSubmission
    from app.services.rules.engine import DocumentReport


class OnboardingSummary:
    """
    Produces the canonical clean summary dict from parsed data + document report.
    This is the single source of truth consumed by all future integrations.
    """

    @staticmethod
    def build(sub: "ParsedSubmission", doc_report: "DocumentReport") -> dict[str, Any]:
        return {
            # ── Metadata ──────────────────────────────────────────────────
            "meta": {
                "submission_id":  sub.submission_id,
                "form_id":        sub.form_id,
                "form_title":     sub.form_title,
                "username":       sub.username,
                "submitter_ip":   sub.submitter_ip,
                "received_at":    sub.received_at,
                "processed_at":   datetime.now(timezone.utc).isoformat(),
                "unique_id":      sub.meta.get("unique_id", ""),
                "refund_id":      sub.meta.get("refund_id", ""),
                "deal_name":      sub.system.get("deal_name", ""),
                "company":        sub.system.get("company_name", ""),
            },

            # ── Customer (incoming tenant) ────────────────────────────────
            "customer": {
                "full_name":    sub.customer.get("full_name", ""),
                "first_name":   sub.customer.get("first_name", ""),
                "last_name":    sub.customer.get("last_name", ""),
                "email":        sub.customer.get("email", ""),
                "phone":        sub.customer.get("phone", ""),
                "id_number":    sub.customer.get("id_number", ""),
                "move_type":    sub.customer.get("move_type", ""),
                "person_type":  sub.customer.get("person_type", ""),
                "payment_type": sub.customer.get("payment_type", ""),
                "tenant_status":sub.customer.get("tenant_status", ""),
            },

            # ── Property ─────────────────────────────────────────────────
            "property": {
                "city":             sub.property.get("city", ""),
                "street":           sub.property.get("street", ""),
                "building_number":  sub.property.get("building_number", ""),
                "apartment_number": sub.property.get("apartment_number", ""),
                "full_address":     sub.property.get("full_address", ""),
                "asset_number":     sub.property.get("asset_number", ""),
                "customer_number":  sub.property.get("customer_number", ""),
            },

            # ── Lease ─────────────────────────────────────────────────────
            "lease": {
                "move_in_date":  sub.lease.get("move_in_date", ""),
                "lease_end_date":sub.lease.get("lease_end_date", ""),
                "duration_days": sub.lease.get("duration_days", ""),
                "direction":     sub.lease.get("direction", ""),
            },

            # ── Selected services & utilities ─────────────────────────────
            "services": {
                "selected_packages": sub.services.get("selected_packages", []),
                "utilities":         sub.services.get("utilities", {}),
                "bills_to":          sub.services.get("bills_to", ""),
                "electricity_meter": sub.services.get("electricity_meter", ""),
                "electricity_reading":sub.services.get("electricity_reading", ""),
            },

            # ── Payment ───────────────────────────────────────────────────
            "payment": {
                "amount":         sub.payment.get("amount", 0.0),
                "coupon_code":    sub.payment.get("coupon_code", ""),
                "coupon_discount":sub.payment.get("coupon_discount", ""),
                "transaction_id": sub.payment.get("transaction_id", ""),
                "total_paid":     sub.payment.get("total_paid", ""),
            },

            # ── Documents ─────────────────────────────────────────────────
            "documents": {
                "id_photo_present":     sub.documents.get("id_photo", {}).get("present", False),
                "signature_present":    sub.documents.get("signature", {}).get("present", False),
                "terms_accepted":       sub.documents.get("terms_accepted", False),
                "agreement_signed":     sub.documents.get("agreement_signed", False),
                "received":             doc_report.received,
                "missing":              doc_report.missing,
                "optional_missing":     doc_report.optional_missing,
                "is_complete":          doc_report.is_complete,
                "detail":               doc_report.to_dict()["detail"],
            },

            # ── Outgoing tenant ───────────────────────────────────────────
            "outgoing_tenant": {
                "present":    bool(sub.outgoing_tenant.get("first_name")),
                "full_name":  sub.outgoing_tenant.get("full_name", ""),
                "first_name": sub.outgoing_tenant.get("first_name", ""),
                "last_name":  sub.outgoing_tenant.get("last_name", ""),
                "email":      sub.outgoing_tenant.get("email", ""),
                "phone":      sub.outgoing_tenant.get("phone", ""),
                "id_number":  sub.outgoing_tenant.get("id_number", ""),
            },

            # ── Landlord ──────────────────────────────────────────────────
            "landlord": {
                "present":    bool(sub.landlord.get("first_name")),
                "full_name":  sub.landlord.get("full_name", ""),
                "first_name": sub.landlord.get("first_name", ""),
                "last_name":  sub.landlord.get("last_name", ""),
                "email":      sub.landlord.get("email", ""),
                "phone":      sub.landlord.get("phone", ""),
                "id_number":  sub.landlord.get("id_number", ""),
            },

            # ── Future AI extension point ─────────────────────────────────
            # Downstream AI services can read this block to understand what
            # still needs to happen. No AI logic lives here yet.
            "automation_hints": {
                "ready_for_hubspot":  doc_report.is_complete,
                "missing_docs_count": len(doc_report.missing),
                "needs_follow_up":    len(doc_report.missing) > 0,
                "direction":          sub.lease.get("direction", ""),
                "move_type":          sub.customer.get("move_type", ""),
            },
        }
