"""Documents library (1.7): Word, Excel and PDF files kept for download and linked to corrective actions, CNHI decisions,
deliverables and hospital-dispute batches.

Unlike the six registers (read, then deleted), a library file is kept: it is the document itself that people need.
Safeguards, applied at upload:
  - types: .pdf, .docx, .xlsx, .xlsm only, checked by content (signature), not by name; legacy .doc/.xls are refused
    because their content cannot be checked;
  - patient identifiers: the text is scanned for 10-digit numbers starting with 1 or 2 (national ID / iqama format) and for
    patient-identifier labels. A match, or a file with no readable text (a scan), is refused unless the uploader confirms the
    file holds no patient identifiers; the confirmation is written to the audit log. Matches are counted, never stored;
  - visibility per document: 'kpmg' (KPMG users only) or 'shared' (also CNHI users);
  - files are served only as downloads to signed-in users allowed to see them, and every download is audited.
The extracted text is kept only for search inside the library.
"""
import hashlib
import io
import os
import re
import zipfile

from . import db

LIB_DIR = None
MAX_BYTES = 25 * 1024 * 1024
EXT = {".pdf": "application/pdf",
       ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
       ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
       ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12"}
CATEGORIES = {  # key -> (English, Arabic, suggested link kind)
    "monthly": ("Monthly review report", "تقرير المراجعة الشهري", "deliverable"),
    "quarterly": ("Quarterly financial report", "التقرير المالي الربعي", "deliverable"),
    "annual": ("Annual consolidated report", "التقرير السنوي الموحد", "deliverable"),
    "gss": ("GSS assurance report", "تقرير ضمان GSS", "deliverable"),
    "minutes": ("CNHI minutes", "محضر اجتماع المركز", "decision"),
    "memo": ("Decision memo", "مذكرة قرار", "decision"),
    "evidence": ("Corrective-action evidence", "دليل إجراء تصحيحي", "action"),
    "letter": ("TPA or provider correspondence", "مراسلات مع الشركة أو مقدم الخدمة", "action"),
    "objection": ("Hospital objection file", "ملف اعتراض مستشفى", "batch"),
    "opinion": ("KPMG dispute opinion", "رأي KPMG في الاعتراض", "batch"),
    "policy": ("Policy, manual or circular", "سياسة أو دليل أو تعميم", ""),
    "other": ("Other", "أخرى", ""),
}
LINK_KINDS = {"action": ("Corrective action", "إجراء تصحيحي"), "decision": ("CNHI decision", "قرار المركز"),
              "deliverable": ("Deliverable", "مخرج"), "batch": ("Dispute batch", "دفعة اعتراضات")}
ID_RE = re.compile(r"(?<![\d/.-])[12]\d{9}(?![\d/.-])")
LABEL_RE = re.compile(r"(national\s*id|iqama|patient\s*name|رقم\s*الهوية|رقم\s*الإقامة|اسم\s*المريض|هوية\s*المريض)", re.I)


class LibraryError(ValueError):
    pass


def init(data_dir):
    global LIB_DIR
    LIB_DIR = os.path.join(data_dir, "library")
    os.makedirs(LIB_DIR, exist_ok=True)


def path(doc):
    return os.path.join(LIB_DIR, f"{int(doc['id'])}{doc['ext']}")


def sniff(raw, ext):
    """True when the bytes really are the claimed type."""
    if ext == ".pdf":
        return raw[:5] == b"%PDF-"
    if raw[:2] != b"PK":
        return False
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = set(z.namelist())
    except zipfile.BadZipFile:
        return False
    if "[Content_Types].xml" not in names:
        return False
    return ("word/document.xml" in names) if ext == ".docx" else ("xl/workbook.xml" in names)


def extract_text(raw, ext, limit=300_000):
    """Plain text for search and the identifier check. '' when none can be read (for example a scanned PDF)."""
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(raw))
            out = []
            for pg in r.pages[:300]:
                out.append(pg.extract_text() or "")
                if sum(map(len, out)) > limit:
                    break
            text = "\n".join(out)
        elif ext == ".docx":
            z = zipfile.ZipFile(io.BytesIO(raw))
            parts = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*|footnotes|comments)\.xml$", n)]
            xml = " ".join(z.read(n).decode("utf-8", "ignore") for n in parts)
            xml = re.sub(r"</w:p>|<w:tab/>|<w:br/>", "\n", xml)
            text = re.sub(r"<[^>]+>", "", xml)
        else:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    cells = []
                    for v in row:
                        if v is None:
                            continue
                        if isinstance(v, float) and v.is_integer():
                            v = int(v)                    # a 10-digit ID typed in a cell reads back as a float
                        cells.append(str(v))
                    if cells:
                        out.append(" ".join(cells))
                    if sum(map(len, out)) > limit:
                        break
            text = "\n".join(out)
    except Exception:  # noqa: BLE001 - an unreadable file is treated as 'no readable text'
        text = ""
    import html
    return html.unescape(re.sub(r"[ \t]+", " ", text)).strip()[:limit]


