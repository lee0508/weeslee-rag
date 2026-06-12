6. JobTracker는 2차로 구현
frontend/js/job-tracker.js
공통 Job 상태 조회 endpoint 후보:
GET /api/admin/jobs/{job_id}
필수 표시 항목:
job_id
job_type
status
progress_percent
processed_count
total_count
success_count
failed_count
started_at
finished_at
last_message