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
        //连接恢复后重放发送失败的请求
        this.wsManager.on('connected', this.handleReconnect.bind(this));

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
        params: ClientPayload[ClientMessageType.QUERY] & {
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
                    imageModel_config: {
                        modelImage: params.imageModel_config.modelImage,
                        realTimeRendering: params.imageModel_config.realTimeRendering,
                    },
                    voiceCate: params.voiceCate,
                    //多轮上下文：时间正序，不含当前这条
                    ...(params.history ? { history: params.history } : {}),
                    ...(params.sessionId ? { sessionId: params.sessionId } : {}),
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
                    //发送失败多半是连接已断：保留 pending 记录并入队等重连后重发，
                    //响应回来时仍能对应到同一个 promise。这里不能直接 reject，
                    //否则一次闪断就把请求判死；真正的失败由超时或重试用尽来兜底。
                    this.enqueueRetry(message);
                    console.error('请求发送失败，已加入重试队列: ', error);
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

        const cancelMsg: AnyClientMessage = {
            type: ClientMessageType.CANCEL,
            message_id: uuidv4(),
            payload: {
                target_message_id: messageID,
            }
        };

        try {
            this.wsManager.send(cancelMsg);
        } catch (error) {
            console.error('发送请求失败: ', error);
        }

        //顺序不能反：先 reject 再清理。反过来的话 reject 一旦抛异常
        //就会跳过 delete，这条请求会永久留在表里占用内存。
        request.reject(new Error('请求已被用户取消'));
        this.pendingRequests.delete(messageID);
    }

    //重发队列：发送失败的请求在此排队，连接恢复后重放
    private retryQueue: Array<{
        message: AnyClientMessage;
        retriesLeft: number;
    }> = [];

    private readonly maxRetriesPerMessage = 3;

    private enqueueRetry(message: AnyClientMessage): void {
        this.retryQueue.push({
            message,
            retriesLeft: this.maxRetriesPerMessage,
        });
    }

    //连接恢复后重放队列。重试用尽的请求要主动 reject 掉对应的 pending promise，
    //否则调用方会一直挂在那儿等一个永远不来的响应。
    public handleReconnect() {
        const queue = this.retryQueue;
        this.retryQueue = [];

        queue.forEach(item => {
            try {
                this.wsManager.send(item.message);
            } catch (error) {
                if (item.retriesLeft > 0) {
                    this.retryQueue.push({
                        message: item.message,
                        retriesLeft: item.retriesLeft - 1,
                    });
                    return;
                }

                console.error('请求重试用尽，已丢弃: ', error);
                const pending = this.pendingRequests.get(item.message.message_id);
                if (pending) {
                    clearTimeout(pending.timeoutID);
                    this.pendingRequests.delete(item.message.message_id);
                    pending.reject(new Error('请求重试用尽，已丢弃'));
                }
            }
        });
    }

    public disconnect(): void {
        this.retryQueue = [];
        this.pendingRequests.forEach(request => clearTimeout(request.timeoutID));
        this.pendingRequests.clear();
        this.wsManager.disconnect();
    }
}