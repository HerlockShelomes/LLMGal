import re
import traceback

from Text import get_llm_response
from Voice import Voice_Generation_through_http
from Image import emotional_bro
from Image import static_images
from Image import original_image_generation

# class MultimodalAdapter:
#     def __init__(self, provider: str):
#         self.provider = provider  # "openai"/"volcengine"/"localai"
#
#     def call(self, input: dict):
#         # 文本处理
#         if input["modality"] == "text":
#             if self.provider == "openai":
#                 yield from self._openai_text(input)
#             elif self.provider == "volcengine":
#                 yield from self._volc_text(input)
#
#         # 图像生成
#         elif input["modality"] == "image":
#             if self.provider == "openai":
#                 yield from self._dalle_api(input)
#             elif self.provider == "volcengine":
#                 yield from self._volc_image(input)
#
#         # 语音合成
#         elif input["modality"] == "audio":
#
#
# # 使用示例（前端无需修改）
# adapter = MultimodalAdapter("volcengine")
# for chunk in adapter.call({"text": "你好", "modality": "voice"}):
#     websocket.send(chunk)

def request_confirmation(voice, emo):
    """
    :param voice: 指示此次前端选择的语音模型
    :param emo: 指示本次大语言模型回复的情绪状态
    :return: 返回根据声音选择和情绪状态输入得到的转换：具体声音类型字符串、回复声音情绪状态、情绪图片标题[0]及具体描述。
    """
    match voice:
        case "GirlFriend":
            selected_voice = "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"
        case "BoyFriend":
            selected_voice = "zh_male_yourougongzi_emo_v2_mars_bigtts"
        case "ElderSister":
            selected_voice = "zh_female_gaolengyujie_emo_v2_mars_bigtts"
        case "LiteratureGuy":
            selected_voice = "zh_male_ruyayichen_emo_v2_mars_bigtts"
        case _:
            selected_voice = "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"
        # 前端调整之后这里或许可以直接获取对应的数值，但这段代码还是先保留吧。
    match emo:
        case '中性':
            selected_emo_voice = "neutral"
            selected_emo_image = ["neutral", "calm with a smile on the face"]
        case '高兴':
            selected_emo_voice = "neutral"
            selected_emo_image = ["happy", "happy to hear your response"]
        case '悲伤':
            selected_emo_voice = "sad"
            selected_emo_image = ["sad", "very sad because you hurt the person's feelings and there are tears on the face"]
        case '害怕':
            selected_emo_voice = "fear"
            selected_emo_image = ["fear", "scared because you said something too scary"]
        case '生气':
            selected_emo_voice = "neutral"
            selected_emo_image = ["angry", "angry because you said something too rude"]
        case '惊喜':
            selected_emo_voice = "neutral"
            selected_emo_image = ["surprised", "surprised because your response is quite unexpected"]
        case '害羞':
            selected_emo_voice = "neutral"
            selected_emo_image = ["shy", "shy due to the truth that the person likes you as well, and cheeks are red"]
        case _:
            selected_emo_voice = "neutral"
            selected_emo_image = ["neutral", "calm with a smile on the face"]

    return selected_voice, selected_emo_voice, selected_emo_image


def updateLinks(roleName, updatedUrl, updatedIndex):
    with open(f'../frontend/src/assets/Records.txt', 'r', encoding='utf-8') as file:
        lines = file.readlines()

    with open(f'../frontend/src/assets/Records.txt', 'w', encoding='utf-8') as writeFile:
        for i in range(len(lines)):
            if f"{roleName}:\n" in lines[i]:
                lines[i+1] = f'Recent_Url:{updatedUrl}\n'
                lines[i+2] = f'index:{updatedIndex}\n'

            writeFile.write(lines[i])


