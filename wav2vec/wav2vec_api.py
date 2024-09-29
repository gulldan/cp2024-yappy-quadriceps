import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager, suppress

import aiofiles
import aiohttp
from confluent_kafka import Consumer, Producer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, conlist
from qdrant_client_api import QdrantClientApi
from video_clipper import VideoClipper

from wav2vec import Wav2Vec

logging.basicConfig(level=logging.INFO)

QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = os.getenv("QDRANT_PORT")
DEVICE = os.getenv("DEVICE")
RECREATE = os.getenv("CREATE_COLLECTION")
KAFKA_ADDR = os.getenv("KAFKA_ADDR")
KAFKA_PORT = os.getenv("KAFKA_PORT")
KAFKA_CONSUME_TOPIC = os.getenv("KAFKA_CONSUME_TOPIC")
KAFKA_PRODUCE_TOPIC = os.getenv("KAFKA_PRODUCE_TOPIC")
RECREATE = True

kafka_conf = {
    "bootstrap.servers": f"{KAFKA_ADDR}:{KAFKA_PORT}",
    "group.id": "fastapi-group",
    "auto.offset.reset": "earliest",
}
producer = Producer(kafka_conf)

consumer = Consumer(kafka_conf)
consumer.subscribe([KAFKA_CONSUME_TOPIC])


class EmbeddingResponse(BaseModel):
    embedding: conlist(float, max_length=512, min_length=512)


class UpdateDatabaseAnswer(BaseModel):
    response: str


class CopyrightAnswer(BaseModel):
    task_id: int
    copyright: list


class RequestModel(BaseModel):
    link: str


class UpdRequestModel(BaseModel):
    link: str
    filename: str


class CopyrightRequestModel(RequestModel):
    task_id: int


app = FastAPI()

qdrant_client = QdrantClientApi(QDRANT_HOST, QDRANT_PORT, create_collection=RECREATE)
audio_clips_save_path = "clipped_audio"
videoclip_client = VideoClipper(audio_clips_save_path)
wav2vec = Wav2Vec(qdrant_client, videoclip_client, device=DEVICE)


async def download_file(url: str, dest: str) -> None:
    """Загружает файл по указанному URL и сохраняет его в указанное место.

    Args:
        url (str): URL файла для загрузки.
        dest (str): Путь для сохранения загруженного файла.

    Raises:
        HTTPException: Если не удалось загрузить файл.
    """
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status == 200:
            async with aiofiles.open(dest, "wb") as f:
                await f.write(await response.read())
        else:
            raise HTTPException(status_code=response.status, detail=f"Failed to download file from {url}")


def generate_short_filename(url: str) -> str:
    """Генерирует короткое имя файла на основе хэша URL.

    Args:
        url (str): URL файла.

    Returns:
        str: Короткое имя файла.
    """
    return hashlib.md5(url.encode()).hexdigest() + ".wav"


@app.post(
    "/find_copyright_infringement",
    description="Send URL of .wav file to find copyright infringement",
    response_description="Find copyright infringement",
    response_model=CopyrightAnswer,
)
async def consume_messages_background():
    """Ищет нарушение авторских прав в аудио файле по указанному URL.

    Args:
        request (CopyrightRequestModel): Модель запроса с URL аудио файла и идентификатором задачи.

    Returns:
        CopyrightAnswer: Ответ с результатами поиска нарушений авторских прав.

    Raises:
        HTTPException: Если произошла ошибка при обработке.
    """
    while True:
        msg = consumer.poll(timeout=0.1)
        if msg is None:
            await asyncio.sleep(0.1)
            continue
        if msg.error():
            logging.error(f"Consumer error: {msg.error()}")
            continue
        try:
            request = CopyrightRequestModel(**json.loads(msg.value().decode("utf-8")))
            audio_save_path = f"audio/{generate_short_filename(request.link)}"
            await download_file(request.link, audio_save_path)
            answer = wav2vec.process_search_results(wav2vec.wav2vec_find_copyright_infringement(audio_save_path))
            await asyncio.create_subprocess_shell(f"rm -rf {audio_save_path}")
            await asyncio.create_subprocess_shell(f"rm -rf {audio_clips_save_path}")
            await asyncio.create_subprocess_shell(f"mkdir {audio_clips_save_path}")

            # Преобразование данных в нужный формат
            transformed_answer = {
                "task_id": request.task_id,
                "copyright": [{"name": item[0], "probability": item[1]} for item in answer],
            }
            response = CopyrightAnswer(**transformed_answer)
            producer.produce(KAFKA_PRODUCE_TOPIC, value=response.model_dump_json().encode("utf-8"))
            producer.flush()
        except Exception as e:
            logging.error(f"ERROR: {e}")
        await asyncio.sleep(0.1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Контекстный менеджер для управления жизненным циклом приложения.

    Args:
        app (FastAPI): Экземпляр приложения FastAPI.

    Returns:
        None
    """
    background_task = asyncio.create_task(consume_messages_background())
    yield
    background_task.cancel()
    with suppress(asyncio.CancelledError):
        await background_task
    consumer.close()
    producer.flush()


app = FastAPI(lifespan=lifespan)


@app.post(
    "/exctract_embedding",
    description="Send URL of .wav file to extract embedding",
    response_description="Audio embeddings",
    response_model=EmbeddingResponse,
)
async def exctract_embedding(request: RequestModel) -> EmbeddingResponse:
    """Извлекает эмбеддинги из аудио файла по указанному URL.

    Args:
        request (RequestModel): Модель запроса с URL аудио файла.

    Returns:
        EmbeddingResponse: Эмбеддинги аудио файла.

    Raises:
        HTTPException: Если произошла ошибка при обработке.
    """
    try:
        audio_save_path = f"audio/{generate_short_filename(request.link)}"
        await download_file(request.link, audio_save_path)
        embedding = wav2vec.exctract_embedding(audio_save_path)
        await asyncio.create_subprocess_shell(f"rm -rf {audio_save_path}")
        await asyncio.create_subprocess_shell(f"rm -rf {audio_clips_save_path}")
        await asyncio.create_subprocess_shell(f"mkdir {audio_clips_save_path}")

        return {"embedding": embedding}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/update_database",
    description="Send URL of .wav file to add its into vector database",
    response_description="Update database",
    response_model=UpdateDatabaseAnswer,
)
async def update_data_base(request: UpdRequestModel) -> UpdateDatabaseAnswer:
    """Обновляет базу данных векторных представлений с помощью аудио файла по указанному URL.

    Args:
        request (UpdRequestModel): Модель запроса с URL аудио файла и именем файла.

    Returns:
        UpdateDatabaseAnswer: Ответ об успешном обновлении базы данных.

    Raises:
        HTTPException: Если произошла ошибка при обработке.
    """
    try:
        audio_save_path = f"audio/{generate_short_filename(request.filename)}"
        await download_file(request.link, audio_save_path)
        wav2vec.wav2vec_update_database(audio_save_path)
        await asyncio.create_subprocess_shell(f"rm -rf {audio_save_path}")
        await asyncio.create_subprocess_shell(f"rm -rf {audio_clips_save_path}")
        await asyncio.create_subprocess_shell(f"mkdir {audio_clips_save_path}")

        return {"response": "video was uploaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
