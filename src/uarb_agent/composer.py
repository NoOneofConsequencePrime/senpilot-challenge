"""Email wording and layout. Every fact comes from the scraper through these templates (the LLM never writes facts).

Each email has two parts:
- plain text, which keeps the assignment's example wording as a narrative paragraph;
- HTML, which shows the same facts as scannable components (status, chips, filing timeline, count tiles, file list).
  The HTML is email-safe: table layout, inline styles, no external assets, 600 px wide.
"""

from dataclasses import dataclass, field
from datetime import date
from email.utils import parseaddr
from html import escape

from .models import DocRequest, DocType, FetchResult, MatterMetadata
from .packager import Delivery

SINGULAR = {
    DocType.EXHIBITS: "Exhibit",
    DocType.KEY_DOCUMENTS: "Key Document",
    DocType.OTHER_DOCUMENTS: "Other Document",
    DocType.TRANSCRIPTS: "Transcript",
    DocType.RECORDINGS: "Recording",
}
PRODUCT = "UARB Documents"
SITE_URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
ACCENT = "#2563eb"
INK, BODY, MUTED, FAINT = "#111827", "#374151", "#6b7280", "#9ca3af"
LINE, BORDER, PAGE_BG = "#eceef1", "#e5e7eb", "#f4f5f7"
GREEN = ("#ecfdf5", "#a7f3d0", "#047857")
AMBER = ("#fffbeb", "#fde68a", "#b45309")
GREY = ("#f3f4f6", "#e5e7eb", "#4b5563")
RED = "#b91c1c"


# ---------------------------------------------------------------- formatting


def fmt_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def fmt_short(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def fmt_size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 100_000 else f"{max(n // 1000, 1)} KB"


def doc_count(n: int, t: DocType) -> str:
    return f"{n} {SINGULAR[t] if n == 1 else t.value}"


def join_and(items: list[str], word: str = "and") -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} {word} {items[1]}"
    return f"{', '.join(items[:-1])}, {word} {items[-1]}"


# ---------------------------------------------------------------- narrative (plain-text part)


def counts_sentence(counts: dict[DocType, int]) -> str:
    """'I found 13 Exhibits, 5 Key Documents, 21 Other Documents, and no Transcripts or Recordings (39 files in total).'"""
    present = [doc_count(counts[t], t) for t in DocType if counts[t]]
    absent = [t.value for t in DocType if not counts[t]]
    total = sum(counts.values())
    if not present:
        return f"I found no {join_and(absent, 'or')} in this matter."
    parts = present + ([f"no {join_and(absent, 'or')}"] if absent else [])
    files = "1 file" if total == 1 else f"{total} files"
    return f"I found {join_and(parts)} ({files} in total)."


def matter_paragraph(md: MatterMetadata, counts: dict[DocType, int]) -> str:
    sentences = [f"{md.matter} is about the {md.title.rstrip('.')}."]
    if md.category and md.type:
        sentences.append(f"It relates to {md.category} within the {md.type} category.")
    if md.date_received and md.date_final:
        sentences.append(
            f"The matter had an initial filing on {fmt_date(md.date_received)} "
            f"and a final filing on {fmt_date(md.date_final)}."
        )
    elif md.date_received:
        sentences.append(f"The matter had an initial filing on {fmt_date(md.date_received)} and no final filing yet.")
    if md.status:
        outcome = f" (outcome: {md.outcome})" if md.outcome else ""
        sentences.append(f"Its status is {md.status}{outcome}.")
    sentences.append(counts_sentence(counts))
    return " ".join(sentences)


