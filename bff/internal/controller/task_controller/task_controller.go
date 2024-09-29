package taskcontroller

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gulldan/cp2024yappy/bff/internal/model"
	"github.com/gulldan/cp2024yappy/bff/internal/pkg/ffmpeg"
	"github.com/gulldan/cp2024yappy/bff/internal/repository/minio"
	"github.com/gulldan/cp2024yappy/bff/pkg/config"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/rs/xid"
	"github.com/rs/zerolog"
	"github.com/segmentio/kafka-go"

	pgsql "github.com/gulldan/cp2024yappy/bff/internal/repository/postgres"
)

type TaskController struct {
	cfg         *config.Config
	ffmpegExec  *ffmpeg.FfmpegExecutor
	minioClient *minio.MinioClient
	log         *zerolog.Logger
	pgConn      *pgsql.Queries
	audioReader *kafka.Reader
	videoReader *kafka.Reader
	producer    *kafka.Writer
}

// New initializes and returns a new TaskController instance.
func New(cfg *config.Config, log *zerolog.Logger) (*TaskController, error) {
	// Create a Kafka reader for the audio copyright topic.
	audioReader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:  []string{cfg.Kafka.Address},
		Topic:    cfg.Kafka.AudioCopyrightTopic,
		GroupID:  "bff-audio-copyright-reader",
		MaxBytes: 10e6, // 10MB
	})

	// Create a Kafka reader for the video copyright topic.
	videoReader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:  []string{cfg.Kafka.Address},
		Topic:    cfg.Kafka.VideoCopyrightTopic,
		GroupID:  "bff-video-copyright-reader",
		MaxBytes: 10e6, // 10MB
	})

	// Create a Kafka producer.
	producer := &kafka.Writer{
		Addr:     kafka.TCP(cfg.Kafka.Address),
		Balancer: &kafka.LeastBytes{},
	}

	// Set up the HTTP client with a timeout.
	httpCl := http.DefaultClient
	httpCl.Timeout = time.Hour

	pg, err := pgxpool.New(context.Background(), cfg.Postgres.Addr)
	if err != nil {
		return nil, fmt.Errorf("postgres connect failed: %w", err)
	}

	// Create a new Minio client.
	m, err := minio.NewMinioClient(&cfg.Minio)
	if err != nil {
		return nil, fmt.Errorf("failed to create minio client: %w", err)
	}

	// Initialize the TaskController instance.
	controller := &TaskController{
		cfg:         cfg,
		ffmpegExec:  ffmpeg.New(log),
		minioClient: m,
		log:         log,
		pgConn:      pgsql.New(pg),
		audioReader: audioReader,
		videoReader: videoReader,
		producer:    producer,
	}

	// Create necessary Kafka topics.
	controller.createTopics()

	// Start handling Kafka input messages.
	controller.handleKafkaInput(context.Background())

	// Return the initialized TaskController.
	return controller, nil
}

// createTopics creates the necessary Kafka topics as defined in the configuration.
func (ctl *TaskController) createTopics() {
	// Dial the Kafka broker to establish a connection.
	conn, err := kafka.Dial("tcp", ctl.cfg.Kafka.Address)
	if err != nil {
		ctl.log.Error().Err(err).Msg("failed to dial kafka")
		return
	}
	defer conn.Close()

	// Get the Kafka controller information.
	controller, err := conn.Controller()
	if err != nil {
		ctl.log.Error().Err(err).Msg("failed to create controller kafka")
		return
	}

	// Dial the Kafka controller to establish a connection.
	var controllerConn *kafka.Conn
	controllerConn, err = kafka.Dial("tcp", net.JoinHostPort(controller.Host, strconv.Itoa(controller.Port)))
	if err != nil {
		ctl.log.Error().Err(err).Msg("failed to kafka dial")
		return
	}
	defer controllerConn.Close()

	// Define the topic configurations for the necessary Kafka topics.
	topicConfigs := []kafka.TopicConfig{
		{
			Topic:             ctl.cfg.Kafka.AudioInputTopic,
			NumPartitions:     1,
			ReplicationFactor: 1,
		},
		{
			Topic:             ctl.cfg.Kafka.AudioCopyrightTopic,
			NumPartitions:     1,
			ReplicationFactor: 1,
		},
		{
			Topic:             ctl.cfg.Kafka.VideoCopyrightTopic,
			NumPartitions:     1,
			ReplicationFactor: 1,
		},
		{
			Topic:             ctl.cfg.Kafka.VideoInputTopic,
			NumPartitions:     1,
			ReplicationFactor: 1,
		},
	}

	// Create the Kafka topics using the defined configurations.
	_ = controllerConn.CreateTopics(topicConfigs...)
}