def Response_Collection(textModel, imageModel, roleName, voiceName, realTimeGeneration, text):
    """
    现阶段设计下，模型应该只支持中文对话。后续应当如何更改提升泛化能力？
    :param textModel: 指示此次生成所使用的文本模型。
    :param imageModel: 指示此次生成所使用的图生图模型。
    :param roleName: 指示此次生成回复所使用的角色。
    :param voiceName: 指示此次回复应当使用的声音。
    :param realTimeGeneration: 指示此次是否需要实时生成图片。为二元布尔值。
    注意，实时生成的图片，因为保持人物的样式需要使用图片url，有效期为24小时，
    因此此处采取一个判断。
    前端记录最近文件的url，并尝试调用此url用于图生图模型姿态调整。
    如果成功，那就使用以此法生成的新图片。
    如果失败，就调用文生图模型生成新的形象。
    静态资源和实时生成资源需要区分开。
    :param text: 指示此次的用户输入提示词。
    :return: 返回前端回复文本内容、对应调用的图片及语音资源文件位置，最近一次生成图片对应的url，同时跟踪的index值也必须反馈前端。
    """

    try:
        with open(f'../frontend/src/assets/Records.txt', 'r', encoding='utf-8') as file:
            content = file.read()
            pattern = fr'{roleName}:\nRecent_Url:\s*([^\n]*)\nindex:(\d+)'
            matches = re.findall(pattern, content, flags=re.MULTILINE)
            imgurl, index = matches[0]

    except FileNotFoundError:
        print("文件未找到，请检查文件路径。将调用静态默认模型代替")
        realTimeGeneration = False
        imgurl = ""
        index = "0"
    except IOError:
        print("发生IO错误，无法读取文件。将调用静态默认模型代替。")
        realTimeGeneration = False
        imgurl = ""
        index = "0"
    # index: 指示此次生成所对应的角色资源序号。（从0-9，超出9就复归0重新计数）

    answer = get_llm_response(textModel, roleName, text)

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

    voiceType, voiceEmotion, imageEmotion = request_confirmation(voiceName, emotion)

    Voice_Generation_through_http(roleName, voiceType, voiceEmotion, answer, index)
    # 注意此处：role的名称尚未提取，可以使用正则表达式提取；
    # 此处更改了规范，以role的名称索引对应的角色提示词和形象生成词。
    # 角色提示词规范，后续还需要继续优化。
    # 一旦更新了index，那么前端应当调用的音频序号，就是当前index-1.同时如果index==0，那么调用音频的index就是9.
    # 此处为了调用的一致性，index统一跟随音频index变换，不做实时渲染和音频序号的区分。

    updatedUrl = ""
    print("是否进行实时图片生成: ", realTimeGeneration)
    if (realTimeGeneration):
        print("实时图片生成调用")
        # do something...此处需要获取最新的url用于图片的生成。
        # 如果没有url或者url失效（代码层面，这两者产生的效果相同，都是invalid url）
        # 那就调用原始图像生成模型使用提示词创建一个，
        # 将其存储后反馈前端。
        try:
            updatedUrl = emotional_bro(imgurl, roleName, [emotion, emo_desc], index, imageModel)
        except Exception as exception:
            print("Url out of date, regenerating...")
            traceback.print_exc()
            updatedUrl = original_image_generation(roleName, "".join([emotion, " because ", emo_desc]), index)
        # 一旦更新了index，那么前端应当调用的图片，就是当前index-1.同时如果index==0，那么调用图片的index就是9.

        # 将最新的index和url更新入文本文档内

    else:
        # 不采取实时图片渲染模式，就直接从静态图片库中检查图片。
        # 如果角色新创建，一张图片都没有，就调用静态图片生成函数原地生成。
        # 这只是一层保险，一般而言创建角色初期就应当完成静态图片的全部生成。

        # 后续和前端协作时，需要注意转到角色创建界面时，
        # 先使用函数生成单张图片确定符合用户预期效果，
        # 再转入情绪图片生成。或许也不必一次生成所有图片，而是需要用户确认一张图片情绪符合自己需求后再转入下一张？
        # 不用了，暂时在确认基本需求的一张图片之后，就把所有情绪图片一把生成出来吧，也算是给用户留一点悬念？
        # 指定文件夹路径
        # 现阶段采取一个很暴力的纠错方式。
        # 如果发现角色名称下静态资源图片不全，就调用模型立刻生成一波新的图片。
        # 这个纠错模式不是不可行，但是很明显有更节省资源的方法。
        # 但是现阶段先将东西做出来再说优化吧。
        print("静态图片生成调用")
        updatedUrl = static_images(roleName, imageModel)

    index = int(index)
    index = (index + 1) % 10
    updatedIndex = str(index)
    updateLinks(roleName, updatedUrl, updatedIndex)

    print("运行到这里了，Check!")

    return answer, str((index-1)%10), imageEmotion[0], updatedUrl
    #此处返回的index必须-1，或者归为9(index==0时)，才能正确索引应使用图片及语音。




