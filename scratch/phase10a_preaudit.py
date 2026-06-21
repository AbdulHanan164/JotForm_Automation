"""
Phase 10A Pre-Audit: Test ACTUAL FilenameClassifier against Phase 9D filenames.
Shows which files really are classified vs. which truly fail.
"""
import sys
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from app.pipeline.reconciliation_merge import FilenameClassifier

clf = FilenameClassifier()

# All 75 files from Phase 9D, paired with their pair context
FILES = [
    # Pair 1 - אריק שמש
    ("6574271317125403787", "WhatsApp_Image_2026-06-16_at_16.29.27.jpeg"),
    ("6574271317125403787", "WhatsApp_Image_2026-06-16_at_16.29.02.jpeg"),
    ("6574271317125403787", "WhatsApp_Image_2026-06-16_at_16.31.10.jpeg"),
    ("6574271317125403787", "WhatsApp_Image_2026-06-16_at_16.51.28.jpeg"),
    # Pair 2 - נטליה חתונצב
    ("6573577625768407601", "נטליה_חתון_חוזה_שכירות_2026_שלוה_166.pdf"),
    ("6573577625768407601", "WhatsApp_Image_2026-06-10_at_13.18.46.jpeg"),
    ("6573577625768407601", "WhatsApp_Image_2026-06-10_at_13.18.46_(2).jpeg"),
    # Pair 3 - אלי משה נבו (1)
    ("6573196609414366217", "צילום_חשבון_ארנונה.pdf"),
    # Pair 4 - אלי משה נבו (2)
    ("6573193309416613553", "נסח_טאבו_לגיא_28229.pdf"),
    ("6573193309416613553", "חוזה_שכירות_חתום.pdf"),
    # Pair 5 - ליאת הניג בליצבלאו
    ("6572688775303926395", "WhatsApp_Image_2026-06-03_at_17.42.19_(1).jpeg"),
    ("6572688775303926395", "WhatsApp_Image_2026-06-03_at_17.42.19_(2).jpeg"),
    ("6572688775303926395", "WhatsApp_Image_2026-06-03_at_17.42.19_(3).jpeg"),
    ("6572688775303926395", "WhatsApp_Image_2026-06-03_at_17.42.19_(4).jpeg"),
    ("6572688775303926395", "WhatsApp_Image_2026-06-03_at_17.42.19_(5).jpeg"),
    ("6572688775303926395", "WhatsApp_Image_2026-06-03_at_17.42.19_(6).jpeg"),
    ("6572688775303926395", "WhatsApp_Image_2026-06-03_at_17.42.19.jpeg"),
    # Pair 6 - אזמט אוסמונוב
    ("6569852209518748333", "8def5d98-f521-4526-af4e-d6818c8155ad.jpeg"),
    ("6569852209518748333", "c99f90a1-012f-483b-b396-566261754e7f.jpeg"),
    ("6569852209518748333", "IMG_8350.png"),
    ("6569852209518748333", "IMG_8325.jpeg"),
    ("6569852209518748333", "IMG_8315.jpeg"),
    ("6569852209518748333", "IMG_8317.jpeg"),
    ("6569852209518748333", "IMG_8316.jpeg"),
    ("6569852209518748333", "IMG_8318.jpeg"),
    ("6569852209518748333", "IMG_8320.jpeg"),
    ("6569852209518748333", "IMG_8319.jpeg"),
    ("6569852209518748333", "IMG_8321.jpeg"),
    ("6569852209518748333", "IMG_8322.jpeg"),
    ("6569852209518748333", "IMG_8323.jpeg"),
    ("6569852209518748333", "IMG_8324.jpeg"),
    # Pair 7 - יורי פולבוי
    ("6562335640111332794", "WhatsApp_Image_2026-05-21_at_17.15.57.jpeg"),
    ("6562335640111332794", "WhatsApp_Image_2026-05-21_at_17.15.56.jpeg"),
    ("6562335640111332794", "WhatsApp_Image_2026-05-21_at_17.15.58.jpeg"),
    # Pair 8 - ליאור סיבוני
    ("6562302400428019091", "Screenshot_2026-05-21-14-53-29-667_WhatsApp.jpg"),
    ("6562302400428019091", "Screenshot_2026-05-21-14-53-22-001_WhatsApp.jpg"),
    ("6562302400428019091", "Screenshot_2026-05-21-14-53-10-025_WhatsApp.jpg"),
    # Pair 9 - אסיה אורלוב
    ("6560564243521410541", "Screenshot_20260531_101207_WhatsApp.jpg"),
    ("6560564243521410541", "Screenshot_20260531_101117_Gallery.jpg"),
    ("6560564243521410541", "Screenshot_20260531_101133_Gallery.jpg"),
    ("6560564243521410541", "Screenshot_20260531_101146_Gallery.jpg"),
    ("6560564243521410541", "Screenshot_20260531_101159_Gallery.jpg"),
    ("6560564243521410541", "Screenshot_20260531_101207_WhatsApp (1).jpg"),
    ("6560564243521410541", "Screenshot_20260531_101207_WhatsApp (2).jpg"),
    # Pair 10+11 - שירלי חדד שחר
    ("6560440298424628961", "WhatsApp_Image_2026-05-31_at_09.39.41.jpeg"),
    ("6560440298424628961", "WhatsApp_Image_2026-05-31_at_09.39.41_(2).jpeg"),
    ("6560438768425161076", "WhatsApp_Image_2026-05-31_at_09.39.41_(3).jpeg"),
    ("6560438768425161076", "WhatsApp_Image_2026-05-31_at_09.39.41_(4).jpeg"),
    ("6560438768425161076", "WhatsApp_Image_2026-05-31_at_09.38.56.jpeg"),
    # Pair 12 - אסף אבידן
    ("6560253951019669426", "WhatsApp_Image_2026-05-29_at_22.56.49.jpeg"),
    ("6560253951019669426", "WhatsApp_Image_2026-05-29_at_22.56.49_(2).jpeg"),
    ("6560253951019669426", "WhatsApp_Image_2026-05-29_at_22.57.28.jpeg"),
    ("6560253951019669426", "WhatsApp_Image_2026-05-29_at_22.59.29.jpeg"),
    # Pair 13 - נהוראי לוי
    ("6560209135285340330", "WhatsApp_Image_2026-05-31_at_15.32.32.jpeg"),
    ("6560209135285340330", "WhatsApp_Image_2026-05-31_at_15.32.35.jpeg"),
    ("6560209135285340330", "WhatsApp_Image_2026-05-31_at_15.40.01.jpeg"),
    ("6560209135285340330", "WhatsApp_Image_2026-05-31_at_15.40.07.jpeg"),
    # Pair 14 - יוחנן יוהן לאופולד
    ("6557564914027438043", "תז וספח JGL.jpg"),
    ("6557564914027438043", "רותי ויץ לאופולד תז 2024.pdf"),
    ("6557564914027438043", "נדב כהן תז וספח.jpg"),
    ("6557564914027438043", "סיום שכירות יואב 18.pdf"),
    ("6557564914027438043", "קריאת מונה מים יואב 18.jpeg"),
    ("6557564914027438043", "קריאת מונה חשמל יואב 18.jpeg"),
]