def download_sentence(result: FetchResult, attaching_here: bool) -> str:
    req, t = result.request, result.request.doc_type
    available = result.counts[t]
    n = len(result.files)
    if not available:
        return f"There are no {t.value} in this matter, so there is nothing to download."
    if not n:
        return f"I found {doc_count(available, t)} but couldn't download any of them. " + "; ".join(result.failures) + "."
    if n == available:
        text = f"I downloaded all {doc_count(available, t)}"
    else:
        text = f"I downloaded {n} out of the {doc_count(available, t)}"
        text += f" ({_selection(req, n + len(result.failures))} as listed on the UARB site)"
    text += " and am attaching them as a ZIP here." if attaching_here else "."
    if result.failures:
        text += f" I couldn't download {len(result.failures)} of them: " + "; ".join(result.failures) + "."
    if result.skipped_for_size:
        text += " " + _recordings_note(result)
    return text


def _selection(req: DocRequest, n: int) -> str:
    return f"the first {n}" if req.start == 1 else f"numbers {req.start} to {req.start + n - 1}"


def _recordings_note(result: FetchResult) -> str:
    n = len(result.files)
    nxt = result.request.start + n
    size = sum(f.size for f in result.files)
    return (
        f"Recordings are large, so I stopped after {n} ({fmt_size(size)}) to keep the download manageable."
        f" To get the next ones, reply with something like \"send recordings {nxt}-{nxt + 2} for {result.request.matter}\"."
    )


# ---------------------------------------------------------------- reply data


@dataclass
class Reply:
    text: str
    html: str


@dataclass
class Notice:
    """A request that failed entirely, e.g. matter not found."""

    title: str
    detail: str


@dataclass
class ReplyParts:
    results: list[FetchResult]
    errors: list[Notice] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    delivery: Delivery | None = None  # None when there is no ZIP
    zip_size: int = 0
    link: str | None = None
    link_days: int = 7
    link_expires: date | None = None
    job_id: str = ""
    name: str = "there"  # for the greeting, see first_name()


def first_name(from_header: str) -> str:
    """'Jane Doe <jane@x.com>' -> 'Jane'. Falls back to 'there' when there's no usable display name."""
    name = parseaddr(from_header or "")[0].strip().strip("\"'")
    first = name.split()[0] if name else ""
    if not first or not first.replace("-", "").replace("'", "").isalpha():
        return "there"
    return first[0].upper() + first[1:]


# ---------------------------------------------------------------- HTML components


def _greeting(name: str) -> str:
    return f'<div style="font:15px {FONT};color:{BODY};margin:0 0 16px">Hi {escape(name)},</div>'


def _logo() -> str:
    return (
        f'<span style="display:inline-block;width:18px;height:18px;border-radius:5px;background:{ACCENT};'
        f'vertical-align:-4px;margin-right:8px"></span>{PRODUCT}'
    )


def _page(preheader: str, card: str, job_id: str, example: str) -> str:
    return (
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{escape(preheader)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE_BG}" '
        f'style="background:{PAGE_BG}"><tr><td align="center" style="padding:28px 12px">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">'
        f'<tr><td style="padding:0 4px 14px;font:600 14px {FONT};color:{INK}">{_logo()}</td></tr>'
        f"{card}"
        f'<tr><td style="padding:18px 8px;font:12px/1.6 {FONT};color:{FAINT};text-align:center">'
        f"Reply to this thread to ask for more, e.g. &quot;{escape(example)}&quot;.<br>"
        f'Data from the <a href="{SITE_URL}" style="color:{MUTED}">UARB public documents database</a>'
        f" &middot; Ref {escape(job_id)}</td></tr></table></td></tr></table>"
    )


def _card(sections: list[str]) -> str:
    """Stack sections into one rounded white card (rows keep borders continuous across email clients)."""
    rows = []
    last = len(sections) - 1
    for i, body in enumerate(sections):
        top, bottom = i == 0, i == last
        radius = {(True, True): "14px", (True, False): "14px 14px 0 0", (False, True): "0 0 14px 14px"}.get(
            (top, bottom), "0"
        )
        borders = f"border:1px solid {BORDER};" + ("" if top else "border-top:0;") + ("" if bottom else "border-bottom:0;")
        padding = f"{'30px' if top else '4px'} 32px {'28px' if bottom else '22px'}"
        rows.append(
            f'<tr><td bgcolor="#ffffff" style="background:#ffffff;{borders}border-radius:{radius};padding:{padding}">'
            f"{body}</td></tr>"
        )
    return "".join(rows)


