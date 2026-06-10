/**
 * Generates sample_operator_summary.docx — operator-facing summary for client review.
 * Based on real submission MZK6852 (אבנר שבו, 09/06/2026).
 * Run: node scripts/generate_summary_docx.js
 */
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign, HeadingLevel, PageNumber,
} = require("docx");
const fs = require("fs");
const path = require("path");

// ── Color palette ─────────────────────────────────────────────────────────────
const BLUE_HEADER  = "1E4D8C";
const BLUE_LIGHT   = "D5E8F0";
const GREY_ROW     = "F5F5F5";
const WHITE        = "FFFFFF";
const RED_TEXT     = "C00000";
const GREEN_TEXT   = "207020";
const ORANGE_TEXT  = "B45309";

const CONTENT_WIDTH = 9360; // US Letter - 1" margins each side
const COL1 = 2800;
const COL2 = CONTENT_WIDTH - COL1;

// ── Helpers ───────────────────────────────────────────────────────────────────
function border(color = "CCCCCC") {
  const b = { style: BorderStyle.SINGLE, size: 1, color };
  return { top: b, bottom: b, left: b, right: b };
}

function headerCell(text, colspan) {
  return new TableCell({
    columnSpan: colspan,
    borders: border(BLUE_HEADER),
    shading: { fill: BLUE_HEADER, type: ShadingType.CLEAR },
    margins: { top: 100, bottom: 100, left: 160, right: 160 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text, bold: true, color: WHITE, size: 22, font: "Arial" })],
    })],
  });
}

function labelCell(text, shade = false) {
  return new TableCell({
    width: { size: COL1, type: WidthType.DXA },
    borders: border(),
    shading: { fill: shade ? GREY_ROW : WHITE, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text, bold: true, size: 20, font: "Arial" })],
    })],
  });
}

function valueCell(text, shade = false, options = {}) {
  const color = options.red ? RED_TEXT : options.green ? GREEN_TEXT : options.orange ? ORANGE_TEXT : undefined;
  return new TableCell({
    width: { size: COL2, type: WidthType.DXA },
    borders: border(),
    shading: { fill: shade ? GREY_ROW : WHITE, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text, size: 20, font: "Arial", ...(color ? { color } : {}) })],
    })],
  });
}

function row(label, value, shade = false, valueOptions = {}) {
  return new TableRow({
    children: [labelCell(label, shade), valueCell(value, shade, valueOptions)],
  });
}

function sectionTable(title, rows) {
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [COL1, COL2],
    rows: [
      new TableRow({ children: [headerCell(title, 2)] }),
      ...rows,
    ],
  });
}

function spacer() {
  return new Paragraph({ children: [new TextRun({ text: "", size: 16 })] });
}

function statusRow(label, status, shade = false) {
  const isOk      = status.includes("✅");
  const isMissing = status.includes("❌");
  const isWarn    = status.includes("⚠️");
  return new TableRow({
    children: [
      labelCell(label, shade),
      new TableCell({
        width: { size: COL2, type: WidthType.DXA },
        borders: border(),
        shading: { fill: shade ? GREY_ROW : WHITE, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [new TextRun({
            text: status, size: 20, font: "Arial",
            color: isOk ? GREEN_TEXT : isMissing ? RED_TEXT : isWarn ? ORANGE_TEXT : undefined,
          })],
        })],
      }),
    ],
  });
}

