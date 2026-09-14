import {type AnyServerMessage, ClientMessageType, isServerMessage, type ClientMessage} from "./MessageType.ts";

type EventHandler<in T=unknown> = (data: T) => void;

export class WebSocketManager {
    private socket: WebSocket | null = null;
    private handlers: Map<string, Set<EventHandler<unknown>>> = new Map();
    //on() 注册进 handlers 的是 wrapper，off() 若重新 new 一个 wrapper 就永远删不掉监听器。
    //因此按 event -> (原始 handler -> wrapper) 缓存引用，off() 时取出同一个 wrapper 再 delete。
    private wrappers: Map<string, Map<EventHandler<unknown>, EventHandler<unknown>>> = new Map();
    private reconnectAttempts = 0;
    private readonly maxRetries = 3;
    private heartbeatInterval: number | null = null;
    private lastHeartbeat = 0;
    //主动 disconnect 时置位，避免 close 事件被当成异常断开来处理
    private manualClose = false;

    //心跳周期与判死阈值：周期必须小于阈值，否则永远等不到服务端回包就自我重连
    private readonly heartbeatPeriod = 30_000;
    private readonly heartbeatTimeout = 90_000;


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

            this.manualClose = false;
            this.socket = new WebSocket(this.url);

            this.socket?.addEventListener('open', (event) => {
                this.reconnectAttempts = 0;
                this.startHeartbeat();
                this.emit('connected', event);
                resolve();
            })

            this.socket?.addEventListener('error', (error) => {
                this.emit('error', error);
                reject(error);
            })

            this.socket?.addEventListener('message', this.handleMessage.bind(this));

            this.socket?.addEventListener('close', (event) => {
                //断开时必须停掉心跳，否则定时器会一直持有已失效的 socket
                this.stopHeartbeat();

                if (!this.manualClose && !event.wasClean && this.reconnectAttempts < this.maxRetries) {
                    setTimeout(() => {
                        console.log(`尝试重连：${this.reconnectAttempts + 1}/${this.maxRetries}`);
                        this.reconnectAttempts++;
                        this.connect().catch(reject);
                    }, 1000 * this.reconnectAttempts);
                } else {
                    this.emit('disconnected', event);
                    reject(new Error("Connection Closed"));
                }

            });




        });
    }

    private handleMessage = (event: MessageEvent) => {
        //任何服务端报文都证明链路还活着
        this.lastHeartbeat = Date.now();
        try {
            const data = JSON.parse(event.data);

            // 后端对心跳回的是 pong（Connect.py），而 pong 不在 ServerMessageType 里。
            // 漏在这里就会被下面的 isServerMessage 判成非法消息，
            // 结果每 30 秒弹一次「请求被后端拒绝：未知原因」。
            if (data.type === 'heartbeat' || data.type === 'pong') {
                return;
            }

            //invalid_message 不带 status，过不了 isServerMessage，
            //必须单独识别，否则会被当成"未知消息"静默丢弃。
            if (data.type === 'invalid_message') {
                this.emit("invalid_message", data);
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
        const wrapper: EventHandler<unknown> = data => handler(data as T);
        if (!this.handlers.has(event)) {
            this.handlers.set(event, new Set());
        }
        this.handlers.get(event)?.add(wrapper);

        if (!this.wrappers.has(event)) {
            this.wrappers.set(event, new Map());
        }
        this.wrappers.get(event)?.set(handler as EventHandler<unknown>, wrapper);
    }

    public off<T>(event: string, handler: EventHandler<T>): void {
        const wrapper = this.wrappers.get(event)?.get(handler as EventHandler<unknown>);
        if (!wrapper) return;

        this.handlers.get(event)?.delete(wrapper);
        this.wrappers.get(event)?.delete(handler as EventHandler<unknown>);
    }

    private handleServerMessage(message: AnyServerMessage): void {
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
        //无条件回调：像 disconnected 这类不带数据的事件，
        //若要求 data !== undefined 就永远不会触发。
        this.handlers.get(event)?.forEach(handler => {
            handler(data);
        });
    }

    public disconnect(): void {
        this.manualClose = true;
        this.stopHeartbeat();
        this.socket?.close();
        this.socket = null;
        this.handlers.clear();
        this.wrappers.clear();
    }

    private startHeartbeat() {
        this.stopHeartbeat();
        this.lastHeartbeat =  Date.now();
        this.heartbeatInterval = window.setInterval(() => {
            if (Date.now() - this.lastHeartbeat > this.heartbeatTimeout) {
                console.log('心不跳力，现在重连');
                this.reconnect();
                return;
            }


            if (this.socket?.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify({type: 'heartbeat', timestamp: Date.now()}));
            }
        }, this.heartbeatPeriod) as unknown as number;
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
        this.connect().catch(error => {
            console.error('重连失败: ', error);
        });
    }
}
