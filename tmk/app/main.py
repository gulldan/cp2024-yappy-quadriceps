import logging
import os

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, HttpUrl

from .batch_download import batch_download
from .clustering import cluster_videos
from .download import download_video
from .video_processing import process_videos_in_parallel

# Инициализация FastAPI приложения
app = FastAPI()

# Настройка логирования
logging.basicConfig(filename="logs/app.log", level=logging.INFO, format="%(asctime)s:%(levelname)s:%(message)s")


# Модели для запросов и ответов
class VideoLinkRequest(BaseModel):
    link: HttpUrl


class BatchDownloadRequest(BaseModel):
    links: list[HttpUrl]


class ClusterResponse(BaseModel):
    clusters: dict[int, list[HttpUrl]]


class ProcessVideosRequest(BaseModel):
    csv_path: str  # Путь к CSV файлу с UUID видео


class ProcessVideosResponse(BaseModel):
    message: str


@app.post("/download-video")
async def download_video_handler(request: VideoLinkRequest):
    """Скачать видео по указанной ссылке.

    Аргументы:
        request (VideoLinkRequest): Объект запроса с URL видео.

    Возвращает:
        dict: Сообщение об успешной загрузке.

    Исключения:
        HTTPException: Если загрузка не удалась.
    """
    try:
        video_path = download_video(request.link)
        logging.info(f"Видео успешно загружено: {request.link}")
        return {"message": f"Успешно загружено: {video_path}"}
    except Exception as e:
        logging.error(f"Ошибка загрузки видео: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка загрузки видео")


@app.post("/batch-download")
async def batch_download_handler(request: BatchDownloadRequest, background_tasks: BackgroundTasks):
    """Батчевое скачивание видео по списку ссылок.

    Аргументы:
        request (BatchDownloadRequest): Объект запроса со списком URL видео.
        background_tasks (BackgroundTasks): Фоновые задачи для скачивания.

    Возвращает:
        dict: Сообщение об успешном старте скачивания.

    Исключения:
        HTTPException: Если какая-либо загрузка не удалась.
    """
    try:
        links = [str(link) for link in request.links]
        batch_download(links, background_tasks)
        logging.info(f"Батчевое скачивание запущено для {len(request.links)} видео.")
        return {"message": f"Батчевое скачивание начато для {len(request.links)} видео."}
    except Exception as e:
        logging.error(f"Ошибка батчевого скачивания: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка батчевого скачивания")


@app.post("/process-videos", response_model=ProcessVideosResponse)
async def process_videos_handler(request: ProcessVideosRequest):
    """Обработка видео для извлечения признаков (длительность, размер, MD5).

    Аргументы:
        request (ProcessVideosRequest): Объект запроса с путем к CSV файлу.

    Возвращает:
        dict: Сообщение об успешной обработке.

    Исключения:
        HTTPException: Если обработка не удалась.
    """
    try:
        # Загрузка данных из CSV
        data = pd.read_csv(request.csv_path)
        if "uuid" not in data.columns:
            raise Exception("CSV должен содержать колонку 'uuid'")

        # Обработка видео
        processed_data = process_videos_in_parallel(data)

        # Сохранение обновленного DataFrame
        updated_csv_path = "updated_" + os.path.basename(request.csv_path)
        processed_data.to_csv(updated_csv_path, index=False)

        logging.info(f"Видео успешно обработаны и сохранены в {updated_csv_path}")
        return {"message": f"Видео успешно обработаны и сохранены в {updated_csv_path}"}
    except Exception as e:
        logging.error(f"Ошибка обработки видео: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка обработки видео")


@app.post("/cluster-videos", response_model=ClusterResponse)
async def cluster_videos_handler(request: BatchDownloadRequest):
    """Кластеризация видео по ссылкам.

    Аргументы:
        request (BatchDownloadRequest): Объект запроса со списком URL видео.

    Возвращает:
        ClusterResponse: Информация о кластерах.

    Исключения:
        HTTPException: Если кластеризация не удалась.
    """
    try:
        links = [str(link) for link in request.links]

        # Создание DataFrame с UUID и ссылками
        data = pd.DataFrame(
            {
                "uuid": [str(hash(link)) for link in links],  # Генерация UUID на основе ссылок
                "link": links,
            }
        )

        # Сохранение CSV для последующей обработки
        csv_path = "videos_to_process.csv"
        data.to_csv(csv_path, index=False)

        # Обработка видео
        processed_data = process_videos_in_parallel(data)

        # Кластеризация
        clusters = cluster_videos(processed_data)

        # Сохранение результатов кластеризации
        cluster_csv_path = "clustered_videos.csv"
        processed_data.to_csv(cluster_csv_path, index=False)

        logging.info(f"Видео успешно кластеризованы и сохранены в {cluster_csv_path}")
        return clusters
    except Exception as e:
        logging.error(f"Ошибка кластеризации видео: {e}")
        raise HTTPException(status_code=500, detail="Ошибка кластеризации видео")


@app.post("/submit")
async def generate_submission(file: UploadFile = File(...)) -> dict:
    """Генерация submission.csv на основе тестового набора данных.

    Аргументы:
        file (UploadFile): Загруженный CSV файл с тестовыми данными.

    Возвращает:
        dict: Сообщение об успешной генерации файла submission.csv.
    """
    try:
        # Загрузка тестовых данных из загруженного CSV файла
        test_data = pd.read_csv(file.file)

        # Проверка наличия необходимых колонок
        required_columns = {"created", "uuid", "link"}
        if not required_columns.issubset(test_data.columns):
            raise HTTPException(status_code=400, detail="Неверный формат CSV файла. Ожидаются колонки: 'created', 'uuid', 'link'")

        # Логика для определения дубликатов
        processed_test_data = process_videos_in_parallel(test_data)
        clusters = cluster_videos(processed_test_data)

        # Создаем пустой DataFrame для submission
        submission = pd.DataFrame(columns=["created", "uuid", "link", "is_duplicate", "duplicate_for"])

        for _index, row in test_data.iterrows():
            is_duplicate = False
            duplicate_for = None

            # Проверяем, находится ли видео в одном кластере с другими
            for cluster_videos in clusters["clusters"].values():
                if row["uuid"] in cluster_videos:
                    is_duplicate = True
                    duplicate_for = cluster_videos[0]

            # Добавляем строку в submission
            submission = submission.append(
                {
                    "created": row["created"],
                    "uuid": row["uuid"],
                    "link": row["link"],
                    "is_duplicate": is_duplicate,
                    "duplicate_for": duplicate_for,
                },
                ignore_index=True,
            )

        # Сохранение submission в файл
        submission_csv_path = "submission.csv"
        submission.to_csv(submission_csv_path, index=False)

        logging.info(f"Файл submission успешно сгенерирован: {submission_csv_path}")
        return {"message": f"Файл submission успешно сгенерирован: {submission_csv_path}"}
    except Exception as e:
        logging.error(f"Ошибка при генерации submission: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка при генерации submission")
