from django.db import migrations

SQL = """
CREATE FUNCTION sinau_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Audit records are append only'; END; $$;
CREATE TRIGGER sinau_audit_immutable BEFORE UPDATE OR DELETE ON core_auditlog
FOR EACH ROW EXECUTE FUNCTION sinau_audit_immutable();
CREATE FUNCTION sinau_medical_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.published_at IS NOT NULL THEN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Published medical records cannot be deleted'; END IF;
    IF (to_jsonb(NEW) - 'is_current' - 'updated_at') IS DISTINCT FROM
       (to_jsonb(OLD) - 'is_current' - 'updated_at') THEN
      RAISE EXCEPTION 'Published medical content requires a new version';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER sinau_medical_immutable BEFORE UPDATE OR DELETE ON care_medicalrecordversion
FOR EACH ROW EXECUTE FUNCTION sinau_medical_immutable();
"""
REVERSE = """
DROP TRIGGER IF EXISTS sinau_medical_immutable ON care_medicalrecordversion;
DROP FUNCTION IF EXISTS sinau_medical_immutable();
DROP TRIGGER IF EXISTS sinau_audit_immutable ON core_auditlog;
DROP FUNCTION IF EXISTS sinau_audit_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial"), ("care", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
