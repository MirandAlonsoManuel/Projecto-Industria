import type { ID } from "./CommonTypes";

/** Protocolos de comunicación de la cámara industrial */
export type CameraProtocol = 
    "usb3" 
    | "usb2" 
    | "gige" 
    | "rtsp" 
    | "http" 
    | "https" 
    | "file" 
    | "ip" 
    | "other";

export type CameraConnectionStatus =
    | "connected"
    | "disconnected"
    | "connecting"
    | "disconnecting"
    | "error";

export interface CameraResolution {
    readonly width: number;
    readonly height: number;
}

/** Camara industrial disponible para alimentar la inspección */
export interface Camera {
    readonly id: ID;
    name: string;
    protocol: CameraProtocol;
    resolution: CameraResolution;
    fps: number;
    status: CameraConnectionStatus;
    isActive: boolean;
    lastErrorMessage?: string;
}