import sys
from pathlib import Path
from pypdf import PdfReader
from models.resume import ResumeModel
from config.settings import get_llm
from db.resume_repository import save_resume_to_db


def extract_pdf_text(
    resume_path,
    max_pages: int | None = None,
    max_chars: int | None = None,
) -> str:
    """Read a resume PDF and return its concatenated text.

    `extract_text()` can return None for image/empty pages, so we coalesce to ""
    to avoid a TypeError when concatenating.
    """
    text = ""
    with open(resume_path, "rb") as file:
        reader = PdfReader(file)
        if max_pages is not None and len(reader.pages) > max_pages:
            raise ValueError(f"PDF has too many pages. Limit is {max_pages}.")
        for page in reader.pages:
            text += page.extract_text() or ""
            if max_chars is not None and len(text) > max_chars:
                raise ValueError(
                    f"PDF text is too long. Limit is {max_chars} characters."
                )
    return text


def parse_resume_text(text: str) -> ResumeModel:
    """Extract a structured ResumeModel from raw resume text via the LLM.

    The extraction chain (prompt + structured output) is unchanged; it was only
    lifted out of __main__ so the web app can reuse it for both PDF uploads and
    the quick profile builder.
    """
    structured_llm = get_llm().with_structured_output(ResumeModel)
    return structured_llm.invoke(f"""
                                        Extract structured resume data from the resume text below.

                                        Rules:
                                        - Use only information present in the resume text.
                                        - Do not guess or add extra information.
                                        - If an optional field is missing, set it to null.
                                        - If a list field has no values, return an empty list.
                                        - For `urls`, include ONLY the candidate's personal profile/contact links
                                          from the header/contact area (LinkedIn, portfolio/website, GitHub profile).
                                          Do NOT include URLs that belong to specific projects, employers, or articles.
                                        - Follow the ResumeModel schema.

                                        Resume text:
                                        {text}
                                        """)


if __name__ == "__main__":

        HERE = Path(__file__).resolve().parent.parent
        my_resume_path = HERE / "data" / "resumes" / "sample_resume.pdf"

        resume_path = sys.argv[1] if len(sys.argv) > 1 else my_resume_path

        try:
            text = extract_pdf_text(resume_path)

            # Parse the structured resume to llm via ResumeModel
            resume = parse_resume_text(text)

            print(resume.model_dump_json(indent=2))

            resume_id = save_resume_to_db(resume, resume_path)
            print(f"Resume saved with ID: {resume_id}")

        except Exception as e:
            print(f"An error occurred while parsing the resume: {e}")
