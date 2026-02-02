# Custom data migration to preserve production student data
# This migration must run BEFORE 0020_remove_user_assigned_teacher...

from django.db import migrations, models
import django.utils.timezone


def migrate_students_to_users(apps, schema_editor):
    """Migrate billing_student records to billing_user records"""
    db_alias = schema_editor.connection.alias

    # We can't use apps.get_model because the Student model doesn't exist in current code
    # Use raw SQL instead
    with schema_editor.connection.cursor() as cursor:
        # Check if billing_student table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'billing_student'
            );
        """)
        table_exists = cursor.fetchone()[0]

        if not table_exists:
            print("billing_student table doesn't exist, skipping migration")
            return

        # Migrate students to User table
        # Note: Students don't need login accounts, so we create placeholder emails
        # to satisfy the unique constraint
        print("Migrating students from billing_student to billing_user...")
        cursor.execute("""
            INSERT INTO billing_user (
                password,
                last_login,
                is_superuser,
                first_name,
                last_name,
                is_staff,
                date_joined,
                user_type,
                email,
                phone_number,
                address,
                city,
                country,
                postal_code,
                province_state,
                is_approved,
                oauth_provider,
                oauth_id,
                bio,
                instruments,
                hourly_rate,
                parent_email,
                parent_phone,
                is_active
            )
            SELECT
                '',  -- empty password (no login)
                NULL,  -- last_login
                FALSE,  -- is_superuser
                first_name,
                last_name,
                FALSE,  -- is_staff
                created_at,  -- date_joined
                'student',  -- user_type
                'student_' || id || '_noemail@maplekeymusic.internal',  -- placeholder email (unique)
                COALESCE(phone, ''),  -- phone_number
                '',  -- address (empty)
                '',  -- city (empty - will be in BillableContact)
                '',  -- country (empty - will be in BillableContact)
                '',  -- postal_code (empty - will be in BillableContact)
                '',  -- province_state (empty - will be in BillableContact)
                TRUE,  -- is_approved (students are active, so approve them)
                '',  -- oauth_provider
                '',  -- oauth_id
                '',  -- bio
                '',  -- instruments
                50.00,  -- hourly_rate (default)
                '',  -- parent_email (deprecated)
                '',  -- parent_phone (deprecated)
                is_active
            FROM billing_student
            WHERE id NOT IN (
                SELECT COALESCE(user_account_id, -1) FROM billing_student WHERE user_account_id IS NOT NULL
            );
        """)

        rows_migrated = cursor.rowcount
        print(f"Migrated {rows_migrated} students to billing_user")

        # Create mapping table for old student IDs to new user IDs
        print("Creating student ID mapping...")
        cursor.execute("""
            CREATE TEMP TABLE student_to_user_mapping AS
            SELECT
                s.id as old_student_id,
                u.id as new_user_id
            FROM billing_student s
            INNER JOIN billing_user u ON (
                u.first_name = s.first_name
                AND u.last_name = s.last_name
                AND u.user_type = 'student'
                AND u.date_joined = s.created_at
            );
        """)

        # Verify mapping
        cursor.execute("SELECT COUNT(*) FROM student_to_user_mapping;")
        mapping_count = cursor.fetchone()[0]
        print(f"Created {mapping_count} student-to-user mappings")


def migrate_billable_contacts(apps, schema_editor):
    """Transform BillableContact schema and update student references"""
    with schema_editor.connection.cursor() as cursor:
        print("Transforming BillableContact schema...")

        # Drop old foreign key first (before any data changes)
        cursor.execute("""
            ALTER TABLE billing_billablecontact
            DROP CONSTRAINT IF EXISTS billing_billablecont_student_id_4bff1ff9_fk_billing_s;
        """)

        # Drop columns that don't exist in new schema (before data changes)
        cursor.execute("""
            ALTER TABLE billing_billablecontact
            DROP COLUMN IF EXISTS address_line2,
            DROP COLUMN IF EXISTS country,
            DROP COLUMN IF EXISTS relationship_notes,
            DROP COLUMN IF EXISTS payment_preferences;
        """)

        # Rename columns to match new schema (only if they exist)
        # Check if address_line1 exists, rename to street_address
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'billing_billablecontact' AND column_name = 'address_line1'
                ) THEN
                    ALTER TABLE billing_billablecontact RENAME COLUMN address_line1 TO street_address;
                END IF;
            END $$;
        """)

        # Check if province_state exists, rename to state
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'billing_billablecontact' AND column_name = 'province_state'
                ) THEN
                    ALTER TABLE billing_billablecontact RENAME COLUMN province_state TO state;
                END IF;
            END $$;
        """)

        # Update state column to be 2 chars max (if it exists)
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'billing_billablecontact' AND column_name = 'state'
                ) THEN
                    ALTER TABLE billing_billablecontact ALTER COLUMN state TYPE varchar(2);
                END IF;
            END $$;
        """)

        # Update postal_code column to be 10 chars max (if it exists)
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'billing_billablecontact' AND column_name = 'postal_code'
                ) THEN
                    ALTER TABLE billing_billablecontact ALTER COLUMN postal_code TYPE varchar(10);
                END IF;
            END $$;
        """)

        # NOW update the data after schema changes are done (only if mapping table exists)
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM pg_tables
                WHERE schemaname = 'pg_temp'
                AND tablename LIKE '%student_to_user_mapping%'
            );
        """)
        mapping_exists = cursor.fetchone()[0]

        if mapping_exists:
            print("Updating BillableContact student references...")
            cursor.execute("""
                UPDATE billing_billablecontact bc
                SET student_id = m.new_user_id
                FROM student_to_user_mapping m
                WHERE bc.student_id = m.old_student_id;
            """)

            rows_updated = cursor.rowcount
            print(f"Updated {rows_updated} billable contact student references")
        else:
            print("No student mapping table found - skipping billable contact updates")

        # Add new foreign key to point to billing_user
        cursor.execute("""
            ALTER TABLE billing_billablecontact
            ADD CONSTRAINT billing_billablecontact_student_id_fk_billing_user
            FOREIGN KEY (student_id)
            REFERENCES billing_user(id)
            DEFERRABLE INITIALLY DEFERRED;
        """)


