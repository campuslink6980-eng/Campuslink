"""
Private resume generator: builds HTML and PDF from current user profile only.
No storage, no approval. Used by /resume-preview and /resume-download.
"""
from io import BytesIO
import re


def _escape_html(s):
    if s is None:
        return ""
    s = str(s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    return s


def _text(s):
    if s is None:
        return ""
    return str(s).strip()


def build_resume_html(user: dict, profile: dict) -> str:
    """
    Build resume HTML fragment (body content) from user and profile.
    Sections: Name, Headline/About, Education, Skills, Internships, Projects, Certifications, Contact (email).
    Missing sections are skipped.
    """
    first = _text(user.get("first_name"))
    last = _text(user.get("last_name"))
    full_name = f"{first} {last}".strip() or "Name"
    email = _text(user.get("email"))

    basic = profile.get("basic") or {}
    headline = _text(basic.get("headline")) or _text(profile.get("headline"))
    about = _text(profile.get("about"))
    education = list(profile.get("education") or [])
    experience = list(profile.get("experience") or [])  # internships
    projects = list(profile.get("projects") or [])
    skills = list(profile.get("skills") or [])
    certs = list(profile.get("certifications") or [])
    achievements = list(profile.get("achievements") or [])
    languages = list(profile.get("languages") or [])
    interests = list(profile.get("interests") or [])
    clubs = list(profile.get("clubs") or [])

    parts = []

    # Name
    parts.append(f'<h1 class="resume-name">{_escape_html(full_name)}</h1>')

    # Headline / About
    if headline or about:
        block = []
        if headline:
            block.append(f'<p class="resume-headline">{_escape_html(headline)}</p>')
        if about:
            block.append(f'<p class="resume-about">{_escape_html(about)}</p>')
        parts.append('<div class="resume-section resume-headline-block">' + "".join(block) + "</div>")

    # Contact (email only)
    if email:
        parts.append(
            '<div class="resume-section"><h2 class="resume-h2">Contact</h2>'
            f'<p class="resume-contact">Email: {_escape_html(email)}</p></div>'
        )

    # Education
    if education:
        items = []
        for edu in education:
            if not isinstance(edu, dict):
                continue
            inst = _text(edu.get("institution") or edu.get("school"))
            degree = _text(edu.get("degree"))
            cgpa = edu.get("cgpa")
            cgpa_str = f" CGPA: {cgpa}" if cgpa is not None and _text(str(cgpa)) else ""
            period = _text(edu.get("end_year") or edu.get("end_date") or "")
            if period and _text(edu.get("start_year") or edu.get("start_date")):
                period = f"{_text(edu.get('start_year') or edu.get('start_date'))} – {period}"
            line = _escape_html(inst or "Institution")
            if degree:
                line += f" — {_escape_html(degree)}"
            if cgpa_str:
                line += _escape_html(cgpa_str)
            if period:
                line += f" ({_escape_html(period)})"
            items.append(f"<li>{line}</li>")
        if items:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Education</h2><ul class="resume-list">'
                + "".join(items)
                + "</ul></div>"
            )

    # Skills
    if skills:
        skill_strs = []
        for s in skills:
            if isinstance(s, dict):
                skill_strs.append(_text(s.get("name") or s.get("skill") or s.get("value")))
            elif s:
                skill_strs.append(_text(str(s)))
        skill_strs = [x for x in skill_strs if x]
        if skill_strs:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Skills</h2>'
                f'<p class="resume-skills">{_escape_html(", ".join(skill_strs))}</p></div>'
            )

    # Internships (experience)
    if experience:
        items = []
        for exp in experience:
            if not isinstance(exp, dict):
                continue
            title = _text(exp.get("title") or exp.get("role"))
            company = _text(exp.get("company") or exp.get("organization"))
            period = _text(exp.get("end_year") or exp.get("end_date") or "")
            if period and _text(exp.get("start_year") or exp.get("start_date")):
                period = f"{_text(exp.get('start_year') or exp.get('start_date'))} – {period}"
            desc = _text(exp.get("description"))
            line = f"<strong>{_escape_html(title or 'Role')}</strong>"
            if company:
                line += f" — {_escape_html(company)}"
            if period:
                line += f" ({_escape_html(period)})"
            if desc:
                line += f"<br/><span class=\"resume-desc\">{_escape_html(desc)}</span>"
            items.append(f"<li>{line}</li>")
        if items:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Internships</h2><ul class="resume-list">'
                + "".join(items)
                + "</ul></div>"
            )

    # Projects
    if projects:
        items = []
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            title = _text(proj.get("title") or proj.get("name"))
            desc = _text(proj.get("description"))
            period = _text(proj.get("end_year") or proj.get("end_date") or "")
            if period and _text(proj.get("start_year") or proj.get("start_date")):
                period = f"{_text(proj.get('start_year') or proj.get('start_date'))} – {period}"
            line = f"<strong>{_escape_html(title or 'Project')}</strong>"
            if period:
                line += f" ({_escape_html(period)})"
            if desc:
                line += f"<br/><span class=\"resume-desc\">{_escape_html(desc)}</span>"
            items.append(f"<li>{line}</li>")
        if items:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Projects</h2><ul class="resume-list">'
                + "".join(items)
                + "</ul></div>"
            )

    # Certifications
    if certs:
        items = []
        for c in certs:
            if isinstance(c, dict):
                name = _text(c.get("name") or c.get("title"))
                issuer = _text(c.get("issuer"))
                if name or issuer:
                    items.append(f"<li>{_escape_html(name or issuer)}</li>")
            elif c:
                items.append(f"<li>{_escape_html(str(c))}</li>")
        if items:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Certifications</h2><ul class="resume-list">'
                + "".join(items)
                + "</ul></div>"
            )

    # Achievements
    if achievements:
        items = []
        for a in achievements:
            if isinstance(a, dict):
                title = _text(a.get("title"))
                issuer = _text(a.get("issuer"))
                desc = _text(a.get("description"))
                if title or issuer or desc:
                    items.append(f"<li>{_escape_html(title or issuer or desc)}</li>")
            elif a:
                items.append(f"<li>{_escape_html(str(a))}</li>")
        if items:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Achievements</h2><ul class="resume-list">'
                + "".join(items)
                + "</ul></div>"
            )

    # Languages
    if languages:
        lang_strs = [_text(x) for x in languages if x]
        if lang_strs:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Languages</h2>'
                f'<p class="resume-skills">{_escape_html(", ".join(lang_strs))}</p></div>'
            )

    # Interests
    if interests:
        int_strs = [_text(x) for x in interests if x]
        if int_strs:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Interests</h2>'
                f'<p class="resume-skills">{_escape_html(", ".join(int_strs))}</p></div>'
            )

    # Clubs
    if clubs:
        items = []
        for c in clubs:
            if isinstance(c, dict):
                name = _text(c.get("name"))
                role = _text(c.get("role"))
                duration = _text(c.get("duration"))
                if name or role or duration:
                    line = _escape_html(name or "Club")
                    if role:
                        line += f" — {_escape_html(role)}"
                    if duration:
                        line += f" ({_escape_html(duration)})"
                    items.append(f"<li>{line}</li>")
            elif c:
                items.append(f"<li>{_escape_html(str(c))}</li>")
        if items:
            parts.append(
                '<div class="resume-section"><h2 class="resume-h2">Clubs &amp; Activities</h2><ul class="resume-list">'
                + "".join(items)
                + "</ul></div>"
            )

    return "\n".join(parts)


