"""Central LLM + embeddings factory.

Provider: NVIDIA NIM (Nemotron) via `langchain-nvidia-ai-endpoints`.

The whole app talks to the model ONLY through `get_llm()` / `get_embeddings()`,
and every phase relies on `.with_structured_output(PydanticModel)`. So the model
is configured here for *reliable structured JSON*:

  - temperature 0 (deterministic) by default
  - reasoning / "thinking" disabled by default (a visible thinking trace fights
    with strict structured output and wastes tokens/latency)

Everything is overridable from `.env` so you can swap models without code changes.

Quick smoke test:
    python -m config.settings
"""

import os
import warnings

from dotenv import load_dotenv

# langchain-nvidia warns that `chat_template_kwargs` isn't a native ChatNVIDIA
# field and moves it into `model_kwargs` — which is exactly what we want (it
# forwards `enable_thinking: false` to the NIM API, verified to cut output from
# 63 reasoning tokens to 2). The warning is cosmetic and fires on every call, so
# silence it to keep the timing logs readable.
warnings.filterwarnings(
    "ignore", message=".*chat_template_kwargs is not default parameter.*"
)

# Trust the OS certificate store so a corporate proxy's root CA is recognized.
# Best-effort: only needed behind some corporate networks; never crash startup.
try:  # pragma: no cover - environment dependent
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover
    pass

# Load the .env file
load_dotenv()


def _env(*names, default=None):
    """First non-empty value among several env var names.

    Accepts NVIDIA_* names while staying backward compatible with older OPENAI_*
    names that older .env files use.
    """
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def _as_bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Defaults; override any of these via .env.
DEFAULT_NVIDIA_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_EMBEDDING_MODEL = "nvidia/nv-embedqa-e5-v5"


def _default_model() -> str:
    """The app-wide model when no per-task override is set."""
    return _env("NVIDIA_MODEL", "OPENAI_MODEL", default=DEFAULT_NVIDIA_MODEL)


def fast_model() -> str:
    """Model for mechanical structured tasks (score, keyword-classify, coach).

    These are JSON-shaped, low-creativity calls where a smaller/faster Nemotron is
    just as accurate but ~2-3x quicker. Falls back to the app-wide model.
    """
    return _env("NVIDIA_MODEL_FAST", default=_default_model())


def tailor_model() -> str:
    """Model for resume tailoring (the one quality-sensitive generation)."""
    return _env("NVIDIA_MODEL_TAILOR", default=_default_model())


def parse_model() -> str:
    """Model for resume PARSING (runs once per upload).

    Parsing is accuracy-critical — every downstream tailor reuses the factual
    fields it extracts (education, projects, location, contact) — and it happens
    only once, so it favors a more capable model over the fast tier. Defaults to
    the capable DEFAULT_NVIDIA_MODEL (49B) *independently* of NVIDIA_MODEL, so
    running a nano base for the per-tailor mechanical calls doesn't degrade
    parsing. Override with NVIDIA_MODEL_PARSE.
    """
    return _env("NVIDIA_MODEL_PARSE", default=DEFAULT_NVIDIA_MODEL)


# Provider prefixes that route get_llm() to a non-NVIDIA backend. A model id like
# "groq/llama-3.3-70b-versatile" selects ChatGroq; "google/gemini-2.0-flash" selects
# Gemini. Anything else (incl. "nvidia/...") stays on ChatNVIDIA — the quality baseline.
_KNOWN_PROVIDERS = {"groq", "google", "gemini"}


def _split_provider(model: str) -> tuple[str, str]:
    """('groq', 'llama-3.3-70b') from 'groq/llama-3.3-70b'. Defaults to NVIDIA,
    keeping the FULL id (ChatNVIDIA expects the 'nvidia/...' prefix)."""
    head, _, rest = model.partition("/")
    if head in _KNOWN_PROVIDERS and rest:
        return head, rest
    return "nvidia", model