print(f"{'#':>3}  {'Filename':<52}  {'Type':<16}  {'Conf':>5}  Reason")
print("-" * 110)

resolved = 0
unresolved = 0
partial = []   # matched but < 0.90

for i, (sub_id, filename) in enumerate(FILES, 1):
    fake_path = f"data/missing_docs_submissions/{sub_id}/{filename}"
    result = clf.classify(fake_path)
    conf = result["confidence"]
    dtype = result["document_type"] or "(none)"
    
    status = "✅ AUTO" if conf >= 0.90 else ("⚡ PARTIAL" if conf > 0 else "❌ MISS")
    
    if conf >= 0.90:
        resolved += 1
    else:
        unresolved += 1
        if conf > 0:
            partial.append((filename, dtype, conf))
    
    short_name = filename[:50]
    print(f"{i:>3}  {short_name:<52}  {dtype:<16}  {conf:>5.2f}  {status}")

print()
print(f"Auto-resolved (≥0.90) : {resolved} / {len(FILES)}")
print(f"Unresolved            : {unresolved} / {len(FILES)}")
print(f"Partial (0<conf<0.90) : {len(partial)}")
print()
if partial:
    print("Partial matches (these expose where threshold or patterns need tuning):")
    for fn, dt, cf in partial:
        print(f"  {fn}  →  {dt}  @ {cf:.2f}")
