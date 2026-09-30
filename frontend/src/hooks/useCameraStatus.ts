import type { Camera, CameraConnectionStatus } from "../types/indexTypes";

const MOCK_CAMERA: Pick<Camera, "status" | "name"> = {
  status: "connected",
  name: "Cámara de prueba",
};

export function useCameraStatus(): {
    status: CameraConnectionStatus;
    cameraName: string | undefined;
} {
    return {
        status: MOCK_CAMERA.status,
        cameraName: MOCK_CAMERA.name,
    };
}