// ── Document sections ─────────────────────────────────────────────────────────
function buildDoc() {
  const children = [];

  // Title block
  children.push(new Paragraph({
    alignment: AlignmentType.RIGHT,
    spacing: { before: 0, after: 120 },
    children: [new TextRun({ text: "סיכום בקשה — מה זה קל", bold: true, size: 36, font: "Arial", color: BLUE_HEADER })],
  }));
  children.push(new Paragraph({
    alignment: AlignmentType.RIGHT,
    spacing: { before: 0, after: 60 },
    children: [new TextRun({ text: "פנייה MZK6852  |  09/06/2026  |  שם לקוח: אבנר שבו", size: 22, font: "Arial" })],
  }));
  children.push(new Paragraph({
    alignment: AlignmentType.RIGHT,
    spacing: { before: 0, after: 240 },
    children: [new TextRun({ text: "⚠️  סטטוס: ממתין להשלמת מסמכים", bold: true, size: 24, font: "Arial", color: ORANGE_TEXT })],
  }));

  // 1. מידע על העסקה
  children.push(sectionTable("1. מידע על העסקה", [
    row("סוג עסקה",        "כניסה — מתחיל שכירות",                       false),
    row("חבילת שירות",     "כניסה — רישום כמשלם עד 2 חשבונות",           true),
    row("עיר",             "חולון",                                        false),
    row("סוג לקוח",        "אדם פרטי",                                    true),
    row("סוג תשלום",       "משלם יחיד",                                   false),
  ]));
  children.push(spacer());

  // 2. שירותים מבוקשים
  children.push(sectionTable("2. שירותים מבוקשים", [
    statusRow("ארנונה — מיסי עירייה", "✅ נבחר",  false),
    statusRow("מים",                   "✅ נבחר",  true),
    statusRow("חשמל",                  "✅ נבחר",  false),
    statusRow("גז",                    "לא נבחר",  true),
    statusRow("ועד בית",               "לא נבחר",  false),
  ]));
  children.push(spacer());

  // 3. פרטי הנכס
  children.push(sectionTable("3. פרטי הנכס", [
    row("כתובת מלאה",   "צבי תדמור 8 דירה 42, חולון",  false),
    row("עיר",          "חולון",                          true),
    row("רחוב",         "צבי תדמור",                     false),
    row("מספר בניין",   "8",                              true),
    row("דירה",         "42",                             false),
    row("קומה",         "לא סופק",                       true),
    row("כניסה",        "לא סופק",                       false),
  ]));
  children.push(spacer());

  // 4. תאריכים
  children.push(sectionTable("4. תאריכים", [
    row("תאריך כניסה",        "11/06/2026",   false),
    row("תאריך יציאה",        "לא סופק",      true),
    row("תאריך סיום חוזה",    "10/06/2027",   false),
    row("משך חוזה",           "364 ימים",     true),
    row("תאריך העברה",        "לא סופק",      false),
  ]));
  children.push(spacer());

  // 5. דייר נכנס
  children.push(sectionTable("5. דייר נכנס", [
    row("שם מלא",       "אבנר שבו",                  false),
    row("טלפון",        "050-5542388",               true),
    row("אימייל",       "avner@microdiuk.co.il",     false),
    row("תעודת זהות",   "028721819",                 true),
    row("סוג",          "אדם פרטי",                  false),
  ]));
  children.push(spacer());

  // 6. שוכר שני / שותף
  children.push(sectionTable("6. שוכר שני / שותף", [
    row("שם מלא",       "לא סופק",  false),
    row("טלפון",        "לא סופק",  true),
    row("אימייל",       "לא סופק",  false),
    row("תעודת זהות",   "לא סופק",  true),
  ]));
  children.push(spacer());

  // 7. דייר יוצא
  children.push(sectionTable("7. דייר יוצא", [
    row("שם מלא",       "רן בנישתי",    false),
    row("טלפון",        "050-2822206",  true),
    row("אימייל",       "❌ חסר",       false, { red: true }),
    row("תעודת זהות",   "308346311",    true),
  ]));
  children.push(spacer());

  // 8. בעל הבית
  children.push(sectionTable("8. בעל הבית", [
    row("שם מלא",       "ראובן שמש",    false),
    row("טלפון",        "052-5011146",  true),
    row("אימייל",       "❌ חסר",       false, { red: true }),
    row("תעודת זהות",   "❌ חסר",       true,  { red: true }),
  ]));
  children.push(spacer());

  // 9. חשבון ארנונה
  children.push(sectionTable("9. מידע חשבון ארנונה", [
    row("מספר נכס",              "לא סופק",  false),
    row("מספר לקוח",             "לא סופק",  true),
    row("מספר זיהוי נכס",        "לא סופק",  false),
    row("מספר חשבון תושב",       "לא סופק",  true),
    row("מספר חשבון לקוח",       "לא סופק",  false),
  ]));
  children.push(new Paragraph({
    alignment: AlignmentType.RIGHT,
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text: "הערה: בקשת כניסה חדשה — מספרי חשבון ייוצרו על ידי העירייה לאחר הרישום.", italics: true, size: 18, font: "Arial", color: "555555" })],
  }));
  children.push(spacer());

  // 10. חשבון מים
  children.push(sectionTable("10. מידע חשבון מים", [
    row("מספר נכס",   "לא סופק",  false),
    row("מספר לקוח",  "לא סופק",  true),
  ]));
  children.push(spacer());

  // 11. חשבון חשמל
  children.push(sectionTable("11. מידע חשבון חשמל", [
    row("מספר מונה",    "19010202",  false),
    row("קריאת מונה",   "094498",    true),
    row("מספר נכס",     "לא סופק",  false),
    row("מספר לקוח",    "לא סופק",  true),
  ]));
  children.push(spacer());

  // 12. מסמכים
  children.push(sectionTable("12. מסמכים", [
    statusRow("תעודת זהות (צילום)",         "❌ חסר",                         false),
    statusRow("חתימה דיגיטלית",             "❌ חסר",                         true),
    statusRow("חוזה שכירות",               "לא סופק",                         false),
    statusRow("חשבון ארנונה",              "לא סופק",                         true),
    statusRow("אישור תנאים",               "✅ התקבל",                        false),
    statusRow("הסכם שירות",                "✅ נחתם",                         true),
    statusRow("תעודת התאגדות",             "לא רלוונטי — לקוח פרטי",          false),
    statusRow("נסח טאבו",                  "לא רלוונטי — לקוח פרטי",          true),
  ]));
  children.push(spacer());

  // 13. פרטי תשלום
  children.push(sectionTable("13. פרטי תשלום", [
    row("חבילה",         "כניסה — רישום כמשלם עד 2 חשבונות",  false),
    row("סכום",          "199 ₪",                               true),
    statusRow("סטטוס תשלום", "✅ שולם",                        false),
    row("תאריך תשלום",   "09/06/2026",                          true),
  ]));
  children.push(spacer());

  // 14. מידע חסר
  children.push(sectionTable("14. מידע חסר", [
    new TableRow({ children: [
      new TableCell({
        columnSpan: 2,
        borders: border(),
        shading: { fill: WHITE, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "❌  תעודת זהות — צילום  |  חובה  |  נדרש לאימות זהות הדייר הנכנס", size: 20, font: "Arial", color: RED_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "❌  חתימה דיגיטלית  |  חובה  |  נדרש לאישור הבקשה", size: 20, font: "Arial", color: RED_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "❌  אימייל דייר יוצא (רן בנישתי)  |  נדרש  |  לתיאום מול הדייר היוצא", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "❌  אימייל בעל הבית (ראובן שמש)  |  נדרש  |  לאישור ההעברה", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "❌  תעודת זהות — בעל הבית  |  נדרש  |  לאימות זהות בעל הנכס", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
        ],
      }),
    ]}),
  ]));
  children.push(spacer());

  // 15. אזהרות ובעיות
  children.push(sectionTable("15. אזהרות ובעיות", [
    new TableRow({ children: [
      new TableCell({
        columnSpan: 2,
        borders: border(),
        shading: { fill: WHITE, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "⚠️  מסמכים נדרשים חסרים — תעודת זהות וחתימה דיגיטלית לא הועלו", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "⚠️  פרטי בעל הבית חלקיים — חסרים אימייל ותעודת זהות", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "⚠️  פרטי דייר יוצא חלקיים — חסר אימייל לתיאום", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "ℹ️   אין מספרי חשבון ארנונה — בקשת כניסה חדשה, מספרים ייוצרו עם העירייה", size: 20, font: "Arial", color: "0070C0" })] }),
        ],
      }),
    ]}),
  ]));
  children.push(spacer());

  // 16. פעולה מומלצת
  children.push(sectionTable("16. פעולה מומלצת", [
    new TableRow({ children: [
      new TableCell({
        columnSpan: 2,
        borders: border(),
        shading: { fill: WHITE, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 160, right: 160 },
        children: [
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "📧  יש לשלוח מייל לדייר הנכנס עם בקשה להשלמת הפרטים הבאים:", bold: true, size: 22, font: "Arial" })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: " ", size: 16, font: "Arial" })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "1.  ❌  צילום תעודת זהות (אבנר שבו — 028721819)", size: 20, font: "Arial", color: RED_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "2.  ❌  חתימה דיגיטלית על הטופס", size: 20, font: "Arial", color: RED_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "3.  ❌  אימייל הדייר היוצא — רן בנישתי", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "4.  ❌  אימייל ותעודת זהות של בעל הבית — ראובן שמש (052-5011146)", size: 20, font: "Arial", color: ORANGE_TEXT })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: " ", size: 16, font: "Arial" })] }),
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "⏳  הבקשה לא ניתנת לשליחה לעיבוד עד להשלמת כל הפרטים החסרים.", bold: true, size: 20, font: "Arial", color: ORANGE_TEXT })] }),
        ],
      }),
    ]}),
  ]));
  children.push(spacer());

  // 17. מידע פנימי
  children.push(sectionTable("17. מידע פנימי", [
    row("מספר פנייה",   "MZK6852",      false),
    row("מזהה החזר",    "MZKR1952",     true),
    row("תאריך הגשה",   "09/06/2026",   false),
    row("שעת הגשה",     "12:29",        true),
    row("שם לקוח",      "אבנר שבו",     false),
  ]));

  return new Document({
    styles: {
      default: {
        document: { run: { font: "Arial", size: 22 } },
      },
    },
    sections: [{
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            alignment: AlignmentType.RIGHT,
            border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BLUE_HEADER, space: 1 } },
            children: [new TextRun({ text: "מה זה קל  |  058-773-2700  |  docs@mazekal.co.il", size: 18, font: "Arial", color: "555555" })],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            border: { top: { style: BorderStyle.SINGLE, size: 6, color: BLUE_HEADER, space: 1 } },
            children: [
              new TextRun({ text: "עמוד ", size: 18, font: "Arial", color: "555555" }),
              new TextRun({ children: [PageNumber.CURRENT], size: 18, font: "Arial", color: "555555" }),
              new TextRun({ text: " | מסמך זה מיועד לשימוש פנימי בלבד", size: 18, font: "Arial", color: "555555" }),
            ],
          })],
        }),
      },
      children,
    }],
  });
}

// ── Main ──────────────────────────────────────────────────────────────────────
const doc = buildDoc();
const outPath = path.join(__dirname, "..", "sample_operator_summary.docx");

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outPath, buffer);
  console.log("Created:", outPath);
}).catch(err => {
  console.error("Failed:", err.message);
  process.exit(1);
});
