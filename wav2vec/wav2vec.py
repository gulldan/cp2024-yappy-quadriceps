import datetime
import logging
import os
import subprocess
from collections import defaultdict
from glob import glob

import librosa
import torch
from qdrant_client import models
from qdrant_client.models import PointStruct
from qdrant_client_api import QdrantClientApi
from tqdm import tqdm
from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2Model
from video_clipper import VideoClipper


def extract_audio_name(filename: str) -> str:
    """Извлекает имя аудиофайла из полного пути.

    Args:
        filename (str): Полный путь к файлу.

    Returns:
        str: Имя аудиофайла.
    """
    match = "_".join(filename.split("/")[-1].split("_")[: len([filename.split("_")]) - 3])
    return match


def count_audio_matches(data: dict) -> set:
    """Подсчитывает количество совпадений аудиофайлов в данных.

    Args:
        data (dict): Словарь с данными о совпадениях.

    Returns:
        set: Набор с количеством совпадений для каждого аудиофайла.
    """
    keys_cnt = len(list(data.keys()))
    audio_count = defaultdict(int)
    for matches in data.values():
        maches_set = set()
        for match in matches:
            audio_name = extract_audio_name(match)
            if audio_name:
                if audio_name in maches_set:
                    continue

                maches_set.add(audio_name)
                audio_count[audio_name] += 1

    audio_score = {(k, v / keys_cnt) for k, v in dict(audio_count).items()}

    return audio_score


def get_top_k_audio(audio_count: set, k: int) -> list:
    """Возвращает топ K аудиофайлов по количеству совпадений.

    Args:
        audio_count (set): Набор с количеством совпадений для каждого аудиофайла.
        k (int): Количество топовых аудиофайлов для возврата.

    Returns:
        list: Список топ K аудиофайлов.
    """
    sorted_audio = sorted(audio_count, key=lambda x: x[1], reverse=True)
    return sorted_audio[:k]


