"""Indexing pipeline (Phase 4.2, step 2): story bank -> Chroma vector store.

Mentor note: this is normally the USER's hand-written RAG piece. Written here at
the user's request; the high-value learning is in REVIEWING it (see "Review
focus" below), not typing it.

This is the INDEXING half of RAG (the offline half):

    load (data/stories/*.md) -> split (RecursiveCharacterTextSplitter)
        -> embed (get_embeddings()) -> store (Chroma, persisted to data/stores/)

The RETRIEVAL + GENERATION half (embed query -> similarity search -> grounded
LCEL chain) is the NEXT task and will live in phase4_prep/generate_prep.py.

Design decisions (be ready to defend each in an interview):
  * Loader uses pathlib + read_text, NOT DirectoryLoader, to (a) avoid the
    deprecated langchain-community dependency and (b) control the skip rule:
    files starting with "_" (_TEMPLATE.md, _EXAMPLE.md) are NOT real stories.
  * Each story becomes a Document carrying metadata (source filename + title).
    Metadata is how a retrieved chunk can later be cited back to its story.
  * Splitter is markdown-aware (separators favour STAR headings, then blank
    lines) so a chunk tends to be a coherent Situation/Task/Action/Result piece
    rather than text cut mid-thought. chunk_size/overlap are tuned for short
    STAR stories and are the #1 thing to experiment with.
  * Embeddings come ONLY from get_embeddings() (provider-agnostic) — never a
    hardcoded model. The SAME model must embed corpus AND query later, or the
    vectors live in different spaces and similarity is meaningless.
  * Re-runs are idempotent: the collection is CLEARED before re-adding, so
    re-indexing never silently appends duplicate chunks (Chroma.from_documents
    on its own APPENDS). Trade-off: this re-embeds the whole corpus each run —
    fine here (a few small stories, run by hand) and the safest correctness
    choice. At scale you'd upsert incrementally keyed on a content hash so
    unchanged stories aren't re-embedded.

Review focus (your learning targets while reviewing):
  1. Chunking: why split at all? what do chunk_size and chunk_overlap trade off?
     (overlap = boundary context, NOT speed; too big = diluted embedding +
     lost-in-the-middle). Change the numbers and watch retrieval change.
  2. Document + metadata: why wrap text in Document and attach source/title?
  3. Idempotency: why does from_documents duplicate on re-run, and how does
     clear-then-rebuild fix it? What would the incremental-hash version do?
  4. get_embeddings(): why must the query embedding use this SAME factory later?
  5. Persistence: why persist to disk (data/stores/) vs in-memory? (cost — don't
     re-embed on every process start; same reasoning as choosing SQLite).

Run:  python -m phase4_prep.index_stories
"""
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

from config.settings import get_embeddings

# Anchored to the repo root via __file__ so it runs from anywhere.
ROOT_DIR = Path(__file__).resolve().parents[1]
STORIES_DIR = ROOT_DIR / "data" / "stories"
STORE_DIR = ROOT_DIR / "data" / "stores" / "story_bank"
COLLECTION_NAME = "story_bank"

# Tuned for short STAR stories. Markdown-aware separators keep a STAR section
# together before falling back to paragraph -> line -> word -> char.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
_SEPARATORS = ["\n## ", "\n### ", "\n\n", "\n", " ", ""]


def _title_of(text: str, fallback: str) -> str:
    """Pull the '# Title: ...' line for citation metadata; fall back to filename."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("# title:"):
            return stripped.split(":", 1)[1].strip()
    return fallback


def load_story_documents() -> list[Document]:
    """Load real stories as Documents, skipping underscore-prefixed files."""
    files = sorted(
        p for p in STORIES_DIR.glob("*.md") if not p.name.startswith("_")
    )
    if not files:
        raise FileNotFoundError(
            f"No story files found in {STORIES_DIR} "
            f"(underscore-prefixed files are skipped). Add real STAR stories first."
        )

    docs: list[Document] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        docs.append(
            Document(
                page_content=text,
                metadata={"source": path.name, "title": _title_of(text, path.stem)},
            )
        )
    return docs


def index_stories() -> int:
    """Build/refresh the story-bank vector store. Returns the chunk count.

    Idempotent: clears the existing collection first so re-runs don't duplicate.
    """
    docs = load_story_documents()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=_SEPARATORS,
    )
    chunks = splitter.split_documents(docs)

    embeddings = get_embeddings()
    STORE_DIR.mkdir(parents=True, exist_ok=True)

    # Instantiating Chroma get-or-creates the collection; delete it so this run
    # rebuilds from scratch (no duplicate chunks on re-index).
    Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(STORE_DIR),
    ).delete_collection()

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(STORE_DIR),
    )
    return len(chunks)


if __name__ == "__main__":
    story_count = len(load_story_documents())
    chunk_count = index_stories()
    print(f"Indexed {story_count} stories -> {chunk_count} chunks into {STORE_DIR}")
