"""Render 构建时预先准备 CPU OCR 模型，不依赖数据库、用户图片或 Flask 配置。"""
from PIL import Image, ImageDraw

from shards.vision import recognize_line


def prepare():
    image = Image.new('RGB', (180, 64), 'white')
    ImageDraw.Draw(image).text((10, 8), '123', fill='black', font_size=36)
    text, score = recognize_line(image)
    if not text:
        raise RuntimeError('OCR 模型预加载失败，请检查构建日志中的模型下载或 ONNX Runtime 错误。')
    print('CPU OCR model is ready. No database or user images were accessed.', flush=True)


if __name__ == '__main__':
    prepare()
