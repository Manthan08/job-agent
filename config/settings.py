import os

import truststore
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# Trust the OS (Windows) certificate store so the corporate proxy's root CA is
# recognized. Must run before any HTTPS call is made.
truststore.inject_into_ssl()

# Load the .env file
load_dotenv()

def get_llm():

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    llm_model = os.getenv("OPENAI_MODEL")

    if not all([api_key, base_url, llm_model]):
        raise ValueError("Please ensure OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL are set in the .env file.")

    return ChatOpenAI(
        api_key = api_key,
        base_url = base_url,
        model = llm_model,
        temperature = 0,
    )

def get_embeddings():
    """Provider-agnostic embeddings factory (mirrors get_llm).

    Reads the same OpenAI-compatible endpoint as chat, plus a separate
    OPENAI_EMBEDDING_MODEL, so RAG embeddings stay swappable with no code change.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    embed_model = os.getenv("OPENAI_EMBEDDING_MODEL")

    if not all([api_key, base_url, embed_model]):
        raise ValueError("Please ensure OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_EMBEDDING_MODEL are set in the .env file.")

    return OpenAIEmbeddings(
        model = embed_model,
        api_key = api_key,
        base_url = base_url,
    )

if __name__ == "__main__":

    print(get_llm().invoke("Reply with exactly hello"))
    print("embedding dim:", len(get_embeddings().embed_query("hello")))

