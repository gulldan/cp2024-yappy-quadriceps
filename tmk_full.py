import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Video Service API",
    version="1.0.0",
)


# Configuration
class Config:
    VIDEO_FOLDER = "train_dataset"
    TMK_EXECUTABLE_PATH = "/jupyter/ThreatExchange/tmk/cpp"
    FFMPEG_PATH = "/usr/bin/ffmpeg"
    EMBEDDING_DIRECTORY = "/jupyter/emb"
    VIDEO_URL_TEMPLATE = "https://s3.ritm.media/yappy-db-duplicates/{uuid}.mp4"
    MAX_WORKERS = 32


# Pydantic models
class VideoLinkRequest(BaseModel):
    link: str


class BatchDownloadRequest(BaseModel):
    links: list[str]


class ProcessVideosRequest(BaseModel):
    csv_path: str


class ClusterResponse(BaseModel):
    clusters: dict[str, list[str]]


class VideoLink(BaseModel):
    uuid: str
    link: str | None = None


# Helper functions
def download_video(video_url: str, output_path: str) -> str | None:
    """Download a video from a URL to a specified output path.

    Args:
        video_url (str): The URL of the video to download.
        output_path (str): The file path where the video will be saved.

    Returns:
        Optional[str]: The path to the downloaded video, or None if the download failed.
    """
    try:
        logger.info(f"Downloading video from {video_url} to {output_path}")
        response = requests.get(video_url, stream=True, timeout=60)
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
            if os.path.exists(output_path):
                logger.info(f"Video downloaded successfully: {output_path}")
                return output_path
            else:
                logger.error(f"Failed to save the video file: {output_path}")
                return None
        else:
            logger.error(f"Failed to download video, status code: {response.status_code} for {video_url}")
            return None
    except Exception as e:
        logger.error(f"Exception occurred while downloading video {video_url}: {e}")
        return None


def generate_tmk_embedding(video_path: str) -> str | None:
    """Generate TMK embedding for a video using TMK tool.

    Args:
        video_path (str): The path to the video file.

    Returns:
        Optional[str]: The path to the generated TMK embedding file, or None if failed.
    """
    try:
        if not os.path.exists(Config.EMBEDDING_DIRECTORY):
            os.makedirs(Config.EMBEDDING_DIRECTORY)

        video_filename = os.path.basename(video_path)
        video_base_name = os.path.splitext(video_filename)[0]
        tmk_output = os.path.join(Config.EMBEDDING_DIRECTORY, f"{video_base_name}.tmk")

        if os.path.exists(tmk_output):
            return tmk_output  # Embedding already exists

        command = [
            os.path.join(Config.TMK_EXECUTABLE_PATH, "tmk-hash-video"),
            "-f",
            Config.FFMPEG_PATH,
            "-i",
            video_path,
            "-o",
            tmk_output,
        ]

        subprocess.run(command, check=True)
        return tmk_output
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to generate embedding for {video_path}: {e}")
        return None


def process_video(uuid: str, video_link: str | None, retries: int = 2) -> str | None:
    """Process a video: download and generate embedding.

    Args:
        uuid (str): The UUID of the video.
        video_link (Optional[str]): The URL of the video.
        retries (int, optional): Number of retries for downloading. Defaults to 2.

    Returns:
        Optional[str]: The path to the embedding, or None if failed.
    """
    video_path = os.path.join(Config.VIDEO_FOLDER, f"{uuid}.mp4")

    for attempt in range(retries + 1):
        if not os.path.exists(video_path) or attempt > 0:
            if attempt > 0:
                logger.info(f"Retry #{attempt} downloading {uuid}")
            if not video_link:
                video_link = Config.VIDEO_URL_TEMPLATE.format(uuid=uuid)
            video_path = download_video(video_link, video_path)
            if video_path is None:
                return None
        tmk_embedding_path = generate_tmk_embedding(video_path)
        if tmk_embedding_path:
            return tmk_embedding_path
        if os.path.exists(video_path):
            os.remove(video_path)
            logger.warning(f"Removed corrupted video: {video_path}")
    return None


