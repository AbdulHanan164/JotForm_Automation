import logging
import re
from typing import Any

logger = logging.getLogger("webhook.reconciliation")

class MissingDocsReconciler:
    """
    Engine to match original Arnona submissions with Missing Documents form submissions.
    """

    @staticmethod
    def normalize_id(val: Any) -> str:
        """
        Normalize ID/Company number: strip non-digits and pad to 9 digits with leading zeros.
        Returns empty string if invalid/empty.
        """
        if not val:
            return ""
        digits = "".join(c for c in str(val) if c.isdigit())
        if not digits:
            return ""
        return digits.zfill(9)

    @staticmethod
    def normalize_phone(val: Any) -> str:
        """
        Normalize phone: strip spaces, dashes, parentheses, +972 prefix, and leading 0.
        Returns empty string if invalid/empty.
        """
        if not val:
            return ""
        # Remove non-digits
        digits = "".join(c for c in str(val) if c.isdigit())
        if not digits:
            return ""
        # Remove country code if present (972)
        if digits.startswith("972"):
            digits = digits[3:]
        # Remove leading zero
        if digits.startswith("0"):
            digits = digits[1:]
        return digits

    @staticmethod
    def normalize_mzk(val: Any) -> str:
        """
        Extract only digits from the MZK reference (e.g. 'MZK5207' -> '5207').
        """
        if not val:
            return ""
        digits = "".join(c for c in str(val) if c.isdigit())
        return digits

    @staticmethod
    def normalize_name(val: Any) -> str:
        """
        Normalize name: lowercase, strip extra whitespace.
        """
        if not val:
            return ""
        return " ".join(str(val).lower().split())

    def match_submission(self, original: dict[str, Any], missing_subs: list[dict]) -> list[dict]:
        """
        Matches an original Arnona submission (as raw parsed dict, raw JotForm API dict, or PipelineResult)
        against a list of Missing Documents Form submissions.
        
        Returns a list of matches, each as:
        {
            "matched_submission": dict,  # missing-docs submission dict
            "confidence": float,
            "reason": str
        }
        """
        # Extract identities from the original submission
        answers = original.get("answers")
        if answers and isinstance(answers, dict):
            # Extract from raw JotForm API structure
            orig_mzk_raw = answers.get("184", {}).get("answer") or answers.get("291", {}).get("answer")
            orig_id_raw = answers.get("32", {}).get("answer")
            orig_email = (answers.get("30", {}).get("answer") or "").lower().strip()
            orig_phone = self.normalize_phone(answers.get("208", {}).get("answer"))
            orig_first = answers.get("21", {}).get("answer") or ""
            orig_last = answers.get("20", {}).get("answer") or ""
            orig_fullname = self.normalize_name(f"{orig_first} {orig_last}")
            
            # Check other IDs in answers (e.g. related fields like outgoing tenant ID etc. if mapped)
            other_ids = set()
            for qid_key, ans_dict in answers.items():
                if qid_key != "32" and isinstance(ans_dict, dict) and "ת" in (ans_dict.get("text") or ""):
                    oid = self.normalize_id(ans_dict.get("answer"))
                    if oid:
                        other_ids.add(oid)
        else:
            # Extract from parsed result or business submission
            bd = original.get("business_data") or original.get("_business") or original
            orig_mzk_raw = original.get("mzk_ref")
            if not orig_mzk_raw:
                orig_mzk_raw = (original.get("parsed") or {}).get("system", {}).get("מזהה_מזכ")
            if not orig_mzk_raw:
                orig_mzk_raw = original.get("summary", {}).get("מידע_פנימי", {}).get("מספר_פנייה")
                
            incoming = bd.get("incoming_tenant") or bd.get("customer") or {}
            orig_id_raw = incoming.get("id_number") or original.get("parsed", {}).get("customer", {}).get("תעודת_זהות")
            orig_email = (incoming.get("email") or original.get("parsed", {}).get("customer", {}).get("אימייל") or "").lower().strip()
            orig_phone = self.normalize_phone(incoming.get("phone") or original.get("parsed", {}).get("customer", {}).get("טלפון"))
            orig_first = incoming.get("first_name") or original.get("parsed", {}).get("customer", {}).get("שם_פרטי") or ""
            orig_last = incoming.get("last_name") or original.get("parsed", {}).get("customer", {}).get("שם_משפחה") or ""
            orig_fullname = self.normalize_name(incoming.get("full_name") or f"{orig_first} {orig_last}")
            
            other_ids = set()
            for role in ["partner", "outgoing_tenant", "landlord"]:
                role_data = bd.get(role) or {}
                rid = self.normalize_id(role_data.get("id_number"))
                if rid:
                    other_ids.add(rid)

        orig_mzk = self.normalize_mzk(orig_mzk_raw)
        orig_id = self.normalize_id(orig_id_raw)
        
        matches = []
        for sub in missing_subs:
            answers = sub.get("answers", {})
            
            # Extract Missing-Docs info
            sub_mzk_raw = answers.get("184", {}).get("answer") or answers.get("291", {}).get("answer")
            sub_mzk = self.normalize_mzk(sub_mzk_raw)
            
            sub_id_raw = answers.get("32", {}).get("answer")
            sub_id = self.normalize_id(sub_id_raw)
            
            sub_email = (answers.get("30", {}).get("answer") or "").lower().strip()
            sub_phone = self.normalize_phone(answers.get("208", {}).get("answer"))
            
            sub_first = answers.get("21", {}).get("answer") or ""
            sub_last = answers.get("20", {}).get("answer") or ""
            sub_fullname = self.normalize_name(f"{sub_first} {sub_last}")
            
            matched = False
            confidence = 0.0
            reason = ""
            
            # Match 1: MZK Reference (Priority 1, Conf = 1.0)
            if orig_mzk and sub_mzk and orig_mzk == sub_mzk:
                matched = True
                confidence = 1.0
                reason = f"MZK Reference Match ({orig_mzk_raw} == {sub_mzk_raw})"
            
            # Match 2: ID + Email (Priority 3, Conf = 0.95)
            elif orig_id and sub_id and orig_id == sub_id and orig_email and sub_email and orig_email == sub_email:
                matched = True
                confidence = 0.95
                reason = f"ID + Email Match (ID: {orig_id_raw}, Email: {orig_email})"
                
            # Match 3: ID + Phone (Priority 4, Conf = 0.95)
            elif orig_id and sub_id and orig_id == sub_id and orig_phone and sub_phone and orig_phone == sub_phone:
                matched = True
                confidence = 0.95
                reason = f"ID + Phone Match (ID: {orig_id_raw}, Phone: {orig_phone})"
                
            # Match 4: ID Match (Priority 2, Conf = 0.9)
            elif orig_id and sub_id and orig_id == sub_id:
                matched = True
                confidence = 0.9
                reason = f"ID Match ({orig_id_raw})"
            elif sub_id and sub_id in other_ids:
                matched = True
                confidence = 0.9
                reason = f"ID Match with related entity ({sub_id_raw})"
                
            # Match 5: Email + Phone (Priority 5, Conf = 0.8)
            elif orig_email and sub_email and orig_email == sub_email and orig_phone and sub_phone and orig_phone == sub_phone:
                matched = True
                confidence = 0.8
                reason = f"Email + Phone Match (Email: {orig_email}, Phone: {orig_phone})"
                
            if matched:
                matches.append({
                    "matched_submission": sub,
                    "confidence": confidence,
                    "reason": reason,
                    "sub_fullname": sub_fullname
                })
        
        # Tie-breaker using Full Name if multiple matches exist
        if len(matches) > 1 and orig_fullname:
            # Check if any match has a matching normalized name
            name_matches = []
            for m in matches:
                # Check if original name is a substring or close match to missing doc name
                sub_fullname = m["sub_fullname"]
                if orig_fullname in sub_fullname or sub_fullname in orig_fullname:
                    name_matches.append(m)
                    
            if name_matches:
                # Keep only name-matching ones, or mark them with a flag/higher priority
                # If only one matches name, we can select it. If not, we keep all but log the tie-break
                logger.info("Tie-breaker resolved %d matches to %d matches using name: %s", len(matches), len(name_matches), orig_fullname)
                matches = name_matches
                
        # Clean up transient fields
        for m in matches:
            m.pop("sub_fullname", None)
            
        # Sort matches by confidence descending
        matches.sort(key=lambda x: x["confidence"], reverse=True)
        return matches