class Wav2Vec:
    def __init__(
        self,
        qdrant_client: QdrantClientApi,
        videoclip_client: VideoClipper,
        model_name: str = "facebook/wav2vec2-large-xlsr-53",
        model_sample_rate: int = 16000,
        device: str = "cuda",
    ) -> None:
        """Инициализирует объект Wav2Vec.

        Args:
            qdrant_client (QdrantClientApi): Клиент Qdrant.
            videoclip_client (VideoClipper): Клиент для обрезки видео.
            model_name (str): Название модели Wav2Vec.
            model_sample_rate (int): Частота дискретизации модели.
            device (str): Устройство для выполнения вычислений ("cuda" или "cpu").
        """
        self.feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(model_name)
        self.model = Wav2Vec2Model.from_pretrained(model_name)
        self.qdrant_client = qdrant_client
        self.videoclip_client = videoclip_client
        self.model_sample_rate = model_sample_rate

        self.device = device
        if self.device == "cuda":
            self.model = self.model.cuda()

    def get_input_audio(self, audio_path: str) -> torch.tensor:
        """Загружает и подготавливает аудиофайл для модели.

        Args:
            audio_path (str): Путь к аудиофайлу.

        Returns:
            torch.tensor: Подготовленный аудиофайл в виде тензора.
        """
        audio, sr = librosa.load(audio_path)

        if sr != self.model_sample_rate:
            resampled_audio = librosa.resample(audio, orig_sr=sr, target_sr=self.model_sample_rate)
        else:
            resampled_audio = audio

        input_audio = self.feature_extractor(resampled_audio, return_tensors="pt", sampling_rate=self.model_sample_rate)

        if self.device == "cuda":
            return input_audio.input_values.clone().detach().cuda()
        return input_audio.input_values.clone().detach()

    def exctract_embedding(self, audio_path: str, audio_type: str = "index") -> list:
        """Извлекает эмбеддинг из аудиофайла.

        Args:
            audio_path (str): Путь к аудиофайлу.
            audio_type (str): Тип аудио ("index" или "val").

        Returns:
            list: Эмбеддинг аудиофайла.
        """
        if audio_type == "index":
            with torch.no_grad():
                return torch.mean(self.model(self.get_input_audio(audio_path)).extract_features[0], dim=0).cpu().detach().tolist()

        vector_search = self.qdrant_client.qdrant_client.scroll(
            collection_name="val_embbedings",
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="audio",
                        match=models.MatchValue(value=audio_path),
                    ),
                ]
            ),
            with_vectors=True,
        )[0]

        if len(vector_search) != 0:
            return vector_search[0].vector

        with torch.no_grad():
            embbeding = (
                torch.mean(self.model(self.get_input_audio(audio_path)).extract_features[0], dim=0).cpu().detach().tolist()
            )
            point = PointStruct(
                id=self.qdrant_client.test_id_counter,
                vector=embbeding,
                payload={
                    "audio": audio_path,
                },
            )
            self.qdrant_client.test_id_counter += 1

            self.qdrant_client.qdrant_client.upsert(collection_name="val_embbedings", points=[point])

        return embbeding

    def merge_tuples(self, tuples: list) -> list:
        """Объединяет пересекающиеся интервалы в списке кортежей.

        Args:
            tuples (list): Список кортежей с интервалами.

        Returns:
            list: Список объединенных кортежей.
        """
        sorted_tuples = sorted([list(x) for x in tuples], key=lambda x: x[0])

        merged = [sorted_tuples[0]]

        for current_tuple in sorted_tuples[1:]:
            last_tuple = merged[-1]

            if current_tuple[0] - 50 <= last_tuple[1] + 50:
                last_tuple[1] = max(last_tuple[1], current_tuple[1])
            else:
                merged.append(current_tuple)

        return merged

    def process_search_results(self, search_dict: dict[str, list[str]]) -> dict:
        """Обрабатывает результаты поиска и возвращает топовые аудиофайлы.

        Args:
            search_dict (dict[str, list[str]]): Словарь с результатами поиска.

        Returns:
            dict: Словарь с топовыми аудиофайлами.
        """
        search_results_count = 0
        for result in search_dict:
            search_results_count += len(search_dict[result])

        copyright_index_count = []

        for audio in search_dict:
            for copyright_audio in search_dict[audio]:
                sub_clip_split = copyright_audio.split("/")[-1]
                sub_clip_hash = "_".join(sub_clip_split.split("_")[: len([sub_clip_split.split("_")]) - 3])
                copyright_index_count.append(sub_clip_hash)

        if len(copyright_index_count) == 0:
            return {}

        max_inp_index = max(copyright_index_count, key=copyright_index_count.count)
        audio_count = count_audio_matches(search_dict)

        k = 10
        top_k_audio = get_top_k_audio(audio_count, k)

        return top_k_audio

    def wav2vec_update_database(self, audio_path: str) -> None:
        """Обновляет базу данных эмбеддингов аудиофайлов.

        Args:
            audio_path (str): Путь к аудиофайлу.
        """
        embeddings_dict = {}

        self.videoclip_client.clip_audio(audio_path=audio_path, audio_duration=1, step=1, sample_rate=self.model_sample_rate)

        all_audios = glob(str(self.videoclip_client.audioclips_save_path) + "/*.wav")

        for path in tqdm(all_audios):
            embeddings_dict[path] = self.exctract_embedding(path, "index")

        self.qdrant_client.upload_vectors(embeddings_dict)

    def wav2vec_find_copyright_infringement(self, audio_path: str) -> list:
        """Находит нарушения авторских прав в аудиофайле.

        Args:
            audio_path (str): Путь к аудиофайлу.

        Returns:
            list: Список нарушений авторских прав.
        """
        embeddings_dict = {}

        self.videoclip_client.clip_audio(audio_path=audio_path, audio_duration=1, step=1, sample_rate=self.model_sample_rate)

        all_audios = glob(str(self.videoclip_client.audioclips_save_path) + "/*.wav")

        for path in tqdm(all_audios):
            embeddings_dict[path] = self.exctract_embedding(path, "val")

        return self.qdrant_client.find_nearest_vectors(all_audios, embeddings_dict)


if __name__ == "__main__":
    import logging

    import yappi

    logging.basicConfig(filename="wav2vec.log", level=logging.INFO)

    yappi.set_clock_type("cpu")
    yappi.start()
    start_time = datetime.datetime.now()
    audio_clips_save_path = "./audioclips"

    qdrant_client = QdrantClientApi("127.0.0.1", 6333)
    video_clipper = VideoClipper(audio_clips_save_path)
    wav2vec = Wav2Vec(
        qdrant_client,
        video_clipper,
        device="cuda",
    )

    wav2vec.wav2vec_update_database("./audio/The-Pretty-Reckless-Make-Me-Wanna-Die.wav")

    # subprocess.run("rm -rf ./audioclips", shell=True, check=False)

    logging.info(
        wav2vec.process_search_results(
            wav2vec.wav2vec_find_copyright_infringement(
                "./audio/The-Pretty-Reckless-Make-Me-Wanna-Die.wav",
            )
        )
    )

    # subprocess.run("rm -rf ./audioclips", shell=True, check=False)
    yappi.stop()
    end_time = datetime.datetime.now()
    curr_date = str(datetime.datetime.now().date()).replace("-", ".")

    filename = "yappi_profile." + curr_date + ".pstat"
    filepath = os.path.join(os.getcwd(), filename)
    stats = yappi.get_func_stats()
    stats.save(filepath, type="PSTAT")

    subprocess.run(["gprof2dot", "-f", "pstats", filename, "-o", "yappi_graph.dot"], check=False)
    subprocess.run(["dot", "-Tsvg", "yappi_graph.dot", "-o", "tmp/yappi_graph.html"], check=False)
    os.unlink(filepath)
    os.unlink(os.path.join(os.getcwd(), "yappi_graph.dot"))
    logging.info("File yappi_graph.html is Done !!!!")
