"""Email wording. Every fact comes from the scraper through these templates (the LLM never writes facts),
following the style of the assignment's example reply."""

from dataclasses import dataclass, field
from datetime import date
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
SIGNATURE = "UARB Document Agent"


def fmt_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


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
        last = req.start + n - 1
        text += f" ({'the first ' + str(n) if req.start == 1 else f'numbers {req.start} to {last}'} as listed on the UARB site)"
    text += " and am attaching them as a ZIP here." if attaching_here else "."
    if result.failures:
        text += f" I couldn't download {len(result.failures)} of them: " + "; ".join(result.failures) + "."
    if result.skipped_for_size:
        nxt = req.start + n
        size = sum(f.size for f in result.files)
        text += (
            f" Recordings are large, so I stopped after {n} ({fmt_size(size)}) to keep the download manageable."
            f" To get the next ones, reply with something like \"send recordings {nxt}-{nxt + 2} for {req.matter}\"."
        )
    return text


@dataclass
class Reply:
    text: str
    html: str


@dataclass
class ReplyParts:
    results: list[FetchResult]
    errors: list[str] = field(default_factory=list)  # requests that failed entirely (e.g. matter not found)
    notes: list[str] = field(default_factory=list)
    delivery: Delivery | None = None  # None when there is no ZIP
    zip_size: int = 0
    link: str | None = None
    link_days: int = 7
    job_id: str = ""


def compose_result(p: ReplyParts) -> Reply:
    paragraphs: list[str] = []
    attached = p.delivery in (Delivery.INLINE, Delivery.URL_ATTACHMENT)
    single = len(p.results) == 1
    seen: dict[str, MatterMetadata] = {}
    for r in p.results:
        sentence = download_sentence(r, attaching_here=attached and single)
        if r.metadata.matter not in seen:
            seen[r.metadata.matter] = r.metadata
            paragraphs.append(matter_paragraph(r.metadata, r.counts) + " " + sentence)
        else:
            paragraphs.append(sentence)
    paragraphs += p.errors + p.notes
    if p.delivery is Delivery.LINK_ONLY:
        paragraphs.append(
            f"The ZIP is {fmt_size(p.zip_size)}, which is too large to attach to an email, "
            f"so you can download it here (link valid for {p.link_days} days): {p.link}"
        )
    elif p.delivery is not None:
        if not single:
            paragraphs.append(f"All the files are attached in one ZIP ({fmt_size(p.zip_size)}).")
        paragraphs.append(f"You can also download the ZIP here (link valid for {p.link_days} days): {p.link}")
    return _render(paragraphs, p.results, p.job_id)


def _render(paragraphs: list[str], results: list[FetchResult], job_id: str) -> Reply:
    files = [(r, f) for r in results for f in r.files]
    multi = len(results) > 1
    lines = ["Hi,", "", *[x for para in paragraphs for x in (para, "")]]
    if files:
        lines.append("Files:")
        for r, f in files:
            prefix = f"[{r.request.matter} {r.request.doc_type.value}] " if multi else ""
            when = fmt_date(f.row.date) if f.row.date else "no date"
            lines.append(f"- {prefix}{f.row.doc_no or '-'} | {f.row.title} | {when} | {fmt_size(f.size)}")
        lines.append("")
    lines += [f"{SIGNATURE} (ref {job_id})"]

    html_paras = "".join(f"<p>{_linkify(para)}</p>" for para in paragraphs)
    table = ""
    if files:
        head = "".join(
            f'<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #ccc">{h}</th>'
            for h in ((["Matter", "Type"] if multi else []) + ["Doc #", "Title", "Date", "Size"])
        )
        body = ""
        for r, f in files:
            cells = ([r.request.matter, r.request.doc_type.value] if multi else []) + [
                f.row.doc_no or "-", f.row.title, fmt_date(f.row.date) if f.row.date else "-", fmt_size(f.size),
            ]
            body += "<tr>" + "".join(f'<td style="padding:4px 8px">{escape(c)}</td>' for c in cells) + "</tr>"
        table = f'<table style="border-collapse:collapse;font-size:14px"><tr>{head}</tr>{body}</table>'
    html = (
        f'<div style="font-family:Arial,sans-serif;font-size:14px"><p>Hi,</p>{html_paras}{table}'
        f'<p style="color:#666">{SIGNATURE} (ref {escape(job_id)})</p></div>'
    )
    return Reply(text="\n".join(lines), html=html)


def _linkify(text: str) -> str:
    out = []
    for word in text.split(" "):
        if word.startswith("https://"):
            out.append(f'<a href="{escape(word)}">download link</a>')
        else:
            out.append(escape(word))
    return " ".join(out)


def _simple(text: str, job_id: str) -> Reply:
    lines = ["Hi,", "", text, "", f"{SIGNATURE} (ref {job_id})"]
    html = (
        f'<div style="font-family:Arial,sans-serif;font-size:14px"><p>Hi,</p><p>{escape(text)}</p>'
        f'<p style="color:#666">{SIGNATURE} (ref {escape(job_id)})</p></div>'
    )
    return Reply(text="\n".join(lines), html=html)


def compose_ack(requests: list[DocRequest], job_id: str) -> Reply:
    asks = join_and([f"{r.doc_type.value} for {r.matter}" for r in requests])
    slow = any(r.doc_type is DocType.RECORDINGS for r in requests)
    eta = "Recordings are large, so this can take 10-15 minutes." if slow else "This usually takes 1-3 minutes."
    return _simple(f"Got it: fetching {asks} from the UARB site. {eta} I'll reply here when it's ready.", job_id)


def compose_clarification(question: str, job_id: str) -> Reply:
    return _simple(question, job_id)


def compose_rate_limited(job_id: str) -> Reply:
    return _simple(
        "You've reached the limit of requests for now (it keeps this free demo within its email quota). "
        "Please try again in an hour.", job_id,
    )


def compose_not_allowed(job_id: str) -> Reply:
    return _simple("Sorry, this agent only serves approved senders.", job_id)


def compose_failure(job_id: str) -> Reply:
    return _simple(
        "Something went wrong on my side while handling your request, so I couldn't finish it. "
        "Please send it again in a few minutes. If it keeps failing, quote the reference below.", job_id,
    )
