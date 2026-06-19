import re


def _filename_component(value: str | None) -> str:
    """Return a readable, filesystem-safe filename component."""
    component = re.sub(r"[^A-Za-z0-9]+", "_", (value or "").strip())
    component = re.sub(r"_+", "_", component).strip("_")
    return component or "Untitled"


def tailored_artifact_stem(
    candidate_name: str | None,
    company: str | None,
    position: str | None,
) -> str:
    """Readable artifact stem: Name_Company_Position."""
    return "_".join(
        [
            _filename_component(candidate_name),
            _filename_component(company),
            _filename_component(position),
        ]
    )


def tailored_artifact_filename(
    candidate_name: str | None,
    company: str | None,
    position: str | None,
    extension: str,
) -> str:
    """Readable artifact filename, e.g. Jane_Candidate_Acme_AI_Engineer.pdf."""
    ext = re.sub(r"[^A-Za-z0-9]+", "", extension or "").lower() or "pdf"
    return f"{tailored_artifact_stem(candidate_name, company, position)}.{ext}"


def compact_artifact_label(filename: str, max_chars: int = 42) -> str:
    """Compact a long filename for UI display while preserving the extension."""
    text = str(filename or "").strip()
    if len(text) <= max_chars:
        return text

    dot_index = text.rfind(".")
    suffix = text[dot_index:] if dot_index > 0 else ""
    available = max_chars - len(suffix) - 3
    if available < 8:
        return text[:max_chars]
    return f"{text[:available]}...{suffix}"
