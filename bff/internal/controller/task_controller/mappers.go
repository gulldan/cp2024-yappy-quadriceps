package taskcontroller

import (
	"encoding/json"

	"github.com/gulldan/cp2024yappy/bff/internal/model"

	pgsql "github.com/gulldan/cp2024yappy/bff/internal/repository/postgres"
)

// statusToModel converts a PostgreSQL task status to a model task status.
func statusToModel(s pgsql.TaskStatus) model.TaskStatus {
	switch s {
	case pgsql.TaskStatusDone:
		return model.TaskStatusDone
	case pgsql.TaskStatusFail:
		return model.TaskStatusFailed
	case pgsql.TaskStatusInProgress:
		return model.TaskStatusInProgress
	default:
		return model.TaskStatusFailed
	}
}

// taskSliceToModel converts a slice of PostgreSQL tasks to a slice of model tasks.
func taskSliceToModel(t []pgsql.Task) ([]model.Task, error) {
	// Create a slice of model tasks with the same length as the input slice.
	m := make([]model.Task, len(t))
	var err error

	// Iterate over the input slice and convert each PostgreSQL task to a model task.
	for i := range t {
		m[i], err = taskToModel(t[i])
		if err != nil {
			return nil, err
		}
	}

	// Return the converted slice of model tasks.
	return m, nil
}

// taskToModel converts a PostgreSQL task to a model task.
func taskToModel(t pgsql.Task) (model.Task, error) {
	// Initialize variables for audio and video copyright responses.
	var aud model.KafkaResponse
	var vid model.KafkaResponse

	// Unmarshal the audio copyright JSON into the audio response struct.
	if err := json.Unmarshal(t.AudioCopyright, &aud); err != nil {
		aud = model.KafkaResponse{} // Initialize to an empty struct if unmarshaling fails.
	}

	// Unmarshal the video copyright JSON into the video response struct.
	if err := json.Unmarshal(t.VideoCopyright, &vid); err != nil {
		vid = model.KafkaResponse{} // Initialize to an empty struct if unmarshaling fails.
	}

	// Return the converted model task.
	return model.Task{
		TaskID:         t.TaskID,
		Status:         statusToModel(t.Status.TaskStatus),
		VideoCopyright: vid.Copy,
		AudioCopyright: aud.Copy,
	}, nil
}
