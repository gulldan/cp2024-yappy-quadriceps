CREATE TYPE task_status AS ENUM ('in_progress', 'fail', 'done');

CREATE TABLE task (
  task_id BIGSERIAL PRIMARY KEY,
  video_name TEXT,
  audio_file TEXT,
  video_file TEXT,
  preview_id TEXT,
  status task_status,
  audio_copyright JSONB,
  video_copyright JSONB
);

CREATE TABLE origvideo (
  video_id TEXT,
  video_hash TEXT UNIQUE
);
