import logging

import pandas as pd
from sklearn.cluster import KMeans


def cluster_videos(data: pd.DataFrame, n_clusters: int = 5) -> dict:
    """Кластеризация видео на основе признаков длительности и размера.

    Аргументы:
        data (pd.DataFrame): DataFrame с информацией о видео.
        n_clusters (int): Количество кластеров для K-Means.

    Возвращает:
        Dict: Информация о кластере с ID и списком видео.

    Исключения:
        Exception: Если кластеризация не удалась.
    """
    try:
        logging.info("Начата кластеризация видео")

        # Проверка наличия необходимых колонок
        if not {"duration", "size"}.issubset(data.columns):
            raise Exception("DataFrame должен содержать колонки 'duration' и 'size'")

        # Заполнение пропущенных значений средними
        data_filled = data[["duration", "size"]].fillna(data[["duration", "size"]].mean())

        # Инициализация и обучение модели K-Means
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        data["cluster_id"] = kmeans.fit_predict(data_filled)

        # Формирование результата
        clusters = {}
        for cluster_id in range(n_clusters):
            cluster_videos = data[data["cluster_id"] == cluster_id]["link"].tolist()
            clusters[cluster_id] = cluster_videos

        logging.info("Кластеризация завершена успешно")
        return {"clusters": clusters}
    except Exception as e:
        logging.error(f"Ошибка при кластеризации видео: {e}")
        raise Exception(f"Ошибка при кластеризации видео: {e}")
