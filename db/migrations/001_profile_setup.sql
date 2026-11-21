-- JobAI v1.1 — profile setup fields (onboarding steps 1–6)
-- Run in pgAdmin Query Tool while connected to jobai_db, after jobai_v1_schema.sql.
-- Transactional and safe to rerun: existing columns/tables are skipped, no data is changed.
BEGIN;

-- 1. user_profiles: Basic Info + Additional Information
ALTER TABLE jobai.user_profiles
 ADD COLUMN IF NOT EXISTS total_experience_years NUMERIC(4,1)
   CONSTRAINT user_profiles_total_experience_chk CHECK (total_experience_years IS NULL OR total_experience_years BETWEEN 0 AND 60),
 ADD COLUMN IF NOT EXISTS career_gap VARCHAR(20)
   CONSTRAINT user_profiles_career_gap_chk CHECK (career_gap IN ('none','under_6_months','6_to_12_months','over_1_year')),
 ADD COLUMN IF NOT EXISTS work_authorization_status VARCHAR(30)
   CONSTRAINT user_profiles_work_auth_status_chk CHECK (work_authorization_status IN ('citizen','permanent_resident','work_visa','student_visa','other')),
 ADD COLUMN IF NOT EXISTS work_authorization_country CHAR(2)
   CONSTRAINT user_profiles_work_auth_country_chk CHECK (work_authorization_country ~ '^[A-Z]{2}$');

-- 2. job_preferences: Career Preferences + Additional Information switches
ALTER TABLE jobai.job_preferences
 ADD COLUMN IF NOT EXISTS employment_status VARCHAR(20)
   CONSTRAINT job_preferences_employment_status_chk CHECK (employment_status IN ('student','fresher','employed','actively_looking')),
 ADD COLUMN IF NOT EXISTS recruiter_visibility BOOLEAN NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS daily_job_match_digest BOOLEAN NOT NULL DEFAULT false;

-- 3. user_certifications: one row per certification
CREATE TABLE IF NOT EXISTS jobai.user_certifications (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id UUID NOT NULL REFERENCES jobai.users(id) ON DELETE CASCADE,
 certification_name VARCHAR(250) NOT NULL,
 issuing_organization VARCHAR(250),
 issue_date DATE, expiry_date DATE,
 credential_id VARCHAR(200), credential_url TEXT,
 display_order SMALLINT NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK (length(trim(certification_name)) > 0),
 CHECK (expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date)
);
CREATE INDEX IF NOT EXISTS user_certifications_user_idx ON jobai.user_certifications(user_id,display_order);

-- 4. user_languages: one row per language, no duplicates per user
CREATE TABLE IF NOT EXISTS jobai.user_languages (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id UUID NOT NULL REFERENCES jobai.users(id) ON DELETE CASCADE,
 language_name VARCHAR(100) NOT NULL,
 proficiency_level VARCHAR(20) NOT NULL CHECK (proficiency_level IN ('basic','conversational','intermediate','professional','native')),
 display_order SMALLINT NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK (length(trim(language_name)) > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS user_languages_user_name_ci_uq ON jobai.user_languages(user_id,lower(language_name));

-- 5. keep updated_at current on the new tables (same trigger as the other tables)
DO $$ DECLARE tab TEXT; BEGIN
 FOREACH tab IN ARRAY ARRAY['user_certifications','user_languages'] LOOP
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'touch_updated_at_' || tab AND tgrelid = ('jobai.' || tab)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON jobai.%I FOR EACH ROW EXECUTE FUNCTION jobai.touch_updated_at()', 'touch_updated_at_' || tab,tab);
  END IF;
 END LOOP;
END $$;

COMMIT;
