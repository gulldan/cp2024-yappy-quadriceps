package ffmpeg

import (
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"github.com/rs/xid"
	"github.com/rs/zerolog"
)

// ErrWrongTimeOutput is an error indicating invalid time output.
var ErrWrongTimeOutput = errors.New("invalid time output")

// FfmpegExecutor is a struct that handles FFmpeg operations.
type FfmpegExecutor struct {
	log *zerolog.Logger
}

// New initializes and returns a new FfmpegExecutor instance.
func New(log *zerolog.Logger) *FfmpegExecutor {
	return &FfmpegExecutor{
		log: log,
	}
}

// timespan is a type alias for time.Duration.
type timespan time.Duration

// GetAudioFromVideo extracts the audio from a video file and saves it as a .wav file.
func (f *FfmpegExecutor) GetAudioFromVideo(filename string) (string, error) {
	// Generate a unique name for the audio file.
	audioName := xid.New().String() + ".wav"

	// Define the FFmpeg command flags to extract audio from the video.
	flags := []string{
		"-i", filename,
		"-vn",
		"-acodec", "pcm_s16le",
		"-ar", "44100",
		"-ac", "2", audioName,
	}

	// Create and run the FFmpeg command.
	cmd := exec.Command("ffmpeg", flags...)
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("failed to run ffmpeg: %w", err)
	}

	// Return the name of the generated audio file.
	return audioName, nil
}

// Format formats the timespan as a string.
func (t timespan) Format(format string) string {
	// Create a zero time instance and add the timespan duration.
	z := time.Unix(0, 0).UTC()
	return z.Add(time.Duration(t)).Format(format)
}

// GetScreenshotFromVideo generates a screenshot from the middle of the video.
func (f *FfmpegExecutor) GetScreenshotFromVideo(filename string) (string, error) {
	// Generate a unique name for the screenshot file.
	id := xid.New().String() + ".png"

	// Get the length of the video.
	length, err := f.GetVideoLength(filename)
	if err != nil {
		return "", fmt.Errorf("get video length failed: %w", err)
	}

	// Calculate the middle point of the video.
	length /= 2

	// Define the FFmpeg command flags to generate a screenshot from the video.
	flags := []string{"-ss", timespan(length).Format("15:04:05"), "-i", filename, "-frames:v", "1", id}

	// Create and run the FFmpeg command.
	cmd := exec.Command("ffmpeg", flags...)
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("ffmpeg run failed: %w", err)
	}

	// Return the name of the generated screenshot file.
	return id, nil
}

// GetVideoLength retrieves the length of the video using ffprobe.
func (f *FfmpegExecutor) GetVideoLength(filename string) (time.Duration, error) {
	// Define the ffprobe command flags to get the video duration.
	flags := []string{"-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", "-sexagesimal", filename}
	f.log.Debug().Strs("flags", flags).Msg("starting ffprobe")

	// Create and run the ffprobe command.
	cmd := exec.Command("ffprobe", flags...)

	// Capture the output of the ffprobe command.
	outputBytes, err := cmd.Output()
	if err != nil {
		return 0, fmt.Errorf("ffprobe get output failed: %w", err)
	}

	// Parse the output to get the video duration.
	return parseTime(string(outputBytes))
}

// parseTime parses the time output from ffprobe and returns it as a time.Duration.
func parseTime(t string) (time.Duration, error) {
	// Split the time output into hours, minutes, and seconds.
	sp := strings.Split(t, ".")
	if len(sp) != 2 {
		return 0, fmt.Errorf("%w: %s", ErrWrongTimeOutput, t)
	}

	// Parse the time string into a time.Time instance.
	tt, err := time.Parse("15:04:05", sp[0])
	if err != nil {
		return 0, fmt.Errorf("failed to parse time: %w", err)
	}

	// Calculate the duration by subtracting the zero time instance.
	return tt.Sub(time.Time{}), nil
}
