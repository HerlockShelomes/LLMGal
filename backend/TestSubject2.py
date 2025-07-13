from enum import Enum
from volcengine.visual.VisualService import VisualService
import re
import sys
import time


ACCESS = 'AKLTODlhZDdkMzc3OTU3NGE3Zjk2NWIwODlkNDY2ZDQ1Y2I'
SECRET = 'T1RrME1HRTFaVFppWkRNMk5EUTJZMkUwTURnMllUUmhNelZoT1dSa01UZw=='
prompt_original = f"""a 9 years old senior citizen with yellow hair and rather thin eyebrows, anime style"""


class emotions(Enum):
    happy = 0
    sad = 1
    scared = 2
    angry = 3
    surprised = 4
    shy = 5
index = 0

emotions.happy.description = "happy to hear your response"
emotions.sad.description = "sad because you could not accompany her"
emotions.scared.description = "scared because you said something too scary"
emotions.angry.description = "angry since you could not understand her feelings"
emotions.surprised.description = "surprised because she did not expect that you like her"
emotions.shy.description = "shy due to the truth that she likes you as well"
# emotion = emotions(index)
# 不知为何，写emotion再代入以下循环的形式无法更新emotion，同一条信息（emotions(0).description）将重复6遍

class voice_type(Enum):
    StandardGirlfriend = 0
    StandardBoyfriend = 1
    Elder_Sis = 2
    Gentle_Man = 3

voice_type.StandardGirlfriend.code = "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"
voice_type.StandardBoyfriend.code = "zh_male_yangguangqingnian_emo_v2_mars_bigtts"
voice_type.Elder_Sis.code = "zh_female_gaolengyujie_emo_v2_mars_bigtts"
voice_type.Gentle_Man.code = "zh_male_ruyayichen_emo_v2_mars_bigtts"

selected_voice_type = voice_type.StandardGirlfriend.code

text = "你好"

class emotion(Enum):
    neutral = 0
    happy = 1
    sad = 2
    scared = 3
    angry = 4
    surprised = 5
    shy = 6

emotion.neutral.translation = "neutral"
emotion.happy.translation = "neutral"
emotion.sad.translation = "sad"
emotion.scared.translation = "fear"
emotion.angry.translation = "neutral"
emotion.surprised.translation = "neutral"
emotion.shy.translation = "neutral"

selected_emotion = emotion.neutral.translation

def request_confirmation(voice, emo, text_content):
    selected_voice_type = f"{voice_type(voice).name}"
    selected_emotion = f"{emotion(emo).value}"
    text = text_content

    print(selected_voice_type)
    print(selected_emotion)
    print(text)
    return selected_voice_type, selected_emotion, text

def updateLinks(roleName, updatedUrl, updatedIndex):
    with open(f'../frontend/src/assets/Records.txt', 'r', encoding='utf-8') as file:
        lines = file.readlines()

    with open(f'../frontend/src/assets/Records.txt', 'w', encoding='utf-8') as writeFile:
        for i in range(len(lines)):
            if f"{roleName}:\n" in lines[i]:
                lines[i+1] = f'Recent_Url:{updatedUrl}\n'
                lines[i+2] = f'index:{updatedIndex}\n'

            writeFile.write(lines[i])

if __name__ == '__main__':
    # request_confirmation(1, 3, "这个事情有点吓人了兄弟")
    # for index in range(6):
    #     print(emotions(index).description)
    # visual_service = VisualService()
    #
    # # call below method if you don't set ak and sk in $HOME/.volc/config
    # visual_service.set_ak(ACCESS)
    # visual_service.set_sk(SECRET)
    #
    # # 请求Body(查看接口文档请求参数-请求示例，将请求参数内容复制到此)
    # form = {
    # "req_key":"high_aes_general_v20_L",
    # "prompt":prompt_original,
    # "seed":-1,
    # "scale":3.5,
    # "ddim_steps":16,
    # "width":512,
    # "height":512,
    # "use_sr":True,
    # "use_pre_llm": True,
    # "return_url":True
    #
    # }
    # resp = visual_service.cv_process(form)
    # print(resp)
    # answer = ""
    # try:
    #     with open(f'../frontend/test.txt', 'r', encoding='utf-8') as file:
    #         answer = file.read()
    #         print(answer)
    # except FileNotFoundError:
    #     print("文件未找到，请检查文件路径。")
    # except IOError:
    #     print("发生IO错误，无法读取文件。")

    # pattern_transform_1 = r'"+'
    # pattern_transform_2 = r"'+"
    #
    # replacement_transform_1 = r'\"'
    # replacement_transform_2 = r"\'"
    #
    # test = re.sub(pattern_transform_1, replacement_transform_1, answer)
    # response = re.sub(pattern_transform_2, replacement_transform_2, test)
    # print(response)

    answer = "(高兴)(因为今天吃到了点心)(你不应当看到我的)"
    pattern = r'\((.*?)\)'
    try:
        match = re.findall(pattern, answer)
        if len(match) >= 2:
            emotion = match[0]
            emo_desc = match[1]
        elif len(match) == 1:
            emotion = match[0]
            emo_desc = ''
        else:
            emotion = '中性'
            emo_desc = ''
        print("人物情绪：", emotion)
        print("具体描述：", emo_desc)
    except:
        emotion = '中性'
        emo_desc = ''
        print("情绪提取不成功……，复归默认值")

