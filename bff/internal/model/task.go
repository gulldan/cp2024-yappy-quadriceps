package model

type TaskStatus uint

const (
	TaskStatusDone TaskStatus = iota
	TaskStatusInProgress
	TaskStatusFailed
)

type KafkaLink struct {
	TaskID int64  `json:"task_id"`
	Link   string `json:"link"`
}

type KafkaResponse struct {
	TaskID int64       `json:"task_id"`
	Copy   []Copyright `json:"copyright"`
}

type Copyright struct {
	Name        string
	Probability float64
}

type Task struct {
	TaskID         int64
	Status         TaskStatus
	VideoCopyright []Copyright
	AudioCopyright []Copyright
}