// handleKafkaInput handles incoming Kafka messages for audio and video copyright topics.
func (ctl *TaskController) handleKafkaInput(ctx context.Context) {
	// checkTaskDone checks if a task is done by verifying if both audio and video copyrights are set.
	checkTaskDone := func(taskID int64) {
		// Retrieve the task from the database.
		task, err := ctl.pgConn.GetTask(ctx, taskID)
		if err != nil {
			ctl.log.Error().Err(err).Msg("get task failed")
			return
		}

		// Check if both audio and video copyrights are set.
		if len(task.AudioCopyright) != 0 && len(task.VideoCopyright) != 0 {
			// Update the task status to done.
			if err := ctl.pgConn.UpdateTaskStatus(ctx, pgsql.UpdateTaskStatusParams{
				TaskID: taskID,
				Status: pgsql.NullTaskStatus{
					TaskStatus: pgsql.TaskStatusDone,
					Valid:      true,
				},
			}); err != nil {
				ctl.log.Error().Err(err).Msg("update task status to done")
			}
		}
	}

	// Goroutine to handle video copyright Kafka messages.
	go func() {
		for {
			// Read a message from the video copyright Kafka topic.
			msg, err := ctl.videoReader.ReadMessage(ctx)
			if err != nil {
				ctl.log.Error().Err(err).Msg("read message video failed")
				continue
			}

			// Unmarshal the message value into a KafkaResponse struct.
			var k model.KafkaResponse
			if err := json.Unmarshal(msg.Value, &k); err != nil {
				ctl.log.Error().Err(err).Msg("unmarshal message video failed")
				continue
			}

			// Update the video copyright for the task in the database.
			if err := ctl.pgConn.UpdateTaskVideoCopyright(ctx, pgsql.UpdateTaskVideoCopyrightParams{
				TaskID:         k.TaskID,
				VideoCopyright: msg.Value,
			}); err != nil {
				ctl.log.Error().Err(err).Msg("update video copyright failed")
				continue
			}

			// Check if the task is done.
			checkTaskDone(k.TaskID)
		}
	}()

	// Goroutine to handle audio copyright Kafka messages.
	go func() {
		for {
			// Read a message from the audio copyright Kafka topic.
			msg, err := ctl.audioReader.ReadMessage(ctx)
			if err != nil {
				ctl.log.Error().Err(err).Msg("read message audio failed")
				continue
			}

			// Unmarshal the message value into a KafkaResponse struct.
			var k model.KafkaResponse
			if err := json.Unmarshal(msg.Value, &k); err != nil {
				ctl.log.Error().Err(err).Msg("unmarshal message audio failed")
				continue
			}

			// Update the audio copyright for the task in the database.
			if err := ctl.pgConn.UpdateTaskAudioCopyright(ctx, pgsql.UpdateTaskAudioCopyrightParams{
				TaskID:         k.TaskID,
				AudioCopyright: msg.Value,
			}); err != nil {
				ctl.log.Error().Err(err).Msg("update audio copyright failed")
				continue
			}

			// Check if the task is done.
			checkTaskDone(k.TaskID)
		}
	}()
}

