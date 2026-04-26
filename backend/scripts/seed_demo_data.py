"""Seed deterministic demo data for local docker-compose demo runs.

This script is intentionally idempotent so it can run on every
``docker compose -f docker-compose.demo.yml up`` without duplicating rows.

Seeded entities:
- Teacher account (email verified + onboarding complete)
- One class with two enrolled students
- One rubric with two criteria
- One assignment in review status with immutable rubric snapshot
- Two essays with one version each
- Locked grades + criterion scores for both essays
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

        assignment_title = "Demo Persuasive Essay"
        assignment_result = await db.execute(
            select(Assignment).where(
                Assignment.class_id == class_row.id,
                Assignment.title == assignment_title,
            )
        )
        assignment = assignment_result.scalar_one_or_none()
        if assignment is None:
            assignment = Assignment(
                class_id=class_row.id,
                rubric_id=rubric.id,
                rubric_snapshot=build_rubric_snapshot(rubric, criteria),
                title=assignment_title,
                prompt="Write a persuasive essay about improving the school day.",
                status=AssignmentStatus.review,
            )
            db.add(assignment)
            await db.flush()
        else:
            assignment.status = AssignmentStatus.review

        essay_texts = {
            "Student Alpha": "Our school day should include a daily advisory block so students get support and organization time.",
            "Student Beta": "Schools should add more reading choice time because motivation rises when students can pick texts.",
        }

        for idx, student in enumerate(students, start=1):
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

            version_result = await db.execute(
                select(EssayVersion).where(
                    EssayVersion.essay_id == essay.id,
                    EssayVersion.version_number == 1,
                )
            )
            version = version_result.scalar_one_or_none()
            if version is None:
                content = essay_texts.get(student.full_name, "Demo essay content.")
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

            grade_result = await db.execute(
                select(Grade).where(Grade.essay_version_id == version.id)
            )
            grade = grade_result.scalar_one_or_none()
            if grade is None:
                total = Decimal("8.00") if idx == 1 else Decimal("7.00")
                grade = Grade(
                    essay_version_id=version.id,
                    total_score=total,
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
                grade.is_locked = True
                grade.locked_at = grade.locked_at or now

            for criterion in criteria:
                score_result = await db.execute(
                    select(CriterionScore).where(
                        CriterionScore.grade_id == grade.id,
                        CriterionScore.rubric_criterion_id == criterion.id,
                    )
                )
                score = score_result.scalar_one_or_none()
                if score is None:
                    ai_score = 4 if criterion.display_order == 1 else 3
                    db.add(
                        CriterionScore(
                            grade_id=grade.id,
                            rubric_criterion_id=criterion.id,
                            ai_score=ai_score,
                            teacher_score=None,
                            final_score=ai_score,
                            ai_justification="Demo justification generated for walkthrough.",
                            ai_feedback="Demo criterion feedback.",
                            teacher_feedback=None,
                            confidence=ConfidenceLevel.medium,
                        )
                    )

            # Seed one integrity report and one open regrade request for feature demos.
            if idx == 1:
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
            if idx == 2:
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

        await db.commit()


async def _run() -> None:
    teacher = await _get_or_create_teacher()
    await _seed_teacher_scoped_data(teacher.id)
    print(f"Demo data ready for {DEMO_EMAIL}")


if __name__ == "__main__":
    asyncio.run(_run())
