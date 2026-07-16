"""跨平台图片导出 —— 按目标平台自动裁切/补白/加标注。"""


from app.core.logging import logger

# --- 平台规格定义

PLATFORM_SPECS = {
    "amazon": {
        "target_size": (1000, 1000),
        "background_color": (255, 255, 255),
        "allow_ai_primary": False,
        "format": "JPEG",
        "quality": 95,
        "label": "Amazon",
    },
    "tmall": {
        "target_size": (800, 800),
        "background_color": (255, 255, 255),
        "allow_ai_primary": True,
        "ai_badge": True,
        "format": "JPEG",
        "quality": 90,
        "label": "天猫",
    },
    "tiktok_shop": {
        "target_size": (1080, 1920),
        "background_color": None,
        "allow_ai_primary": True,
        "ai_badge": True,
        "format": "JPEG",
        "quality": 90,
        "label": "TikTok Shop",
    },
    "tiktok_square": {
        "target_size": (1080, 1080),
        "background_color": None,
        "allow_ai_primary": True,
        "ai_badge": True,
        "format": "JPEG",
        "quality": 90,
        "label": "TikTok Shop (方图)",
    },
    "shopify": {
        "target_size": (2048, 2048),
        "background_color": None,
        "allow_ai_primary": True,
        "ai_badge": False,
        "format": "JPEG",
        "quality": 95,
        "label": "Shopify",
    },
}


def get_platform_spec(platform: str) -> dict | None:
    """获取平台规格配置"""
    return PLATFORM_SPECS.get(platform.lower())


async def export_for_platform(
    image_data: bytes,
    platform: str,
    *,
    is_ai_generated: bool = True,
    add_badge: bool = True,
) -> bytes:
    """将图片导出为目标平台格式

    平台规格来自 PLATFORM_SPECS，不支持时抛 ValueError。
    """
    import io

    from PIL import Image, ImageDraw, ImageFont

    spec = get_platform_spec(platform)
    if not spec:
        raise ValueError(f"不支持的平台: {platform}。可用: {list(PLATFORM_SPECS.keys())}")

    # Amazon 主图合规校验
    if platform == "amazon" and is_ai_generated and not spec["allow_ai_primary"]:
        logger.warning(
            "Amazon 主图不允许 AI 生成内容",
            extra={"platform": platform},
        )
        raise ValueError(
            "Amazon 主图不允许使用 AI 生成内容。"
            "请将 AI 生成图片用于 A+ 页面（详情页），主图需使用实拍。"
        )

    img = Image.open(io.BytesIO(image_data)).convert("RGB")
    target_w, target_h = spec["target_size"]
    bg_color = spec["background_color"]

    # 裁切 + 补白
    if bg_color:
        canvas = Image.new("RGB", (target_w, target_h), color=bg_color)
        img.thumbnail((target_w, target_h), Image.LANCZOS)
        paste_x = (target_w - img.width) // 2
        paste_y = (target_h - img.height) // 2
        canvas.paste(img, (paste_x, paste_y))
        img = canvas
    else:
        img = img.resize((target_w, target_h), Image.LANCZOS)

    # AI 标注角标
    if add_badge and spec.get("ai_badge") and is_ai_generated:
        draw = ImageDraw.Draw(img)

        badge_height = 36
        badge_y = target_h - badge_height
        overlay = Image.new("RGBA", (target_w, badge_height), (0, 0, 0, 128))
        img_rgba = img.convert("RGBA")
        img_rgba.paste(overlay, (0, badge_y), overlay)
        img = img_rgba.convert("RGB")
        draw = ImageDraw.Draw(img)

        badge_text = "AI生成" if platform in ("tmall",) else "AI创作"
        text_position = (target_w - 130, badge_y + 8)

        try:
            font_paths = [
                "C:/Windows/Fonts/msyh.ttc",
                "/System/Library/Fonts/PingFang.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            ]
            font = None
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, 18)
                    break
                except OSError:
                    continue
            if font is None:
                font = ImageFont.load_default()
        except OSError:
            font = ImageFont.load_default()

        draw.text(text_position, badge_text, fill=(255, 255, 255), font=font)

    # 输出 JPEG
    output = io.BytesIO()
    img.save(output, format="JPEG", quality=spec["quality"])
    result = output.getvalue()

    logger.info(
        "图片已适配平台",
        platform=platform,
        size=f"{target_w}x{target_h}",
        ai_generated=is_ai_generated,
    )

    return result


def get_platform_summary() -> list[dict]:
    """返回所有平台规格摘要（供前端下拉选择）"""
    return [
        {
            "key": key,
            "label": spec["label"],
            "size": f"{spec['target_size'][0]}x{spec['target_size'][1]}",
            "allow_ai_primary": spec["allow_ai_primary"],
        }
        for key, spec in PLATFORM_SPECS.items()
    ]
