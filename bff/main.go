package main

import (
	"context"
	"embed"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gulldan/cp2024yappy/bff/pkg/config"
	"github.com/rs/zerolog"
)

//go:embed swagger-ui/docs
var swaggerDocsFS embed.FS

func main() {
	cfg, logLevel, err := config.InitConfig()
	if err != nil {
		panic(err)
	}

	log := zerolog.New(os.Stdout).Level(*logLevel).With().Timestamp().Logger()
	a, err := New(cfg, &log, &swaggerDocsFS)
	if err != nil {
		log.Error().Err(err).Msg("start http server failed")
		return
	}

	go func() {
		err = a.Start()
		if err != nil {
			log.Error().Err(err).Msg("start http server failed")
		}
	}()

	if err := gracefulShutdown(&log); err != nil {
		log.Error().Err(err).Msg("graceful shutdown failed")
	}
}

func gracefulShutdown(logger *zerolog.Logger) error {
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)

	ctx := context.Background()
	ctx, cancel := context.WithTimeout(ctx, time.Second*5)

	sig := <-sigs
	logger.Info().Str("signal", sig.String()).Msg("signal received, graceful shutdown")

	defer cancel()

	return nil
}
