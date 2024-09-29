import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from moviepy.editor import VideoFileClip
from tqdm import tqdm

# Путь к папке с видеофайлами (может быть настроен)
video_folder = "downloaded_videos"


def get_video_info(index: int, video_uuid: str) -> tuple:
    """Получение информации о видеофайле.

    Аргументы:
        index (int): Индекс видео в наборе данных.
        video_uuid (str): Уникальный идентификатор видеофайла.

    Возвращает:
        tuple: Индекс, длительность видео, размер в байтах и MD5 хэш.
    """
    video_path = os.path.join(video_folder, f"{video_uuid}.mp4")
    try:
        # Проверка, существует ли файл
        if not os.path.exists(video_path):
            logging.error(f"Видео не найдено: {video_path}")
            return index, None, None, None

        # Получение длительности и размера видео
        clip = VideoFileClip(video_path)
        duration = clip.duration
        size = os.path.getsize(video_path)

        # Вычисление MD5 хэша
        md5_hash = hashlib.md5()
        with open(video_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        md5_value = md5_hash.hexdigest()

        return index, duration, size, md5_value
    except Exception as e:
        logging.error(f"Ошибка при обработке видео {video_path}: {e}")
        return index, None, None, None


def process_videos_in_parallel(data: pd.DataFrame, max_workers: int = 32) -> pd.DataFrame:
    """Параллельная обработка видео для получения информации о длительности, размере и MD5.

    Аргументы:
        data (pd.DataFrame): DataFrame, содержащий информацию о видео.
        max_workers (int): Максимальное количество потоков для параллельной обработки.

    Возвращает:
        pd.DataFrame: Обновленный DataFrame с информацией о видео.
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(get_video_info, index, row["uuid"]) for index, row in data.iterrows()]

        for future in tqdm(futures, desc="Обработка видео"):
            result = future.result()
            results.append(result)

    for result in results:
        index, duration, size, md5_value = result
        data.at[index, "duration"] = duration
        data.at[index, "size"] = size
        data.at[index, "md5"] = md5_value

    return data
