"""
Comprehensive pipeline test — 5 realistic Hebrew scenarios.
Writes results to test_results/ folder so Hebrew text survives Windows console.

Run:  python test_comprehensive.py
"""
import json
import pathlib
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from app.pipeline.orchestrator import run_pipeline

OUT = pathlib.Path("test_results")
OUT.mkdir(exist_ok=True)

FORM_ID = "251955479892982"
FORM_TITLE = "העברת חשבון ארנונה"


def make_fields(**kwargs) -> dict:
    """Wrap kwargs as a rawRequest payload for the arnona form."""
    base = {
        "formID":    FORM_ID,
        "formTitle": FORM_TITLE,
    }
    # submissionID comes from multipart envelope, not rawRequest
    submission_id = kwargs.pop("_submission_id", "TEST-0000")
    raw = {**kwargs}
    return {
        **base,
        "submissionID": submission_id,
        "rawRequest": json.dumps(raw, ensure_ascii=False),
    }


def run_test(name: str, slug: str, fields: dict) -> dict:
    result = run_pipeline(
        raw_fields   = fields,
        content_type = "multipart/form-data",
        headers      = {},
    )
    data = {
        "test_name":    name,
        "timestamp":    datetime.now().isoformat(),
        "submission_id":result.submission_id,
        "service":      result.service_name,
        "is_complete":  result.is_complete,
        "missing_info": result.missing_info_labels,
        "missing_docs": result.missing_doc_labels,
        "business_summary": result.to_business_dict(),
        "email": result.email,
    }
    path = OUT / f"{slug}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [{'+' if result.is_complete else '!'}] {name}")
    print(f"       complete={result.is_complete}  "
          f"missing_info={len(result.missing_info_labels)}  "
          f"missing_docs={len(result.missing_doc_labels)}  "
          f"email={'yes' if result.email else 'no'}")
    if result.missing_info_labels:
        # Print with ascii fallback for windows console
        labels_safe = [l.encode('ascii', 'replace').decode('ascii') for l in result.missing_info_labels]
        print(f"       info missing : {labels_safe}")
    if result.missing_doc_labels:
        labels_safe = [l.encode('ascii', 'replace').decode('ascii') for l in result.missing_doc_labels]
        print(f"       docs missing : {labels_safe}")
    print(f"       saved -> {path}")
    data["slug"] = slug
    return data


import os, io
# Force UTF-8 output so Hebrew doesn't crash on Windows cp1252 console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

print("=" * 65)
print("COMPREHENSIVE PIPELINE TEST - JotForm Arnona")
print(f"Form ID: {FORM_ID}")
print("=" * 65)
print()

# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Perfect submission: רמת גן, פרטי, ארנונה, all docs present
# Based on actual submission MZK5203 from client chat
# ─────────────────────────────────────────────────────────────────────────────
print("TEST 1: Complete - Ramat Gan, arnona, private, 2 tenants")
t1 = run_test(
    name = "הגשה מלאה — שני שוכרים, ארנונה, רמת גן",
    slug = "test1_complete_ramat_gan",
    fields = make_fields(
        _submission_id = "6567166949011445919",
        # Basic
        **{"q4_cityName4":   "רמת גן",
           "q5_services5":   "ארנונה",
           "q7_moveInDate7": "09/06/2026",
           "q8_leaseEnd8":   "09/06/2028",
           "q9_transferDate9":"09/06/2026",
           "q10_personType10":"פרטי",
           "q3_moveType3":   "שכירות",
           # Main customer
           "q21_firstName21":"רן",
           "q22_lastName22": "אקל",
           "q23_phone23":    "052-353-9837",
           "q24_email24":    "ran.akal@gmail.com",
           "q25_idNumber25": "209047182",
           # Partner (second tenant from lease)
           "q104_input104":  "בנימין",
           "q235_input235":  "ליונס",
           "q103_input103":  "052-655-1151",
           "q105_email105":  "benjamin.lyons@gmail.com",
           "q106_idNumber106":"337591937",
           # Outgoing tenant
           "q30_outFirstName30":"גני",
           "q31_outLastName31": "וייסברג",
           "q33_outPhone33":    "050-400-3571",
           "q34_outEmail34":    "gani@example.com",
           "q32_outId32":       "324826833",
           # Landlord (same as outgoing for this case)
           "q40_ownerName40": "גני וייסברג",
           "q41_ownerPhone41":"050-400-3571",
           "q42_ownerEmail42":"gani@example.com",
           "q43_ownerId43":   "324826833",
           # Property
           "q50_street50":   "המעיין 6",
           "q51_building51": "6",
           "q52_apartment52":"8",
           "q53_floor53":    "2",
           # Arnona — רמת גן only needs מספר נכס (others hidden by JotForm logic)
           "q60_arnonaProperty60":"016755951",
           # Docs
           "q80_idPhoto80":       "https://jotform.com/uploads/id_photo.jpg",
           "q81_arnonaBill81":    "https://jotform.com/uploads/arnona_bill.pdf",
           "q82_leaseContract82": "https://jotform.com/uploads/lease_contract.pdf",
           "q83_signature83":     "https://jotform.com/uploads/signature.png",
           "q87_terms87":         "accepted",
           # Payment
           "q90_amount90":  "149",
           # System
           "q100_mzkId100": "MZK5203",
           "q101_refundId101":"MZKR0303",
        }
    ),
)
print()

# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Partial: missing partner ID, missing arnona bill
# Real scenario: tenant filled everything except second tenant's ID
# ─────────────────────────────────────────────────────────────────────────────
print("TEST 2: Partial - missing partner ID + missing arnona bill")
t2 = run_test(
    name = "הגשה חלקית — ת.ז שוכר שני וחשבון ארנונה חסרים",
    slug = "test2_partial_missing",
    fields = make_fields(
        _submission_id = "6567546758414115472",
        **{"q4_cityName4":   "רמת גן",
           "q5_services5":   "ארנונה",
           "q7_moveInDate7": "26/04/2026",
           "q8_leaseEnd8":   "26/04/2027",
           "q10_personType10":"פרטי",
           # Main customer
           "q21_firstName21":"אושרי",
           "q22_lastName22": "מנדלאוי",
           "q23_phone23":    "052-662-4784",
           "q24_email24":    "oshri9281mandelawi@gmail.com",
           "q25_idNumber25": "209360957",
           # Partner present BUT no ID number
           "q104_input104":  "אורי",
           "q235_input235":  "איצקוביץ",
           "q103_input103":  "050-241-0006",
           "q105_email105":  "oriitz29@gmail.com",
           # NO q106_idNumber106 — this should be flagged
           # Outgoing tenant
           "q30_outFirstName30":"יונתן",
           "q31_outLastName31": "שלו",
           "q33_outPhone33":    "058-437-6543",
           "q32_outId32":       "324826833",
           # Landlord
           "q40_ownerName40": "יונתן שלו",
           "q41_ownerPhone41":"058-437-6543",
           "q42_ownerEmail42":"liatslv63@gmail.com",
           # Property
           "q50_street50":   "פרוג 3",
           "q52_apartment52":"10",
           "q51_building51": "3",
           "q53_floor53":    "3",
           # Arnona
           "q60_arnonaProperty60":"1160003110000",
           # Docs — arnona bill is MISSING
           "q80_idPhoto80":       "https://jotform.com/uploads/id.jpg",
           # NO q81_arnonaBill81
           "q82_leaseContract82": "https://jotform.com/uploads/lease.pdf",
           "q83_signature83":     "https://jotform.com/uploads/sig.png",
           # Payment
           "q90_amount90":  "199",
           "q100_mzkId100": "MZK6848",
        }
    ),
)
print()

# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Tel Aviv: different city, more arnona fields required
# In תל אביב the fields that are hidden for רמת גן are VISIBLE and required
# ─────────────────────────────────────────────────────────────────────────────
print("TEST 3: Tel Aviv - more arnona fields required (not hidden)")
t3 = run_test(
    name = "הגשה — תל אביב, ארנונה, שדות נוספים נדרשים",
    slug = "test3_tel_aviv_arnona",
    fields = make_fields(
        _submission_id = "9901234567890123456",
        **{"q4_cityName4":   "תל אביב",
           "q5_services5":   "ארנונה",
           "q7_moveInDate7": "01/07/2026",
           "q8_leaseEnd8":   "01/07/2027",
           "q10_personType10":"פרטי",
           # Customer
           "q21_firstName21":"דנה",
           "q22_lastName22": "לוי",
           "q23_phone23":    "054-321-9876",
           "q24_email24":    "dana.levi@gmail.com",
           "q25_idNumber25": "312456789",
           # No partner
           # Landlord
           "q40_ownerName40": "משה כהן",
           "q41_ownerPhone41":"050-111-2233",
           # Property
           "q50_street50":   "דיזנגוף 100",
           "q52_apartment52":"5",
           "q53_floor53":    "4",
           # Arnona — Tel Aviv shows all fields
           # Only מספר נכס filled, others missing → should flag them
           "q60_arnonaProperty60":"987654321",
           # NO q61_arnonaCust61, NO q62_arnonaId62 — should be flagged for TA
           # Docs
           "q80_idPhoto80":       "https://jotform.com/uploads/id.jpg",
           "q82_leaseContract82": "https://jotform.com/uploads/lease.pdf",
           "q83_signature83":     "https://jotform.com/uploads/sig.png",
           # Payment
           "q90_amount90":  "149",
           "q100_mzkId100": "MZK9901",
        }
    ),
)
print()

# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Company (חברה): needs corporate docs instead of personal ID
# ─────────────────────────────────────────────────────────────────────────────
print("TEST 4: Company type - needs corp cert + tabu, not personal ID")
t4 = run_test(
    name = "הגשת חברה — מסמכי חברה נדרשים",
    slug = "test4_company",
    fields = make_fields(
        _submission_id = "7712345678901234567",
        **{"q4_cityName4":   "ירושלים",
           "q5_services5":   "ארנונה",
           "q7_moveInDate7": "01/08/2026",
           "q10_personType10":"חברה",   # ← company type
           # Company rep
           "q21_firstName21":"יוסי",
           "q22_lastName22": "ישראלי",
           "q23_phone23":    "02-123-4567",
           "q24_email24":    "yossi@company.co.il",
           # Landlord
           "q40_ownerName40": "עיריית ירושלים",
           "q41_ownerPhone41":"02-629-2929",
           # Property
           "q50_street50":   "יפו 1",
           "q52_apartment52":"101",
           # Arnona
           "q60_arnonaProperty60":"JER-123456",
           "q61_arnonaCust61":    "CUST-789",
           # Docs — has ID photo but NOT corp cert or tabu (company type requires these)
           "q80_idPhoto80":       "https://jotform.com/uploads/id.jpg",
           "q82_leaseContract82": "https://jotform.com/uploads/lease.pdf",
           "q83_signature83":     "https://jotform.com/uploads/sig.png",
           # NO corp cert, NO tabu
           # Payment
           "q90_amount90":  "249",
           "q100_mzkId100": "MZK7712",
        }
    ),
)
print()

# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Multiple services: ארנונה + חשמל + מים, חיפה
# ─────────────────────────────────────────────────────────────────────────────
print("TEST 5: Multi-service - arnona + electricity + water, Haifa")
t5 = run_test(
    name = "מולטי-שירות — ארנונה, חשמל, מים, חיפה",
    slug = "test5_multi_service_haifa",
    fields = make_fields(
        _submission_id = "8823456789012345678",
        **{"q4_cityName4":   "חיפה",
           "q5_services5":   "ארנונה,חשמל,מים",
           "q7_moveInDate7": "15/07/2026",
           "q8_leaseEnd8":   "15/07/2028",
           "q6_moveOutDate6":"14/07/2026",
           "q10_personType10":"פרטי",
           "q3_moveType3":   "שכירות",
           # Customer
           "q21_firstName21":"מיכל",
           "q22_lastName22": "אברהם",
           "q23_phone23":    "050-987-6543",
           "q24_email24":    "michal.av@gmail.com",
           "q25_idNumber25": "456789123",
           # Outgoing
           "q30_outFirstName30":"שלמה",
           "q31_outLastName31": "גולדברג",
           "q33_outPhone33":    "053-111-2222",
           "q32_outId32":       "111222333",
           # Landlord
           "q40_ownerName40": "רחל גרין",
           "q41_ownerPhone41":"054-444-5555",
           "q42_ownerEmail42":"rachel.green@example.com",
           # Property
           "q50_street50":   "הנביאים 45",
           "q52_apartment52":"3",
           "q53_floor53":    "1",
           "q54_entrance54": "ב",
           # Arnona — Haifa: fields NOT hidden, all should be checked
           "q60_arnonaProperty60":"HFA-001122",
           "q61_arnonaCust61":    "C-445566",
           # Water
           "q70_waterProperty70": "W-001122",
           "q71_waterCust71":     "WC-445566",
           # Docs — full set
           "q80_idPhoto80":       "https://jotform.com/uploads/id.jpg",
           "q81_arnonaBill81":    "https://jotform.com/uploads/arnona.pdf",
           "q82_leaseContract82": "https://jotform.com/uploads/lease.pdf",
           "q83_signature83":     "https://jotform.com/uploads/sig.png",
           # Payment
           "q90_amount90":  "349",
           "q91_serviceName91":"ארנונה + חשמל + מים",
           "q100_mzkId100": "MZK8823",
        }
    ),
)
print()

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 65)
print("RESULTS SUMMARY")
print("=" * 65)
tests = [t1, t2, t3, t4, t5]
for t in tests:
    status = "COMPLETE" if t["is_complete"] else f"INCOMPLETE ({len(t['missing_info'])} info, {len(t['missing_docs'])} docs)"
    print(f"  {t['slug'] if 'slug' in t else t['test_name'][:50]}")
    print(f"  Status: {status}")
    if t["missing_info"]:
        safe = [l.encode('ascii','replace').decode('ascii') for l in t['missing_info']]
        print(f"  Missing info: {safe}")
    if t["missing_docs"]:
        safe = [l.encode('ascii','replace').decode('ascii') for l in t['missing_docs']]
        print(f"  Missing docs: {safe}")
    print()

print(f"All test outputs saved to: {OUT.resolve()}")
print()
print("Open each JSON file to see the full Hebrew output.")
print("Key files:")
for f in sorted(OUT.glob("*.json")):
    print(f"  {f.name}")
