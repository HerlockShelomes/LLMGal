from __future__ import print_function
from volcengine.visual.VisualService import VisualService
import traceback
import requests
import os
import re

# 你的密钥信息
ACCESS = 'AKLTODlhZDdkMzc3OTU3NGE3Zjk2NWIwODlkNDY2ZDQ1Y2I'
SECRET = 'T1RrME1HRTFaVFppWkRNMk5EUTJZMkUwTURnMllUUmhNelZoT1dSa01UZw=='
# 此处的提示词存储规范：绘画基本提示词格式如上。去除Subject_Description、Appearance Details和Expression Adjustment具体的内容，
# 根据用户对角色的需求填充对应词汇。
# 所以存储提示词的规范也是，从上至下，Subject Description, Appearance Details 和Expression Adjustment.
# Subject Description和Appearance Details存储角色基本信息，一经确定就不会更改。可以放至文本文档里。
# Expression Adjustment根据用户的需求填入内容。正常对应大语言模型提供的括号输出。
# increase when generating new images.
# The index follows one order of 0 - happy; 1 - sad; 2 - scared; 3 - angry; 4 - surprised; 5 - shy (really?)
# This plan has been abandoned already.

emo_image = [["neutral", "calm with a smile on the face"],
             ["happy", "happy to hear your response"],
             ["sad", "very sad because you hurt the person's feelings and there are tears on the face"],
             ["fear", "scared because you said something too scary"],
             ["angry", "angry because you said something too rude"],
             ["surprised", "surprised because your response is quite unexpected"],
             ["shy", "shy due to the truth that the person likes you as well, and cheeks are lightly reddish"]]
def save_image_from_url(url, save_path):
    """将URL图片保存到固定路径（自动创建目录）"""
    try:
        # 创建目录（如果不存在）
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # 发起GET请求
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return True
        else:
            print(f"下载失败，状态码：{response.status_code}")
            return False
    except Exception as e:
        print(f"保存异常：{str(e)}")
        return False

def create_role_image_prompt(role_Name, subject_description, appearance_details):
    storePath = f'../frontend/src/assets/pictures/Role_Description/{role_Name}.txt'
    try:
        os.makedirs(os.path.dirname(storePath), exist_ok=True)
    except OSError as error:
        print(f"创建目录时出错: {error}")
        return False

    store = f"""Subject Description: {subject_description}
Appearance Details: {appearance_details}"""

    try:
        with open(storePath, "w", encoding="utf-8") as file:
            file.write(store)
        print(f"文件已成功创建并写入内容: {storePath}")
    except IOError as error:
        print(f"写入文件时出错: {error}")
        return False

    return True


def get_role_image_prompt(role_Name):
    role_description = ""
    try:
        with open(f'../frontend/src/assets/pictures/Role_Description/{role_Name}.txt', 'r', encoding='utf-8') as file:
            role_description = file.read()
            print(role_description)
    except FileNotFoundError:
        print("文件未找到，请检查文件路径。")
    except IOError:
        print("发生IO错误，无法读取文件。")

    # 不要忘记此处的换行符。似乎不添加这个换行符会引起错误。具体原因暂时不明。
    pattern_subject = r'Subject Description:\s*(.+?)(?=\nAppearance Details|$)'
    subject_description = re.findall(pattern_subject, role_description, re.DOTALL)
    pattern_appearance = r'Appearance Details:\s*(.+?)(?=\0|$)'
    appearance_details = re.findall(pattern_appearance, role_description, re.DOTALL)
    print("\n", subject_description[0])
    print(appearance_details[0])

    return subject_description[0], appearance_details[0]

def original_image_generation (nameRole, imgEmo, i):

    subject, appearance = get_role_image_prompt(nameRole)
    print(f"开始图像生成, 静态图像, 角色: {nameRole}, 情绪: {imgEmo}, 序号: {i}")

    original_prompt = f"""
    Positive Prompt: best quality, masterpiece, ultra-high resolution, head portrait, Japanese anime style.
    
    [Subject Description: {subject}],
    [Appearance Details: {appearance}],
    [Expression Adjustment: {imgEmo}],
    [Background: pure white background, could contain natural shadows, isolated],
    [Photography: studio lighting, sharp focus],
    [Perspective: front view],
    [Style: anime]

    Negative prompt: low quality, deformed, text, signature, watermark, multiple people, background elements, blurry, out of frame.
    """
    savePath = f"../frontend/src/assets/pictures/{nameRole}/{nameRole}_{i}.jpg"

    visual_service = VisualService()

    # call below method if you don't set ak and sk in $HOME/.volc/config
    visual_service.set_ak(ACCESS)
    visual_service.set_sk(SECRET)

    # 请求Body(查看接口文档请求参数-请求示例，将请求参数内容复制到此)
    form = {
    "req_key":"high_aes_general_v20_L",
    "prompt":original_prompt,
    "seed":-1,
    "scale":3.5,
    "ddim_steps":16,
    "width":512,
    "height":512,
    "use_sr":True,
    "use_pre_llm": True,
    "return_url":True

    }
    resp = visual_service.cv_process(form)
    print(resp)
    image_url = resp['data']['image_urls'][0]
    save_image_from_url(image_url, savePath)
    
    return image_url