#     role_description = ""
#     try:
#         with open(f'../frontend/src/assets/pictures/Role_Description/Testificate_Boy.txt', 'r', encoding='utf-8') as file:
#             role_description = file.read()
#             print(role_description)
#     except FileNotFoundError:
#         print("文件未找到，请检查文件路径。")
#     except IOError:
#         print("发生IO错误，无法读取文件。")
#
#     # 不要忘记此处的换行符。似乎不添加这个换行符会引起错误。具体原因暂时不明。
#     pattern_subject = r'Subject Description:\s*(.+?)(?=\nAppearance Details|$)'
#     subject_description = re.findall(pattern_subject, role_description, re.DOTALL)
#     pattern_appearance = r'Appearance Details:\s*(.+?)(?=\0|$)'
#     appearance_description = re.findall(pattern_appearance, role_description, re.DOTALL)
#     print(subject_description[0])
#     print("\n", appearance_description[0])
#
#     role_Name = "Testificate_Boy"
#
#     subject_description = "a undergraduate boy student, he is thin with a pair of square-frame glasses."
#     appearance_details = "He is a programmer, so he always wear a plaid shirt. He holds a notebook in his hand. He has hair that is a little wavy, with small eyes and thin eyebrows."
#
#     storePath = f'../frontend/src/assets/pictures/Role_Description/{role_Name}.txt'
#     try:
#         os.makedirs(os.path.dirname(storePath), exist_ok=True)
#     except OSError as error:
#         print(f"创建目录时出错: {error}")
#
#     store = f"""Subject Description: {subject_description}
# Appearance Details: {appearance_details}"""
#
#     try:
#         with open(storePath, "w", encoding="utf-8") as file:
#             file.write(store)
#         print(f"文件已成功创建并写入内容: {storePath}")
#     except IOError as error:
#         print(f"写入文件时出错: {error}")

    emo_image = [["neutral", "calm with a smile on the face"],
                 ["happy", "happy to hear your response"],
                 ["sad", "very sad because you hurt the person's feelings and there are tears on the face"],
                 ["fear", "scared because you said something too scary"],
                 ["angry", "angry because you said something too rude"],
                 ["surprised", "surprised because your response is quite unexpected"],
                 ["shy", "shy due to the truth that the person likes you as well, and cheeks are red"]]

    print(emo_image[1][1])

#     for i in range(1, 6):
#         print(i)
#
#     role_prompt = "TestSubject 1"
#     print(role_prompt)
#
#     Emotion_Prompt = """adsfasdlfkj;lk
# """
#     role_prompt = "".join([role_prompt, Emotion_Prompt])
#     print(role_prompt)

    # folder_path = f"../frontend/src/assets/pictures/Wendy"
    # # 获取文件夹内所有文件和子目录的名称列表
    # files_dirs = os.listdir(folder_path)
    # # 过滤出文件名（排除子目录）
    # files = [f for f in files_dirs if os.path.isfile(os.path.join(folder_path, f))]
    # # 打印文件名
    # for file in files:
    #     print(file)

    joined_string = "".join(["高兴", " because ", "因为能够和主人一起狩猎冰呪龙了"])
    print(joined_string)

    print(sys.version)

    index = 11

    print(index%10)
    # roleName = "Wendy"
    # with open(f'../frontend/src/assets/Records.txt', 'r', encoding='utf-8') as file:
    #     content = file.read()
    #     index = 0
    #     pattern = fr'{roleName}:\nRecent_Url:\s*([^\n]*)\nindex:(\d+)'
    #     matches = re.findall(pattern, content, flags=re.MULTILINE)
    #     imgurl, index = matches[0]
    #     print(matches)
    #     print("image url is: ", imgurl)
    #     print("index is: ", index)

    startTime = (time.time())
    time.sleep(3)
    stopTime = time.time()

    print(f"Duration: {(stopTime - startTime):.2f}s")

    # updateLinks('GirlProgrammer', '更新的URL', '更新的index')

    with open(f'../frontend/src/assets/Records.txt', 'r', encoding='utf-8') as file:
        content = file.read()
        pattern = r'Wendy:\nRecent_Url:\s*([^\n]*)\nindex:(\d+)'
        matches = re.findall(pattern, content, flags=re.MULTILINE)
        imgurl, index = matches[0]
        print(matches[0])