def process_videos_in_parallel(data: pd.DataFrame, max_workers: int = Config.MAX_WORKERS) -> None:
    """Process videos in parallel: download and generate embeddings.

    Args:
        data (pd.DataFrame): The DataFrame containing video data.
        max_workers (int, optional): Maximum number of worker threads. Defaults to Config.MAX_WORKERS.
    """
    if "tmk_embedding" not in data.columns:
        data["tmk_embedding"] = None

    if "duplicate_tmk_embedding" not in data.columns:
        data["duplicate_tmk_embedding"] = None

    tasks = []

    for index, row in data.iterrows():
        uuid = row["uuid"]
        video_link = row.get("link", None)
        duplicate_uuid = row.get("duplicate_for", None)
        tasks.append((index, uuid, video_link, duplicate_uuid))

    def process_both_videos(
        index: int, uuid: str, video_link: str | None, duplicate_uuid: str | None, data: pd.DataFrame
    ) -> None:
        tmk_embedding_path = process_video(uuid, video_link)
        if tmk_embedding_path:
            data.at[index, "tmk_embedding"] = tmk_embedding_path

        if pd.notna(duplicate_uuid) and pd.isna(data.at[index, "duplicate_tmk_embedding"]):
            duplicate_row = data[data["uuid"] == duplicate_uuid]
            duplicate_video_link = duplicate_row.iloc[0]["link"] if not duplicate_row.empty else None
            duplicate_tmk_embedding_path = process_video(duplicate_uuid, duplicate_video_link)
            if duplicate_tmk_embedding_path:
                data.at[index, "duplicate_tmk_embedding"] = duplicate_tmk_embedding_path
            else:
                logger.error(f"Failed to process duplicate_uuid {duplicate_uuid}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for task in tasks:
            index, uuid, video_link, duplicate_uuid = task
            futures.append(executor.submit(process_both_videos, index, uuid, video_link, duplicate_uuid, data))
        for future in futures:
            future.result()


def run_tmk_clusterize() -> str:
    """Run the tmk-clusterize-parallel command and get its output.

    Returns:
        str: The output from the clustering command.
    """
    command = f"find {Config.EMBEDDING_DIRECTORY} -name '*.tmk' | {os.path.join(Config.TMK_EXECUTABLE_PATH, 'tmk-clusterize-parallel')} -s --min 2 -i"
    result = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
    cluster_output = result.stdout
    return cluster_output


def parse_tmk_cluster_output(cluster_output: str) -> dict[int, list[str]]:
    """Parse the output from tmk-clusterize-parallel.

    Args:
        cluster_output (str): The output string from the clustering command.

    Returns:
        Dict[int, List[str]]: A dictionary mapping cluster indices to lists of UUIDs.
    """
    clusters = {}
    for line in cluster_output.strip().splitlines():
        match = re.match(r"clidx=(\d+),clusz=(\d+),filename=.*\/([a-f0-9\-]+)\.tmk", line)
        if match:
            clidx = int(match.group(1))
            uuid = match.group(3)
            if clidx not in clusters:
                clusters[clidx] = []
            clusters[clidx].append(uuid)
    return clusters


def compare_two_tmks(tmk1_path: str, tmk2_path: str) -> bool | None:
    """Compare two .tmk files using tmk-compare-two-tmks command.

    Args:
        tmk1_path (str): Path to the first .tmk file.
        tmk2_path (str): Path to the second .tmk file.

    Returns:
        Optional[bool]: True if similar, False if not similar, None if error.
    """
    command = f"{os.path.join(Config.TMK_EXECUTABLE_PATH, 'tmk-compare-two-tmks')} {tmk1_path} {tmk2_path}"
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60, check=False)
        output = result.stdout.lower()
        if "similar" in output:
            return True
        elif "not similar" in output:
            return False
        else:
            return None
    except subprocess.TimeoutExpired:
        logger.error(f"Comparison command timed out for {tmk1_path} and {tmk2_path}.")
        return None
    except Exception as e:
        logger.error(f"Error comparing {tmk1_path} and {tmk2_path}: {e}")
        return None