// CreateTask creates a new task for a given video file and filename.
func (ctl *TaskController) CreateTask(_ context.Context, file io.Reader, filename string) (int64, error) {
	// Upload the video and extract video and audio files, and generate a preview ID.
	videoFile, audioFile, err := ctl.makePreviewUploadVideo(context.Background(), file)
	if err != nil {
		return 0, fmt.Errorf("failed to upload video: %w", err)
	}

	// Calculate the hash for the uploaded video.
	hash, err := ctl.getHashFromVideo(context.Background(), videoFile, ctl.minioClient.GetVideoBucketName())
	if err != nil {
		return 0, fmt.Errorf("failed to calculate hash for video: %w", err)
	}

	// Retrieve original videos with the same hash from the database.
	videos, err := ctl.pgConn.GetOrigVideosByHash(context.Background(), pgtype.Text{
		String: hash,
		Valid:  true,
	})
	if err != nil {
		return 0, fmt.Errorf("failed to compare hash with original videos: %w", err)
	}

	// If there are existing videos with the same hash, create a new task with status done.
	if len(videos) != 0 {
		// Create a new task with the status set to done.
		task, errC := ctl.pgConn.CreateTask(context.Background(), pgsql.CreateTaskParams{
			VideoFile: pgtype.Text{String: videoFile, Valid: true},
			AudioFile: pgtype.Text{String: audioFile, Valid: true},
			PreviewID: pgtype.Text{String: "aaa", Valid: true},
			Status:    pgsql.NullTaskStatus{TaskStatus: pgsql.TaskStatusDone, Valid: true},
			VideoName: pgtype.Text{String: filename, Valid: true},
		})
		if errC != nil {
			return 0, fmt.Errorf("create task failed: %w", err)
		}

		// Prepare the copyright information for the existing video.
		c := model.Copyright{
			Name:        videos[0].VideoID.String,
			Probability: 1,
		}

		// Marshal the copyright information to JSON.
		copyright, errC := json.Marshal(c)
		if errC != nil {
			return 0, fmt.Errorf("failed to marshal copyright to json: %w", err)
		}

		// Update the video and audio copyright for the task.
		if errC = ctl.pgConn.UpdateTaskVideoCopyright(context.Background(), pgsql.UpdateTaskVideoCopyrightParams{
			TaskID:         task.TaskID,
			VideoCopyright: copyright,
		}); errC != nil {
			return 0, fmt.Errorf("failed to update task copyright: %w", err)
		}

		if errC = ctl.pgConn.UpdateTaskAudioCopyright(context.Background(), pgsql.UpdateTaskAudioCopyrightParams{
			TaskID:         task.TaskID,
			AudioCopyright: copyright,
		}); errC != nil {
			return 0, fmt.Errorf("failed to update task copyright: %w", err)
		}

		// Return the task ID.
		return task.TaskID, nil
	}

	// If no existing videos with the same hash are found, create a new task with status in progress.
	task, err := ctl.pgConn.CreateTask(context.Background(), pgsql.CreateTaskParams{
		VideoFile: pgtype.Text{
			String: videoFile,
			Valid:  true,
		},
		AudioFile: pgtype.Text{String: audioFile, Valid: true},
		PreviewID: pgtype.Text{
			String: "aaa",
			Valid:  true,
		},
		Status: pgsql.NullTaskStatus{
			TaskStatus: pgsql.TaskStatusInProgress,
			Valid:      true,
		},
		VideoName: pgtype.Text{
			String: filename,
			Valid:  true,
		},
	})
	if err != nil {
		return 0, fmt.Errorf("create task failed: %w", err)
	}

	// Start a goroutine to check for copyright infringement.
	go func() {
		if err := ctl.checkForCopyright(context.Background(), task); err != nil {
			ctl.log.Error().Err(err).Any("task", task).Msg("check for copyright failed")
		}
	}()

	// Return the task ID.
	return task.TaskID, nil
}

