import type { ID } from "./CommonTypes";
import type { Model } from "./ModelTypes";
import type { ROI } from "./ROITypes";
import type { Frame } from "./FrameTypes";

/** Representa un cuadro delimitador en una imagen */
export interface BoundingBox {
    x: number;
    y: number;
    width: number;
    height: number;
}

/** Exporta la información de una detección realizada por un modelo de IA */
export interface Detection {
    readonly id: ID;
    readonly FrameId: Frame["id"];
    readonly roiID: ROI["id"];
    readonly modelId: Model["id"];
    readonly classID: number;
    /** Confianza de la detección, valor entre 0 y 1 */
    readonly confidence: number;
    readonly boundingBox: BoundingBox;
}