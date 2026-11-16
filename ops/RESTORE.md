# Restore (Supabase)

1. Confirm PITR / backups are enabled on the Supabase project.
2. To restore: use Supabase dashboard → Database → Backups, or `pg_dump` / `psql` restore to a new project and update `DATABASE_URL`.
3. After restore, restart Railway workers and verify `newsie demo` / health workflow.
4. Engage `KILL_SWITCH=true` during restore if digests must pause.
