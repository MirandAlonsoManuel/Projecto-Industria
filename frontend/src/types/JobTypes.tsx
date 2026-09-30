import type { ID, Timestamp, InspectionResult } from './CommonTypes';
import type { Camera } from './CameraTypes';
import type { Model } from './ModelTypes';
import type { Frame } from './FrameTypes';

/** Estado de la sesión de inspección */
export type JobStatus = 'idle' | 'running' | 'stopped' | 'error';

/** Resumen del último resultado de inspección */
export interface JobResultSummary{
    readonly frameId: Frame["id"];
    readonly result: InspectionResult;
    readonly timestamp: Timestamp;
}

/** Información de una sesión de inspección */
export interface Job {
    readonly id: ID;
    readonly cameraId: Camera["id"];
    readonly modelId: Model["id"];
    status: JobStatus;
    startedAt?: Timestamp;
    stoppedAt?: Timestamp;
    errorMessage?: string;
    lastResult?: JobResultSummary;
}