def _label(text: str) -> str:
    return (
        f'<div style="font:600 11px {FONT};color:{MUTED};letter-spacing:.06em;text-transform:uppercase;'
        f'margin:0 0 10px">{text}</div>'
    )


def _pill(text: str, colors: tuple[str, str, str]) -> str:
    bg, border, fg = colors
    return (
        f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;background:{bg};'
        f'border:1px solid {border};font:600 11px {FONT};color:{fg};vertical-align:1px">&#9679; {text}</span>'
    )


def _button(label: str, href: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td bgcolor="{ACCENT}" '
        f'style="border-radius:8px;background:{ACCENT}"><a href="{escape(href)}" style="display:inline-block;'
        f'padding:11px 18px;font:600 14px {FONT};color:#ffffff;text-decoration:none;border-radius:8px">{label}</a>'
        f"</td></tr></table>"
    )


def _callout(lines: list[str], colors: tuple[str, str, str] = AMBER) -> str:
    bg, border, _ = colors
    items = "".join(f'<div style="margin:2px 0">{line}</div>' for line in lines)
    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:10px;padding:12px 14px;'
        f'font:14px/1.5 {FONT};color:{BODY}">{items}</div>'
    )


def _chip(key: str, value: str) -> str:
    return (
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:5px 10px;border:1px solid {BORDER};'
        f'border-radius:999px;font:13px {FONT};color:{MUTED};background:#ffffff">{key} '
        f'<b style="color:{INK};font-weight:600">{escape(value)}</b></span>'
    )


def _dot(color: str) -> str:
    return f'<div style="width:10px;height:10px;border-radius:50%;background:{color}"></div>'


def _timeline(md: MatterMetadata) -> str:
    if not md.date_received:
        return ""

    def point(color: str, name: str, value: str, value_color: str = INK) -> str:
        return (
            f'<td width="12" style="vertical-align:top;padding-top:5px">{_dot(color)}</td>'
            f'<td style="padding:0 0 0 8px;vertical-align:top"><div style="font:12px {FONT};color:{MUTED}">{name}</div>'
            f'<div style="font:600 14px {FONT};color:{value_color}">{value}</div></td>'
        )

    end = point(INK, "Final filing", fmt_short(md.date_final)) if md.date_final else point(
        "#d1d5db", "Final filing", "Not yet", FAINT
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px"><tr>'
        f'{point(ACCENT, "Initial filing", fmt_short(md.date_received))}'
        f'<td width="36%" style="vertical-align:top;padding-top:9px"><div style="border-top:2px dashed #d1d5db"></div></td>'
        f"{end}</tr></table>"
    )


def _about(md: MatterMetadata, with_title: bool) -> str:
    chips = "".join(
        _chip(k, v) for k, v in
        (("Category", md.category), ("Type", md.type), ("Status", md.status), ("Outcome", md.outcome)) if v
    )
    title = (
        f'<div style="font:600 15px/1.4 {FONT};color:{INK};margin:0 0 10px">'
        f'<span style="font:700 12px {MONO};color:{ACCENT}">{md.matter}</span>&nbsp; {escape(md.title)}</div>'
        if with_title else ""
    )
    return _label("About this matter") + title + chips + _timeline(md)


