import {v4 as uuidv4} from 'uuid';
import {WebSocketManager} from '../utils/WebSocketManager.ts';
import {
    type AnyClientMessage,
    type AnyServerMessage,
    ClientMessageType,
    type ClientPayload,
    type ServerMessage,
    ServerMessageType,
    type ServerPayload,
} from "../utils/MessageType.ts";

type PendingRequest = {
    resolve: (value: ServerPayload[ServerMessageType.RESPONSE]) => void;
    reject: (reason?: unknown) => void;
    timeoutID: NodeJS.Timeout;
};

export class LLMClient {
    private wsManager: WebSocketManager;
    private pendingRequests = new Map<string, PendingRequest>();
    private DEFAULT_TIMEOUT = 30_000;//30s

    constructor(
        endpoint: string,
        //好奇怪，这里一旦去掉private就会有很多报错……何种原因导致的？
        private options: {
            autoConnect?: boolean;
            timeout?: number;
        } = {}
    ) {
        this.wsManager = new WebSocketManager(endpoint);
        this.options = {
            autoConnect: true,
            ...options };

        //绑定消息处理器
        this.wsManager.on('message', this.handleMessage.bind(this));
        this.wsManager.on('error', this.handleError.bind(this));

        if (this.options.autoConnect) {
            this.connect();
        }
    }

    public async connect(): Promise<void>  {
        try {
            await this.wsManager.connect();
        } catch (error) {
            console.error('连接失败', error);
            throw new Error('无法连接到AI服务');
        }
    }

    public async sendQuery(
        params: Omit<ClientPayload[ClientMessageType.QUERY], 'text'> &  {
            text: string
            onProgress?: (progress: number) => void
        }
    ): Promise<ServerPayload[ServerMessageType.RESPONSE]> {
        const messageID = uuidv4();

        return new Promise((resolve, reject) => {
            const timeoutID = setTimeout(() => {
                this.pendingRequests.delete(messageID);
                reject(new Error('请求超时'));
            }, this.options.timeout || this.DEFAULT_TIMEOUT);

            //注册请求：
            this.pendingRequests.set(messageID, {
                resolve,
                reject,
                timeoutID,
            });

            //构建消息：
            const message: AnyClientMessage = {
                type: ClientMessageType.QUERY,
                message_id: messageID,
                payload: {
                    textModel_config: {
                        text: params.textModel_config.text,
                        modelText: params.textModel_config.modelText,
                    },
                    role: params.role,   //角色选择
                    imageMode_config: {
                        modelImage: params.imageMode_config.modelImage,
                        realTimeRendering: params.imageMode_config.realTimeRendering,
                    },
                    voiceCate: params.voiceCate,
                }
            };

            //请求发送
            try{
                this.wsManager.send(message);

                //处理进度问题
                if (params.onProgress) {
                    const progressHandler = (progressMsg: ServerPayload[ServerMessageType.PROGRESS]) => {
                        if (progressMsg.status === 'processing') {
                            params.onProgress?.(progressMsg.progress);
                        }
                    };
                    this.wsManager.on('progress', progressHandler);

                    //请求完成时关闭监听
                    const cleanup = () => {
                        this.wsManager.off('progress', progressHandler);
                    };
                    this.pendingRequests.get(messageID)!.reject = (reason) => {
                        cleanup();
                        reject(reason);
                    };
                    this.pendingRequests.get(messageID)!.resolve = (value) => {
                        cleanup();
                        resolve(value);
                    };
                }
            } catch (error) {
                this.pendingRequests.delete(messageID);
                reject(error);
            }
        });
    }

    private handleMessage(message: AnyServerMessage): void {
        //第一层判断：确定类型位于枚举类内。
        if (!Object.values(ServerMessageType).includes(message.type)) {
            throw new Error('未知消息类型: ' + message.type);
        }

        //第二层判断：利用类型谓词精确收窄
        switch (message.type) {
            case ServerMessageType.RESPONSE:
                this.handleResponse(message as ServerMessage<ServerMessageType.RESPONSE>);
                break;
            case ServerMessageType.ERROR:
                this.handleServerError(message as ServerMessage<ServerMessageType.ERROR>);
                break;
                //Possibly handle other types of errors.
        }
    }

    private handleResponse(response: ServerMessage<ServerMessageType.RESPONSE>): void {
        const request = this.pendingRequests.get(response.message_id);
        if (!request) {
            console.warn(`收到未知请求ID的响应: ${response.message_id}`);
            return;
        }

        clearTimeout(request.timeoutID);
        this.pendingRequests.delete(response.message_id);
        request.resolve(response.payload);
    }

    private handleServerError(errorMsg: ServerMessage<ServerMessageType.ERROR>): void {
        const request = this.pendingRequests.get(errorMsg.message_id);
        if (!request) return;

        clearTimeout(request.timeoutID);
        this.pendingRequests.delete(errorMsg.message_id);

        const error = new Error(`${errorMsg.payload.code}: ${errorMsg.payload.message}`);
        if (errorMsg.payload.detail) {
            console.error('服务器详情错误: ', errorMsg.payload.detail);
        }
        request.reject(error);
    }

    private handleError(error: Error): void {
        //处理所有未完成的错误请求。
        //这里好像有一个假定前提：所有未完成的错误请求都是超时请求？
        this.pendingRequests.forEach (request => {
            clearTimeout(request.timeoutID);
            request.reject(error);
        });
        this.pendingRequests.clear();
    }

    public cancelRequest(messageID: string): void {
        const request = this.pendingRequests.get(messageID);
        if (!request) return;

        clearTimeout(request.timeoutID);
        this.pendingRequests.delete(messageID);

        const cancelMsg: AnyClientMessage = {
            type: ClientMessageType.CANCEL,
            message_id: uuidv4(),
            payload: {
                target_message_id: messageID,
            }
        };

        try {
            this.wsManager.send(cancelMsg);
            request.reject(new Error('请求已被用户取消'));
        } catch (error) {
            console.error('发送请求失败: ', error);
        }
    }

    private retryQueue: Array<{
        message: AnyClientMessage;
        retriesLeft: number;
    }> = [];

    public handleReconnect() {
        this.retryQueue.forEach(item => {
            this.wsManager.send(item.message);
        });
    }
}