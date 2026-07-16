"""
CLIP Embedding 服务 —— 图像/文本向量化。
使用 CLIP-ViT-B/32（huggingface transformers），CPU 推理 ~200ms/张。
默认通过 HF_ENDPOINT=https://hf-mirror.com 国内镜像下载。
"""

import logging
import os

# 关键：在导入 transformers 之前设置 HF_ENDPOINT
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

logger = logging.getLogger(__name__)

# 全局模型实例
_model: CLIPModel | None = None
_processor: CLIPProcessor | None = None
_device: torch.device | None = None


def load_clip_model():
    """别名，兼容不同调用方。"""
    init_embedding_model()


def init_embedding_model():
    """初始化 CLIP 模型（应用启动时调用一次）。"""
    global _model, _processor, _device

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_name = os.environ.get("CLIP_MODEL_NAME", "openai/clip-vit-base-patch32")

    endpoint = os.environ.get("HF_ENDPOINT", "huggingface.co")
    logger.info(f"Loading CLIP model '{model_name}' on {_device} (endpoint={endpoint})...")
    _model = CLIPModel.from_pretrained(model_name, use_safetensors=False).to(_device)
    _processor = CLIPProcessor.from_pretrained(model_name, use_safetensors=False)
    _model.eval()
    logger.info("CLIP model loaded successfully")


def get_embedding_model():
    """懒加载：首次调用自动初始化。"""
    if _model is None or _processor is None:
        init_embedding_model()
    return _model, _processor, _device


def _extract_tensor(output):
    """兼容 transformers 4.x 和 5.x 的输出格式。"""
    if hasattr(output, "pooler_output"):
        return output.pooler_output
    return output


def get_clip_embedding(image: Image.Image) -> list[float]:
    """对 PIL Image 对象向量化，返回 512 维归一化向量。"""
    model, processor, device = get_embedding_model()

    img = image.convert("RGB")
    inputs = processor(images=img, return_tensors="pt").to(device)

    with torch.no_grad():
        image_features = _extract_tensor(model.get_image_features(**inputs))

    image_features = image_features / image_features.norm(dim=-1, keepdim=True)
    return image_features.cpu().numpy()[0].tolist()


def encode_image(image_path: str | Path) -> list[float]:
    """编码图片文件（支持 URL 和本地路径）。"""
    from app.services.image_fetcher import open_image_source

    image = open_image_source(image_path)
    return get_clip_embedding(image)


def encode_text(text: str) -> list[float]:
    """编码文本，返回 512 维归一化向量。"""
    model, processor, device = get_embedding_model()

    inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True).to(device)

    with torch.no_grad():
        text_features = _extract_tensor(model.get_text_features(**inputs))

    text_features = text_features / text_features.norm(dim=-1, keepdim=True)
    return text_features.cpu().numpy()[0].tolist()


def compute_similarity(vec1: list[float], vec2: list[float]) -> float:
    """余弦相似度（已归一化时等同点积）。"""
    a = np.array(vec1)
    b = np.array(vec2)
    return float(np.dot(a, b))