def _tiles(counts: dict[DocType, int]) -> str:
    cells = "".join(
        f'<td width="20%" style="padding:3px"><div style="border:1px solid {"#dbe4ff" if n else "#eef0f2"};'
        f'border-radius:10px;padding:10px 4px;text-align:center;background:{"#f5f8ff" if n else "#fafafa"}">'
        f'<div style="font:700 22px/1.2 {FONT};color:{INK if n else "#c4c8ce"}">{n}</div>'
        f'<div style="height:28px;font:500 11px/1.25 {FONT};color:{MUTED if n else FAINT};margin-top:2px">{t.value}</div>'
        f"</div></td>"
        for t, n in ((t, counts[t]) for t in DocType)
    )
    total = sum(counts.values())
    return (
        _label(f"Files in this matter &nbsp;&middot;&nbsp; {total} total")
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'
    )


def _file_list(result: FetchResult, heading: str) -> str:
    rows = "".join(
        f'<tr><td style="padding:10px 0;border-top:1px solid {LINE};font:12px {MONO};color:{ACCENT};width:66px;'
        f'vertical-align:top">{escape(f.row.doc_no or "")}</td>'
        f'<td style="padding:10px 8px;border-top:1px solid {LINE};font:14px/1.35 {FONT};color:{INK}">'
        f"{escape(f.row.title)}"
        f'<div style="font:12px {FONT};color:{MUTED};margin-top:2px">{fmt_short(f.row.date) if f.row.date else ""}</div>'
        f'</td><td align="right" style="padding:10px 0;border-top:1px solid {LINE};font:12px {FONT};color:{MUTED};'
        f'white-space:nowrap;vertical-align:top">{fmt_size(f.size)}</td></tr>'
        for f in result.files
    )
    return _label(heading) + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>'


def _delivery_html(result: FetchResult, attached_single: bool) -> str:
    t, n = result.request.doc_type, len(result.files)
    available = result.counts[t]
    muted = f'<span style="color:{MUTED}">'
    if not available:
        return f"There are no <b>{t.value}</b> in {result.request.matter}, so there&rsquo;s nothing to download."
    if not n:
        return f"I couldn&rsquo;t download any of the <b>{doc_count(available, t)}</b> in {result.request.matter}."
    if n == available:
        text = f"Downloaded <b style=\"color:{INK}\">all {doc_count(available, t)}</b>"
    else:
        text = (
            f'Downloaded <b style="color:{INK}">{n} of {available} {t.value}</b> '
            f"{muted}({_selection(result.request, n + len(result.failures))} as listed on the UARB site)</span>"
        )
    return text + (" and attached them as a ZIP." if attached_single else ".")


def _status(p: ReplyParts) -> tuple[str, tuple[str, str, str]]:
    files = sum(len(r.files) for r in p.results)
    partial = p.errors or any(r.failures or r.skipped_for_size for r in p.results)
    if not files:
        return "No files", GREY
    return ("Partially ready", AMBER) if partial else ("Ready", GREEN)


def _example(p: ReplyParts) -> str:
    matter = p.results[0].request.matter if p.results else "M12205"
    return f"send 5 Exhibits for {matter}"


# ---------------------------------------------------------------- result email


def compose_result(p: ReplyParts) -> Reply:
    if not p.results:
        return _compose_errors_only(p)
    return Reply(text=_result_text(p), html=_result_html(p))


