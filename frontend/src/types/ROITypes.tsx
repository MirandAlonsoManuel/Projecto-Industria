import type { ID, Timestamp } from './CommonTypes';
import type { Camera } from './CameraTypes';

/** Exporta la forma geométrica de la zona de interés */
export type ROIShape = 'rectangle' | 'polygon';

export interface ROIPoint {
    readonly x: number;
    readonly y: number;
}

/** Exporta el tipo de forma geométrica de la zona de interés */
export interface ROIRect {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface ROI {
    readonly id: ID;
    readonly cameraId: Camera["id"];
    
    /** Etiqueta descriptiva de la zona de interés */
    label: string;
    /** Tipo de forma geométrica de la zona de interés */
    shapeType: ROIShape;
    rect?: ROIRect;
    points?: ROIPoint[];
    /** Color de la zona de interés */
    color?: string;
    /** Indica si la zona de interés está habilitada */
    isEnabled: boolean;
    createdAt: Timestamp;
    updatedAt: Timestamp;

}