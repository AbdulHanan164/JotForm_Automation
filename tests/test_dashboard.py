"""
Operator dashboard (/dashboard) — server-rendered HTML, cookie auth that
reuses OPERATOR_API_KEY. Uses only the existing review queue.
"""
from __future__ import annotations

import pytest

from app.review.models import ReviewItem, ReviewStatus
from app.review import queue as Q

KEY = "test-key-12345"  # matches auth_client fixture's OPERATOR_API_KEY


def _seed(submission_id="dash-1", status=ReviewStatus.PENDING_REVIEW, errors=False):
    vi = [{"severity": "error", "label": "בעיה"}] if errors else []
    item = ReviewItem(
        submission_id=submission_id, service_name="arnona_transfer",
        form_title="NEW MAIN FORM", received_at="2026-06-18T10:00:00",
        customer_name="אריק שמש", customer_phone="0544485914",
        property_address="הינץ כהן 6, חולון", services="מים, ארנונה", mzk_ref="MZK6853",
        status=status,
        summary={"מסמכים": {"תעודת_זהות": "❌"}},
        business_data={"incoming_tenant": {"full_name": "אריק שמש", "phone": "0544485914",
                                           "email": "a@b.com", "id_number": "039541446"},
                       "property": {"full_address": "הינץ כהן 6, חולון", "city": "חולון"},
                       "dates": {"move_in": "01-06-2026", "lease_end": "31-05-2027"}},
        missing_info=[{"label": "מספר זיהוי נכס", "reason": "מופיע בחשבון"}],
        missing_docs=[{"label": "תעודת זהות", "reason": "אימות זהות"}],
        validation_issues=vi,
        draft_email={"subject": "השלמת פרטים", "body": "שלום אריק,\nחסרים פרטים."},
    )
    Q.save(item)
    return submission_id


class TestDashboardAuth:
    def test_login_page_public(self, auth_client):
        r = auth_client.get("/dashboard/login")
        assert r.status_code == 200
        assert "כניסת מפעיל" in r.text

    def test_dashboard_redirects_without_cookie(self, auth_client):
        r = auth_client.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/dashboard/login"

    def test_login_wrong_key_rejected(self, auth_client):
        r = auth_client.post("/dashboard/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert r.status_code == 401

    def test_login_correct_key_sets_cookie(self, auth_client):
        r = auth_client.post("/dashboard/login", data={"api_key": KEY}, follow_redirects=False)
        assert r.status_code == 303
        assert "dash_key" in r.headers.get("set-cookie", "")


class TestDashboardPages:
    def test_list_shows_seeded_item(self, auth_client, tmp_dirs):
        _seed("dash-list-1")
        auth_client.cookies.set("dash_key", KEY)
        r = auth_client.get("/dashboard")
        assert r.status_code == 200
        assert "MZK6853" in r.text
        assert "אריק שמש" in r.text
        assert "ממתין לבדיקה" in r.text  # status badge

    def test_search_filter(self, auth_client, tmp_dirs):
        _seed("dash-search-1")
        auth_client.cookies.set("dash_key", KEY)
        assert "אריק שמש" in auth_client.get("/dashboard?q=אריק").text
        assert "אריק שמש" not in auth_client.get("/dashboard?q=זזזזז").text

    def test_detail_page(self, auth_client, tmp_dirs):
        sid = _seed("dash-detail-1")
        auth_client.cookies.set("dash_key", KEY)
        r = auth_client.get(f"/dashboard/review/{sid}")
        assert r.status_code == 200
        assert "פרטי לקוח" in r.text
        assert "039541446" in r.text          # ID number
        assert "השלמת פרטים" in r.text         # email subject preview
        assert "מספר זיהוי נכס" in r.text       # missing info

    def test_detail_404(self, auth_client, tmp_dirs):
        auth_client.cookies.set("dash_key", KEY)
        assert auth_client.get("/dashboard/review/nope").status_code == 404


class TestDashboardActions:
    def test_approve(self, auth_client, tmp_dirs):
        sid = _seed("dash-approve-1")
        auth_client.cookies.set("dash_key", KEY)
        r = auth_client.post(f"/dashboard/review/{sid}/approve", data={}, follow_redirects=False)
        assert r.status_code == 303
        assert Q.load(sid).status == ReviewStatus.APPROVED

    def test_approve_blocked_on_errors(self, auth_client, tmp_dirs):
        sid = _seed("dash-err-1", errors=True)
        auth_client.cookies.set("dash_key", KEY)
        auth_client.post(f"/dashboard/review/{sid}/approve", data={}, follow_redirects=False)
        assert Q.load(sid).status == ReviewStatus.PENDING_REVIEW  # not approved

    def test_approve_override_errors(self, auth_client, tmp_dirs):
        sid = _seed("dash-err-2", errors=True)
        auth_client.cookies.set("dash_key", KEY)
        auth_client.post(f"/dashboard/review/{sid}/approve",
                         data={"override_errors": "1", "notes": "ok"}, follow_redirects=False)
        assert Q.load(sid).status == ReviewStatus.APPROVED

    def test_reject_requires_reason(self, auth_client, tmp_dirs):
        sid = _seed("dash-rej-1")
        auth_client.cookies.set("dash_key", KEY)
        auth_client.post(f"/dashboard/review/{sid}/reject", data={"reason": "מסמכים שגויים"}, follow_redirects=False)
        assert Q.load(sid).status == ReviewStatus.REJECTED

    def test_needs_info(self, auth_client, tmp_dirs):
        sid = _seed("dash-ni-1")
        auth_client.cookies.set("dash_key", KEY)
        auth_client.post(f"/dashboard/review/{sid}/needs_info", data={"notes": "חסר חוזה"}, follow_redirects=False)
        assert Q.load(sid).status == ReviewStatus.NEEDS_INFO

    def test_document_404_when_absent(self, auth_client, tmp_dirs):
        auth_client.cookies.set("dash_key", KEY)
        assert auth_client.get("/dashboard/documents/nope/x.png").status_code == 404
