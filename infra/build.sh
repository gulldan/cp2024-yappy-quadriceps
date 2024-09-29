#!/bin/bash

echo "TARGET_IP=$TARGET_IP" >> ./configs/envs/dev.env
#
# for local testing uncomment below strings
#
# echo "LOCALHOST_IP=127.0.0.1" >> ./envs/dev.env
# echo "POSTGRES_EXT_PORT=15432" >> ./envs/dev.env
source ./configs/envs/dev.env

sudo mkdir -p "$PREFIX"/cp2024yappi/prometheus/config \
"$PREFIX"/cp2024yappi/prometheus/data \
"$PREFIX"/cp2024yappi/db \
"$PREFIX"/cp2024yappi/grafana/provisioning \
"$PREFIX"/cp2024yappi/openobserve \
"$PREFIX"/cp2024yappi/vector \
"$PREFIX"/cp2024yappi/models/ve \
"$PREFIX"/cp2024yappi/models/qdrant \
"$PREFIX"/cp2024yappi/qdrant \
"$PREFIX"/cp2024yappi/meilisearch \
"$PREFIX"/cp2024yappi/minio/data

#bash cert.sh
QDRANT_COLLECTIONS_PATH="${QDRANT_PATH}/collections"
mkdir $QDRANT_COLLECTIONS_PATH

chmod -R 777 "$PREFIX"/cp2024yappi/prometheus/config
chmod -R 777 "$PREFIX"/cp2024yappi/prometheus/data
chmod -R 777 "$PREFIX"/cp2024yappi/grafana
chmod -R 777 "$PREFIX"/cp2024yappi/openobserve
chmod -R 777 "$PREFIX"/cp2024yappi/vector
chmod -R 777 "$PREFIX"/cp2024yappi/db
chmod -R 777 "$PREFIX"/cp2024yappi/models
chmod -R 777 "$PREFIX"/cp2024yappi/qdrant
chmod -R 777 "$QDRANT_COLLECTIONS_PATH"

cp configs/prometheus/prometheus.yml "$PREFIX"/cp2024yappi/prometheus/config
cp -R configs/grafana/provisioning/* "$PREFIX"/cp2024yappi/grafana/provisioning
cp -f configs/vector/vector.toml "$PREFIX"/cp2024yappi/vector

FILE_URLS=("https://drive.usercontent.google.com/download?id=1un80YKwZW463S1lgu8BW1rSiBL0ECsdo&confirm=xxx")

FILE_NAMES=("${ENCODER_MODEL}")

# Количество файлов
NUM_FILES=${#FILE_URLS[@]}
# Цикл для проверки и скачивания файлов


for (( i=0; i<$NUM_FILES; i++ )); do
    FILE_URL=${FILE_URLS[$i]}
    FILE_NAME=${FILE_NAMES[$i]}

    # Проверка существования файла
    if [ -f "$FILE_NAME" ]; then
        echo "Файл $FILE_NAME уже существует, пропуск скачивания."
    else
        echo "Файл $FILE_NAME не найден, начинаю скачивание."
        # Скачивание файла с использованием curl
        curl -L -o "$FILE_NAME" "$FILE_URL"
    fi
done

unzip -d $QDRANT_COLLECTIONS_PATH $AUDIO_EMBBEDINGS
unzip -d $QDRANT_COLLECTIONS_PATH $FBL

rm $AUDIO_EMBBEDINGS
rm $FBL

docker compose --env-file ./configs/envs/dev.env up --build -d
sleep 1

echo "done"
