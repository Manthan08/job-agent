"""Renderer (AI-owned plumbing): TailoredResumeModel + original resume -> sendable PDF.

Mentor split: this is low-interview-value rendering plumbing. The interview-worthy
code (the LCEL chain + prompt that PRODUCES the TailoredResumeModel, including the
**bold** keyword decisions and skill categorisation) is user-written.

Design notes (engineering rationale, for study):
  * Pipeline is (original resume dict + TailoredResumeModel) -> HTML(+CSS) -> PDF.
    Separating data / structure / presentation means a new look only touches the
    HTML/CSS here, never the data or LLM layers.
  * What gets tailored vs carried: the LLM only reframes WORDING (summary, skill
    emphasis, experience bullets). Factual data — contact links, company names,
    dates, projects — is carried straight from the original resume, never sent to
    an LLM. So this renderer MERGES the two sources.
  * Engine is xhtml2pdf (pisa) — pure-Python, no native deps (WeasyPrint needs
    GTK/Cairo, painful on Windows). It consumes HTML + a CSS subset and emits PDF.
  * House style: ONE consistent, minimal, single-column, ATS-safe template that any
    uploaded resume flows into — we do NOT pixel-clone the source PDF (arbitrary
    layouts can't be reproduced reliably; a known-good template is safer).
  * Layout policy: single column + minimal chrome, target ONE page. Skills only fall
    back to a compact two-column grid when that actually reduces the page count
    (auto-fit: render single-column, count pages, retry two-column, keep the smaller).
  * ATS-safety: real text (no images), standard headings, embedded standard font,
    ASCII punctuation. The optional skills grid is a single contained table that
    still extracts as readable "Category: skills" text.
  * The LLM emits **bold** Markdown around JD-critical keywords; we convert that to
    <strong> so the emphasis survives all the way to the PDF.

Internal-only fields (skill_gaps, bridge_notes) are intentionally NOT rendered — the
PDF is the sendable artifact, not the coaching notes.
"""
import html
import json
import re
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from xhtml2pdf import pisa

from models.tailored import TailoredResumeModel
from phase4_tailor.artifacts import tailored_artifact_filename

TAILORED_DIR = Path(__file__).resolve().parent.parent / "data" / "tailored"

