import type { ID } from "./CommonTypes";

/* Arquitecturas de modelos de IA para detección de objetos */
export type ModelArchitecture = "yolov8" | "yolov11" | "cnn" | "resnet" | "custom";

export interface ModelClass {
    readonly id: ID;
    name: string;
}

/** Modelo de IA para detección de objetos */
export interface Model {
    readonly id: ID;
    name: string;
    architecture: ModelArchitecture;
    classes: ModelClass[];
    confidenceThreshold: number;
    isActive: boolean;
}