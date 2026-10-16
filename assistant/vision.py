# -*- coding: utf-8 -*-
"""图片识别：把买家发来的图片交给多模态视觉模型，产出简短描述。
配置在同目录的 软件配置.json：
  vision_base_url   OpenAI 兼容地址，例如 https://dashscope.aliyuncs.com/compatible-mode/v1
  vision_key        API Key
  vision_model      模型名，例如 qwen-vl-plus
"""
import base64
import json
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")

VISION_PROMPT = ("你是闲鱼店铺的客服助手。用一两句话客观描述这张买家发来的图片："
                 "商品照片就说型号、成色、可见标识；截图就说关键文字、价格、型号；"
                 "故障图就说现象。不超过 80 字，不要客套，不要猜测图片以外的信息。")


def soft_config(config):
    try:
        p = Path(__file__).resolve().parent / "软件配置.json"
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _vision_cfg(config):
    s = soft_config(config)
    base = str(s.get("vision_base_url") or s.get("llm_base_url")
               or "https://open.bigmodel.cn/api/paas/v4").strip().rstrip("/")
    key = str(s.get("vision_key") or s.get("llm_key") or s.get("deepseek_key") or "").strip()
    model = str(s.get("vision_model") or "glm-5.3-flash").strip()
    return base, key, model


def enabled(config):
    base, key, model = _vision_cfg(config)
    return bool(base and key and model)


def download(url):
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.goofish.com/"},
                     timeout=25)
    r.raise_for_status()
    return r.content, (r.headers.get("Content-Type") or "image/jpeg").split(";")[0]


def _shrink(img_bytes, max_side=1280, quality=85):
    """压到长边 max_side 的 JPEG，减小体积与 token；失败原样返回。"""
    try:
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(img_bytes))
        im = im.convert("RGB")
        w, h = im.size
        m = max(w, h)
        if m > max_side:
            r = max_side / float(m)
            im = im.resize((max(1, int(w * r)), max(1, int(h * r))))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return img_bytes, None


def describe_image(config, img_bytes, mime="image/jpeg"):
    """返回描述文本；未配置或失败返回 None。"""
    base, key, model = _vision_cfg(config)
    if not (base and key and model):
        return None
    small, new_mime = _shrink(img_bytes)
    if new_mime:
        img_bytes, mime = small, new_mime
    b64 = base64.b64encode(img_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "max_tokens": 2000,
    }
    r = requests.post(f"{base}/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json=payload, timeout=90)
    r.raise_for_status()
    return str(r.json()["choices"][0]["message"]["content"]).strip()


def describe_url(config, url):
    """下载 + 识别；任一步失败返回 None。"""
    try:
        data, mime = download(url)
        return describe_image(config, data, mime)
    except Exception:
        return None