def id_check(text):
    """('clean' | 'ids_found' | 'no_text', count of identifier-like matches)."""
    if len(text.strip()) < 20:
        return "no_text", 0
    n = len(ID_RE.findall(text)) + len(LABEL_RE.findall(text))
    return ("ids_found", n) if n else ("clean", 0)


def save(raw, filename, meta, user, confirm=False, parent=None):
    """Validate and store a document; returns its id. meta: title, category, period, description, visibility, links."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in (".doc", ".xls"):
        raise LibraryError("Save the file as .docx or .xlsx first: the older format cannot be checked for patient identifiers.")
    if ext not in EXT:
        raise LibraryError("Upload a PDF, Word (.docx) or Excel (.xlsx, .xlsm) file.")
    if not raw:
        raise LibraryError("The file is empty.")
    if len(raw) > MAX_BYTES:
        raise LibraryError("The file is larger than 25 MB.")
    if not sniff(raw, ext):
        raise LibraryError("The file content does not match its type. Open it and save it again as " + ext + ".")
    if meta.get("category") not in CATEGORIES:
        raise LibraryError("Choose a category.")
    if meta.get("visibility") not in ("kpmg", "shared"):
        raise LibraryError("Choose who can see the document.")
    title = (meta.get("title") or "").strip()[:200] or os.path.splitext(os.path.basename(filename))[0][:200]
    text = extract_text(raw, ext)
    check, n = id_check(text)
    if check != "clean" and not confirm:
        if check == "ids_found":
            raise LibraryError(f"The file appears to contain patient identifiers ({n} ID-like numbers or labels). Remove them, "
                               "or tick the confirmation if they are not personal identifiers.")
        raise LibraryError("No text could be read from the file (for example a scanned PDF), so it could not be checked for "
                           "patient identifiers. Tick the confirmation if it holds none.")
    safe_name = re.sub(r"[^\w؀-ۿ .()-]+", "_", os.path.basename(filename))[:150] or ("document" + ext)
    doc_id = db.insert("documents", title=title, category=meta["category"], period=(meta.get("period") or "")[:7],
                       description=(meta.get("description") or "").strip()[:500], visibility=meta["visibility"],
                       filename=safe_name, ext=ext, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), text=text,
                       id_check=check + ("_confirmed" if check != "clean" else ""), id_count=n, parent_id=parent,
                       status="active", uploaded_by=user, uploaded_at=db.now())
    with open(os.path.join(LIB_DIR, f"{doc_id}{ext}"), "wb") as fh:
        fh.write(raw)
    set_links(doc_id, meta.get("links") or [])
    if parent:
        db.ex("UPDATE documents SET status='superseded' WHERE id=?", (parent,))
    return doc_id, check, n


def set_links(doc_id, links):
    db.ex("DELETE FROM doc_links WHERE doc_id=?", (doc_id,))
    for kind, ref in links:
        if kind in LINK_KINDS and ref:
            db.ex("INSERT OR IGNORE INTO doc_links(doc_id, kind, ref) VALUES(?,?,?)", (doc_id, kind, str(ref)[:120]))


def links(doc_id):
    return [(r["kind"], r["ref"]) for r in db.q("SELECT kind, ref FROM doc_links WHERE doc_id=? ORDER BY kind, ref", (doc_id,))]


def visible_sql(internal):
    return "status='active'" + ("" if internal else " AND visibility='shared'")


def get(doc_id, internal):
    d = db.q1("SELECT * FROM documents WHERE id=? AND status IN ('active','superseded')", (doc_id,))
    if d is None or (not internal and d["visibility"] != "shared"):
        return None
    return d


def search(internal, q="", category="", kind="", ref="", period=""):
    sql = "SELECT d.* FROM documents d WHERE " + visible_sql(internal).replace("status", "d.status").replace("visibility", "d.visibility")
    args = []
    if category:
        sql += " AND d.category=?"
        args.append(category)
    if period:
        sql += " AND d.period=?"
        args.append(period)
    if kind and ref:
        sql += " AND EXISTS (SELECT 1 FROM doc_links l WHERE l.doc_id=d.id AND l.kind=? AND l.ref=?)"
        args += [kind, ref]
    elif kind:
        sql += " AND EXISTS (SELECT 1 FROM doc_links l WHERE l.doc_id=d.id AND l.kind=?)"
        args.append(kind)
    for word in (q or "").split()[:6]:
        sql += " AND (d.title LIKE ? OR d.description LIKE ? OR d.text LIKE ? OR d.filename LIKE ?)"
        args += [f"%{word}%"] * 4
    return db.q(sql + " ORDER BY d.uploaded_at DESC, d.id DESC LIMIT 500", tuple(args))


def for_link(kind, ref, internal):
    return db.q("SELECT d.* FROM documents d JOIN doc_links l ON l.doc_id=d.id WHERE l.kind=? AND l.ref=? AND d."
                + visible_sql(internal).replace("visibility", "d.visibility") + " ORDER BY d.uploaded_at DESC", (kind, ref))


def counts_for(kind, internal):
    """{ref: number of visible documents} for one link kind (tracker paperclips)."""
    rows = db.q("SELECT l.ref, COUNT(*) AS n FROM doc_links l JOIN documents d ON d.id=l.doc_id WHERE l.kind=? AND d."
                + visible_sql(internal).replace("visibility", "d.visibility") + " GROUP BY l.ref", (kind,))
    return {r["ref"]: r["n"] for r in rows}


def versions(doc):
    """The chain of versions this document belongs to, newest first."""
    root = doc
    while root["parent_id"]:
        nxt = db.q1("SELECT * FROM documents WHERE id=?", (root["parent_id"],))
        if nxt is None:
            break
        root = nxt
    chain, cur = [root], root
    while True:
        nxt = db.q1("SELECT * FROM documents WHERE parent_id=? ORDER BY id", (cur["id"],))
        if nxt is None:
            break
        chain.append(nxt)
        cur = nxt
    return list(reversed(chain))


def delete(doc):
    """Removes the file for good (all versions stay listed as deleted in the audit log)."""
    for d in versions(doc):
        p = path(d)
        if os.path.exists(p):
            os.remove(p)
        db.ex("UPDATE documents SET status='deleted', text='' WHERE id=?", (d["id"],))


def link_options(data):
    """Choices for the link fields, built from the published registers."""
    opts = {k: [] for k in LINK_KINDS}
    f6 = data.get("F6") or {}
    for a in f6.get("actions", []):
        opts["action"].append((a["id"], f"{a['id']} · {a['type']} · {a['target'] or 'Provider (not named)'}"))
    for d in f6.get("decisions", []):
        opts["decision"].append((d["id"], f"{d['id']} · {d['topic']} · {d['decision']}" + (f" · {d['minutes']}" if d.get("minutes") else "")))
    for x in (data.get("F5") or {}).get("deliverables", []):
        key = x.get("ref") or f"{x['type']} {x['period']}"
        opts["deliverable"].append((key, f"{x['type']} · {x['period']}" + (f" · {x['ref']}" if x.get("ref") else "")))
    seen = {}
    for d in (data.get("F3") or {}).get("disputes", []):
        if d.get("batch") and d["batch"] not in seen:
            seen[d["batch"]] = d.get("hospital") or ""
    opts["batch"] = [(b, f"{b} · {h}") for b, h in sorted(seen.items())]
    return opts