# API endpoints
@app.post("/download-video")
async def download_video_endpoint(request: VideoLinkRequest):
    """Download a video by URL.

    Args:
        request (VideoLinkRequest): The request containing the video URL.

    Returns:
        dict: A success message or error message.
    """
    video_url = request.link
    video_filename = video_url.split("/")[-1]
    output_path = os.path.join(Config.VIDEO_FOLDER, video_filename)

    result = download_video(video_url, output_path)
    if result:
        return {"message": "Video downloaded successfully.", "path": result}
    else:
        raise HTTPException(status_code=500, detail="Failed to download video.")


@app.post("/batch-download")
async def batch_download_endpoint(request: BatchDownloadRequest):
    """Batch download videos by URLs.

    Args:
        request (BatchDownloadRequest): The request containing a list of video URLs.

    Returns:
        dict: A success message or error message.
    """
    video_urls = request.links
    results = []

    def download_and_collect(video_url: str) -> str | None:
        video_filename = video_url.split("/")[-1]
        output_path = os.path.join(Config.VIDEO_FOLDER, video_filename)
        return download_video(video_url, output_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(download_and_collect, url) for url in video_urls]
        for future in futures:
            result = future.result()
            results.append(result)

    if all(results):
        return {"message": "All videos downloaded successfully."}
    else:
        return {"message": "Some videos failed to download.", "results": results}


@app.post("/process-videos")
async def process_videos_endpoint(request: ProcessVideosRequest):
    """Process videos to extract features.

    Args:
        request (ProcessVideosRequest): The request containing the CSV path.

    Returns:
        dict: A success message or error message.
    """
    csv_path = request.csv_path
    try:
        data = pd.read_csv(csv_path)
        process_videos_in_parallel(data)
        data.to_csv("updated_" + os.path.basename(csv_path), index=False)
        return {"message": "Videos processed successfully."}
    except Exception as e:
        logger.error(f"Exception occurred while processing videos: {e}")
        raise HTTPException(status_code=500, detail="Failed to process videos.")


@app.post("/cluster-videos", response_model=ClusterResponse)
async def cluster_videos_endpoint(request: BatchDownloadRequest):
    """Cluster videos by the provided URLs.

    Args:
        request (BatchDownloadRequest): The request containing a list of video URLs.

    Returns:
        ClusterResponse: The clustering information.
    """
    video_urls = request.links
    video_paths = []

    def download_and_collect(video_url: str) -> str | None:
        video_filename = video_url.split("/")[-1]
        output_path = os.path.join(Config.VIDEO_FOLDER, video_filename)
        return download_video(video_url, output_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(download_and_collect, url) for url in video_urls]
        for future in futures:
            result = future.result()
            if result:
                video_paths.append(result)
            else:
                logger.error("Failed to download video.")

    embeddings = []
    for video_path in video_paths:
        embedding_path = generate_tmk_embedding(video_path)
        if embedding_path:
            embeddings.append(embedding_path)
        else:
            logger.error(f"Failed to generate embedding for {video_path}")

    cluster_output = run_tmk_clusterize()
    clusters = parse_tmk_cluster_output(cluster_output)

    # Convert cluster indices to strings for JSON serialization
    clusters_str_keys = {str(k): v for k, v in clusters.items()}

    return ClusterResponse(clusters=clusters_str_keys)


@app.post("/submit")
async def submit_endpoint(file: UploadFile = File(...)):
    """Generate submission.csv based on test data.

    Args:
        file (UploadFile): The CSV file with test data.

    Returns:
        FileResponse: The generated submission.csv file.
    """
    try:
        # Read the uploaded file
        contents = await file.read()
        # Save the uploaded file to a temporary location
        temp_input_path = "temp_input.csv"
        with open(temp_input_path, "wb") as f:
            f.write(contents)

        # Process the file
        data = pd.read_csv(temp_input_path)
        # Placeholder logic for generating submission.csv
        output_path = "submission.csv"
        data.to_csv(output_path, index=False)

        # Return the submission.csv file
        return FileResponse(path=output_path, filename="submission.csv", media_type="text/csv")

    except Exception as e:
        logger.error(f"Exception occurred while generating submission: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate submission.")
