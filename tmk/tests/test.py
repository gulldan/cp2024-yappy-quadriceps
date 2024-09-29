from app.download import download_video
import os

def test_download_video():
    link = "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_1mb.mp4"
    download_folder = "test_downloads"
    if os.path.exists(download_folder):
        # Очистка папки перед тестом
        for f in os.listdir(download_folder):
            os.remove(os.path.join(download_folder, f))
    else:
        os.makedirs(download_folder)
    
    result = download_video(link, download_folder)
    assert os.path.exists(result)
    assert result.endswith(".mp4")
    
    # Очистка после теста
    os.remove(result)
    os.rmdir(download_folder)