def _result_text(p: ReplyParts) -> str:
    attached = p.delivery in (Delivery.INLINE, Delivery.URL_ATTACHMENT)
    single = len(p.results) == 1
    status, _ = _status(p)
    head = p.results[0].metadata if single else None
    lines = [f"Hi {p.name},", "", f"{head.matter} - {head.title}" if head else "Your UARB documents", status, ""]
    seen: set[str] = set()
    for r in p.results:
        sentence = download_sentence(r, attaching_here=attached and single)
        if r.metadata.matter not in seen:
            seen.add(r.metadata.matter)
            lines += [matter_paragraph(r.metadata, r.counts) + " " + sentence, ""]
        else:
            lines += [sentence, ""]
    lines += [f"{e.title}. {e.detail}" for e in p.errors] + p.notes
    if p.errors or p.notes:
        lines.append("")
    if p.link:
        until = f", until {fmt_date(p.link_expires)}" if p.link_expires else ""
        if p.delivery is Delivery.LINK_ONLY:
            lines.append(f"The ZIP is {fmt_size(p.zip_size)}, which is too large to attach to an email.")
        elif not single:
            lines.append(f"All the files are attached in one ZIP ({fmt_size(p.zip_size)}).")
        lines += [f"Download the ZIP (link valid for {p.link_days} days{until}):", p.link, ""]
    for r in p.results:
        if r.files:
            lines.append(f"Files: {r.request.matter} {r.request.doc_type.value}")
            for f in r.files:
                when = fmt_short(f.row.date) if f.row.date else "no date"
                lines.append(f"  {f.row.doc_no or '-'}  {f.row.title}  ({when}, {fmt_size(f.size)})")
            lines.append("")
    lines += ["--", f'Reply to this thread to ask for more, e.g. "{_example(p)}".', f"{PRODUCT} - Ref {p.job_id}"]
    return "\n".join(lines)


def _result_html(p: ReplyParts) -> str:
    attached = p.delivery in (Delivery.INLINE, Delivery.URL_ATTACHMENT)
    single = len(p.results) == 1
    status, colors = _status(p)
    first = p.results[0]

    # Header: what this is, what happened, the one action.
    if single:
        kicker = f'<span style="font:700 13px {MONO};color:{ACCENT}">{first.metadata.matter}</span>&nbsp; '
        headline = escape(first.metadata.title)
    else:
        kicker = f'<span style="font:600 13px {FONT};color:{ACCENT}">{len(p.results)} requests</span>&nbsp; '
        headline = "Your documents from " + join_and(sorted({escape(r.request.matter) for r in p.results}))
    deliveries = "".join(
        f'<div style="margin:0 0 6px">{_delivery_html(r, attached and single)}</div>' for r in p.results
    )
    header = (
        _greeting(p.name)
        + f"<div>{kicker}{_pill(status, colors)}</div>"
        f'<h1 style="margin:10px 0 14px;font:700 21px/1.35 {FONT};color:{INK}">{headline}</h1>'
        f'<div style="font:15px/1.5 {FONT};color:{BODY};margin:0 0 16px">{deliveries}</div>'
    )
    if p.link:
        expires = f"link expires {fmt_short(p.link_expires)}" if p.link_expires else f"link valid {p.link_days} days"
        if p.delivery is Delivery.LINK_ONLY:
            sub = f"Too large to attach to an email &middot; {expires}"
        else:
            sub = f"{'Attached to this email' if single else 'All files attached as one ZIP'} &middot; {expires}"
        header += (
            _button(f"Download ZIP &nbsp;&middot;&nbsp; {fmt_size(p.zip_size)}", p.link)
            + f'<div style="font:12px {FONT};color:{MUTED};margin-top:9px">{sub}</div>'
        )
    sections = [header]

    # Anything the user should know that isn't "it worked".
    notices = [f"<b>{escape(e.title)}.</b> {escape(e.detail)}" for e in p.errors]
    for r in p.results:
        if r.failures:
            notices.append(
                f"<b>Couldn&rsquo;t download {len(r.failures)} file{'s' if len(r.failures) > 1 else ''}</b> "
                f"({escape(r.request.matter)} {r.request.doc_type.value}): " + escape("; ".join(r.failures))
            )
        if r.skipped_for_size:
            notices.append(escape(_recordings_note(r)))
    notices += [escape(n) for n in p.notes]
    if notices:
        sections.append(_callout(notices))

    # Facts per matter, then the files per request.
    seen: set[str] = set()
    for r in p.results:
        if r.metadata.matter in seen:
            continue
        seen.add(r.metadata.matter)
        sections += [_about(r.metadata, with_title=not single), _tiles(r.counts)]
    for r in p.results:
        if r.files:
            heading = "In this ZIP" if single else f"In this ZIP &nbsp;&middot;&nbsp; {r.request.matter} {r.request.doc_type.value}"
            sections.append(_file_list(r, heading))

    preheader = _strip_tags(" ".join(_delivery_html(r, attached and single) for r in p.results))
    return _page(preheader, _card(sections), p.job_id, _example(p))