// checkForCopyright checks for copyright infringement for a given task.
func (ctl *TaskController) checkForCopyright(ctx context.Context, task pgsql.Task) error {
	// Update the task status to "in progress" in the database.
	if err := ctl.pgConn.UpdateTaskStatus(ctx, pgsql.UpdateTaskStatusParams{
		TaskID: task.TaskID,
		Status: pgsql.NullTaskStatus{
			TaskStatus: pgsql.TaskStatusInProgress,
			Valid:      true,
		},
	}); err != nil {
		return fmt.Errorf("failed to update task status: %w", err)
	}

	// Get the URL for the audio file from Minio.
	audioUrl, err := ctl.minioClient.GetFileURL(ctx, task.AudioFile.String, ctl.minioClient.GetAudioBucketName())
	if err != nil {
		return fmt.Errorf("failed to get audio url: %w", err)
	}

	// Get the URL for the video file from Minio.
	videoUrl, err := ctl.minioClient.GetFileURL(ctx, task.VideoFile.String, ctl.minioClient.GetVideoBucketName())
	if err != nil {
		return fmt.Errorf("failed to get video url: %w", err)
	}

	// Marshal the audio URL into a JSON message for Kafka.
	bodyAudio, err := json.Marshal(model.KafkaLink{
		Link:   audioUrl,
		TaskID: task.TaskID,
	})
	if err != nil {
		return fmt.Errorf("failed to marshal kafka link: %w", err)
	}

	// Write the audio URL message to the audio input Kafka topic.
	if err := ctl.producer.WriteMessages(ctx, kafka.Message{
		Topic: ctl.cfg.Kafka.AudioInputTopic,
		Value: bodyAudio,
	}); err != nil {
		return fmt.Errorf("failed to write message to audio topic: %w", err)
	}

	// Marshal the video URL into a JSON message for Kafka.
	bodyVideo, err := json.Marshal(model.KafkaLink{
		Link:   videoUrl,
		TaskID: task.TaskID,
	})
	if err != nil {
		return fmt.Errorf("failed to marshal kafka link: %w", err)
	}

	// Write the video URL message to the video input Kafka topic.
	if err := ctl.producer.WriteMessages(ctx, kafka.Message{
		Topic: ctl.cfg.Kafka.VideoInputTopic,
		Value: bodyVideo,
	}); err != nil {
		return fmt.Errorf("failed to write message to video topic: %w", err)
	}

	// Return nil if all steps are successful.
	return nil
}

// GetTask retrieves a task by its ID.
func (ctl *TaskController) GetTask(_ context.Context, id int64) (model.Task, error) {
	// Retrieve the task from the database using the provided ID.
	pgtask, err := ctl.pgConn.GetTask(context.Background(), id)
	if err != nil {
		return model.Task{}, fmt.Errorf("get task failed: %w", err)
	}

	// Convert the retrieved task from the database model to the application model.
	task, err := taskToModel(pgtask)
	if err != nil {
		return model.Task{}, err
	}

	// Return the converted task.
	return task, nil
}

// GetTasks retrieves a list of tasks with pagination.
func (ctl *TaskController) GetTasks(_ context.Context, limit, offset uint64) ([]model.Task, int64, error) {
	// Retrieve the tasks from the database with the specified limit and offset for pagination.
	pgtasks, err := ctl.pgConn.GetTasks(context.Background(), pgsql.GetTasksParams{
		Limit:  int32(limit),
		Offset: int32(offset),
	})
	if err != nil {
		return nil, 0, fmt.Errorf("get tasks failed: %w", err)
	}

	// Convert the retrieved tasks from the database model to the application model.
	tasks, err := taskSliceToModel(pgtasks)
	if err != nil {
		return nil, 0, err
	}

	// Get the total count of tasks in the database.
	total, err := ctl.pgConn.GetTasksCount(context.Background())
	if err != nil {
		return nil, 0, fmt.Errorf("failed to get tasks count: %w", err)
	}

	// Return the list of tasks and the total count.
	return tasks, total, nil
}

