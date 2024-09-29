import logging
import os
from urllib.parse import urlparse

import requests


def download_video(link: str, download_folder: str = "downloaded_videos") -> str:
    """Скачивание видео по указанной ссылке.

    Аргументы:
        link (str): URL видео для скачивания.
        download_folder (str): Папка для сохранения скачанных видео.

    Возвращает:
        str: Путь к скачанному видео.

    Исключения:
        Exception: Если скачивание не удалось.
    """
    try:
        # Создание папки для скачивания, если не существует
        os.makedirs(download_folder, exist_ok=True)

        # Получение имени файла из URL
        parsed_url = urlparse(link)
        filename = os.path.basename(parsed_url.path)
        if not filename:
            filename = f"video_{hash(link)}.mp4"

        file_path = os.path.join(download_folder, filename)

        logging.info(f"Начало скачивания видео с: {link}")

        # Скачивание видео
        response = requests.get(link, stream=True)
        response.raise_for_status()

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        logging.info(f"Видео успешно скачано: {file_path}")
        return file_path
    except Exception as e:
        logging.error(f"Ошибка при скачивании видео с {link}: {e}")
        raise Exception(f"Ошибка при скачивании видео с {link}: {e}")
