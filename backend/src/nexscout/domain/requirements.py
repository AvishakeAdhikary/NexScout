"""Requirements read from a posting's own text (pure, deterministic).

Most real postings come as free text, not structured fields: no skill list, no "minimum years"
field. This module reads what the text says, the same way a person skims it:

- skills it mentions (a curated vocabulary plus the candidate's own skill names),
- the minimum years of experience it asks for, in the main European languages,
- the seniority its title implies,
- the language it is written in, and whether it asks for a doctorate.

Every reading keeps the words that triggered it, so explanations can quote the posting. Nothing
here guesses: no match means "not stated".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# Canonical name -> spellings found in postings (lowercase). Kept to terms that are skills in
# job ads, not ordinary words ("go", "r", "c" and "excel" are left out: too ambiguous in prose).
SKILLS: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "Java": ("java",),
    "JavaScript": ("javascript",),
    "TypeScript": ("typescript",),
    "C++": ("c++", "cpp"),
    "C#": ("c#", ".net", "dotnet"),
    "Go": ("golang",),
    "Rust": ("rust",),
    "Scala": ("scala",),
    "Kotlin": ("kotlin",),
    "Swift": ("swiftui", "swift (ios)", "ios swift"),  # bare "swift" is an ordinary word
    "SQL": ("sql",),
    "Bash": ("bash", "shell scripting"),
    "MATLAB": ("matlab",),
    "Julia": ("julia language", "julialang"),
    "PyTorch": ("pytorch", "torch"),
    "TensorFlow": ("tensorflow",),
    "Keras": ("keras",),
    "JAX": ("jax",),
    "scikit-learn": ("scikit-learn", "sklearn", "scikit learn"),
    "XGBoost": ("xgboost", "lightgbm", "catboost"),
    "Hugging Face": ("hugging face", "huggingface", "transformers library"),
    "LangChain": ("langchain", "langgraph", "llamaindex", "llama index"),
    "LLMs": (
        "llm",
        "llms",
        "large language model",
        "large language models",
        "genai",
        "generative ai",
    ),
    "RAG": ("rag", "retrieval-augmented", "retrieval augmented"),
    "Fine-tuning": ("fine-tuning", "fine tuning", "finetuning", "lora", "qlora", "peft", "rlhf"),
    "Prompt engineering": ("prompt engineering",),
    "AI agents": ("ai agents", "agentic", "multi-agent", "tool calling"),
    "NLP": ("nlp", "natural language processing"),
    "Computer vision": (
        "computer vision",
        "image processing",
        "object detection",
        "image segmentation",
        "opencv",
    ),
    "Deep learning": (
        "deep learning",
        "neural network",
        "neural networks",
        "cnn",
        "cnns",
        "transformer models",
        "lstm",
    ),
    "Machine learning": ("machine learning",),
    "Reinforcement learning": ("reinforcement learning",),
    "Speech": ("speech recognition", "asr", "text-to-speech", "tts"),
    "Recommender systems": ("recommender system", "recommender systems", "recommendation systems"),
    "Time series": ("time series", "forecasting"),
    "Statistics": (
        "statistics",
        "statistical modelling",
        "statistical modeling",
        "bayesian",
        "a/b testing",
    ),
    "MLOps": ("mlops", "ml ops", "model deployment", "model serving"),
    "MLflow": ("mlflow",),
    "Kubeflow": ("kubeflow",),
    "Airflow": ("airflow",),
    "Spark": ("apache spark", "pyspark", "spark sql", "databricks"),  # not "spark curiosity"
    "Kafka": ("kafka",),
    "dbt": ("dbt",),
    "Snowflake": ("snowflake",),
    "BigQuery": ("bigquery",),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "CUDA": ("cuda",),
    "ONNX": ("onnx", "tensorrt"),
    "Quantization": ("quantization", "quantisation", "gguf", "llama.cpp"),
    "Vector databases": (
        "vector database",
        "vector databases",
        "pinecone",
        "weaviate",
        "qdrant",
        "milvus",
        "pgvector",
        "faiss",
    ),
    "Docker": ("docker", "containers", "containerization"),
    "Kubernetes": ("kubernetes", "k8s"),
    "Terraform": ("terraform",),
    "AWS": ("aws", "amazon web services", "sagemaker"),
    "GCP": ("gcp", "google cloud", "vertex ai"),
    "Azure": ("azure",),
    "Linux": ("linux",),
    "Git": ("git", "github", "gitlab"),
    "CI/CD": ("ci/cd", "continuous integration", "github actions"),
    "PostgreSQL": ("postgresql", "postgres"),
    "MongoDB": ("mongodb",),
    "Redis": ("redis",),
    "Elasticsearch": ("elasticsearch", "opensearch"),
    "REST APIs": ("rest api", "rest apis", "restful"),
    "GraphQL": ("graphql",),
    "FastAPI": ("fastapi",),
    "Django": ("django",),
    "Flask": ("flask",),
    "React": ("react", "react.js", "reactjs"),
    "Node.js": ("node.js", "nodejs"),
    "Microservices": ("microservices", "micro-services"),
    "Distributed systems": ("distributed systems", "distributed training"),
    "Data engineering": ("data engineering", "etl", "data pipelines", "data pipeline"),
    "Data visualization": ("data visualization", "data visualisation", "tableau", "power bi"),
    "Robotics": ("robotics", "ros", "ros2"),
    "Embedded": ("embedded systems", "embedded software", "firmware"),
}


def _words_of(s: str) -> frozenset[str]:
    return frozenset(s.split())


# Function words per language (frequent, short, rarely used in other languages' postings).
_STOPWORDS: dict[str, frozenset[str]] = {
    "en": _words_of("the and of to with for you our are will we your in is on as be"),
    "de": _words_of(
        "und der die das mit für wir sie ihre eine einen bei von zu ist auf sind unser "
        "unsere werden oder auch"
    ),
    "fr": _words_of("et le la les des une un pour avec vous nous dans sur est sont votre notre"),
    "nl": _words_of("en het een van voor met je jij wij zijn ons onze bij naar wordt"),
    # Nordic languages share most short words (som, med, har, på), so only distinctive ones.
    "sv": _words_of("och är inte också eller vår våra inom söker arbetar kommer kunna mycket"),
    "fi": _words_of("ja on että sekä tai kanssa olemme meillä sinulla työ myös"),
    "da": _words_of("og ikke også vores meget arbejde jeres af søger"),
    "no": _words_of("og ikke også våre mye arbeide jobber søker"),
    "es": _words_of("y el la los las de para con en una un que por nuestro nuestra es"),
    "it": _words_of("e il la di per con un una che nel della del sono nostro nostra"),
    "pl": _words_of("i w na z do się jest dla oraz nasz nasza jako lub"),
    "pt": _words_of("e o a os as de para com em uma um que por nosso nossa é"),
}

LANGUAGE_NAMES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "nl": "Dutch",
    "sv": "Swedish",
    "fi": "Finnish",
    "da": "Danish",
    "no": "Norwegian",
    "es": "Spanish",
    "it": "Italian",
    "pl": "Polish",
    "pt": "Portuguese",
}

_EXPERIENCE_WORDS = re.compile(
    r"experience|erfahrung|berufserfahrung|erfarenhet|erfaring|kokemus|expérience|experience"
    r"|ervaring|werkervaring|esperienza|experiencia|doświadcz|experiência",
    re.I,
)
_YEARS = re.compile(
    r"(?<![\d.,])(\d{1,2})(?:\s*[-\u2013]\s*\d{1,2})?\s*\+?\s*"  # "3-5", also with an en dash
    r"(?:years?|yrs|jahre?n?|år|års|vuo(?:si|den|tta)|ans|jaar|anni|años|anos|lat)\b",
    re.I,
)
_SENIOR = re.compile(
    r"(?<![(\[/])\b(senior|sr\.?|lead|principal|staff|head of|director)\b(?![)\]])", re.I
)
_JUNIOR = re.compile(r"\b(junior|jr\.?|graduate|entry[- ]level|trainee|intern(ship)?)\b", re.I)
_POSTDOC = re.compile(r"\bpost[- ]?doc(toral)?\b|\bpostdoktor|\bpost-doctoral\b", re.I)


@dataclass(frozen=True)
class Requirements:
    skills: tuple[str, ...]  # canonical names, in order of first mention
    min_years: float | None
    years_quote: str | None
    seniority: str | None  # "senior" | "junior" | None
    seniority_word: str | None
    language: str | None  # ISO 639-1 the text is written in (None: too short or mixed)
    needs_doctorate: bool


@lru_cache(maxsize=1)
def _skill_patterns() -> list[tuple[re.Pattern[str], str]]:
    out = []
    for name, spellings in SKILLS.items():
        alts = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
        out.append((re.compile(rf"(?<![a-z0-9+#.]){'(?:' + alts + ')'}(?![a-z0-9+#])"), name))
    return out


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zà-ÿäöåøæœßąćęłńóśźż]+", text.lower())


def skills_in(text: str, extra: list[str] | None = None) -> list[str]:
    """Skills a text mentions: the vocabulary above plus `extra` names (the candidate's own
    skills, so a niche skill they list still counts when the posting names it)."""
    low = " ".join(text.lower().split())
    found: list[tuple[int, str]] = []
    for pat, name in _skill_patterns():
        m = pat.search(low)
        if m:
            found.append((m.start(), name))
    known = {n.lower() for _, n in found}
    for raw in extra or []:
        s = raw.strip()
        if len(s) < 3 or s.lower() in known:
            continue
        m = re.search(rf"(?<![a-z0-9+#.]){re.escape(s.lower())}(?![a-z0-9+#])", low)
        if m:
            found.append((m.start(), s))
            known.add(s.lower())
    return [n for _, n in sorted(found)]


def min_years(text: str) -> tuple[float | None, str | None]:
    """The smallest "N years of experience" the text asks for (conservative: a posting that
    asks for 5 years overall and 2 in a tool asks for 2+ somewhere, never more than 5)."""
    best: tuple[float, str] | None = None
    for m in _YEARS.finditer(text):
        n = float(m.group(1))
        if not 1 <= n <= 20:
            continue
        window = text[max(0, m.start() - 60) : m.end() + 60]
        if not _EXPERIENCE_WORDS.search(window):
            continue
        lo = text.rfind(" ", 0, max(0, m.start() - 30)) + 1  # start on a whole word
        quote = " ".join(text[lo : m.end() + 40].split())
        if best is None or n < best[0]:
            best = (n, quote)
    return (best[0], best[1]) if best else (None, None)


def written_in(text: str) -> str | None:
    """The language a text is written in, from function words. None when the text is short or
    mixed (a bilingual posting isn't assigned to either language)."""
    words = _words(text)
    if len(words) < 60:
        return None
    counts = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    (top, n1), (_, n2) = ranked[0], ranked[1]
    if n1 < 15 or n1 < 1.6 * n2:
        return None
    return top


def read_requirements(title: str, description: str | None) -> Requirements:
    text = f"{title}\n{description or ''}"
    years, quote = min_years(description or "")
    senior = _SENIOR.search(title)
    junior = _JUNIOR.search(title)
    seniority, word = (
        ("junior", junior.group(1))
        if junior
        else ("senior", senior.group(1))
        if senior
        else (None, None)
    )
    return Requirements(
        skills=tuple(skills_in(text)),
        min_years=years,
        years_quote=quote,
        seniority=seniority,
        seniority_word=word,
        language=written_in(description or ""),
        needs_doctorate=bool(_POSTDOC.search(title)),
    )
