"""图像像素分析公共工具 —— 供 reward_scorer / vision_reward / predictor 共享。

所有评分函数返回 0-100 的 float。
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from app.services.image_fetcher import open_image_source

logger = logging.getLogger(__name__)


# --- 图片加载

def is_url(source: str | Path) -> bool:
    """判断 source 是否为 HTTP(S) URL。"""
    return str(source).startswith(("http://", "https://"))


def load_image(source: str | Path) -> Image.Image:
    """统一图片加载入口 —— 支持 HTTP(S) URL 和本地路径。"""
    return open_image_source(source)


def load_image_pixels(source: str | Path) -> np.ndarray | None:
    """加载图片并返回 RGB float64 像素数组，失败时返回 None。"""
    try:
        img = load_image(source).convert("RGB")
        return np.array(img, dtype=np.float64)
    except Exception as e:
        logger.warning(f"图片像素加载失败 {source}: {e}")
        return None


# --- 内部工具

def _to_gray(pixels: np.ndarray) -> np.ndarray:
    """将 RGB 像素数组转为灰度（通道均值）。"""
    if pixels.ndim == 3:
        return np.mean(pixels, axis=2)
    return pixels


# --- 单维度像素统计算法（0-100）

def sharpness_score(pixels: np.ndarray) -> float:
    """清晰度（灰度方差越大越清晰）。"""
    gray = _to_gray(pixels)
    var = np.var(gray)
    return min(100, max(0, var / 50))


def lighting_uniformity_score(pixels: np.ndarray) -> float:
    """光影均匀度（亮度标准差越小越均匀）。"""
    gray = _to_gray(pixels)
    std = np.std(gray)
    return min(100, max(0, 100 - std / 2))


def color_richness_score(pixels: np.ndarray) -> float:
    """色彩丰富度（RGB 三通道标准差均值）。"""
    r_std = np.std(pixels[:, :, 0])
    g_std = np.std(pixels[:, :, 1])
    b_std = np.std(pixels[:, :, 2])
    return min(100, max(0, (r_std + g_std + b_std) / 3 * 0.8))


def composition_balance_score(pixels: np.ndarray) -> float:
    """构图平衡（中心区域亮度与整体均值差异越小越平衡）。"""
    gray = _to_gray(pixels)
    h, w = gray.shape
    hc, wc = h // 2, w // 2
    hq, wq = h // 4, w // 4
    center_brightness = np.mean(gray[hc - hq:hc + hq, wc - wq:wc + wq])
    edge_brightness = np.mean(gray) - center_brightness
    return min(100, max(0, 100 - abs(edge_brightness) * 3))


def pixel_range_score(pixels: np.ndarray, floor: float = 0) -> float:
    """像素值动态范围得分。floor 用于 vision_reward 主体维度。"""
    pixel_range = np.max(pixels) - np.min(pixels)
    return min(100, max(floor, pixel_range / 2.55))


def histogram_entropy_score(pixels: np.ndarray, bins: int = 10) -> float:
    """直方图熵（光影层次，熵越高层次越丰富）。"""
    gray = _to_gray(pixels)
    hist = np.histogram(gray, bins=bins, range=(0, 255))[0]
    hist_norm = hist / (hist.sum() + 1e-10)
    entropy = -np.sum(hist_norm * np.log2(hist_norm + 1e-10))
    return min(100, entropy * 33)


# --- L2 质量评估算法（参考学术标准实现）

def laplacian_variance(pixels: np.ndarray) -> float:
    """Laplacian 方差 —— 信息密度指标

    3×3 Laplacian 核卷积的方差，越高图片信息密度越高。
    """
    gray = _to_gray(pixels).astype(np.float64)
    h, w = gray.shape
    if h < 3 or w < 3:
        return 50.0

    # 纯 numpy 实现，不依赖 cv2
    result = np.zeros_like(gray)
    result[1:-1, 1:-1] = (
        gray[1:-1, 0:-2]     # left
        + gray[1:-1, 2:]     # right
        + gray[0:-2, 1:-1]   # top
        + gray[2:, 1:-1]     # bottom
        - 4 * gray[1:-1, 1:-1]  # center
    )
    var = np.var(result)
    return min(100, max(0, var / 5))


def hsv_entropy(pixels: np.ndarray) -> float:
    """HSV 色相分布熵 —— 色彩和谐度指标

    RGB→HSV 色相通道 18-bin 直方图的香农熵，越高色彩越均匀。
    纯 numpy 实现，不依赖 OpenCV。
    """
    h, w, _ = pixels.shape
    r = pixels[:, :, 0] / 255.0
    g = pixels[:, :, 1] / 255.0
    b = pixels[:, :, 2] / 255.0

    # RGB → HSV 的 Hue 通道
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    delta = max_c - min_c

    mask = delta > 0.05
    hue = np.zeros_like(delta)

    r_eq = mask & (max_c == r)
    g_eq = mask & (max_c == g) & ~r_eq
    b_eq = mask & (max_c == b) & ~r_eq

    hue[r_eq] = (60 * ((g[r_eq] - b[r_eq]) / (delta[r_eq] + 1e-10)) + 360) % 360
    hue[g_eq] = (60 * ((b[g_eq] - r[g_eq]) / (delta[g_eq] + 1e-10)) + 120) % 360
    hue[b_eq] = (60 * ((r[b_eq] - g[b_eq]) / (delta[b_eq] + 1e-10)) + 240) % 360

    valid_hue = hue[mask]
    if len(valid_hue) < 100:
        return 30.0

    hist = np.histogram(valid_hue, bins=18, range=(0, 360))[0]
    hist_norm = hist / (hist.sum() + 1e-10)
    entropy = -np.sum(hist_norm * np.log2(hist_norm + 1e-10))

    max_entropy = np.log2(18)
    return min(100, max(0, (entropy / max_entropy) * 100))


def fft_high_freq_energy(pixels: np.ndarray) -> float:
    """FFT 高频能量占比 —— 清晰度指标

    2D FFT 后计算高频区域能量占比，越高图片越清晰。
    """
    gray = _to_gray(pixels)
    h, w = gray.shape

    fft = np.fft.fft2(gray)
    fft_shifted = np.fft.fftshift(fft)
    fft_mag = np.abs(fft_shifted)

    total_energy = np.sum(fft_mag ** 2)
    if total_energy == 0:
        return 0.0

    cy, cx = h // 2, w // 2
    y, x = np.ogrid[:h, :w]
    dist_sq = (y - cy) ** 2 + (x - cx) ** 2

    max_radius_sq = float(cy ** 2 + cx ** 2)
    threshold_sq = (0.5 ** 2) * max_radius_sq
    high_freq_mask = dist_sq > threshold_sq

    high_energy = np.sum(fft_mag[high_freq_mask] ** 2)
    ratio = high_energy / total_energy

    return min(100, max(0, ratio * 800))


# --- 预测特征提取函数

def whitespace_ratio(pixels: np.ndarray) -> float:
    """留白比例 —— 亮度 > 240 的像素占比（0-1）。"""
    gray = _to_gray(pixels)
    white_pixels = np.sum(gray > 240)
    total_pixels = gray.size
    return round(float(white_pixels / total_pixels), 4) if total_pixels > 0 else 0.0


def text_density(pixels: np.ndarray) -> float:
    """文字占比 —— 高对比度边缘密度近似（0-1）。"""
    gray = _to_gray(pixels)
    h, w = gray.shape
    if h < 2 or w < 2:
        return 0.0

    grad_h = np.abs(np.diff(gray, axis=1))[:, :-1] if w > 2 else np.zeros((h, 1))
    grad_v = np.abs(np.diff(gray, axis=0))[:-1, :] if h > 2 else np.zeros((1, w))

    gh, gw = min(grad_h.shape[0], grad_v.shape[0]), min(grad_h.shape[1], grad_v.shape[1])
    grad_h = grad_h[:gh, :gw]
    grad_v = grad_v[:gh, :gw]

    combined = (grad_h + grad_v) / 2
    text_pixels = np.sum(combined > 30)
    total_pixels = combined.size
    return round(float(text_pixels / total_pixels), 4) if total_pixels > 0 else 0.0


def saturation_mean(image_source: str | Path | np.ndarray) -> float:
    """主色调饱和度均值 —— HSV S 通道均值（0-1）。"""
    if isinstance(image_source, np.ndarray):
        pixels = image_source
    else:
        pixels = load_image_pixels(image_source)
        if pixels is None:
            return 0.5

    r = pixels[:, :, 0] / 255.0
    g = pixels[:, :, 1] / 255.0
    b = pixels[:, :, 2] / 255.0

    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    delta = max_c - min_c

    saturation = np.divide(delta, max_c + 1e-10, out=np.zeros_like(delta), where=max_c > 0)
    return round(float(np.mean(saturation)), 4)


def image_entropy(pixels: np.ndarray) -> float:
    """全局像素熵 —— 256-bin 灰度直方图香农熵（0-1）。"""
    gray = _to_gray(pixels)
    hist = np.histogram(gray, bins=256, range=(0, 255))[0]
    hist_norm = hist / (hist.sum() + 1e-10)
    entropy = -np.sum(hist_norm * np.log2(hist_norm + 1e-10))
    max_entropy = np.log2(256)
    return round(float(entropy / max_entropy), 4)


def aspect_ratio_deviation(image_source: str | Path) -> float:
    """宽高比偏差 —— 与 1:1 的偏差（0-1）。"""
    try:
        img = load_image(image_source)
        w, h = img.size
        if h == 0:
            return 1.0
        ratio = w / h
        deviation = abs(ratio - 1.0)
        return round(float(min(1.0, deviation)), 4)
    except Exception:
        return 0.0
