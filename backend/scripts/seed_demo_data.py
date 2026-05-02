"""Seed deterministic demo data for local docker-compose demo runs.

This script is intentionally idempotent so it can run on every
``docker compose -f docker-compose.demo.yml up`` without duplicating rows.

Seeded entities:
- Teacher account (email verified + onboarding complete)
- One class with two enrolled students
- One rubric with two criteria
- Two assignments in review status with immutable rubric snapshots
- Four essays with one version each (2 students × 2 assignments)
- Locked grades + criterion scores for all seeded essays
- Browser-writing snapshots + process signals on one essay version (M5)
- Student skill profiles with assignment_count=2 for demo walkthrough (M5)
- One integrity report and one open regrade request for demo workflows
- One skill-gap group (persistent) per seeded student with low evidence scores (M6)
- One worklist item (persistent_gap) per student for the evidence skill gap (M6)
- One instruction recommendation in pending_review state for Student Alpha (M6)
- A second EssayVersion on Student Beta's Assignment A essay + revision comparison (M6)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import bcrypt
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, tenant_session
from app.models.assignment import Assignment, AssignmentStatus
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.essay import Essay, EssayStatus, EssayVersion
from app.models.grade import ConfidenceLevel, CriterionScore, Grade, StrictnessLevel
from app.models.instruction_recommendation import InstructionRecommendation
from app.models.integrity_report import IntegrityReport, IntegrityReportStatus
from app.models.intervention_recommendation import InterventionRecommendation
from app.models.regrade_request import RegradeRequest, RegradeRequestStatus
from app.models.rubric import Rubric, RubricCriterion
from app.models.student import Student
from app.models.student_group import StudentGroup
from app.models.student_skill_profile import StudentSkillProfile
from app.models.user import User, UserRole
from app.models.worklist import TeacherWorklistItem
from app.services.rubric import build_rubric_snapshot

DEMO_EMAIL = "demo@gradewise.app"
DEMO_PASSWORD = "DemoPass123!"
DEMO_FIRST_NAME = "Demo"
DEMO_LAST_NAME = "Teacher"
DEMO_SCHOOL = "GradeWise Demo School"


async def _get_or_create_teacher() -> User:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == DEMO_EMAIL))
        user = result.scalar_one_or_none()

        hashed_password = bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode()

        if user is None:
            user = User(
                email=DEMO_EMAIL,
                hashed_password=hashed_password,
                first_name=DEMO_FIRST_NAME,
                last_name=DEMO_LAST_NAME,
                school_name=DEMO_SCHOOL,
                role=UserRole.teacher,
                email_verified=True,
                onboarding_complete=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

        # Keep credentials and access state predictable for repeated demo runs.
        user.hashed_password = hashed_password
        user.first_name = DEMO_FIRST_NAME
        user.last_name = DEMO_LAST_NAME
        user.school_name = DEMO_SCHOOL
        user.email_verified = True
        user.onboarding_complete = True
        await db.commit()
        await db.refresh(user)
        return user


async def _seed_teacher_scoped_data(teacher_id: uuid.UUID) -> None:
    async with tenant_session(teacher_id) as db:
        now = datetime.now(UTC)

        class_name = "Demo English 8"
        class_result = await db.execute(
            select(Class).where(
                Class.teacher_id == teacher_id,
                Class.name == class_name,
            )
        )
        class_row = class_result.scalar_one_or_none()
        if class_row is None:
            class_row = Class(
                teacher_id=teacher_id,
                name=class_name,
                subject="ELA",
                grade_level="8",
                academic_year="2025-26",
                is_archived=False,
            )
            db.add(class_row)
            await db.flush()

        student_names = ["Student Alpha", "Student Beta"]
        students: list[Student] = []
        for name in student_names:
            student_result = await db.execute(
                select(Student).where(
                    Student.teacher_id == teacher_id,
                    Student.full_name == name,
                )
            )
            student = student_result.scalar_one_or_none()
            if student is None:
                student = Student(teacher_id=teacher_id, full_name=name)
                db.add(student)
                await db.flush()
            students.append(student)

            enrollment_result = await db.execute(
                select(ClassEnrollment).where(
                    ClassEnrollment.class_id == class_row.id,
                    ClassEnrollment.student_id == student.id,
                    ClassEnrollment.removed_at.is_(None),
                )
            )
            enrollment = enrollment_result.scalar_one_or_none()
            if enrollment is None:
                db.add(
                    ClassEnrollment(
                        class_id=class_row.id,
                        student_id=student.id,
                    )
                )

        rubric_name = "Demo Argument Writing Rubric"
        rubric_result = await db.execute(
            select(Rubric).where(
                Rubric.teacher_id == teacher_id,
                Rubric.name == rubric_name,
                Rubric.deleted_at.is_(None),
            )
        )
        rubric = rubric_result.scalar_one_or_none()
        if rubric is None:
            rubric = Rubric(
                teacher_id=teacher_id,
                name=rubric_name,
                description="Demo rubric for persuasive writing.",
                is_template=False,
            )
            db.add(rubric)
            await db.flush()

        criteria_result = await db.execute(
            select(RubricCriterion)
            .where(RubricCriterion.rubric_id == rubric.id)
            .order_by(RubricCriterion.display_order)
        )
        criteria = list(criteria_result.scalars().all())

        if not criteria:
            criteria = [
                RubricCriterion(
                    rubric_id=rubric.id,
                    name="Claim and Thesis",
                    description="Clear, arguable claim with focused thesis.",
                    weight=Decimal("50.00"),
                    min_score=1,
                    max_score=5,
                    display_order=1,
                    anchor_descriptions={"1": "Unclear", "5": "Strong and precise"},
                ),
                RubricCriterion(
                    rubric_id=rubric.id,
                    name="Evidence and Reasoning",
                    description="Uses relevant evidence and explains reasoning.",
                    weight=Decimal("50.00"),
                    min_score=1,
                    max_score=5,
                    display_order=2,
                    anchor_descriptions={"1": "Weak support", "5": "Compelling support"},
                ),
            ]
            for criterion in criteria:
                db.add(criterion)
            await db.flush()

        assignment_specs = [
            (
                "Demo Persuasive Essay A",
                "Write a persuasive essay arguing for one schedule change that improves learning.",
            ),
            (
                "Demo Persuasive Essay B",
                "Write a follow-up persuasive essay revising your argument with stronger evidence.",
            ),
        ]
        rubric_snapshot = build_rubric_snapshot(rubric, criteria)
        assignments: list[Assignment] = []

        for title, prompt in assignment_specs:
            assignment_result = await db.execute(
                select(Assignment).where(
                    Assignment.class_id == class_row.id,
                    Assignment.title == title,
                )
            )
            assignment = assignment_result.scalar_one_or_none()
            if assignment is None:
                assignment = Assignment(
                    class_id=class_row.id,
                    rubric_id=rubric.id,
                    rubric_snapshot=rubric_snapshot,
                    title=title,
                    prompt=prompt,
                    status=AssignmentStatus.review,
                )
                db.add(assignment)
                await db.flush()
            else:
                assignment.status = AssignmentStatus.review
            assignments.append(assignment)

        essay_texts: dict[tuple[int, str], str] = {
            (
                1,
                "Student Alpha",
            ): "Advisory time should be part of every school day to improve planning, organization, and support.",
            (
                1,
                "Student Beta",
            ): "Students should get daily reading-choice time because ownership increases motivation and stamina.",
            (
                2,
                "Student Alpha",
            ): "A revised schedule with advisory plus workshop blocks gives students targeted support and better pacing.",
            (
                2,
                "Student Beta",
            ): "When students can choose reading texts and track goals, engagement and comprehension improve over time.",
        }
        # Per-assignment, per-student criterion scores in rubric display order:
        # Claim and Thesis, Evidence and Reasoning.
        score_plan: dict[tuple[int, str], tuple[int, int]] = {
            (1, "Student Alpha"): (4, 3),
            (1, "Student Beta"): (3, 2),
            (2, "Student Alpha"): (5, 4),
            (2, "Student Beta"): (4, 2),
        }

        for assignment_idx, assignment in enumerate(assignments, start=1):
            for student in students:
                essay_result = await db.execute(
                    select(Essay).where(
                        Essay.assignment_id == assignment.id,
                        Essay.student_id == student.id,
                    )
                )
                essay = essay_result.scalar_one_or_none()
                if essay is None:
                    essay = Essay(
                        assignment_id=assignment.id,
                        student_id=student.id,
                        status=EssayStatus.locked,
                        submitted_at=now,
                    )
                    db.add(essay)
                    await db.flush()
                else:
                    essay.status = EssayStatus.locked
                    essay.submitted_at = essay.submitted_at or now

                content = essay_texts.get(
                    (assignment_idx, student.full_name), "Demo essay content."
                )
                version_result = await db.execute(
                    select(EssayVersion).where(
                        EssayVersion.essay_id == essay.id,
                        EssayVersion.version_number == 1,
                    )
                )
                version = version_result.scalar_one_or_none()
                if version is None:
                    version = EssayVersion(
                        essay_id=essay.id,
                        version_number=1,
                        content=content,
                        file_storage_key=None,
                        word_count=len(content.split()),
                        submitted_at=now,
                    )
                    db.add(version)
                    await db.flush()
                else:
                    version.content = content
                    version.word_count = len(content.split())

                # Seed one browser-written essay with writing snapshots and process
                # signals so the M5 writing-process panel is demo-ready.
                if assignment_idx == 2 and student.full_name == "Student Beta":
                    version.writing_snapshots = [
                        {
                            "seq": 1,
                            "ts": now.isoformat(),
                            "word_count": 10,
                            "html_content": "<p>Students need choice in reading.</p>",
                        },
                        {
                            "seq": 2,
                            "ts": now.isoformat(),
                            "word_count": version.word_count,
                            "html_content": (
                                "<p>When students can choose reading texts and track goals, "
                                "engagement and comprehension improve over time.</p>"
                            ),
                        },
                    ]
                    version.process_signals = {
                        "snapshot_count": 2,
                        "computed_at": now.isoformat(),
                        "has_process_data": True,
                        "session_count": 1,
                        "active_writing_seconds": 300.0,
                        "total_elapsed_seconds": 300.0,
                        "inter_session_gaps_seconds": [],
                        "sessions": [
                            {
                                "session_index": 1,
                                "started_at": now.isoformat(),
                                "ended_at": now.isoformat(),
                                "duration_seconds": 300.0,
                                "snapshot_count": 2,
                                "word_count_start": 10,
                                "word_count_end": version.word_count,
                                "words_added": max(version.word_count - 10, 0),
                            }
                        ],
                        "paste_events": [],
                        "rapid_completion_events": [],
                    }
                else:
                    version.writing_snapshots = None
                    version.process_signals = None

                grade_result = await db.execute(
                    select(Grade).where(Grade.essay_version_id == version.id)
                )
                grade = grade_result.scalar_one_or_none()

                c1, c2 = score_plan[(assignment_idx, student.full_name)]
                total_score = Decimal(str(c1 + c2))
                if grade is None:
                    grade = Grade(
                        essay_version_id=version.id,
                        total_score=total_score,
                        max_possible_score=Decimal("10.00"),
                        summary_feedback="Strong draft with clear next steps.",
                        strictness=StrictnessLevel.balanced,
                        ai_model="demo-seed",
                        prompt_version="demo-v1",
                        is_locked=True,
                        locked_at=now,
                        overall_confidence=ConfidenceLevel.medium,
                    )
                    db.add(grade)
                    await db.flush()
                else:
                    grade.total_score = total_score
                    grade.max_possible_score = Decimal("10.00")
                    grade.summary_feedback = "Strong draft with clear next steps."
                    grade.is_locked = True
                    grade.locked_at = grade.locked_at or now

                score_by_display_order = {1: c1, 2: c2}
                for criterion in criteria:
                    target_score = score_by_display_order.get(criterion.display_order, 3)
                    score_result = await db.execute(
                        select(CriterionScore).where(
                            CriterionScore.grade_id == grade.id,
                            CriterionScore.rubric_criterion_id == criterion.id,
                        )
                    )
                    score = score_result.scalar_one_or_none()
                    if score is None:
                        db.add(
                            CriterionScore(
                                grade_id=grade.id,
                                rubric_criterion_id=criterion.id,
                                ai_score=target_score,
                                teacher_score=None,
                                final_score=target_score,
                                ai_justification="Demo justification generated for walkthrough.",
                                ai_feedback="Demo criterion feedback.",
                                teacher_feedback=None,
                                confidence=ConfidenceLevel.medium,
                            )
                        )
                    else:
                        score.ai_score = target_score
                        score.final_score = target_score
                        score.ai_justification = "Demo justification generated for walkthrough."
                        score.ai_feedback = "Demo criterion feedback."
                        score.confidence = ConfidenceLevel.medium

                # Keep one integrity report and one open regrade request for M4 demos.
                if assignment_idx == 1 and student.full_name == "Student Alpha":
                    integrity_result = await db.execute(
                        select(IntegrityReport).where(
                            IntegrityReport.essay_version_id == version.id,
                            IntegrityReport.provider == "demo",
                        )
                    )
                    if integrity_result.scalar_one_or_none() is None:
                        db.add(
                            IntegrityReport(
                                essay_version_id=version.id,
                                teacher_id=teacher_id,
                                provider="demo",
                                ai_likelihood=0.18,
                                similarity_score=0.11,
                                flagged_passages=[],
                                status=IntegrityReportStatus.pending,
                            )
                        )

                if assignment_idx == 1 and student.full_name == "Student Beta":
                    regrade_result = await db.execute(
                        select(RegradeRequest).where(
                            RegradeRequest.grade_id == grade.id,
                            RegradeRequest.teacher_id == teacher_id,
                        )
                    )
                    if regrade_result.scalar_one_or_none() is None:
                        db.add(
                            RegradeRequest(
                                grade_id=grade.id,
                                criterion_score_id=None,
                                teacher_id=teacher_id,
                                dispute_text="Demo request: review evidence weighting.",
                                status=RegradeRequestStatus.open,
                            )
                        )

        # Seed deterministic student skill profiles so M5 profile views are
        # always populated even when the Celery task is not running.
        skill_profile_payloads: dict[str, dict[str, object]] = {
            "Student Alpha": {
                "thesis": {
                    "avg_score": 0.875,
                    "trend": "improving",
                    "data_points": 2,
                    "last_updated": now.isoformat(),
                },
                "evidence": {
                    "avg_score": 0.625,
                    "trend": "improving",
                    "data_points": 2,
                    "last_updated": now.isoformat(),
                },
            },
            "Student Beta": {
                "thesis": {
                    "avg_score": 0.625,
                    "trend": "improving",
                    "data_points": 2,
                    "last_updated": now.isoformat(),
                },
                "evidence": {
                    "avg_score": 0.375,
                    "trend": "stable",
                    "data_points": 2,
                    "last_updated": now.isoformat(),
                },
            },
        }

        for student in students:
            profile_result = await db.execute(
                select(StudentSkillProfile).where(
                    StudentSkillProfile.teacher_id == teacher_id,
                    StudentSkillProfile.student_id == student.id,
                )
            )
            profile = profile_result.scalar_one_or_none()
            payload = skill_profile_payloads[student.full_name]
            if profile is None:
                db.add(
                    StudentSkillProfile(
                        teacher_id=teacher_id,
                        student_id=student.id,
                        skill_scores=payload,
                        assignment_count=2,
                        last_updated_at=now,
                    )
                )
            else:
                profile.skill_scores = payload
                profile.assignment_count = 2
                profile.last_updated_at = now

        await db.commit()

        # ── M6: Skill-gap groups ──────────────────────────────────────────────
        # One persistent group per skill key where both students score low.
        # The group contains both student UUIDs encoded as a JSONB array.
        # student_ids must be stored as UUID strings.
        student_id_strings = [str(s.id) for s in students]
        for skill_key, label in [
            ("evidence", "Evidence & Reasoning"),
            ("thesis", "Claim & Thesis"),
        ]:
            group_result = await db.execute(
                select(StudentGroup).where(
                    StudentGroup.teacher_id == teacher_id,
                    StudentGroup.class_id == class_row.id,
                    StudentGroup.skill_key == skill_key,
                )
            )
            group = group_result.scalar_one_or_none()
            if group is None:
                db.add(
                    StudentGroup(
                        teacher_id=teacher_id,
                        class_id=class_row.id,
                        skill_key=skill_key,
                        label=label,
                        student_ids=student_id_strings,
                        student_count=len(student_id_strings),
                        stability="persistent",
                        computed_at=now,
                    )
                )
            else:
                group.student_ids = student_id_strings
                group.student_count = len(student_id_strings)
                group.stability = "persistent"
                group.computed_at = now

        await db.commit()

        # ── M6 + M7: Teacher worklist items ───────────────────────────────────
        # Persistent-gap items for both students plus one predictive
        # trajectory-risk item so the M7 demo has deterministic predictive data.
        for student in students:
            wl_result = await db.execute(
                select(TeacherWorklistItem).where(
                    TeacherWorklistItem.teacher_id == teacher_id,
                    TeacherWorklistItem.student_id == student.id,
                    TeacherWorklistItem.trigger_type == "persistent_gap",
                    TeacherWorklistItem.skill_key == "evidence",
                    TeacherWorklistItem.status == "active",
                )
            )
            if wl_result.scalar_one_or_none() is None:
                db.add(
                    TeacherWorklistItem(
                        teacher_id=teacher_id,
                        student_id=student.id,
                        trigger_type="persistent_gap",
                        skill_key="evidence",
                        urgency=3,
                        suggested_action="Schedule a targeted evidence-use mini-lesson with this student.",
                        details={
                            "avg_score": 0.375 if student.full_name == "Student Beta" else 0.625,
                            "data_points": 2,
                            "consecutive_assignments": 2,
                        },
                        status="active",
                    )
                )

        alpha = next((s for s in students if s.full_name == "Student Alpha"), None)
        beta = next((s for s in students if s.full_name == "Student Beta"), None)

        if alpha is not None:
            trajectory_result = await db.execute(
                select(TeacherWorklistItem).where(
                    TeacherWorklistItem.teacher_id == teacher_id,
                    TeacherWorklistItem.student_id == alpha.id,
                    TeacherWorklistItem.trigger_type == "trajectory_risk",
                    TeacherWorklistItem.skill_key == "thesis",
                    TeacherWorklistItem.status == "active",
                )
            )
            if trajectory_result.scalar_one_or_none() is None:
                db.add(
                    TeacherWorklistItem(
                        teacher_id=teacher_id,
                        student_id=alpha.id,
                        trigger_type="trajectory_risk",
                        skill_key="thesis",
                        urgency=4,
                        suggested_action="Check in early with this student before the next graded assignment.",
                        details={
                            "is_predictive": True,
                            "confidence_level": "medium",
                            "consecutive_decline_count": 4,
                            "total_decline": 0.22,
                            "recent_scores": [0.78, 0.70, 0.62, 0.56],
                        },
                        status="active",
                    )
                )

        await db.commit()

        # ── M7: Intervention recommendation (pending_review) ────────────────
        # One seeded recommendation so the M7 API/demo can show a deterministic
        # teacher-reviewed intervention without waiting for the scheduled scan.
        if beta is not None:
            intervention_result = await db.execute(
                select(InterventionRecommendation).where(
                    InterventionRecommendation.teacher_id == teacher_id,
                    InterventionRecommendation.student_id == beta.id,
                    InterventionRecommendation.trigger_type == "persistent_gap",
                    InterventionRecommendation.skill_key == "evidence",
                    InterventionRecommendation.status == "pending_review",
                )
            )
            if intervention_result.scalar_one_or_none() is None:
                db.add(
                    InterventionRecommendation(
                        teacher_id=teacher_id,
                        student_id=beta.id,
                        trigger_type="persistent_gap",
                        skill_key="evidence",
                        urgency=3,
                        trigger_reason="Evidence scores have remained below threshold across both demo assignments.",
                        evidence_summary="Average normalized evidence score is 0.375 across 2 assignments with no clear improvement trend.",
                        suggested_action="Schedule a short evidence-integration conference and model one paragraph revision.",
                        details={
                            "avg_score": 0.375,
                            "trend": "stable",
                            "assignment_count": 2,
                        },
                        status="pending_review",
                    )
                )

        await db.commit()

        # ── M6: Instruction recommendation (pending_review) ──────────────────
        # One pre-generated recommendation for Student Alpha so the demo UI
        # shows a populated recommendation card without requiring an LLM call.
        if alpha is not None:
            rec_result = await db.execute(
                select(InstructionRecommendation).where(
                    InstructionRecommendation.teacher_id == teacher_id,
                    InstructionRecommendation.student_id == alpha.id,
                    InstructionRecommendation.status == "pending_review",
                )
            )
            if rec_result.scalar_one_or_none() is None:
                db.add(
                    InstructionRecommendation(
                        teacher_id=teacher_id,
                        student_id=alpha.id,
                        group_id=None,
                        worklist_item_id=None,
                        skill_key="evidence",
                        grade_level="Grade 8",
                        evidence_summary=(
                            "Student Alpha has scored below 0.70 on the Evidence & Reasoning "
                            "dimension across both graded assignments (avg 0.625). "
                            "The gap is consistent — no upward trend detected."
                        ),
                        recommendations=[
                            {
                                "skill_dimension": "evidence",
                                "title": "Evidence Sandwich Mini-Lesson",
                                "description": "Model a 3-step evidence sandwich (claim → quote → explain) using a short mentor text.",
                                "estimated_minutes": 15,
                                "strategy_type": "mini_lesson",
                            },
                            {
                                "skill_dimension": "evidence",
                                "title": "Single-Paragraph Evidence Practice",
                                "description": "Students write one body paragraph with one embedded quote and a two-sentence analysis.",
                                "estimated_minutes": 20,
                                "strategy_type": "exercise",
                            },
                        ],
                        status="pending_review",
                        prompt_version="instruction-v1",
                    )
                )

            await db.commit()

        # ── M6: Resubmission data for Student Beta, Assignment A ──────────────
        # Add a second EssayVersion (version_number=2) and a RevisionComparison
        # row so the revision comparison UI is populated in the demo without
        # requiring a live LLM call.
        # Student Beta's Assignment A essay was seeded earlier in the loop;
        # locate it by student + assignment.
        if beta is not None and assignments:
            assignment_a = assignments[0]  # Assignment A is index 0 (created first)
            beta_essay_result = await db.execute(
                select(Essay).where(
                    Essay.assignment_id == assignment_a.id,
                    Essay.student_id == beta.id,
                )
            )
            beta_essay = beta_essay_result.scalar_one_or_none()
            if beta_essay is not None:
                # Check if a v2 already exists.
                v2_result = await db.execute(
                    select(EssayVersion).where(
                        EssayVersion.essay_id == beta_essay.id,
                        EssayVersion.version_number == 2,
                    )
                )
                if v2_result.scalar_one_or_none() is None:
                    v2 = EssayVersion(
                        essay_id=beta_essay.id,
                        version_number=2,
                        content=(
                            "This revised essay incorporates stronger textual evidence throughout. "
                            "Each body paragraph now includes a specific quote from the source "
                            "material, followed by a sentence of analysis explaining its relevance "
                            "to the central argument. The thesis has been sharpened and the "
                            "conclusion now synthesises the key supporting points more precisely."
                        ),
                        word_count=67,
                    )
                    db.add(v2)
                    await db.flush()  # populate v2.id

                    # Seed a Grade for v2 (slightly higher than v1).
                    v1_result = await db.execute(
                        select(EssayVersion).where(
                            EssayVersion.essay_id == beta_essay.id,
                            EssayVersion.version_number == 1,
                        )
                    )
                    v1 = v1_result.scalar_one_or_none()

                    # Fetch v1's grade so we can record the base_grade_id.
                    v1_grade = None
                    if v1 is not None:
                        v1_grade_result = await db.execute(
                            select(Grade).where(Grade.essay_version_id == v1.id)
                        )
                        v1_grade = v1_grade_result.scalar_one_or_none()

                    v2_grade = Grade(
                        essay_version_id=v2.id,
                        total_score=Decimal("7.00"),
                        max_possible_score=Decimal("10.00"),
                        summary_feedback=(
                            "Good revision — evidence integration is noticeably stronger. "
                            "Continue developing the analytical sentences after each quote."
                        ),
                        strictness=StrictnessLevel.balanced,
                        ai_model="demo",
                        prompt_version="grading-v1",
                        is_locked=True,
                        locked_at=now,
                    )
                    db.add(v2_grade)
                    await db.flush()  # populate v2_grade.id

                    # Seed RevisionComparison if both v1 and v1_grade exist.
                    if v1 is not None and v1_grade is not None:
                        from app.models.revision_comparison import RevisionComparison

                        rc_result = await db.execute(
                            select(RevisionComparison).where(
                                RevisionComparison.essay_id == beta_essay.id,
                            )
                        )
                        existing_rc = rc_result.scalar_one_or_none()
                        if existing_rc is not None:
                            await db.delete(existing_rc)
                            await db.flush()
                        # Look up criterion IDs by name so the deltas
                        # match the schema (CriterionDeltaResponse
                        # requires criterion_id as a UUID, not a name).
                        _crit_by_name = {c.name: c for c in criteria}
                        _evidence_id = str(
                            _crit_by_name["Evidence and Reasoning"].id
                        )
                        _thesis_id = str(_crit_by_name["Claim and Thesis"].id)
                        db.add(
                            RevisionComparison(
                                essay_id=beta_essay.id,
                                base_version_id=v1.id,
                                revised_version_id=v2.id,
                                base_grade_id=v1_grade.id,
                                revised_grade_id=v2_grade.id,
                                total_score_delta=Decimal("1.00"),
                                created_at=now,
                                criterion_deltas=[
                                    {
                                        "criterion_id": _evidence_id,
                                        "base_score": 3,
                                        "revised_score": 4,
                                        "delta": 1,
                                    },
                                    {
                                        "criterion_id": _thesis_id,
                                        "base_score": 3,
                                        "revised_score": 3,
                                        "delta": 0,
                                    },
                                ],
                                is_low_effort=False,
                                low_effort_reasons=[],
                                feedback_addressed=None,
                            )
                        )

                await db.commit()


async def _run() -> None:
    teacher = await _get_or_create_teacher()
    await _seed_teacher_scoped_data(teacher.id)
    print(f"Demo data ready for {DEMO_EMAIL}")


if __name__ == "__main__":
    asyncio.run(_run())
