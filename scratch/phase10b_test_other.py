import sys
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding='utf-8')
from app.pipeline.reconciliation_merge import FilenameClassifier
clf = FilenameClassifier()
missed_others = [
    "נטליה_חתום_הסכם_שכירות_2026_אלנבי_166.pdf",
    "צילום_חשבון_גז.pdf",
    "אישור_עירייה_לטאבו_28229.pdf",
    "חוזה_מכירה_חתום.pdf",
    "crft.png",
    "тз.pdf",
    "дог.pdf",
    "лрг.pdf",
    "הסכם רכישה חתום.pdf",
    "חשמל מידטאון.jpeg",
    "תעודת זהות שירלי מידטאון.jpeg",
    "חוזה שכירותמידטאון.jpeg",
    "IMG-20260326-WA0005.jpg",
    "IMG-20260531-WA0011.jpg",
    "photo_5251426736270941603_w.jpg",
    "Скан_20260602 (2).png",
    "IMG20260601171301.jpg",
    "pending-1780919657-IMG20260601145417.jpg",
]
for fn in missed_others:
    r = clf.classify(f"data/{fn}")
    status = "AUTO" if r["confidence"] >= 0.90 else "MISS"
    dt = r["document_type"] or "(none)"
    print(f"  [{status}] {r['confidence']:.2f}  {dt:25}  {fn}")
