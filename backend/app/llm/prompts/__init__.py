"""Versioned prompt templates for the Rubric Grading Engine.

Each prompt type has one Python module per version:
    grading_v1.py     — grading rubric criteria → criterion scores + summary
    feedback_v1.py    — locked grade → student-facing written feedback
    instruction_v1.py — student skill profile → targeted exercises

Rules:
    - Prompt changes that could affect scoring require a version bump.
    - Non-scoring fixes (typo, clearer wording) may be patched in place.
    - The active grading version is set by ``settings.grading_prompt_version``.
"""
