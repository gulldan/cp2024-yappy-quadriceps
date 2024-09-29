package main

import (
	"context"
	"encoding/csv"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/gulldan/cp2024yappy/bff/internal/model"
	"github.com/gulldan/cp2024yappy/bff/pkg/config"
	"github.com/rs/zerolog"

	_ "embed"

	taskcontroller "github.com/gulldan/cp2024yappy/bff/internal/controller/task_controller"
)

var dst = "submission.csv"

type VideoLinkRequest struct {
	Link string `json:"link"`
	Name string `json:"-"`
}

type VideoLinkResponse struct {
	DuplicateFor string `json:"duplicate_for,omitempty"`
	IsDuplicate  bool   `json:"is_duplicate,omitempty"`
}

type API struct {
	log           *zerolog.Logger
	r             *gin.Engine
	taskContoller *taskcontroller.TaskController
}

func New(cfg *config.Config, log *zerolog.Logger, f fs.FS) (*API, error) {
	a := &API{
		log: log,
	}

	router := gin.Default()
	router.Use(cors.New(cors.Config{
		AllowOriginFunc: func(origin string) bool {
			return true
		},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"},
		AllowHeaders:     []string{"*"},
		ExposeHeaders:    []string{"Location"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))
	router.MaxMultipartMemory = 32 << 20

	router.POST("/check-video-duplicate", a.CheckVideoDuplicate)
	f, _ = fs.Sub(f, "swagger-ui/docs")
	router.StaticFS("/docs", http.FS(f))
	router.POST("/upload", func(c *gin.Context) {
		// single file
		file, _ := c.FormFile("file")

		// Upload the file to specific dst.
		if err := c.SaveUploadedFile(file, dst); err != nil {
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
				"message": "Save upload file failed: " + err.Error(),
			})
			return
		}

		outputFile, err := os.Create("output.csv")
		if err != nil {
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
				"message": "create submission file failed: " + err.Error(),
			})
			return
		}
		defer outputFile.Close()

		writer := csv.NewWriter(outputFile)

		videos := readCsv()
		for _, v := range videos {
			id, copyrighted, err := a.runCopyright(VideoLinkRequest{
				Link: v.Link,
				Name: v.UUID,
			})
			if err != nil {
				c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
					"message": "run copyright failed: " + err.Error(),
				})
				continue
			}

			record := []string{
				v.Created.Format(time.RFC3339),
				v.UUID,
				v.Link,
				strconv.FormatBool(copyrighted),
				id,
			}

			if err := writer.Write(record); err != nil {
				c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
					"message": "write submission file failed: " + err.Error(),
				})
				continue
			}
		}

		writer.Flush()
		c.File("output.csv")
	})

	a.r = router

	var err error
	a.taskContoller, err = taskcontroller.New(cfg, log)
	if err != nil {
		return nil, err
	}

	return a, nil
}

type Video struct {
	Created time.Time
	UUID    string
	Link    string
}

func readCsv() []Video {
	file, err := os.Open(dst)
	if err != nil {
		log.Fatal(err)
	}
	defer file.Close()

	reader := csv.NewReader(file)

	// Read the header
	header, err := reader.Read()
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("Header:", header)

	// Read the records
	var videos []Video
	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			log.Fatal(err)
		}

		created, err := time.Parse("2006-01-02 15:04:05", record[0])
		if err != nil {
			log.Fatalf("Error parsing date: %v", err)
		}

		video := Video{
			Created: created,
			UUID:    record[1],
			Link:    record[2],
		}

		videos = append(videos, video)
	}

	sort.Slice(videos, func(i, j int) bool {
		return videos[i].Created.Before(videos[j].Created)
	})

	return videos
}

func (a *API) Start() error {
	return a.r.Run(":7083")
}

func (a *API) RunCSV(c *gin.Context) {
}

func (a *API) CheckVideoDuplicate(c *gin.Context) {
	var v VideoLinkRequest
	if err := c.BindJSON(&v); err != nil {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{
			"message": "failed to bind json: " + err.Error(),
		})
		return
	}

	if v.Link == "" {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{
			"message": "No video link",
		})
		return
	}

	id, copyrighted, err := a.runCopyright(v)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
			"message": "run copyright failed: " + err.Error(),
		})
		return
	}

	if copyrighted {
		c.JSON(http.StatusOK, VideoLinkResponse{
			DuplicateFor: id,
			IsDuplicate:  true,
		})
		return
	} else {
		c.JSON(http.StatusOK, VideoLinkResponse{
			DuplicateFor: "",
			IsDuplicate:  false,
		})
		return
	}
}

func (a *API) runCopyright(v VideoLinkRequest) (string, bool, error) {
	resp, err := http.Get(v.Link)
	if err != nil {
		a.log.Error().Err(err).Msg("failed to get video")
		return "", false, err
	}
	defer resp.Body.Close()

	fileNameSpl := strings.Split(v.Link, "/")
	fileName := fileNameSpl[len(fileNameSpl)-1]
	if v.Name != "" {
		fileName = v.Name
	}
	id, err := a.taskContoller.CreateTask(context.Background(), resp.Body, fileName)
	if err != nil {
		return "", false, fmt.Errorf("failed to create task: %w", err)
	}

	for {
		time.Sleep(time.Millisecond * 100)
		m, err := a.taskContoller.GetTask(context.Background(), id)
		if err != nil {
			return "", false, fmt.Errorf("failed to get task: %w", err)
		}

		if m.Status == model.TaskStatusDone {
			id, copyrighted := isCopyrighted(m.VideoCopyright, m.AudioCopyright)
			if copyrighted {
				return id, copyrighted, nil
			} else {
				if err := a.taskContoller.UploadToDatabaseAudio(context.Background(), m.TaskID); err != nil {
					a.log.Error().Err(err).Msg("update database audio failed")
				}
				if err := a.taskContoller.UploadToDatabaseVideo(context.Background(), m.TaskID); err != nil {
					a.log.Error().Err(err).Msg("update database video failed")
				}

				return id, copyrighted, nil
			}
		}
	}
}

func isCopyrighted(videoCopyright []model.Copyright, audioCopyright []model.Copyright) (string, bool) {
	if len(videoCopyright) == 0 || len(audioCopyright) == 0 {
		return "", false
	}

	videoMap := map[string]float64{}
	for _, v := range videoCopyright {
		videoMap[v.Name] = v.Probability
	}

	audioMap := map[string]float64{}
	for _, a := range audioCopyright {
		audioMap[a.Name] = a.Probability
	}

	for k := range videoMap {
		if _, ok := audioMap[k]; !ok {
			delete(videoMap, k)
			continue
		}

		videoMap[k] = 2 * (videoMap[k] * audioMap[k]) / (videoMap[k] + audioMap[k])
	}

	if len(videoMap) == 0 {
		return "", false
	}

	var finProbs []model.Copyright
	for k, v := range videoMap {
		finProbs = append(finProbs, model.Copyright{
			Name:        k,
			Probability: v,
		})
	}

	for i := range finProbs {
		if finProbs[i].Probability < 0.75 {
			finProbs[i] = finProbs[len(finProbs)-1]
			finProbs[len(finProbs)-1] = model.Copyright{}
			finProbs = finProbs[:len(finProbs)-1]
		}
	}

	sort.Slice(finProbs, func(i, j int) bool {
		return finProbs[i].Probability < finProbs[j].Probability
	})

	if len(finProbs) == 0 {
		return "", false
	}

	return finProbs[0].Name, true
}