def get_llm(model: str | None = None, *, max_tokens: int | None = None):
    """Return a chat model configured for reliable structured output.

    Provider is chosen by the model id's prefix (see _split_provider): NVIDIA NIM
    by default (the quality baseline), or Groq / Google Gemini when prefixed. Every
    backend supports `.with_structured_output`, so invoke_structured is unchanged.

    Pass `model` to override per call (see fast_model() / tailor_model() /
    parse_model()). Pass `max_tokens` to cap output for a specific call.

    Reads: LLM_TEMPERATURE (default 0), LLM_MAX_TOKENS (default 4096), plus the
    selected provider's API key (NVIDIA_API_KEY / GROQ_API_KEY / GOOGLE_API_KEY).
    """
    model = model or _default_model()
    provider, model_id = _split_provider(model)

    temperature = float(_env("LLM_TEMPERATURE", default="0"))
    if max_tokens is None:
        max_tokens = int(_env("LLM_MAX_TOKENS", default="4096"))

    if provider == "groq":
        from langchain_groq import ChatGroq

        api_key = _env("GROQ_API_KEY")
        if not api_key:
            raise ValueError("Set GROQ_API_KEY to use a groq/* model.")
        return ChatGroq(
            model=model_id, api_key=api_key, temperature=temperature, max_tokens=max_tokens
        )

    if provider in {"google", "gemini"}:
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = _env("GOOGLE_API_KEY", "GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Set GOOGLE_API_KEY to use a google/* model.")
        kwargs = dict(
            model=model_id,
            google_api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        # Gemini 2.5/3.x flash "think" before answering, which ~doubles latency for
        # our structured tasks at little quality gain. Mirror the NVIDIA policy: off
        # by default (LLM_ENABLE_THINKING), cutting a tailor call ~9.6s -> ~5.1s.
        if not _as_bool(_env("LLM_ENABLE_THINKING"), default=False):
            kwargs["thinking_budget"] = 0
        return ChatGoogleGenerativeAI(**kwargs)

    # Default: NVIDIA NIM (Nemotron) — the established quality baseline.
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    api_key = _env("NVIDIA_API_KEY", "OPENAI_API_KEY")
    base_url = _env("NVIDIA_BASE_URL", "OPENAI_BASE_URL", default=DEFAULT_NVIDIA_BASE_URL)
    if not api_key:
        raise ValueError("Set NVIDIA_API_KEY (or OPENAI_API_KEY) in your .env file.")
    enable_thinking = _as_bool(_env("LLM_ENABLE_THINKING"), default=False)

    return ChatNVIDIA(
        model=model_id,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        # Nemotron reasoning models gate the visible "thinking" trace behind this
        # flag. Keep it OFF so structured-output JSON stays clean.
        chat_template_kwargs={"enable_thinking": enable_thinking},
    )


def get_embeddings():
    """Provider-agnostic embeddings factory (mirrors get_llm).

    Only used by the optional Prep Pack (RAG) feature, disabled by default.
    Reads:
      API key: NVIDIA_API_KEY | OPENAI_API_KEY
      base url: NVIDIA_BASE_URL | OPENAI_BASE_URL
      model  : NVIDIA_EMBEDDING_MODEL | OPENAI_EMBEDDING_MODEL
    """
    from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

    api_key = _env("NVIDIA_API_KEY", "OPENAI_API_KEY")
    base_url = _env("NVIDIA_BASE_URL", "OPENAI_BASE_URL", default=DEFAULT_NVIDIA_BASE_URL)
    model = _env(
        "NVIDIA_EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL", default=DEFAULT_EMBEDDING_MODEL
    )

    if not api_key:
        raise ValueError("Set NVIDIA_API_KEY (or OPENAI_API_KEY) in your .env file.")

    return NVIDIAEmbeddings(model=model, api_key=api_key, base_url=base_url)


if __name__ == "__main__":
    print(get_llm().invoke("Reply with exactly: hello"))
    try:
        print("embedding dim:", len(get_embeddings().embed_query("hello")))
    except Exception as exc:  # embeddings are optional
        print(f"(embeddings not configured / available: {exc})")


# --------------------------------------------------------------------------- #
# Robust structured output for Nemotron.
#
# NIM guided-JSON enforces the JSON *shape* but not that nested arrays are
# populated. At temperature 0 a retry is deterministic (identical output), so a
# useful retry must change something: we bump temperature slightly and re-ask.
# This wrapper invokes a (prompt | structured_llm) chain, and if the result is
# None or "degenerate" (per an optional validator), retries on a hotter LLM.
# --------------------------------------------------------------------------- #
def get_llm_creative(
    temperature: float = 0.4, model: str | None = None, *, max_tokens: int | None = None
):
    """A second LLM handle with a non-zero temperature, for retry fallbacks."""
    import os as _os

    prev = _os.environ.get("LLM_TEMPERATURE")
    _os.environ["LLM_TEMPERATURE"] = str(temperature)
    try:
        return get_llm(model=model, max_tokens=max_tokens)
    finally:
        if prev is None:
            _os.environ.pop("LLM_TEMPERATURE", None)
        else:
            _os.environ["LLM_TEMPERATURE"] = prev


def invoke_structured(
    schema, prompt, payload, *, validate=None, retries=2, model=None, max_tokens=None
):
    """Invoke `prompt | llm.with_structured_output(schema)` reliably.

    - `prompt` is a ChatPromptTemplate, `payload` the dict passed to it.
    - `model` pins a specific NVIDIA model for this call (see fast_model() /
      tailor_model()); None uses the app-wide default.
    - `validate(result) -> bool` flags a result as good. A result that is None or
      fails validation triggers a retry on a hotter model (temp 0 retries would
      be identical and pointless).
    - `retries` is how many EXTRA hotter attempts to make after the first. Keep it
      low for latency; the fast model + forceful prompts rarely return degenerate
      JSON, so each extra attempt is mostly wasted round-trip time.
    Returns the best result obtained (may still be None if the model never
    produced a valid object).
    """
    from config.timing import timed

    temps = [None, 0.4, 0.7][: retries + 1]
    last = None
    label = f"llm.structured[{getattr(schema, '__name__', schema)}|{model or _default_model()}]"
    for attempt, temp in enumerate(temps):
        llm = (
            get_llm(model=model, max_tokens=max_tokens)
            if temp is None
            else get_llm_creative(temp, model=model, max_tokens=max_tokens)
        )
        chain = prompt | llm.with_structured_output(schema)
        try:
            with timed(f"{label} attempt={attempt}"):
                result = chain.invoke(payload)
        except Exception:
            result = None
        last = result if result is not None else last
        if result is not None and (validate is None or validate(result)):
            return result
    return last
