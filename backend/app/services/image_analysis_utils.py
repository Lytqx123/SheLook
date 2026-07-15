"""图像像素分析公共工具 —— 供 reward_scorer / vision_reward / predictor 共享

将像素级统计算法抽取为单一实现，避免维护偏差。
所有评分函数返回 0-100 的 float。

v2 升级内容：
- 新增 L2 质量评估算法：Laplacian方差（信息密度）、HSV色相分布熵（色彩和谐度）、FFT高频能量占比（清晰度）
- 新增预测特征提取函数：留白比例、文字占比、饱和度均值、信息熵、宽高比偏差
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from app.services.image_fetcher import open_image_source

logger = logging.getLogger(__name__)


# ---- 图片加载 ----

def is_url(source: str | Path) -> bool:
    """判断 source 是否为 HTTP(S) URL。"""
    return str(source).startswith(("http://", "https://"))


def load_image(source: str | Path) -> Image.Image:
    """统一图片加载入口 —— 支持 HTTP(S) URL 和本地路径。

    URL 统一经过 allowlist、SSRF、大小和 Content-Type 校验后再解码。

    Raises:
        FileNotFoundError: 本地文件不存在
        ValueError: URL 下载失败或图片解码失败
    """
    return open_image_source(source)


def load_image_pixels(source: str | Path) -> np.ndarray | None:
    """加载图片并返回 RGB float64 像素数组。

    支持 HTTP(S) URL 和本地路径：URL 会先下载到内存再加载。
    失败时返回 None（不抛异常，便于调用方降级）。
    """
    try:
        img = load_image(source).convert("RGB")
        return np.array(img, dtype=np.float64)
    except Exception as e:
        logger.warning(f"图片像素加载失败 {source}: {e}")
        return None


# ---- 内部工具 ----

def _to_gray(pixels: np.ndarray) -> np.ndarray:
    """将 RGB 像素数组转为灰度（通道均值）。"""
    if pixels.ndim == 3:
        return np.mean(pixels, axis=2)
    return pixels


# ============================================================
# 单维度像素统计算法（0-100）
# ============================================================

def sharpness_score(pixels: np.ndarray) -> float:
    """清晰度（灰度方差近似拉普拉斯方差，方差越大越清晰）。"""
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
    """像素值动态范围得分。

    Args:
        pixels: RGB float64 数组
        floor: 最低保底分（vision_reward 主体维度使用 30，质量评分使用 0）
    """
    pixel_range = np.max(pixels) - np.min(pixels)
    return min(100, max(floor, pixel_range / 2.55))


def histogram_entropy_score(pixels: np.ndarray, bins: int = 10) -> float:
    """直方图熵（光影层次 / 美学质量，熵越高层次越丰富）。"""
    gray = _to_gray(pixels)
    hist = np.histogram(gray, bins=bins, range=(0, 255))[0]
    hist_norm = hist / (hist.sum() + 1e-10)
    entropy = -np.sum(hist_norm * np.log2(hist_norm + 1e-10))
    return min(100, entropy * 33)


# ============================================================
# v2 升级：L2 质量评估学术级算法
# ============================================================

def laplacian_variance(pixels: np.ndarray) -> float:
    """Laplacian 方差 —— 信息密度指标（学术标准实现）

    对灰度图应用 3×3 Laplacian 核卷积，计算方差。
    方差越高 → 图片信息密度越高、纹理越丰富。
    用于替代旧的灰度方差近似。

    Laplacian 核:
        [[0,  1, 0],
         [1, -4, 1],
         [0,  1, 0]]
    """
    gray = _to_gray(pixels).astype(np.float64)
    h, w = gray.shape
    if h < 3 or w < 3:
        return 50.0

    # 手动实现 Laplacian 卷积（避免 cv2 依赖）
    result = np.zeros_like(gray)
    result[1:-1, 1:-1] = (
        gray[1:-1, 0:-2]     # left
        + gray[1:-1, 2:]     # right
        + gray[0:-2, 1:-1]   # top
        + gray[2:, 1:-1]     # bottom
        - 4 * gray[1:-1, 1:-1]  # center
    )
    var = np.var(result)
    # 归一化到 0-100，var 典型范围 0-500
    return min(100, max(0, var / 5))


def hsv_entropy(pixels: np.ndarray) -> float:
    """HSV 色相分布熵 —— 色彩和谐度指标（学术标准实现）

    将 RGB 转 HSV，对 H (色相) 通道构建 18-bin 直方图，计算香农熵。
    熵越高 → 色彩分布越均匀、越和谐。
    用于替代旧的 RGB 三通道标准差均值。

    注意：此函数依赖 numpy 和纯 Python 实现的 RGB→HSV 转换，
          不依赖 OpenCV。
    """
    h, w, _ = pixels.shape
    r = pixels[:, :, 0] / 255.0
    g = pixels[:, :, 1] / 255.0
    b = pixels[:, :, 2] / 255.0

    # RGB → HSV 的 Hue 通道（纯 numpy 实现）
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    delta = max_c - min_c

    # 仅对饱和度 > 0.05 的像素计算色相（灰色像素色相无意义）
    mask = delta > 0.05
    hue = np.zeros_like(delta)

    # 分段计算 Hue
    r_eq = mask & (max_c == r)
    g_eq = mask & (max_c == g) & ~r_eq
    b_eq = mask & (max_c == b) & ~r_eq

    hue[r_eq] = (60 * ((g[r_eq] - b[r_eq]) / (delta[r_eq] + 1e-10)) + 360) % 360
    hue[g_eq] = (60 * ((b[g_eq] - r[g_eq]) / (delta[g_eq] + 1e-10)) + 120) % 360
    hue[b_eq] = (60 * ((r[b_eq] - g[b_eq]) / (delta[b_eq] + 1e-10)) + 240) % 360

    valid_hue = hue[mask]
    if len(valid_hue) < 100:
        return 30.0  # 有效色相像素太少，低分

    # 18-bin 直方图（360度/18=20度每bin）
    hist = np.histogram(valid_hue, bins=18, range=(0, 360))[0]
    hist_norm = hist / (hist.sum() + 1e-10)
    entropy = -np.sum(hist_norm * np.log2(hist_norm + 1e-10))

    # 最大熵 = log2(18) ≈ 4.17，映射到 0-100
    max_entropy = np.log2(18)
    return min(100, max(0, (entropy / max_entropy) * 100))


def fft_high_freq_energy(pixels: np.ndarray) -> float:
    """FFT 高频能量占比 —— 清晰度指标（学术标准实现）

    对灰度图做 2D FFT，使用 fftshift 将零频移到中心，
    通过向量化距离掩码计算高频区域（距中心 > 0.5 × max_radius）的能量占比。
    高频能量占比越高 → 图片越清晰、细节越丰富。

    参考：OpenCV FFT sharpness 标准实现
    """
    gray = _to_gray(pixels)
    h, w = gray.shape

    # 2D FFT → shift 零频到中心
    fft = np.fft.fft2(gray)
    fft_shifted = np.fft.fftshift(fft)
    fft_mag = np.abs(fft_shifted)

    # 频域总能量
    total_energy = np.sum(fft_mag ** 2)
    if total_energy == 0:
        return 0.0

    # 向量化：计算每个频率点到中心的距离
    cy, cx = h // 2, w // 2
    y, x = np.ogrid[:h, :w]
    dist_sq = (y - cy) ** 2 + (x - cx) ** 2

    # 高频区域：距离 > 0.5 × max_radius
    max_radius_sq = float(cy ** 2 + cx ** 2)
    threshold_sq = (0.5 ** 2) * max_radius_sq
    high_freq_mask = dist_sq > threshold_sq

    high_energy = np.sum(fft_mag[high_freq_mask] ** 2)
    ratio = high_energy / total_energy

    # 典型高频占比 0.01-0.15，映射到 0-100
    return min(100, max(0, ratio * 800))


# ============================================================
# v2 升级：预测特征提取函数
# ============================================================

def whitespace_ratio(pixels: np.ndarray) -> float:
    """留白比例 —— 亮度 > 240 的像素占比（归一化到 0-1）"""
    gray = _to_gray(pixels)
    white_pixels = np.sum(gray > 240)
    total_pixels = gray.size
    return round(float(white_pixels / total_pixels), 4) if total_pixels > 0 else 0.0


def text_density(pixels: np.ndarray) -> float:
    """文字占比 —— 高对比度边缘密度近似（归一化到 0-1）

    利用水平/垂直梯度的高响应区域近似文字区域。
    文字区域通常具有高对比度边缘特征。
    """
    gray = _to_gray(pixels)
    h, w = gray.shape
    if h < 2 or w < 2:
        return 0.0

    # 水平梯度
    grad_h = np.abs(np.diff(gray, axis=1))[:, :-1] if w > 2 else np.zeros((h, 1))
    # 垂直梯度
    grad_v = np.abs(np.diff(gray, axis=0))[:-1, :] if h > 2 else np.zeros((1, w))

    # 取两者最大尺寸的交集
    gh, gw = min(grad_h.shape[0], grad_v.shape[0]), min(grad_h.shape[1], grad_v.shape[1])
    grad_h = grad_h[:gh, :gw]
    grad_v = grad_v[:gh, :gw]

    combined = (grad_h + grad_v) / 2
    # 梯度 > 30 视为文字边缘
    text_pixels = np.sum(combined > 30)
    total_pixels = combined.size
    return round(float(text_pixels / total_pixels), 4) if total_pixels > 0 else 0.0


def saturation_mean(image_source: str | Path | np.ndarray) -> float:
    """主色调饱和度均值 —— HSV 空间 S 通道均值（归一化到 0-1）

    支持 URL、本地路径和 numpy 数组输入。
    """
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
    """全局像素熵 —— 信息密度指标（归一化到 0-1）

    对灰度图构建 256-bin 直方图，计算香农熵并除以最大可能熵 log2(256)=8。
    """
    gray = _to_gray(pixels)
    hist = np.histogram(gray, bins=256, range=(0, 255))[0]
    hist_norm = hist / (hist.sum() + 1e-10)
    entropy = -np.sum(hist_norm * np.log2(hist_norm + 1e-10))
    max_entropy = np.log2(256)  # = 8.0
    return round(float(entropy / max_entropy), 4)


def aspect_ratio_deviation(image_source: str | Path) -> float:
    """宽高比偏差 —— 当前宽高比与 1:1 的偏差（归一化到 0-1）"""
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
