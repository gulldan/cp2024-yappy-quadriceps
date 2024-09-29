import os
import subprocess

from logger import logger
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException
from qdrant_client.models import Distance, VectorParams


class Matcher:
    def __init__(
        self,
        encoder,
        collection_name="ref",
        vector_dim: int = 1024,
        qdrant_addr: str = "qdrant",
        qdrant_port: int = 6333,
        create_collection: bool = True,
    ) -> None:
        """Инициализация класса Matcher.

        Args:
            encoder: Экземпляр энкодера.
            collection_name (str, optional): Имя коллекции. По умолчанию "ref".
            vector_dim (int, optional): Размерность вектора. По умолчанию 1024.
            qdrant_addr (str, optional): Адрес Qdrant. По умолчанию "qdrant".
            qdrant_port (int, optional): Порт Qdrant. По умолчанию 6333.
            create_collection (bool, optional): Флаг создания коллекции. По умолчанию True.
        """
        self.collection_name = collection_name
        self.encoder = encoder
        try:
            self.client = QdrantClient(qdrant_addr, grpc_port=qdrant_port, timeout=60)
            if create_collection:
                if self.client.collection_exists(collection_name=self.collection_name):
                    logger.info(f"Collection '{self.collection_name}' already exists.")
                else:
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
                        #optimizers_config=models.OptimizersConfigDiff(memmap_threshold=10000),
                    )
                    logger.info(f"Collection '{self.collection_name}' created successfully.")
        except ResponseHandlingException as e:
            logger.error(f"Failed to connect to Qdrant server: {e}")
            raise

    @staticmethod
    def extract_frames(input_video: str, output_directory: str) -> list[str]:
        """Извлекает кадры из видео и сохраняет их в указанную директорию.

        Args:
            input_video (str): Путь к входному видео.
            output_directory (str): Директория для сохранения кадров.

        Returns:
            list[str]: Список путей к извлеченным кадрам.
        """
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)

        command = ["ffmpeg", "-i", input_video, "-vf", "fps=1", os.path.join(output_directory, "%d.jpg")]
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

        frame_names = sorted(os.listdir(output_directory), key=lambda x: int(x.split(".")[0]))
        frame_paths = [os.path.join(output_directory, name) for name in frame_names]
        return frame_paths

    def load_reference(self, video_path: str, uuid: str, frames_dir: str) -> None:
        """Загружает референсное видео в коллекцию.

        Args:
            video_path (str): Путь к видео.
            uuid (str): Уникальный идентификатор видео.
            frames_dir (str): Директория для сохранения кадров.
        """
        logger.info(f"Extracting frames to {frames_dir}")
        frame_paths = self.extract_frames(video_path, frames_dir)
        logger.info("Getting embeddings")
        embeddings = self.encoder.embeddings_one_video(frame_paths)

        payload = [{"frame": i + 1, "video_id": uuid} for i in range(len(embeddings))]
        num_points = self.client.get_collection(collection_name=self.collection_name).points_count
        logger.info(f"Uploading {len(embeddings)} embeddings")
        self.client.upload_collection(
            collection_name=self.collection_name,
            vectors=embeddings,
            payload=payload,
            ids=list(range(num_points, num_points + len(embeddings))),
        )

    def search(self, video_path: str, frames_dir: str) -> dict[str, float]:
        """Выполняет поиск по видео.

        Args:
            video_path (str): Путь к видео.
            frames_dir (str): Директория для сохранения кадров.

        Returns:
            dict[str, float]: Результаты поиска с оценками.
        """
        logger.info(f"Extracting frames to {frames_dir}")
        frame_paths = self.extract_frames(video_path, frames_dir)
        logger.info("Getting embeddings")
        embeddings = self.encoder.embeddings_one_video(frame_paths)

        alpha = 1 / len(embeddings)
        video_scores = {}
        for vector in embeddings:
            results = self.client.search(self.collection_name, query_vector=vector, limit=5)
            image_scores = {}
            for result in results:
                resp_video_name = result.payload["video_id"]
                image_scores[resp_video_name] = max(image_scores.get(resp_video_name, 0), result.score if result.score > 0.5 else 0.0)
            for resp_video_name, score in image_scores.items():
                video_scores[resp_video_name] = video_scores.get(resp_video_name, 0) + (score * alpha)
        return video_scores
