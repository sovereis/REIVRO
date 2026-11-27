-- Only for the trusted operator. Keep its output private; no passwords/tokens/emails.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='20s';
SET LOCAL lock_timeout='5s';
SELECT m.user_id,p.repository_id,m.role
FROM reivro_cloud.memberships m JOIN reivro_cloud.projects p ON p.id=m.project_id
ORDER BY p.repository_id,m.role,m.user_id;
SELECT u.id AS user_id, u.email_confirmed_at IS NOT NULL AS confirmed,
       coalesce(u.is_anonymous,false) AS is_anonymous,
       EXISTS(SELECT FROM reivro_cloud.memberships m WHERE m.user_id=u.id) AS has_membership
FROM auth.users u ORDER BY u.id;
SELECT p.repository_id,r.id AS run_id,r.base_sha,r.head_sha,r.outcome
FROM reivro_cloud.runs r JOIN reivro_cloud.projects p ON p.id=r.project_id
ORDER BY p.repository_id,r.id;
SELECT p.repository_id,s.id AS submission_id,s.actor AS owner_user_id,s.head_sha,s.digest
FROM reivro_cloud.task_submissions s JOIN reivro_cloud.projects p ON p.id=s.project_id
ORDER BY p.repository_id,s.id;
COMMIT;
