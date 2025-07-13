from openai import OpenAI

Emotion_Prompt = """

在正式的文字回复之前，请用独立的两个括号描述自己的情绪。第一个括号内简短描述针对用户提供输入的情绪回复，从以下表达中选择一个
'中性'，'高兴'，'悲伤'，'害怕'，'生气'，'惊喜'，'害羞'，
第二个括号内解释自己情绪产生的原因，字数不超过30字。
例如: (高兴)(因为受到了朋友的邀请)。请注意使用英语括号。
消息整体不得超过150字"""

def get_role_prompt(role_name):
    role_prompt = ""
    try:
        with open(f'../frontend/src/assets/roles/{role_name}.txt', 'r', encoding='utf-8') as file:
            role_prompt = file.read()
            role_prompt = "".join([role_prompt, Emotion_Prompt])
            print(role_prompt)
    except FileNotFoundError:
        print("文件未找到，请检查文件路径。")
    except IOError:
        print("发生IO错误，无法读取文件。")

    return role_prompt

def get_llm_response(model, role, prompt):
    """
    :param model: 指定选择的模型名称，目前可以支持大部分文本模型，只是更换名称的区别而已。
    :param role: 指定的角色名称
    :param prompt: 用户输入的文本，驱动大语言模型给予回复。
    :return: 大语言模型生成的回复。
    """
    answer_content = ""
    role_pro = get_role_prompt(role)
    full_prompt = [{"role": "assistant", "content": role_pro}]
    full_prompt.append(prompt)
    print(full_prompt)

    client = OpenAI(api_key= 'sk-Tk2Rpty6GBWzDx16Cf7f1e2b5a2f425eA5CbA91958A36d16', base_url="https://o3.fan/v1")
    completion = client.chat.completions.create(
        model=model,
        stream=True,
        messages=full_prompt
    )

    for chunk in completion:
        # 如果chunk.choices为空，则打印usage
        if not chunk.choices:
            print("\nUsage:")
            print(chunk.usage)
        else:
            delta = chunk.choices[0].delta
            # 打印思考过程
                # 开始回复
            if delta.content != "":
            # 打印回复过程
                print(delta.content, end='', flush=True)
                answer_content += delta.content
    return answer_content

if __name__ == '__main__':
    answer = ""
    answer = get_llm_response("deepseek-ai/DeepSeek-V3", "Testificate", {"role": "user", "content": "有时间一块桌游吗？"})