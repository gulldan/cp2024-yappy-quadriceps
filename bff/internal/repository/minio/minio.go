package minio

import (
	"context"
	"fmt"
	"io"
	"net/url"
	"time"

	"github.com/gulldan/cp2024yappy/bff/pkg/config"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type MinioClient struct {
	client              *minio.Client
	videoBucket         string
	audioBucket         string
	previewBucket       string
	originalVideoBucket string
}

func NewMinioClient(opts *config.MinioConfig) (*MinioClient, error) {
	minioClient, err := minio.New(opts.Endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(opts.AccessKey, opts.SecretAccessKey, ""),
		Secure: opts.IsUseSsl,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to create new minio client: %w", err)
	}

	return &MinioClient{
		client:              minioClient,
		videoBucket:         opts.VideoBucket,
		audioBucket:         opts.AudioBucket,
		previewBucket:       opts.PreviewBucket,
		originalVideoBucket: opts.OriginVideoBucket,
	}, nil
}

func (m *MinioClient) UploadFile(ctx context.Context, data io.Reader, dataSize int64, objectName, bucketName string) error {
	if exist := m.isBucketExist(ctx, bucketName); !exist {
		if err := m.makeBucket(ctx, bucketName); err != nil {
			return fmt.Errorf("failed to make bucket when upload file to s3: %w", err)
		}
	}

	_, err := m.client.PutObject(ctx, bucketName, objectName, data, dataSize, minio.PutObjectOptions{})
	if err != nil {
		return fmt.Errorf("failed to put object in s3: %w", err)
	}

	return nil
}

func (m *MinioClient) UploadFileFromOs(ctx context.Context, filePath, objectName, bucketName string) error {
	if exist := m.isBucketExist(ctx, bucketName); !exist {
		if err := m.makeBucket(ctx, bucketName); err != nil {
			return fmt.Errorf("failed to make bucket when upload file to s3: %w", err)
		}
	}

	_, err := m.client.FPutObject(ctx, bucketName, objectName, filePath, minio.PutObjectOptions{})
	if err != nil {
		return fmt.Errorf("failed to put object in s3: %w", err)
	}

	return nil
}

func (m *MinioClient) GetFileURL(ctx context.Context, objectName, bucketName string) (string, error) {
	url, err := m.client.PresignedGetObject(ctx, bucketName, objectName, time.Hour, url.Values{})
	if err != nil {
		return "", fmt.Errorf("PresignedGetObject failed: %w", err)
	}

	return url.String(), nil
}

func (m *MinioClient) isBucketExist(ctx context.Context, bucketName string) bool {
	exists, errBucketExists := m.client.BucketExists(ctx, bucketName)
	if errBucketExists == nil && exists {
		return true
	}

	return false
}

func (m *MinioClient) makeBucket(ctx context.Context, bucketName string) error {
	if err := m.client.MakeBucket(ctx, bucketName, minio.MakeBucketOptions{}); err != nil {
		return fmt.Errorf("failed to make bucket:%w", err)
	}

	return nil
}

func (m *MinioClient) GetFileReader(ctx context.Context, objectName, bucketName string) (io.Reader, error) {
	url, err := m.client.GetObject(ctx, bucketName, objectName, minio.GetObjectOptions{})
	if err != nil {
		return nil, fmt.Errorf("GetObject failed: %w", err)
	}

	return url, nil
}

func (m *MinioClient) GetVideoBucketName() string {
	return m.videoBucket
}

func (m *MinioClient) GetAudioBucketName() string {
	return m.audioBucket
}

func (m *MinioClient) GetPreviewBucketName() string {
	return m.previewBucket
}

func (m *MinioClient) GetOrigVideoBucket() string {
	return m.originalVideoBucket
}