def build_resume_pdf(user: dict, profile: dict) -> bytes:
    """
    Build PDF bytes from user and profile. Uses reportlab.
    No file is written to disk; returns bytes.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="ResumeTitle",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        name="ResumeH2",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = styles["Normal"]
    body_style.spaceAfter = 4

    first = _text(user.get("first_name"))
    last = _text(user.get("last_name"))
    full_name = f"{first} {last}".strip() or "Name"
    email = _text(user.get("email"))
    basic = profile.get("basic") or {}
    headline = _text(basic.get("headline")) or _text(profile.get("headline"))
    about = _text(profile.get("about"))
    education = list(profile.get("education") or [])
    experience = list(profile.get("experience") or [])
    projects = list(profile.get("projects") or [])
    skills = list(profile.get("skills") or [])
    certs = list(profile.get("certifications") or [])
    achievements = list(profile.get("achievements") or [])
    languages = list(profile.get("languages") or [])
    interests = list(profile.get("interests") or [])
    clubs = list(profile.get("clubs") or [])

    story = []
    story.append(Paragraph(full_name.replace("&", "&amp;"), title_style))
    if headline:
        story.append(Paragraph(headline.replace("&", "&amp;"), body_style))
    if about:
        story.append(Paragraph(about.replace("&", "&amp;"), body_style))
    if email:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Contact</b><br/>Email: {email}", body_style))

    if education:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Education", h2_style))
        for edu in education:
            if not isinstance(edu, dict):
                continue
            inst = _text(edu.get("institution") or edu.get("school"))
            degree = _text(edu.get("degree"))
            cgpa = edu.get("cgpa")
            cgpa_str = f", CGPA: {cgpa}" if cgpa is not None and _text(str(cgpa)) else ""
            period = _text(edu.get("end_year") or edu.get("end_date") or "")
            if period and _text(edu.get("start_year") or edu.get("start_date")):
                period = f"{_text(edu.get('start_year') or edu.get('start_date'))} – {period}"
            line = f"{inst or 'Institution'}"
            if degree:
                line += f" — {degree}"
            line += cgpa_str
            if period:
                line += f" ({period})"
            story.append(Paragraph(line.replace("&", "&amp;"), body_style))

    if skills:
        skill_strs = []
        for s in skills:
            if isinstance(s, dict):
                skill_strs.append(_text(s.get("name") or s.get("skill") or s.get("value")))
            elif s:
                skill_strs.append(_text(str(s)))
        skill_strs = [x for x in skill_strs if x]
        if skill_strs:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Skills", h2_style))
            story.append(Paragraph(", ".join(skill_strs).replace("&", "&amp;"), body_style))

    if experience:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Internships", h2_style))
        for exp in experience:
            if not isinstance(exp, dict):
                continue
            title = _text(exp.get("title") or exp.get("role"))
            company = _text(exp.get("company") or exp.get("organization"))
            period = _text(exp.get("end_year") or exp.get("end_date") or "")
            if period and _text(exp.get("start_year") or exp.get("start_date")):
                period = f"{_text(exp.get('start_year') or exp.get('start_date'))} – {period}"
            desc = _text(exp.get("description"))
            line = f"<b>{title or 'Role'}</b> — {company or 'Company'} ({period})"
            if desc:
                line += f"<br/>{desc}"
            story.append(Paragraph(line.replace("&", "&amp;"), body_style))

    if projects:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Projects", h2_style))
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            title = _text(proj.get("title") or proj.get("name"))
            desc = _text(proj.get("description"))
            period = _text(proj.get("end_year") or proj.get("end_date") or "")
            if period and _text(proj.get("start_year") or proj.get("start_date")):
                period = f"{_text(proj.get('start_year') or proj.get('start_date'))} – {period}"
            line = f"<b>{title or 'Project'}</b>"
            if period:
                line += f" ({period})"
            if desc:
                line += f"<br/>{desc}"
            story.append(Paragraph(line.replace("&", "&amp;"), body_style))

    if certs:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Certifications", h2_style))
        for c in certs:
            if isinstance(c, dict):
                name = _text(c.get("name") or c.get("title"))
                issuer = _text(c.get("issuer"))
                line = name or issuer or ""
            else:
                line = str(c).strip() if c else ""
            if line:
                story.append(Paragraph(line.replace("&", "&amp;"), body_style))

    if achievements:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Achievements", h2_style))
        for a in achievements:
            if isinstance(a, dict):
                line = _text(a.get("title")) or _text(a.get("issuer")) or _text(a.get("description")) or ""
            else:
                line = str(a).strip() if a else ""
            if line:
                story.append(Paragraph(line.replace("&", "&amp;"), body_style))

    if languages:
        lang_strs = [_text(x) for x in languages if x]
        if lang_strs:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Languages", h2_style))
            story.append(Paragraph(", ".join(lang_strs).replace("&", "&amp;"), body_style))

    if interests:
        int_strs = [_text(x) for x in interests if x]
        if int_strs:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Interests", h2_style))
            story.append(Paragraph(", ".join(int_strs).replace("&", "&amp;"), body_style))

    if clubs:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Clubs & Activities", h2_style))
        for c in clubs:
            if isinstance(c, dict):
                name = _text(c.get("name"))
                role = _text(c.get("role"))
                duration = _text(c.get("duration"))
                line = (name or "Club") + (f" — {role}" if role else "") + (f" ({duration})" if duration else "")
            else:
                line = str(c).strip() if c else ""
            if line:
                story.append(Paragraph(line.replace("&", "&amp;"), body_style))

    doc.build(story)
    return buffer.getvalue()


def safe_resume_filename(user: dict) -> str:
    """Firstname_lastname_resume.pdf with safe characters."""
    first = _text(user.get("first_name")) or "First"
    last = _text(user.get("last_name")) or "Last"
    name = f"{first}_{last}".strip("_")
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[-\s]+", "_", name).strip("_") or "resume"
    return f"{name}_resume.pdf"