def migrate_lesson_references(apps, schema_editor):
    """Update lesson student_id to point to User records"""
    with schema_editor.connection.cursor() as cursor:
        # Check if mapping table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM pg_tables
                WHERE schemaname = 'pg_temp'
                AND tablename LIKE '%student_to_user_mapping%'
            );
        """)
        mapping_exists = cursor.fetchone()[0]

        if not mapping_exists:
            print("No student mapping table found - skipping lesson updates")
            return

        # Drop old foreign key first (before data changes)
        cursor.execute("""
            ALTER TABLE billing_lesson
            DROP CONSTRAINT IF EXISTS billing_lesson_student_id_7c8e5d9a_fk_billing_student_id;
        """)

        print("Updating lesson student references...")
        cursor.execute("""
            UPDATE billing_lesson l
            SET student_id = m.new_user_id
            FROM student_to_user_mapping m
            WHERE l.student_id = m.old_student_id;
        """)

        rows_updated = cursor.rowcount
        print(f"Updated {rows_updated} lesson student references")

        # Add new foreign key
        cursor.execute("""
            ALTER TABLE billing_lesson
            ADD CONSTRAINT billing_lesson_student_id_fk_billing_user
            FOREIGN KEY (student_id)
            REFERENCES billing_user(id)
            DEFERRABLE INITIALLY DEFERRED;
        """)


def migrate_student_teacher_assignments(apps, schema_editor):
    """Migrate student-teacher assignments to new many-to-many table"""
    with schema_editor.connection.cursor() as cursor:
        print("Migrating student-teacher assignments...")

        # Create the new many-to-many table for User.assigned_teachers
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS billing_user_assigned_teachers (
                id BIGSERIAL PRIMARY KEY,
                from_user_id BIGINT NOT NULL REFERENCES billing_user(id) DEFERRABLE INITIALLY DEFERRED,
                to_user_id BIGINT NOT NULL REFERENCES billing_user(id) DEFERRABLE INITIALLY DEFERRED,
                UNIQUE(from_user_id, to_user_id)
            );
        """)

        # Check if mapping table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM pg_tables
                WHERE schemaname = 'pg_temp'
                AND tablename LIKE '%student_to_user_mapping%'
            );
        """)
        mapping_exists = cursor.fetchone()[0]

        if not mapping_exists:
            print("No student mapping table found - skipping assignment migration")
            return

        # Migrate assignments from old table to new table
        cursor.execute("""
            INSERT INTO billing_user_assigned_teachers (from_user_id, to_user_id)
            SELECT m.new_user_id, sta.user_id
            FROM billing_student_assigned_teachers sta
            INNER JOIN student_to_user_mapping m ON sta.student_id = m.old_student_id
            ON CONFLICT (from_user_id, to_user_id) DO NOTHING;
        """)

        rows_migrated = cursor.rowcount
        print(f"Migrated {rows_migrated} student-teacher assignments")


def migrate_invoice_references(apps, schema_editor):
    """Update invoice student_id to point to User records"""
    with schema_editor.connection.cursor() as cursor:
        # Check if mapping table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM pg_tables
                WHERE schemaname = 'pg_temp'
                AND tablename LIKE '%student_to_user_mapping%'
            );
        """)
        mapping_exists = cursor.fetchone()[0]

        if not mapping_exists:
            print("No student mapping table found - skipping invoice updates")
            return

        # Check if there are any invoices referencing students
        cursor.execute("""
            SELECT COUNT(*) FROM billing_invoice
            WHERE student_id IN (SELECT old_student_id FROM student_to_user_mapping);
        """)
        invoice_count = cursor.fetchone()[0]

        if invoice_count > 0:
            # Drop old foreign key first (before data changes)
            cursor.execute("""
                ALTER TABLE billing_invoice
                DROP CONSTRAINT IF EXISTS billing_invoice_student_id_42dbb82c_fk_billing_student_id;
            """)

            print(f"Updating {invoice_count} invoice student references...")
            cursor.execute("""
                UPDATE billing_invoice i
                SET student_id = m.new_user_id
                FROM student_to_user_mapping m
                WHERE i.student_id = m.old_student_id;
            """)

            # Add new foreign key
            cursor.execute("""
                ALTER TABLE billing_invoice
                ADD CONSTRAINT billing_invoice_student_id_fk_billing_user
                FOREIGN KEY (student_id)
                REFERENCES billing_user(id)
                DEFERRABLE INITIALLY DEFERRED;
            """)


def drop_old_tables(apps, schema_editor):
    """Drop the old billing_student table and related tables"""
    with schema_editor.connection.cursor() as cursor:
        print("Dropping old student tables...")

        # Drop old many-to-many table
        cursor.execute("""
            DROP TABLE IF EXISTS billing_student_assigned_teachers CASCADE;
        """)

        # Drop old student table
        cursor.execute("""
            DROP TABLE IF EXISTS billing_student CASCADE;
        """)

        print("Old tables dropped successfully")


def reverse_migration(apps, schema_editor):
    """This migration cannot be reversed - would lose data"""
    raise RuntimeError(
        "This data migration cannot be reversed. "
        "Restore from database backup if you need to roll back."
    )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0019_add_trial_lesson_field'),
    ]

    operations = [
        migrations.RunPython(migrate_students_to_users, reverse_migration),
        migrations.RunPython(migrate_billable_contacts, reverse_migration),
        migrations.RunPython(migrate_lesson_references, reverse_migration),
        migrations.RunPython(migrate_student_teacher_assignments, reverse_migration),
        migrations.RunPython(migrate_invoice_references, reverse_migration),
        migrations.RunPython(drop_old_tables, reverse_migration),
    ]
