mkdir -p "$(pwd)"/models
docker run -d --gpus=all -p 8000:8000 --name wav2vec --net=host --mount type=bind,source="$(pwd)"/models,target=/app/models wav2vec:latest