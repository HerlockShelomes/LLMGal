"""火山引擎视觉 API 手动调试脚本（图生图·表情改写示例）。

密钥不再硬编码：与 config.py 的统一密钥管理保持一致，从 backend/.env /
环境变量读取 IMAGE_VOLC_ACCESS_KEY / IMAGE_VOLC_SECRET_KEY（参考 .env.example）。

用法：
    python image_emotions.py <待处理的图片URL>
"""
from __future__ import print_function

import sys

from volcengine.visual.VisualService import VisualService

import config

prompt = """
Maintain the image style as well as all the features of the girl in this image, and keep the background white,
but alter her facial experssions so she looks happy because she likes spending time with you.
At the same time, alter her pose to be waving hands at you.
"""

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python image_emotions.py <图片URL>", file=sys.stderr)
        raise SystemExit(1)
    imaurl = sys.argv[1]

    if not (config.IMAGE_VOLC_ACCESS_KEY and config.IMAGE_VOLC_SECRET_KEY):
        print(
            "缺少火山引擎密钥：请在 backend/.env 中配置 "
            "IMAGE_VOLC_ACCESS_KEY / IMAGE_VOLC_SECRET_KEY"
            "（参考 .env.example），不要把密钥写进源码。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    visual_service = VisualService()

    # call below method if you don't set ak and sk in $HOME/.volc/config
    visual_service.set_ak(config.IMAGE_VOLC_ACCESS_KEY)
    visual_service.set_sk(config.IMAGE_VOLC_SECRET_KEY)

    # 请求Body(查看接口文档请求参数-请求示例，将请求参数内容复制到此)
    form = {
    "req_key": "high_aes_ip_v20",
    "image_urls": [imaurl],
    "prompt": prompt,
    "desc_pushback": True,
    "seed": -1,
    "scale": 3.5,
    "ddim_steps": 9,
    "width": 512,
    "height": 512,
    "cfg_rescale": 0.7,
    "ref_ip_weight": 0.9,
    "ref_id_weight": 0.36,
    "use_sr": True,
    "return_url": True,
    }

    resp = visual_service.cv_process(form)
    print(resp)