def _inline_md(text: str) -> str:
    """Escape HTML, then convert **bold** Markdown to <strong> (the only inline
    markup the LLM is asked to emit). Order matters: escape first so model text
    can't inject tags, then re-introduce our own <strong> (an allow-list approach)."""
    escaped = html.escape(text or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _coerce_list(value) -> list:
    """Accept a JSON string or an already-parsed list (rows store JSON strings)."""
    if not value:
        return []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return list(value)


def _contact_html(resume: dict) -> str:
    """Build the 'phone | email | linkedin | portfolio | location' line, with the
    URLs rendered as clickable links (href gets an https:// prefix if missing)."""
    parts: list[str] = []
    if resume.get("Phone"):
        parts.append(html.escape(resume["Phone"]))
    if resume.get("Email"):
        email = html.escape(resume["Email"])
        parts.append(f'<a href="mailto:{email}">{email}</a>')
    for url in _coerce_list(resume.get("Urls")):
        text = html.escape(str(url))
        href = text if re.match(r"^https?://", text) else f"https://{text}"
        parts.append(f'<a href="{href}">{text}</a>')
    if resume.get("Location"):
        parts.append(html.escape(resume["Location"]))
    return " | ".join(parts)


def _skills_html(tailored: TailoredResumeModel, two_column: bool) -> str:
    """Categorised skills. Single column by default (one line per category);
    a compact two-column table only when the caller is trying to save a page."""
    cats = tailored.tailored_skills
    if not cats:
        return ""

    def line(category) -> str:
        label = _inline_md(category.category)
        skills = ", ".join(_inline_md(s) for s in category.skills)
        return f"<strong>{label}:</strong> {skills}"

    if not two_column:
        return "".join(f'<p class="skill">{line(c)}</p>' for c in cats)

    def cell(category) -> str:
        if category is None:
            return '<td class="skillcell"></td>'
        return f'<td class="skillcell">{line(category)}</td>'

    rows = ""
    for i in range(0, len(cats), 2):
        left = cell(cats[i])
        right = cell(cats[i + 1] if i + 1 < len(cats) else None)
        rows += f"<tr>{left}{right}</tr>"
    return f'<table class="skills" width="100%">{rows}</table>'


def _experience_html(tailored: TailoredResumeModel) -> str:
    """Experience grouped by employer: company + dates header, role, tailored bullets."""
    blocks = ""
    for job in tailored.tailored_experience:
        company = _inline_md(job.company)
        role = _inline_md(job.role_title)
        end = job.end_date or "Present"
        dates = html.escape(f"{job.start_date} - {end}")
        blocks += f"""
  <div class="job">
    <table class="jobhead" width="100%">
      <tr>
        <td class="jobleft"><strong>{company}</strong> &nbsp; <span class="role">{role}</span></td>
        <td class="jobright">{dates}</td>
      </tr>
    </table>
    {_bullet_list_html(job.bullets)}
  </div>"""
    return blocks


def _bullet_list_html(items: list[str]) -> str:
    """Use ASCII hyphen bullets instead of HTML <li> bullets.

    xhtml2pdf extracts native list bullets as a control character, which is not
    ideal for ATS text parsing. Hyphen bullets stay readable visually and in text.
    """
    return "".join(f'<p class="bullet">- {_inline_md(item)}</p>' for item in items)


def _projects_html(resume: dict) -> str:
    """Projects section, carried verbatim from the original resume (factual, untailored)."""
    projects = _coerce_list(resume.get("Projects"))
    if not projects:
        return ""
    items = ""
    for p in projects:
        name = _inline_md(p.get("name", ""))
        desc = _inline_md(p.get("description", ""))
        tech = ", ".join(_inline_md(t) for t in (p.get("technologies_used") or []))
        tech_html = f' <span class="tech">({tech})</span>' if tech else ""
        items += f'<p class="bullet">- <strong>{name}:</strong> {desc}{tech_html}</p>'
    return f"<h2>Projects</h2>{items}"


def _education_html(resume: dict) -> str:
    """Education carried from the original resume."""
    education = resume.get("Education")
    if not education:
        return ""
    return f"<h2>Education</h2><p>{_inline_md(str(education))}</p>"


def _build_html(tailored: TailoredResumeModel, resume: dict, density: dict) -> str:
    """Assemble a minimal, single-column, ATS-safe HTML document:
    header (name / role / contacts) -> summary -> skills -> experience -> projects.

    `density` tunes margins / font / spacing so the caller can escalate compactness
    to fit one page (see render_tailored_pdf)."""
    name = html.escape(resume.get("Name") or "")
    role = html.escape(resume.get("CurrentPosition") or "")
    contact = _contact_html(resume)
    d = density
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @page {{ size: A4; margin: {d['margin']}; }}
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: {d['body_pt']}pt; color: #222; line-height: {d['line_height']}; }}
  a {{ color: #222; text-decoration: none; }}
  .name {{ font-size: 18pt; font-weight: bold; color: #174a7c; margin: 0; }}
  .headrole {{ font-size: 10pt; color: #333; margin: 1pt 0 0 0; }}
  .contact {{ font-size: 8.5pt; color: #555; margin: 3pt 0 0 0; }}
  h2 {{ font-size: {d['body_pt']}pt; color: #174a7c; text-transform: uppercase; letter-spacing: 0.4pt;
        border-bottom: 0.7pt solid #b8c7d8; padding-bottom: 2pt; margin: {d['h2_top']}pt 0 4pt 0; }}
  p {{ margin: 0 0 {d['p_gap']}pt 0; }}
  p.bullet {{ margin: 0 0 {d['li_gap']}pt 11pt; text-indent: -7pt; }}
  strong {{ color: #111; }}
  p.skill {{ margin: 0 0 2pt 0; }}
  table.skills {{ border-collapse: collapse; margin: 0; }}
  td.skillcell {{ width: 50%; vertical-align: top; padding: 0 10pt 3pt 0; }}
  .job {{ margin-bottom: {d['job_gap']}pt; }}
  table.jobhead {{ border-collapse: collapse; margin: 0 0 1pt 0; }}
  td.jobleft {{ font-size: {d['body_pt']}pt; }}
  td.jobleft .role {{ font-style: italic; color: #444; }}
  td.jobright {{ text-align: right; font-size: 8.5pt; color: #555; white-space: nowrap; }}
  .tech {{ color: #555; font-style: italic; }}
</style>
</head>
<body>
  <p class="name">{name}</p>
  <p class="headrole">{role}</p>
  <p class="contact">{contact}</p>

  <h2>Professional Summary</h2>
  <p>{_inline_md(tailored.tailored_summary)}</p>

  <h2>Skills</h2>
  {_skills_html(tailored, d['two_column_skills'])}

  <h2>Experience</h2>
  {_experience_html(tailored)}

  {_projects_html(resume)}
  {_education_html(resume)}
</body>
</html>"""


# Compactness ladder, most readable first. render_tailored_pdf escalates through
# these only as needed to pull the resume onto a single page.
_DENSITY_LADDER = [
    {"margin": "1.3cm 1.5cm", "body_pt": 9.5, "line_height": 1.25, "h2_top": 9,
     "p_gap": 4, "li_gap": 1.5, "job_gap": 5, "two_column_skills": False},
    {"margin": "1.1cm 1.3cm", "body_pt": 9.0, "line_height": 1.2, "h2_top": 8,
     "p_gap": 3, "li_gap": 1.2, "job_gap": 4, "two_column_skills": False},
    {"margin": "1.0cm 1.2cm", "body_pt": 8.7, "line_height": 1.16, "h2_top": 7,
     "p_gap": 2.5, "li_gap": 1.0, "job_gap": 3.5, "two_column_skills": True},
]


def _render_bytes(source_html: str) -> bytes:
    buffer = BytesIO()
    result = pisa.CreatePDF(src=source_html, dest=buffer, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF generation failed with {result.err} error(s).")
    return buffer.getvalue()


def _page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(BytesIO(pdf_bytes)).pages)


def render_tailored_pdf(
    tailored: TailoredResumeModel,
    resume: dict,
    company: str,
    position: str,
    output_dir: Path | None = None,
) -> Path:
    """Render the tailored resume to data/tailored/Name_Company_Position.pdf.

    `resume` is the ORIGINAL resume row (dict) — used for factual data (contact links,
    location, current position, projects) that is carried over, not tailored.

    Layout auto-fit: render at the most readable density first; if it spills past one
    page, escalate through the compactness ladder (tighter margins / font / spacing,
    finally two-column skills) and stop at the first single-page result. If nothing
    fits one page, keep the most readable variant with the fewest pages. Returns the
    path written; overwrites the same candidate/company/position file (idempotent).
    """
    target_dir = output_dir or TAILORED_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = tailored_artifact_filename(resume.get("Name"), company, position, "pdf")
    path = target_dir / filename

    best_pdf, best_pages = None, None
    for density in _DENSITY_LADDER:
        pdf = _render_bytes(_build_html(tailored, resume, density))
        pages = _page_count(pdf)
        if pages <= 1:
            best_pdf = pdf
            break
        if best_pages is None or pages < best_pages:
            best_pdf, best_pages = pdf, pages

    path.write_bytes(best_pdf)
    return path