// makePreviewUploadVideo uploads a video file, generates an audio file, and creates a preview image.
func (ctl *TaskController) makePreviewUploadVideo(ctx context.Context, file io.Reader) (videoID, audioID string, err error) {
	// Generate a unique ID for the video file.
	id := xid.New().String() + ".mp4"

	// Create a temporary file to store the uploaded video.
	tmpFile, err := os.CreateTemp("", "")
	if err != nil {
		return "", "", fmt.Errorf("failed to create temporary file: %w", err)
	}

	// Copy the uploaded file to the temporary file.
	if _, err = io.Copy(tmpFile, file); err != nil {
		return "", "", fmt.Errorf("io.Copy failed: %w", err)
	}

	// Ensure the temporary file is removed after processing.
	defer func() {
		if errDef := os.Remove(tmpFile.Name()); errDef != nil {
			ctl.log.Error().Err(errDef).Str("path", tmpFile.Name()).Msg("failed to remove tmp file")
		}
	}()

	// Get the metadata of the temporary file.
	stat, err := tmpFile.Stat()
	if err != nil {
		return "", "", fmt.Errorf("failed to get file metainfo: %w", err)
	}

	// Reset the file pointer to the beginning of the file.
	if _, err = tmpFile.Seek(0, 0); err != nil {
		return "", "", fmt.Errorf("failed to reset reader tmpfile: %w", err)
	}

	// Upload the video file to Minio.
	if err = ctl.minioClient.UploadFile(context.Background(), tmpFile, stat.Size(), id, ctl.minioClient.GetVideoBucketName()); err != nil {
		return "", "", fmt.Errorf("failed to upload video to minio: %w", err)
	}

	// Generate an audio file from the video.
	audioFile, err := ctl.generateAudio(ctx, id)
	if err != nil {
		return "", "", fmt.Errorf("failed to generate audio from video: %w", err)
	}

	// Return the video ID, audio file ID, preview image ID, and video length.
	return id, audioFile, nil
}

// getHashFromVideo calculates the MD5 hash of a video file stored in Minio.
func (ctl *TaskController) getHashFromVideo(ctx context.Context, id, bucket string) (string, error) {
	// Get a reader for the video file from Minio.
	rdr, err := ctl.minioClient.GetFileReader(ctx, id, bucket)
	if err != nil {
		return "", fmt.Errorf("failed to get reader from minio: %w", err)
	}

	// Create a new MD5 hash instance.
	h := md5.New()

	// Copy the video file content to the hash instance.
	if _, err := io.Copy(h, rdr); err != nil {
		log.Fatal(err)
	}

	// Return the hexadecimal representation of the hash.
	return hex.EncodeToString(h.Sum(nil)), nil
}

// generateAudio generates an audio file from a video file stored in Minio.
func (ctl *TaskController) generateAudio(ctx context.Context, id string) (string, error) {
	// Get a reader for the video file from Minio.
	videoReader, err := ctl.minioClient.GetFileReader(context.Background(), id, ctl.minioClient.GetVideoBucketName())
	if err != nil {
		return "", err
	}

	// Create a temporary file to store the audio extracted from the video.
	tmpfile, err := os.CreateTemp("", "*.wav")
	if err != nil {
		return "", err
	}
	// Ensure the temporary file is removed and closed after processing.
	defer os.Remove(tmpfile.Name())
	defer tmpfile.Close()

	// Copy the video file content to the temporary file.
	if _, err = io.Copy(tmpfile, videoReader); err != nil {
		return "", err
	}

	// Extract the audio from the video file and get the audio file name.
	audioFileName, err := ctl.ffmpegExec.GetAudioFromVideo(tmpfile.Name())
	if err != nil {
		return "", err
	}

	// Open the extracted audio file.
	audioFile, err := os.Open(audioFileName)
	if err != nil {
		return "", err
	}
	// Ensure the audio file is removed and closed after processing.
	defer os.Remove(audioFileName)
	defer audioFile.Close()

	// Upload the audio file to Minio.
	if err = ctl.minioClient.UploadFileFromOs(context.Background(), audioFileName, audioFileName, ctl.minioClient.GetAudioBucketName()); err != nil {
		return "", fmt.Errorf("failed to upload audio to minio: %w", err)
	}

	// Return the audio file name.
	return audioFileName, nil
}

