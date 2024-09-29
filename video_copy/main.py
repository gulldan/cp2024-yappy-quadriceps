import asyncio
import json
import os
import shutil
import urllib.request
from contextlib import asynccontextmanager, suppress

from confluent_kafka import Consumer, Producer
from encoder_sscd import Encoder
from fastapi import FastAPI, HTTPException
from logger import logger
from matcher import Matcher
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    encoder_path: str = Field("./sscd_disc_large.torchscript.pt", alias="ENCODER_MODEL")
    batch_size: int = Field(128, alias="BATCH_SIZE")
    qdrant_addr: str = Field("0.0.0.0", alias="QDRANT_ADDR")
    qdrant_port: int = Field(6333, alias="QDRANT_PORT")
    kafka_addr: str = Field("0.0.0.0", alias="KAFKA_ADDR")
    kafka_port: int = Field("9092", alias="KAFKA_PORT")
    kafka_consume_topic: str = Field("video-input", alias="KAFKA_CONSUME_TOPIC")
    kafka_produce_topic: str = Field("video-copyright", alias="KAFKA_PRODUCE_TOPIC")
    create_collection: bool = Field(True, alias="CREATE_COLLECTION")


settings = Settings()

kafka_conf = {
    "bootstrap.servers": f"{settings.kafka_addr}:{settings.kafka_port}",
    "group.id": "fastapi-group",
    "auto.offset.reset": "earliest",
}
producer = Producer(kafka_conf)

consumer = Consumer(kafka_conf)
consumer.subscribe([settings.kafka_consume_topic])

# encoder = Encoder("./vit_ddpmm_8gpu_512_torch2_ap31_pattern_condition_first_dgg.pth.tar", batch_size=256)
# encoder = FBEncoder("./sscd_disc_mixup.torchscript.pt")
encoder = Encoder(settings.encoder_path, batch_size=settings.batch_size)

matcher = Matcher(
    encoder,
    "videos",
    1024,
    qdrant_addr=settings.qdrant_addr,
    qdrant_port=settings.qdrant_port,
    create_collection=settings.create_collection,
)


class UploadRequest(BaseModel):
    url: str
    uuid: str


class UploadResponse(BaseModel):
    uuid: str
    message: str


class SearchRequest(BaseModel):
    task_id: int
    link: str


class CopyrightResult(BaseModel):
    name: str
    probability: float


class SearchResponse(BaseModel):
    task_id: int
    copyright: list[CopyrightResult | None]


async def consume_messages_background():
    """Фоновая задача для потребления сообщений из Kafka.

    Args:
        None

    Returns:
        None
    """
    while True:
        msg = consumer.poll(timeout=0.1)
        if msg is None:
            await asyncio.sleep(0.1)
            continue
        if msg.error():
            logger.error(f"Consumer error: {msg.error()}")
            continue
        try:
            req = SearchRequest(**json.loads(msg.value().decode("utf-8")))
            logger.info(f"Consumed message: {req}")
            urllib.request.urlretrieve(req.link, "search.mp4")

            frames_dir = "./tmp_frames_upload"
            if os.path.exists(frames_dir):
                shutil.rmtree(frames_dir)
            os.makedirs(frames_dir)

            results = matcher.search("search.mp4", frames_dir)
            logger.info(f"RESULTs: {results}")
            response = {"task_id": req.task_id, "copyright": [{"name": k, "probability": v} for k, v in results.items()]}
            response = SearchResponse(**response)

            producer.produce(settings.kafka_produce_topic, value=response.model_dump_json().encode("utf-8"))
            producer.flush()
            os.remove("search.mp4")

        except Exception as e:
            logger.error(f"ERROR: {e}")

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
    "/upload_video",
    description="Send video file to add its into vector database",
    response_description="Update database",
    response_model=UploadResponse,
)
async def upload(req: UploadRequest):
    """Загружает видеофайл и добавляет его в векторную базу данных.

    Args:
        req (UploadRequest): Запрос на загрузку с URL и UUID.

    Returns:
        UploadResponse: Ответ с UUID и сообщением об успешной загрузке.
    """
    try:
        logger.info(f"Downloading: {req.uuid}")
        urllib.request.urlretrieve(req.url, "load.mp4")

        frames_dir = "./tmp_frames_upload"
        if os.path.exists(frames_dir):
            shutil.rmtree(frames_dir)
        os.makedirs(frames_dir)

        matcher.load_reference("load.mp4", req.uuid, frames_dir)

        os.remove("load.mp4")

        logger.info(f"File uploaded: {req.uuid}")
        return UploadResponse(uuid=req.uuid, message="File uploaded successfully")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
