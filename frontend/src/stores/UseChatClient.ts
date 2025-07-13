import {ref, reactive, onUnmounted} from "vue";
import { LLMClient} from "./ClientChat.ts";

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
                    text: currentInput,
                    modelText: selectedTextModel.value,
                },
                role: selectedRole.value,   //角色选择
                imageMode_config: {
                    modelImage: selectedImageModel.value,
                    realTimeRendering: realTime,
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
            handleError(err.message);
            updateMessageStatus(userMessageID, 'error');
        }
    };

    const updateMessageProgress = (messageID: string, progress: number) => {
        const message = messages.find(m => m.message_id === messageID);
        if (message) {
            message.metadata.progress = progress;
        }
    };

    const updateMessageStatus = (messageID: string, status: MessageStatus) => {
        const message = messages.find(m => m.message_id === messageID);
        if (message) {
            message.status = status;
        }
    };

    const handleError = (error, msg: string) => {
        error.value = msg;
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