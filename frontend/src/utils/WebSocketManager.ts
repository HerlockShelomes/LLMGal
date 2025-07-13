import {type AnyServerMessage, ClientMessageType, isServerMessage, type ClientMessage} from "./MessageType.ts";

type EventHandler<in T=unknown> = (data: T) => void;

export class WebSocketManager {
    private socket: WebSocket | null = null;
    private handlers: Map<string, Set<EventHandler<unknown>>> = new Map();
    private reconnectAttempts = 0;
    private readonly maxRetries = 3;
    private heartbeatInterval: number | null = null;
    private lastHeartbeat = 0;

    // private listeners: Record<string, Function[]> = {
    //     message: [],
    //     open: [],
    //     close: [],
    //     error: [],
    //     invalid_message: [],
    //     parse_error: [],
    // };


    /*
    * @param url: WebSocket连接服务器地址；
    * @param onMessageCallback: 消息接收回调函数 - handleServerMessage
    * @param onOpenCallback: 连接成功回调函数 - connect
    * @param onErrorCallback: 错误处理回调函数 - 应已被整合入connect函数内。
     */

    constructor(private url: string) {}

    public connect(): Promise<void> {
        return new Promise((resolve, reject) => {
            if (this.socket?.readyState === WebSocket.OPEN) {
                console.log("我已经就位了");
                resolve();
                return;
            }

            this.socket = new WebSocket(this.url);

            this.socket?.addEventListener('open', (event) => {
                console.log('连接已建立');
                this.reconnectAttempts = 0;
                //this.startHeartbeat();
                this.emit('connected', event);
                console.log('这段文字代表连接成功')
                resolve();
            })

            this.socket?.addEventListener('error', (error) => {
                console.log("你改悔罢")
                this.emit('error', error);
                reject(error);
            })

            this.socket?.addEventListener('message', this.handleMessage.bind(this));

            this.socket?.addEventListener('close', (event) => {

                if (!event.wasClean && this.reconnectAttempts < this.maxRetries) {
                    setTimeout(() => {
                        console.log(`尝试重连：${this.reconnectAttempts + 1}/${this.maxRetries}`);
                        this.reconnectAttempts++;
                        this.connect().catch(reject);
                    }, 1000 * this.reconnectAttempts);
                } else {
                    console.log('不干了')
                    //this.stopHeartbeat();
                    this.emit('disconnected', event);
                    reject(new Error("Connection Closed"));
                }

            });




        });
    }

    private handleMessage = (event: MessageEvent) => {
        console.log("[WebSocket] 原始消息接收:", event.data);
        try {
            const data = JSON.parse(event.data);
            console.log("[WebSocket] 解析后的消息:", data);

            if (data.type === 'heartbeat') {
                this.lastHeartbeat = Date.now();
                return;
            }

            if (isServerMessage(data)) {
                this.handleServerMessage(data);
            } else {
                this.emit("invalid_message", data);
            }
        } catch (error) {
            this.emit("parse_error", error);
        }
    }

    public send<T extends ClientMessageType>(message: ClientMessage<T>): void {
        //构建消息格式的事情交给ChatView.vue文件。
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(message));
        } else {
            throw new Error("WebSocket is not connected.");
        }
    }

    public on<T>(event: string, handler: EventHandler<T>): void {
        console.log(`[事件系统] 注册监听器: ${event}`);
        const wrapper: EventHandler<unknown> = data => handler(data as T);
        if (!this.handlers.has(event)) {
            this.handlers.set(event, new Set());
        }
        this.handlers.get(event)?.add(wrapper);

    }

    public off<T>(event: string, handler: EventHandler<T>): void {
        const wrapper: EventHandler<unknown> = data => handler(data as T);
        this.handlers.get(event)?.delete(wrapper);
    }

    private handleServerMessage(message: AnyServerMessage): void {
        console.log("Message Received and Parsed");
        switch (message.type) {
            case "assistant_response":
                this.emit("message", message);
                break;
            case "stream_progress":
                this.emit("progress", message.payload);
                break;
            case "error":
                this.emit("error", message.payload);
                break;
            default:
                this.emit("unknown_message", message);
        }
    }

    public emit<T>(event: string, data?: T extends infer D?D: never): void {
        console.log(`[事件系统] 触发事件: ${event}`, data);
        this.handlers.get(event)?.forEach(handler => {
            if (typeof data !== 'undefined') {
                handler(data);
            }
        });
    }

    public disconnect(): void {
        this.socket?.close();
        this.handlers.clear();
    }

    private startHeartbeat() {
        this.lastHeartbeat =  Date.now();
        this.heartbeatInterval = window.setInterval(() => {
            if (Date.now() - this.lastHeartbeat > 30000) {
                console.log('心不跳力，现在重连');
                this.reconnect();
                return;
            }


            if (this.socket?.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify({type: 'heartbeat', timestamp: Date.now()}));
            }
        }, 1000) as unknown as number;
    }

    private stopHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
    }

    private reconnect() {
        if (this.socket) {
            this.socket.close(1000, 'reconnecting');
        }
        this.connect();
    }
}