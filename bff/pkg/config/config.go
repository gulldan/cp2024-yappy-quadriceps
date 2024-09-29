package config

import (
	"fmt"
	"io/fs"

	"github.com/ilyakaznacheev/cleanenv"
	"github.com/rs/zerolog"
)

type Config struct {
	LogLevel string `yaml:"LOG_LEVEL" env:"LOG_LEVEL" env-default:"info"`

	Grpc          GrpcConfig `yaml:"http"`
	Minio         MinioConfig
	Postgres      PostgresConfig
	Kafka         KafkaConfig
	HTTPPort      string `env:"HTTP_PORT" env-default:"8888"`
	Wav2VecAddr   string `env:"WAV2VEC_ADDR" env-default:"wav2vec:8000"`
	VideocopyAddr string `env:"VIDEOCOPY_ADDR" env-default:"video_copy:8000"`
}

type KafkaConfig struct {
	Address             string `yaml:"kafka_address" env:"KAFKA_ADDRESS" env-default:":7083"`
	AudioInputTopic     string `yaml:"kafka_audio_input_topic" env:"KAFKA_AUDIO_INPUT_TOPIC" env-default:"audio-input"`
	VideoInputTopic     string `yaml:"kafka_video_input_topic" env:"KAFKA_VIDEO_INPUT_TOPIC" env-default:"video-input"`
	VideoCopyrightTopic string `yaml:"kafka_video_copyright_topic" env:"KAFKA_AUDIO_COPYRIGHT_TOPIC" env-default:"audio-copyright"`
	AudioCopyrightTopic string `yaml:"kafka_audio_copyright_topic" env:"KAFKA_VIDEO_COPYRIGHT_TOPIC" env-default:"video-copyright"`
}

type GrpcConfig struct {
	Address string `yaml:"address" env:"HTTP_ADDRESS" env-default:":7083"`
}

type PostgresConfig struct {
	Addr string `yaml:"pg_addr" env:"PG_ADDR"`
}

type MinioConfig struct {
	Endpoint          string `yaml:"minio_addr" env:"MINIO_ADDR"`
	AccessKey         string `yaml:"minio_access_key" env:"MINIO_ACCESS_KEY"`
	SecretAccessKey   string `yaml:"secret_access_key" env:"MINIO_SECRET_ACCESS_KEY"`
	IsUseSsl          bool   `yaml:"is_use_ssl" env:"MINIO_IS_USE_SSL"`
	VideoBucket       string `yaml:"video_bucket" env:"VIDEO_BUCKET" env-default:"video"`
	AudioBucket       string `yaml:"video_bucket" env:"VIDEO_BUCKET" env-default:"audio"`
	PreviewBucket     string `yaml:"preview_bucket" env:"PREVIEW_BUCKET" env-default:"preview"`
	OriginVideoBucket string `yaml:"orig_video_bucket" env:"ORIG_VIDEO_BUCKET" env-default:"origvideo"`
}

func InitConfig() (*Config, *zerolog.Level, error) {
	cnf := Config{}

	err := cleanenv.ReadConfig("config.yml", &cnf)
	if err != nil {
		_, ok := err.(*fs.PathError)
		if ok {
			err = cleanenv.ReadEnv(&cnf)
		}

		if err != nil {
			return nil, nil, fmt.Errorf("failed to read config: %w", err)
		}
	}

	if cnf.LogLevel == "" {
		cnf.LogLevel = "info"
	}

	logLevel, err := zerolog.ParseLevel(cnf.LogLevel)
	if err != nil {
		return nil, nil, fmt.Errorf("invalid log level: %w", err)
	}

	return &cnf, &logLevel, nil
}