def emotional_bro(imaurl, nameRole, emotion, i, modelValue):
    """
    :param imaurl: 传入图片的网址。似乎不可避免地要求对每一个角色的最近URL进行记录，因此需要单开一个文本文档用于记录。
    :param nameRole: 角色名称。
    :param emotion: 角色情绪表征。
    :param i: index跟踪
    :param modelValue: 允许不同图生图模型的选择，前端确定可选模型。
    :return: 一个存好本地的图片，一个URL.
    马上新增一个参量，允许调用不同的图生图模型……
    """

    emotional_prompt = f"""
    Positive Prompt: best quality, masterpiece, ultra-high resolution, head portrait, Japanese anime style.
    
    Maintain the image style as well as all the features of the person in this image, and keep the background white,
    but alter the facial expression of the person so that the person looks {emotion[0]} because {emotion[1]}.
"""

    negative_prompt ="""
    Negative prompt: low quality, deformed, text, signature, watermark, multiple people, background elements, blurry, out of frame."""

    savePath = f"../frontend/src/assets/pictures/{nameRole}/{nameRole}_{i}.jpg"
    saveUrl = ""

    visual_service = VisualService()

    visual_service.set_ak(ACCESS)
    visual_service.set_sk(SECRET)



    if modelValue == "high_aes_ip_v20":
        # 请求Body(查看接口文档请求参数-请求示例，将请求参数内容复制到此)
        print(f"开始图像生成, 实时图像, 角色: {nameRole}, 情绪: {emotion}, 序号: {i}, URL: {imaurl}")
        form = {
            "req_key": modelValue,
            "image_urls": [imaurl],
            "prompt": "".join([emotional_prompt, negative_prompt]),
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
        saveUrl = resp['data']['image_urls'][0]

        save_image_from_url(saveUrl, savePath)

    elif modelValue == "byteedit_v2.0":
        form = {
            "req_key": "byteedit_v2.0",
            "image_urls": [imaurl],
            "prompt": emotional_prompt,
            "negative_prompt": negative_prompt,
            "seed": -1,
            "scale": 0.5,
            "return_url": True,
        }
        resp = visual_service.cv_process(form)
        print(resp)
        saveUrl = resp['data']['image_urls'][0]

        save_image_from_url(saveUrl, savePath)
    else:
        saveUrl = original_image_generation(nameRole, "".join([emotion[0], " because ", emotion[1]]), i)

    return saveUrl

def static_images (roleCall, pic2picValue):
    """
    :param roleCall: 对应角色名称，通过此获取角色描述信息。
    :return: 向缓存存入一组图片，指示不同情绪下应展示的图片。
    """
    folder_path = f"../frontend/src/assets/pictures/{roleCall}"
    os.makedirs(folder_path, exist_ok=True)
    # 获取文件夹内所有文件和子目录的名称列表
    files_dirs = os.listdir(folder_path)
    # 过滤出文件名（排除子目录）
    files = {f for f in files_dirs if os.path.isfile(os.path.join(folder_path, f))}
    # 打印文件名
    image_files = {
        f"{roleCall}_{emo_image[0][0]}.jpg",
        f"{roleCall}_{emo_image[1][0]}.jpg",
        f"{roleCall}_{emo_image[2][0]}.jpg",
        f"{roleCall}_{emo_image[3][0]}.jpg",
        f"{roleCall}_{emo_image[4][0]}.jpg",
        f"{roleCall}_{emo_image[5][0]}.jpg",
        f"{roleCall}_{emo_image[6][0]}.jpg"
    }
    # 定义静态资源图片名称无序集合
    shared_files = image_files.intersection(files)
    # 确认静态资源能否对应
    if (len(shared_files) != 7):
    # 对应不上时，进行一轮重生成
    # 一般而言问题都是生成少了，比如服务器繁忙导致的图片资源丢失？
    # 静态图片文件资源有没有可能更多呢？比如由于服务器繁忙导致的反复生成问题？
        print("静态资源缺少，重新生成中...")
        ori_image_url = original_image_generation(roleCall, emo_image[0][1], emo_image[0][0])
        for i in range(1, 7):
            emotional_bro(ori_image_url, roleCall, emo_image[i], emo_image[i][0], pic2picValue)
        print("static images generated successfully.")
        return ori_image_url

    print("static images already exist.")
    return ""
    # 确保前端存储url时，存在前置判断条件：url不为空。

if __name__ == '__main__':
    # roleCall = "GirlProgrammer"
    #
    # folder_path = f"../frontend/src/assets/pictures/{roleCall}"
    # # 获取文件夹内所有文件和子目录的名称列表
    # files_dirs = os.listdir(folder_path)
    # # 过滤出文件名（排除子目录）
    # files = {f for f in files_dirs if os.path.isfile(os.path.join(folder_path, f))}
    # # 打印文件名
    # image_files = {
    #     f"{roleCall}_{emo_image[0][0]}.jpg",
    #     f"{roleCall}_{emo_image[1][0]}.jpg",
    #     f"{roleCall}_{emo_image[2][0]}.jpg",
    #     f"{roleCall}_{emo_image[3][0]}.jpg",
    #     f"{roleCall}_{emo_image[4][0]}.jpg",
    #     f"{roleCall}_{emo_image[5][0]}.jpg",
    #     f"{roleCall}_{emo_image[6][0]}.jpg"
    # }
    # # 定义静态资源图片名称无序集合
    # shared_files = image_files.intersection(files)
    # print(files)
    # print(image_files)
    # print(len(shared_files))
    # print(shared_files)

    try:
        updatedUrl = emotional_bro("", "GirlProgrammer", emo_image[5], emo_image[5][0], "byteedit_v2.0")
    except Exception as exception:
        print("Url out of date, regenerating...")
        traceback.print_exc()


    # static_images("Testificate_Boy","byteedit_v2.0")