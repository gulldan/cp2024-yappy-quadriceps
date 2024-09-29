-- name: GetTask :one
SELECT * FROM task
WHERE task_id = $1 LIMIT 1;

-- name: GetTasks :many
SELECT * FROM task
ORDER BY task_id ASC
LIMIT $1 OFFSET $2;

-- name: GetTasksCount :one
SELECT count(*) FROM task;

-- name: CreateTask :one
INSERT INTO task (
  video_file, audio_file, preview_id, status, video_name
) VALUES (
  $1, $2, $3, $4, $5
)
RETURNING *;

-- name: UpdateTaskAudioCopyright :exec
UPDATE task SET audio_copyright = $2
WHERE task_id = $1;

-- name: UpdateTaskVideoCopyright :exec
UPDATE task SET video_copyright = $2
WHERE task_id = $1;

-- name: UpdateTaskStatus :exec
UPDATE task SET status = $2
WHERE task_id = $1;


-- name: GetOrigVideo :one
SELECT * FROM origvideo
WHERE video_id = $1 LIMIT 1;

-- name: GetOrigVideos :many
SELECT * FROM origvideo
ORDER BY video_id DESC
LIMIT $1 OFFSET $2;

-- name: GetOrigVideosByHash :many
SELECT * FROM origvideo
WHERE video_hash = $1
ORDER BY video_id DESC;

-- name: CreateOrigVideo :one
INSERT INTO origvideo (
  video_id, video_hash
) VALUES (
  $1, $2
)
RETURNING *;
