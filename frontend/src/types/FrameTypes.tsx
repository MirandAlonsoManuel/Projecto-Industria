import type { ID, Timestamp } from './CommonTypes';
import type { Camera } from './CameraTypes';

/* * Exporta la información de un frame capturado por una cámara industrial */
export type FrameEncoding = "jpeg" | "png" | "bmp" | "webp" | "raw";
export type FrameData = ArrayBuffer | Blob | string;


export interface Frame {
    readonly id: ID;
    readonly cameraId: Camera["id"];
    readonly capturedAt: Timestamp;
    readonly sequence: number;
    encoding: FrameEncoding;
    width: number;
    height: number;
    data: FrameData;
}