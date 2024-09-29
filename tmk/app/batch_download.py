from fastapi import BackgroundTasks

from .download import download_video


def batch_download(links: list[str], background_tasks: BackgroundTasks, download_folder: str = "downloaded_videos"):
    """Батчевое скачивание видео по списку ссылок.

    Аргументы:
        links (List[str]): Список URL видео для скачивания.
        background_tasks (BackgroundTasks): Менеджер фоновых задач.
        download_folder (str): Папка для сохранения скачанных видео.
    """
    for link in links:
        background_tasks.add_task(download_video, link, download_folder)
