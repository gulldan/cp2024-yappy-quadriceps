import logging

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

logging.basicConfig(level=logging.INFO)


class QdrantClientApi:
    def __init__(
        self,
        qdrant_host: str,
        qdrant_port: int,
        collection_name: str = "audio_embeddings",
        embbedings_dim: int = 512,
        create_collection: bool = False,
    ) -> None:
        """Инициализирует экземпляр QdrantClientApi.

        Args:
            qdrant_host (str): Хост Qdrant.
            qdrant_port (int): Порт Qdrant.
            collection_name (str, optional): Имя коллекции. По умолчанию "audio_embeddings".
            embbedings_dim (int, optional): Размерность векторов. По умолчанию 512.
            create_collection (bool, optional): Флаг создания коллекции. По умолчанию False.
        """
        self.qdrant_host = qdrant_host
        self.qdrant_port = qdrant_port
        self.collection_name = collection_name
        self.embbedings_dim = embbedings_dim
        self.create_collection = create_collection

        self.qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)

        if self.create_collection:
            if self.qdrant_client.collection_exists(collection_name=self.collection_name):
                logging.info(f"Collection '{self.collection_name}' already exists.")
            else:
                self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=embbedings_dim, distance=Distance.COSINE),
                )
                logging.info(f"Collection '{self.collection_name}' created successfully.")

            if self.qdrant_client.collection_exists(collection_name="val_embbedings"):
                logging.info("Collection val_embbedings already exists.")
            else:
                self.qdrant_client.create_collection(
                    collection_name="val_embbedings",
                    vectors_config=VectorParams(size=embbedings_dim, distance=Distance.COSINE),
                )
                logging.info("Collection val_embbedings created successfully.")

        self.id_counter = 0
        self.test_id_counter = 0

    def upload_vectors(self, embeddings_dict: dict[str, list[float]]) -> None:
        """Загружает векторы в коллекцию Qdrant.

        Args:
            embeddings_dict (dict[str, list[float]]): Словарь с аудио и их векторами.
        """
        points = []
        for audio in embeddings_dict:
            embedding = embeddings_dict[audio]
            point = PointStruct(
                id=self.id_counter,
                vector=embedding,
                payload={
                    "audio": audio,
                },
            )
            points.append(point)
            self.id_counter += 1

        for point in points:
            self.qdrant_client.upsert(collection_name=self.collection_name, points=[point])

    def find_nearest_vectors(
        self, audios_paths: list[str], all_embbedings: dict[str, list[float]], score_treshold: float = 0.962
    ) -> list[str]:
        """Находит ближайшие векторы для заданных аудио.

        Args:
            audios_paths (list[str]): Список путей к аудио.
            all_embbedings (dict[str, list[float]]): Все векторы эмбеддингов.
            score_treshold (float, optional): Пороговое значение для фильтрации результатов. По умолчанию 0.962.

        Returns:
            list[str]: Список найденных аудио.
        """
        audio_hits = {}
        for audio in audios_paths:
            vector = all_embbedings[audio]

            hits = self.qdrant_client.search(collection_name=self.collection_name, query_vector=vector, limit=1000)

            hits_filtered = []
            for hit in hits:
                if hit.score >= score_treshold:
                    hits_filtered.append(hit.payload["audio"])

            audio_hits[audio] = hits_filtered

        logging.info(audio_hits)

        return audio_hits
