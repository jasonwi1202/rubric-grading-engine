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
from app.models.integrity_report import IntegrityReport, IntegrityReportStatus
from app.models.regrade_request import RegradeRequest, RegradeRequestStatus
from app.models.rubric import Rubric, RubricCriterion
from app.models.student import Student
from app.models.student_skill_profile import StudentSkillProfile
from app.models.user import User, UserRole
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


async def _run() -> None:
    teacher = await _get_or_create_teacher()
    await _seed_teacher_scoped_data(teacher.id)
    print(f"Demo data ready for {DEMO_EMAIL}")


if __name__ == "__main__":
    asyncio.run(_run())
