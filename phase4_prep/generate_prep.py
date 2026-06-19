"""Phase 4.2 step 3 — RETRIEVAL + GENERATION (the RAG chain).

This is the second half of RAG. The first half (phase4_prep/index_stories.py)
already embedded the candidate's STAR stories into a persisted Chroma store.
Here we, for one job:

    JD text --> retrieve the most relevant story chunks (vector similarity)
            --> stuff them as grounded CONTEXT into a prompt
            --> LLM generates a structured InterviewPrepPack

Why RAG and not "put every story in the prompt"? A real candidate accumulates
dozens of stories; we only want the few relevant to THIS job (cost + precision).
Selective retrieval per job IS the point.

Grounding: the prompt forbids inventing experience. Anything the JD wants but no
retrieved story supports must be flagged as a gap (is_gap / study_topics), never
fabricated — the same structural anti-hallucination rule used in tailoring.

Design notes (interview-defensible):
  * We open the SAME Chroma collection the indexer wrote, with the SAME
    get_embeddings() factory — query and corpus MUST share an embedding space.
  * Retriever uses MMR (max-marginal-relevance) so the k chunks are relevant AND
    diverse, instead of 5 near-duplicate chunks from one story.
  * format_docs() prefixes each chunk with its story title so the model (and the
    grounded_in citations) can attribute answers to a specific story.
  * The chain is idiomatic LCEL: a dict of {context, job_text} -> prompt ->
    structured LLM. RunnablePassthrough feeds the same JD string to both the
    retriever (as the search query) and the prompt.

Run:  python -m phase4_prep.generate_prep
"""
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from config.settings import get_embeddings, get_llm
from models.preparation import InterviewPrepPack
from phase4_prep.index_stories import COLLECTION_NAME, STORE_DIR
from phase3_score.score_match import job_to_text
from db.job_repository import get_job_by_id
from db.resume_repository import get_resume_by_id
from db.preparation_repository import get_application_id, save_prep_to_db


def get_retriever(k: int = 6, fetch_k: int = 12):
    """Open the persisted story-bank store and return an MMR retriever."""
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(STORE_DIR),
    )
    return vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"k": k, "fetch_k": fetch_k},
    )


def format_docs(docs: list[Document]) -> str:
    """Render retrieved chunks as titled context blocks for the prompt."""
    blocks = []
    for doc in docs:
        title = doc.metadata.get("title", doc.metadata.get("source", "story"))
        blocks.append(f"[Story: {title}]\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks) if blocks else "(no relevant stories found)"


def generate_prep_for_job(job_text: str) -> InterviewPrepPack:
    """Retrieve relevant stories for a JD and generate a grounded prep pack."""
    retriever = get_retriever()

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an interview coach preparing a candidate for a SPECIFIC job.\n"
         "You are given the job description and CONTEXT: the candidate's real "
         "career stories retrieved from their story bank.\n\n"
         "Rules:\n"
         "- Generate the interview questions THIS job is likely to ask, derived "
         "from the job description.\n"
         "- Answer each question using ONLY the candidate's stories in CONTEXT. "
         "Cite concrete projects, decisions, tradeoffs, and numbers from them.\n"
         "- Set grounded_in to the story titles an answer relies on.\n"
         "- If the job needs something NO story supports, set is_gap=True, leave "
         "grounded_in empty, make the answer a short study pointer, and add the "
         "topic to study_topics. NEVER invent experience not in the stories.\n"
         "- Prioritize questions by how central they are to the role."),
        ("user",
         "JOB DESCRIPTION:\n{job_text}\n\n"
         "CONTEXT (candidate's retrieved stories):\n{context}\n\n"
         "Produce a structured InterviewPrepPack."),
    ])

    structured_llm = get_llm().with_structured_output(InterviewPrepPack)

    # LCEL: the JD string is passed through to both the retriever (search query)
    # and the prompt; retrieved docs are formatted into {context}.
    chain = (
        {
            "context": retriever | format_docs,
            "job_text": RunnablePassthrough(),
        }
        | prompt
        | structured_llm
    )

    return chain.invoke(job_text)


if __name__ == "__main__":
    RESUME_ID = 1
    JOB_ID = 4  # the .NET + Azure OpenAI + RAG role (your strong match)

    resume = get_resume_by_id(RESUME_ID)
    job = get_job_by_id(JOB_ID)
    if resume is None:
        raise SystemExit(f"No resume with Id={RESUME_ID}. Run Phase 1 first.")
    if job is None:
        raise SystemExit(f"No job with Id={JOB_ID}. Ingest a job first.")

    application_id = get_application_id(RESUME_ID, JOB_ID)
    if application_id is None:
        raise SystemExit(
            f"No application for resume {RESUME_ID} x job {JOB_ID}. "
            f"Run phase3_score.score_match first."
        )

    pack = generate_prep_for_job(job_to_text(job))
    print(pack.model_dump_json(indent=2))

    prep_id = save_prep_to_db(application_id, pack)
    print(f"\nSaved prep pack (PreparationMaterials Id={prep_id}) "
          f"for application {application_id}: "
          f"{len(pack.questions)} questions, {len(pack.study_topics)} study topics.")