def _strip_tags(html_fragment: str) -> str:
    """Crude tag strip for the inbox preview line."""
    out, inside = [], False
    for ch in html_fragment:
        if ch == "<":
            inside = True
        elif ch == ">":
            inside = False
        elif not inside:
            out.append(ch)
    return "".join(out).replace("&rsquo;", "'").replace("&middot;", "-")


def _compose_errors_only(p: ReplyParts) -> Reply:
    if len(p.errors) == 1:
        e = p.errors[0]
        return _short("Couldn't complete", AMBER[2], e.title, e.detail, p.job_id, name=p.name)
    detail = " ".join(f"{e.title}. {e.detail}" for e in p.errors)
    body = "".join(f'<div style="margin:0 0 8px"><b>{escape(e.title)}.</b> {escape(e.detail)}</div>' for e in p.errors)
    return _short("Couldn't complete", AMBER[2], "I couldn't fetch your documents", detail, p.job_id,
                  body_html=body, name=p.name)


# ---------------------------------------------------------------- short emails


def _short(kicker: str, color: str, headline: str, text: str, job_id: str, body_html: str | None = None,
           example: str = "send 5 Exhibits for M12205", name: str = "there") -> Reply:
    body = body_html if body_html is not None else escape(text)
    content = (
        _greeting(name)
        + f'<div style="font:600 12px {FONT};color:{color};letter-spacing:.04em;text-transform:uppercase">{kicker}</div>'
        + f'<h1 style="margin:8px 0 10px;font:700 20px/1.35 {FONT};color:{INK}">{escape(headline)}</h1>'
        + f'<div style="font:15px/1.6 {FONT};color:{BODY}">{body}</div>'
    )
    card = _card([content])
    plain = "\n".join([f"Hi {name},", "", headline, "", text, "", "--", f"{PRODUCT} - Ref {job_id}"])
    return Reply(text=plain, html=_page(f"{headline}. {text}", card, job_id, example))


def compose_ack(requests: list[DocRequest], job_id: str, name: str = "there") -> Reply:
    asks = join_and([f"{r.doc_type.value} for {r.matter}" for r in requests])
    slow = any(r.doc_type is DocType.RECORDINGS for r in requests)
    eta = "Recordings are large, so this can take 10-15 minutes." if slow else "This usually takes 1-3 minutes."
    return _short("Working on it", ACCENT, f"Fetching {asks}",
                  f"{eta} I'll reply in this thread with the files.", job_id,
                  example=f"send 5 Exhibits for {requests[0].matter}", name=name)


def compose_clarification(question: str, job_id: str, name: str = "there") -> Reply:
    return _short("Quick question", ACCENT, "I need one more detail", question, job_id, name=name)


def compose_rate_limited(job_id: str, name: str = "there") -> Reply:
    return _short(
        "Limit reached", AMBER[2], "You've reached the hourly limit",
        "To keep this free demo within its email quota, each sender can make a few requests per hour. "
        "Please try again in an hour.", job_id, name=name,
    )


def compose_not_allowed(job_id: str, name: str = "there") -> Reply:
    return _short("Not available", MUTED, "This agent only serves approved senders",
                  "Your address isn't on the list for this deployment.", job_id, name=name)


def compose_failure(job_id: str, name: str = "there") -> Reply:
    return _short(
        "Something went wrong", RED, "I couldn't finish this request",
        "Something failed on my side while handling your email. Please send it again in a few minutes. "
        "If it keeps failing, quote the reference below.", job_id, name=name,
    )
