import { type Message } from "./api.ts"


//Client to Server
export interface ClientMessage<T extends ClientMessageType>{
    type: T;
    message_id: string;
    payload: ClientPayload[T];
}

//Server return to Client
export interface ServerMessage<T extends ServerMessageType> {
    type: T;
    message_id: string;
    status: ServerStatus;
    payload: ServerPayload[T];
}

//多轮上下文里的一条历史消息（正序，不含当前这条提问）
export type HistoryMessage = {
    role: 'user' | 'assistant';
    content: string;
};

//服务端 status 的合法取值
export type ServerStatus = "success" | "partial" | "error";

//Type Enums:
export enum ClientMessageType {
    QUERY = "client_query",
    CANCEL = "canceled_request",
    ERROR = "error",
}

export enum ServerMessageType {
    RESPONSE = "assistant_response",
    PROGRESS = "stream_progress",
    ERROR = "error",
    //后端判定 payload 非法时下发（缺失 role / modelText / realTimeRendering，或 text 是裸字符串）
    INVALID = "invalid_message",
}

//Payload Enums:
export type ClientPayload =  {
    [ClientMessageType.QUERY]: {
        textModel_config: {
            text: Message;
            modelText: string;
        };
        role: string;   //角色选择
        imageModel_config: {
            modelImage: string;
            realTimeRendering: boolean;
        };
        voiceCate: string;
        //多轮上下文：按会话组织，时间正序，不含当前这条；后端暂无该字段时可缺省
        history?: HistoryMessage[];
        sessionId?: string;
    };

    [ClientMessageType.CANCEL]: {
        target_message_id: string;
    };

    [ClientMessageType.ERROR]: {
        code: string;
        message: string;
        detail: string;
    };
};

export type ServerPayload = {
    [ServerMessageType.RESPONSE]: {
        response: string;
        emotion: string;
        index: string;

        metrics: {
            time_cost: number;
            tokens_used: number;
        };
        imageUrl: string;
    };

    [ServerMessageType.PROGRESS]: {
        progress: number;
        status: "processing" | "generating"| "rendering";
    };
    //传入后端的PROGRESS状态报文是否需要额外处理？

    [ServerMessageType.ERROR]: {
        code: string;
        message: string;
        detail: string;
    };

    [ServerMessageType.INVALID]: {
        reason: string;
    };
}

//---辅助参数验证类型---
export type AnyClientMessage = ClientMessage<ClientMessageType>;
export type AnyServerMessage = ServerMessage<ServerMessageType>;

export function isClientMessgage(
    data: unknown
): data is AnyClientMessage {
    return (
        typeof data === "object" &&
        data !== null &&
        "type" in data &&
        "message_id" in data &&
        "payload" in data
    );
}

const VALID_STATUSES: ServerStatus[] = ["success", "partial", "error"];

export function isServerMessage(
    data: unknown
): data is AnyServerMessage {
    if (!data || typeof data !== "object") return false;
    const msg = data as AnyServerMessage;
    return (
        Object.values(ServerMessageType).includes(msg.type) &&
        typeof msg.message_id === "string" &&
        //status 必须存在且落在 success / partial / error 之内，
        //否则缺 status 的报文会被当成合法响应，partial 与错误态都会被误判成成功。
        VALID_STATUSES.includes(msg.status) &&
        "payload" in msg
    );
}

