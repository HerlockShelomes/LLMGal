from __future__ import print_function
from volcengine.visual.VisualService import VisualService
# 你的密钥信息
ACCESS = 'AKLTODlhZDdkMzc3OTU3NGE3Zjk2NWIwODlkNDY2ZDQ1Y2I'
SECRET = 'T1RrME1HRTFaVFppWkRNMk5EUTJZMkUwTURnMllUUmhNelZoT1dSa01UZw=='
prompt = """
Maintain the image style as well as all the features of the girl in this image, and keep the background white,
but alter her facial experssions so that she looks happy because she likes spending time with you.
At the same time, alter her pose to be waving hands at you.
"""
imaurl = "https://p26-aiop-sign.byteimg.com/tos-cn-i-vuqhorh59i/2025070815485819CDF93FB892EFCD5217-0~tplv-vuqhorh59i-image.image?rk3s=7f9e702d&x-expires=1752047352&x-signature=FLbZfewVM7yJHfSqXOy99UbqwBQ%3D"

if __name__ == '__main__':
    visual_service = VisualService()

    # call below method if you don't set ak and sk in $HOME/.volc/config
    visual_service.set_ak(ACCESS)
    visual_service.set_sk(SECRET)

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