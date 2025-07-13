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
    status: string;
    payload: ServerPayload[T];
}

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

export function isServerMessage(
    data: unknown
): data is AnyServerMessage {
    if (!data || typeof data !== "object") return false;
    const msg = data as AnyServerMessage;
    return (
        Object.values(ServerMessageType).includes(msg.type) &&
        typeof msg.message_id === "string" &&
        "payload" in msg
    );
}

