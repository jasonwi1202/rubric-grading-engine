"""Integration test proving PostgreSQL FORCE RLS with a non-superuser role.

Unlike service-layer tenant-isolation tests that run as the testcontainer
superuser (BYPASSRLS), this module creates a temporary non-superuser role and
queries tenant-scoped tables through that role to verify policy enforcement.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_force_rls_blocks_unscoped_reads_for_non_superuser(
    async_engine: AsyncEngine,
    pg_dsn: str,
) -> None:
    """Non-superuser connections must see zero rows without tenant context.

    Steps:
    1. Create two teachers and one class per teacher.
    2. Create a temporary non-superuser role with SELECT on ``classes``.
    3. Query as that role without ``app.current_teacher_id`` set -> zero rows.
    4. Set tenant context to teacher A -> exactly teacher A's class is visible.
    """
    teacher_a_id = uuid.uuid4()
    teacher_b_id = uuid.uuid4()
    class_a_id = uuid.uuid4()
    class_b_id = uuid.uuid4()

    temp_role = f"rls_reader_{uuid.uuid4().hex[:10]}"
    temp_password = "test-role-password"

    parsed = make_url(pg_dsn)
    database_name = parsed.database
    assert database_name is not None

    non_super_engine: AsyncEngine | None = None

    try:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, hashed_password, first_name, last_name,
                        school_name, role, email_verified, onboarding_complete
                    )
                    VALUES
                        (:teacher_a_id, :teacher_a_email, 'hash', 'A', 'Teacher', 'School', 'teacher', true, true),
                        (:teacher_b_id, :teacher_b_email, 'hash', 'B', 'Teacher', 'School', 'teacher', true, true)
                    """
                ),
                {
                    "teacher_a_id": teacher_a_id,
                    "teacher_b_id": teacher_b_id,
                    "teacher_a_email": f"a_{uuid.uuid4().hex[:8]}@school.edu",
                    "teacher_b_email": f"b_{uuid.uuid4().hex[:8]}@school.edu",
                },
            )

            await conn.execute(
                text(
                    """
                    INSERT INTO classes (
                        id, teacher_id, name, subject, grade_level, academic_year, is_archived
                    )
                    VALUES
                        (:class_a_id, :teacher_a_id, 'Class A', 'ELA', '7', '2025-2026', false),
                        (:class_b_id, :teacher_b_id, 'Class B', 'ELA', '8', '2025-2026', false)
                    """
                ),
                {
                    "class_a_id": class_a_id,
                    "class_b_id": class_b_id,
                    "teacher_a_id": teacher_a_id,
                    "teacher_b_id": teacher_b_id,
                },
            )

            await conn.execute(
                text(
                    f"CREATE ROLE {temp_role} LOGIN PASSWORD '{temp_password}' "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT"
                )
            )
            await conn.execute(text(f'GRANT CONNECT ON DATABASE "{database_name}" TO {temp_role}'))
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {temp_role}"))
            await conn.execute(text(f"GRANT SELECT ON TABLE classes TO {temp_role}"))

        non_super_url = parsed.set(username=temp_role, password=temp_password)
        non_super_engine = create_async_engine(
            non_super_url.render_as_string(hide_password=False),
            echo=False,
        )

        async with non_super_engine.connect() as non_super_conn:
            # Without app.current_teacher_id, FORCE RLS should hide all rows.
            result = await non_super_conn.execute(text("SELECT count(*) FROM classes"))
            assert result.scalar_one() == 0

            await non_super_conn.execute(
                text("SELECT set_config('app.current_teacher_id', :teacher_id, false)"),
                {"teacher_id": str(teacher_a_id)},
            )

            scoped_count = await non_super_conn.execute(text("SELECT count(*) FROM classes"))
            assert scoped_count.scalar_one() == 1

            class_a_visible = await non_super_conn.execute(
                text("SELECT count(*) FROM classes WHERE id = :class_id"),
                {"class_id": class_a_id},
            )
            assert class_a_visible.scalar_one() == 1

            class_b_hidden = await non_super_conn.execute(
                text("SELECT count(*) FROM classes WHERE id = :class_id"),
                {"class_id": class_b_id},
            )
            assert class_b_hidden.scalar_one() == 0

    finally:
        if non_super_engine is not None:
            await non_super_engine.dispose()

        async with async_engine.begin() as conn:
            await conn.execute(text(f"REVOKE SELECT ON TABLE classes FROM {temp_role}"))
            await conn.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {temp_role}"))
            await conn.execute(
                text(f'REVOKE CONNECT ON DATABASE "{database_name}" FROM {temp_role}')
            )
            await conn.execute(text(f"DROP ROLE IF EXISTS {temp_role}"))
            await conn.execute(
                text("DELETE FROM classes WHERE id = :class_a_id OR id = :class_b_id"),
                {"class_a_id": class_a_id, "class_b_id": class_b_id},
            )
            await conn.execute(
                text("DELETE FROM users WHERE id = :teacher_a_id OR id = :teacher_b_id"),
                {"teacher_a_id": teacher_a_id, "teacher_b_id": teacher_b_id},
            )
