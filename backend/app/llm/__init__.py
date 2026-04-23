"""LLM client and prompt infrastructure for the Rubric Grading Engine.

All LLM calls go through ``app.llm.client``.  Direct calls to the OpenAI
SDK outside this package are not permitted.

Modules:
    client   — AsyncOpenAI wrapper with retry, timeout, and error normalization.
    parsers  — Schema validation and clamping for LLM responses.
    prompts/ — Versioned prompt templates (one Python module per version).
"""
