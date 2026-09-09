import type {ROIRect} from '../types/ROITypes';

// Convierte coordenadas ROI a coordenadas normalizadas (0 a 1) respecto al tamaño del canvas
export function toNormalized(
    px: { x:  number, y: number, width: number, height: number },
    canvasWidth: number, 
    canvasHeight: number) {
    return {
        x: px.x / canvasWidth,
        y: px.y / canvasHeight,
        width: px.width / canvasWidth,
        height: px.height / canvasHeight,
    }
}

// Convierte coordenadas normalizadas (0 a 1) a coordenadas de píxeles respecto al tamaño del canvas
export function toPixels(
    px: { x:  number, y: number, width: number, height: number }, 
    canvasWidth: number, 
    canvasHeight: number
) {
    return {
        x: px.x * canvasWidth,
        y: px.y * canvasHeight,
        width: px.width * canvasWidth,
        height: px.height * canvasHeight,
    }
}

export function isValidNormalizedRect(
    rect: ROIRect,
    minSize = 0.01,
): boolean {
    return (
        rect.x >= 0 && rect.x <= 1 && 
        rect.y >= 0 && rect.y <= 1 &&
        rect.width >= minSize &&
        rect.height >= minSize &&
        rect.x + rect.width <= 1 &&
        rect.y + rect.height <= 1
    );
}