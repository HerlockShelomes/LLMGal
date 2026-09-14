import {ref, reactive, onUnmounted} from "vue";
import { LLMClient} from "./ClientChat.ts";
import type { HistoryMessage } from "../utils/MessageType.ts";

//多轮上下文保留的最近消息条数（20 轮 = 20 组 user + assistant）
const HISTORY_MESSAGE_LIMIT = 40;

type MessageStatus = 'sending' | 'received' | 'error';

interface ChatMessage {
    message_id: string;
    text: string;
    role: 'user' | 'assistant';
    status: MessageStatus;
    metadata?: {
        modelText?:string;
        voiceCate?: string;
        modelImage?: string;
        role_name?: string;
        realTime?: boolean;
        index?: string;
        emotion?: string;
        progress?: number;
        time_cost?: number;
        code?: string;
    };
}

export default function useChatClient() {
    const client = new LLMClient('ws://localhost:8000/ws/chat', {
        timeout: 30_000
    });


    //组件状态
    const messages = reactive<ChatMessage[]>([]);
    const connectionStatus = ref<'connected' | 'connecting' | 'disconnected'>('disconnected');
    const inputText = ref('');
    const selectedTextModel = ref("deepseek-ai/DeepSeek-R1")
    const selectedImageModel = ref("byteedit_v2.0");
    const selectedVoiceCate = ref("LiteratureGuy");
    const selectedRole = ref("Wendy");
    const realTime = ref(false);
    const error = ref<string | null>(null);

    //同一会话的多轮请求共用一个 sessionId，便于后端按会话组织上下文
    const sessionId = ref<string>(crypto.randomUUID());

    //从已完成的消息里取最近 N 条作为上下文，时间正序、不含当前这条
    const buildHistory = (): HistoryMessage[] =>
        messages
            .filter(m => m.status === 'received' && m.text.trim())
            .slice(-HISTORY_MESSAGE_LIMIT)
            .map(m => ({ role: m.role, content: m.text.trim() }));

    const initialize = async () => {
        try {
            connectionStatus.value = 'connecting';
            await client.connect();
            connectionStatus.value = 'connected';
        } catch (err) {
            handleError(err, "连接失败，请检查网络连接");
        }
    };

    //消息发送逻辑：
    const sendMessage = async () => {
        if (!inputText.value.trim()) return;

        const userMessageID = Date.now().toString();

        //添加用户消息
        messages.push({
            message_id: userMessageID, //生成消息独一ID.
            text: inputText.value,
            role: 'user',
            status: 'sending',
            metadata: {
                modelText: selectedTextModel.value,
                voiceCate: selectedVoiceCate.value,
                modelImage: selectedImageModel.value,
                role_name: selectedRole.value,
                realTime: realTime.value,
            }
        });

        const currentInput = inputText.value;
        inputText.value = ""

        try {
            const response = await client.sendQuery({
                textModel_config: {
                    //契约要求 text 是 {role, content} 消息对象，不能是裸字符串
                    text: { role: 'user', content: currentInput },
                    modelText: selectedTextModel.value,
                },
                role: selectedRole.value,   //角色选择
                history: buildHistory(),
                sessionId: sessionId.value,
                imageModel_config: {
                    modelImage: selectedImageModel.value,
                    realTimeRendering: realTime.value,
                },
                voiceCate: selectedVoiceCate.value,
                onProgress: (percent) => {
                    updateMessageProgress(userMessageID, percent);
                }
            });

            //助手响应：
            messages.push({
                message_id: userMessageID, //生成消息独一ID.
                text: response.response,
                role: 'assistant',
                status: 'received',
                metadata: {
                    index: response.index,
                    emotion: response.emotion,
                    progress: 100,
                    time_cost: response.metrics.time_cost,
                }
            });
        } catch (err) {
            handleError(err);
            updateMessageStatus(userMessageID, 'error');
        }
    };

    const updateMessageProgress = (messageID: string, progress: number) => {
        const message = messages.find(m => m.message_id === messageID);
        if (message?.metadata) {
            message.metadata.progress = progress;
        }
    };

    const updateMessageStatus = (messageID: string, status: MessageStatus) => {
        const message = messages.find(m => m.message_id === messageID);
        if (message) {
            message.status = status;
        }
    };

    //msg 用于覆盖默认文案；缺省时从 error 本身取信息
    const handleError = (err: unknown, msg?: string) => {
        const text = msg
            ?? (err instanceof Error ? err.message : typeof err === 'string' ? err : '未知错误');
        error.value = text;
        setTimeout(() => error.value = null, 5000);
    };

    //清理已离线用户？
    onUnmounted(() => {
        client.disconnect();
    });

    return {
        messages,
        connectionStatus,
        inputText,
        selectedTextModel,
        selectedImageModel,
        selectedVoiceCate,
        selectedRole,
        error,
        sendMessage,
        initialize
    };
}