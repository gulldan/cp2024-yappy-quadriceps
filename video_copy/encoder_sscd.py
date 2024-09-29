import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms


class ImageList(Dataset):
    def __init__(self, image_list: list[str]) -> None:
        """Инициализация класса ImageList.

        Args:
            image_list (list[str]): Список путей к изображениям.
        """
        Dataset.__init__(self)
        self.image_list = image_list

    def __len__(self) -> int:
        """Возвращает количество изображений в списке.

        Returns:
            int: Количество изображений.
        """
        return len(self.image_list)

    def __getitem__(self, i: int) -> torch.Tensor:
        """Возвращает преобразованное изображение по индексу.

        Args:
            i (int): Индекс изображения в списке.

        Returns:
            torch.Tensor: Преобразованное изображение.
        """
        x = Image.open(self.image_list[i])
        x = x.convert("RGB")
        normalize = transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        )
        small_288 = transforms.Compose(
            [
                transforms.Resize([320, 320]),
                transforms.ToTensor(),
                normalize,
            ]
        )

        return small_288(x)


class Encoder:
    def __init__(self, model_path: str, batch_size: int = 1) -> None:
        """Инициализация класса Encoder.

        Args:
            model_path (str): Путь к модели.
            batch_size (int, optional): Размер батча. По умолчанию 1.
        """
        self.batch_size = batch_size
        self.model = torch.jit.load(model_path).eval().cuda()

    def embeddings_one_video(self, image_path_list: list[str]) -> list[list[float]]:
        """Получает эмбеддинги для одного видео.

        Args:
            image_path_list (list[str]): Список путей к изображениям.

        Returns:
            list[list[float]]: Список эмбеддингов.
        """
        dataset = ImageList(image_path_list)
        dataloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=False)
        embeddings = []
        with torch.no_grad():
            for x1 in dataloader:
                x1 = x1.cuda()
                embedding = self.model(x1).detach().tolist()

                embeddings += embedding

        return embeddings