// updateAudioLinkReq represents the request structure for updating an audio link in the database.
type updateAudioLinkReq struct {
	Link     string `json:"link"`
	Filename string `json:"filename"`
}

// UploadToDatabaseAudio uploads the audio file link to the database.
func (ctl *TaskController) UploadToDatabaseAudio(ctx context.Context, taskID int64) error {
	// Retrieve the task from the database using the provided task ID.
	task, err := ctl.pgConn.GetTask(ctx, taskID)
	if err != nil {
		return fmt.Errorf("get task failed: %w", err)
	}

	// Get the URL for the audio file from Minio.
	url, err := ctl.minioClient.GetFileURL(ctx, task.AudioFile.String, ctl.minioClient.GetAudioBucketName())
	if err != nil {
		return fmt.Errorf("get url failed: %w", err)
	}

	// Create the update request structure with the audio file URL and the video filename.
	upd := updateAudioLinkReq{
		Link:     url,
		Filename: task.VideoName.String,
	}

	// Marshal the update request structure to JSON.
	b, err := json.Marshal(upd)
	if err != nil {
		return fmt.Errorf("json marshal failed: %w", err)
	}

	// Create a new HTTP POST request to update the audio link in the database.
	req, err := http.NewRequest(http.MethodPost, ctl.cfg.Wav2VecAddr+"/update_database", bytes.NewBuffer(b))
	if err != nil {
		return fmt.Errorf("create new request failed: %w", err)
	}

	// Send the HTTP request and get the response.
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("make request failed: %w", err)
	}

	// Read the response body.
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("io read all failed: %w", err)
	}

	// Log the response body for debugging purposes.
	ctl.log.Info().Str("resp_body", string(respBody)).Msg("audio add to database")

	// Return nil if all steps are successful.
	return nil
}

// updateVideoLinkReq represents the request structure for updating a video link in the database.
type updateVideoLinkReq struct {
	URL  string `json:"url"`
	UUID string `json:"uuid"`
}

// UploadToDatabaseVideo uploads the video file link to the database.
func (ctl *TaskController) UploadToDatabaseVideo(ctx context.Context, taskID int64) error {
	// Retrieve the task from the database using the provided task ID.
	task, err := ctl.pgConn.GetTask(ctx, taskID)
	if err != nil {
		return fmt.Errorf("get task failed: %w", err)
	}

	// Get the URL for the audio file from Minio.
	url, err := ctl.minioClient.GetFileURL(ctx, task.AudioFile.String, ctl.minioClient.GetAudioBucketName())
	if err != nil {
		return fmt.Errorf("get url failed: %w", err)
	}

	// Create the update request structure with the audio file URL and the video UUID.
	upd := updateVideoLinkReq{
		URL:  url,
		UUID: task.VideoName.String,
	}

	// Marshal the update request structure to JSON.
	b, err := json.Marshal(upd)
	if err != nil {
		return fmt.Errorf("json marshal failed: %w", err)
	}

	// Create a new HTTP POST request to update the video link in the database.
	req, err := http.NewRequest(http.MethodPost, ctl.cfg.VideocopyAddr+"/upload_video", bytes.NewBuffer(b))
	if err != nil {
		return fmt.Errorf("create new request failed: %w", err)
	}

	// Send the HTTP request and get the response.
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("make request failed: %w", err)
	}

	// Read the response body.
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("io read all failed: %w", err)
	}

	// Log the response body for debugging purposes.
	ctl.log.Info().Str("resp_body", string(respBody)).Msg("video add to database")

	// Return nil if all steps are successful.
	return nil
}
