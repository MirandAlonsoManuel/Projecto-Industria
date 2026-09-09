import axios from 'axios';
import type {ROI, ROIRect, ROIShape} from '../types/ROITypes';

const API = axios.create({
    baseURL: 'http://127.0.0.1:8000', timeout: 5000 // Reemplaza con la URL de tu API
});

// Interfaz que representa un ROI tal como se recibe de la API
interface ApiROI {
    id: string;
    camera_id: string;
    label: string;
    shape_type: ROIShape;
    rect?: ROIRect;
    color?: string;
    is_enabled: boolean;
    created_at: number;
    updated_at: number;
}

// Respuesta envuelta
interface RoisResponse {
    data: ApiROI[];
    error: string | null;
    meta: { total: number }
}

// Conversiones
const toROI = (ar: ApiROI): ROI => ({
    id: ar.id,
    cameraId: ar.camera_id,
    label: ar.label,
    shapeType: ar.shape_type,
    rect: ar.rect,
    color: ar.color,
    isEnabled: ar.is_enabled,
    createdAt: ar.created_at,
    updatedAt: ar.updated_at,
});

// Payload que permite hacer POST o PUT de front a back
type ROIPayLoad = {
    camera_id: string;
    label: string;
    shape_type: ROIShape;
    rect?: ROIRect;
    color?: string;
    is_enabled: boolean;
}

const toPayLoad = (roi: Omit<ROI, 'id' | 'createdAt' | 'updatedAt'>): ROIPayLoad => ({
    camera_id: roi.cameraId,
    label: roi.label,
    shape_type: roi.shapeType,
    rect: roi.rect,
    color: roi.color,
    is_enabled: roi.isEnabled,
});

// API publica para interactuar con los ROIs

export const roiApi = {
    // Obtiene todos los ROIs
    getAll: (cameraId: string): Promise<ROI[]> => 
        API.get<RoisResponse>(`/rois`, {
            params: { camera_id: cameraId }
        })
            .then(response => response.data.data.map(toROI)),

    // Crea un nuevo ROI
    create: (roi: Omit<ROI, 'id' | 'createdAt' | 'updatedAt'>): Promise<ROI> =>
        API.post<ApiROI>('/rois', toPayLoad(roi))
            .then(response => toROI(response.data)),

    // Reemplaza totalmente un ROI existente
    update: (id: string, roi: Omit<ROI, 'id' | 'createdAt' | 'updatedAt'>): Promise<ROI> =>
        API.put<ApiROI>(`/rois/${id}`, toPayLoad(roi))
            .then(response => toROI(response.data)),
    
    // Campos parciales en un ROI (isEnabled, label, color)
    patch: (id: string, fields: Partial<Pick<ROI, 'label' | 'color' | 'isEnabled' | 'rect'>>): Promise<ROI> => 
        API.patch<ApiROI>(`/rois/${id}`, fields)
            .then(response => toROI(response.data)),

    // Elimina un ROI existente
    remove: (id: string): Promise<void> =>
        API.delete<void>(`/rois/${id}`).then(() => undefined),
};
