import {create} from 'zustand';
import type {ROI} from '../types/ROITypes';
import {roiApi} from '../services/roiApi';

interface ROIState {
    rois: ROI[];
    isLoading: boolean;
    error: string | null;
    selectedId: string | null;

    // Acciones para manipular el estado
    fetchRois: (cameraId: string) => Promise<void>;
    addRoi: (roi: Omit<ROI, 'id' | 'createdAt' | 'updatedAt'>) => Promise<void>;
    updateRect: (id: string, rect: ROI['rect']) => Promise<void>;
    patchLabel: (id: string, label: string) => Promise<void>;
    toggleRoi: (id: string) => Promise<void>;
    removeRoi: (id: string) => Promise<void>;
    selectRoi: (id: string | null) => void;
    clearRois: () => void; // Limpia todos los ROIs del estado al cambiar de camara
}

export const useRoiStore = create<ROIState>((set, get) => ({
    rois: [],
    isLoading: false,
    error: null,
    selectedId: null,

    fetchRois: async (cameraId) => {
        set({isLoading: true, error: null});
        try {
            const rois = await roiApi.getAll(cameraId);
            console.log('[ROI] fetchRois -> rects normalizados:', rois.map(r => ({ id: r.id, rect: r.rect })));
            set({rois, isLoading: false});
        } catch (error) {
            set({error: (error as Error).message, isLoading: false});
        }
    },

    addRoi: async (roi) => {
        try{
            const created = await roiApi.create(roi);
            console.log('[ROI] addRoi -> rect normalizado creado:', created.id, created.rect);
            set(s => ({rois: [...s.rois, created]}));
        } catch (error) {
            set({error: "No se pudo guardar el ROI", isLoading: false });
        }
    },

    updateRect: async (id, rect) => {
        console.log('[ROI] updateRect -> rect normalizado enviado:', id, rect);
        set(s => ({
            rois: s.rois.map(r => r.id === id ? {...r, rect} : r),
        }));
        try {
            const roi = get().rois.find(r => r.id === id);
            if (roi) await roiApi.patch(id, { rect });
        } catch (error) {
            set({error: 'No se pudo actualizar el ROI', isLoading: false });
        }
    },

    // PATCH Label
    patchLabel: async (id, label) => {
        set(s => ({
            rois: s.rois.map(r => r.id === id ? {...r, label} : r),
        }));
        try{
            await roiApi.patch(id, { label });
        } catch (error) {
            set({error: 'No se pudo actualizar el label', isLoading: false });
        }
    },

    // Toggle desde el sidebar PATCH isEnabled
    toggleRoi: async (id) => {
        const roi = get().rois.find(r => r.id === id);
        if (!roi) return;
        const isEnabled = !roi.isEnabled;
        set(s => ({
        rois: s.rois.map(r => r.id === id ? { ...r, isEnabled } : r),
        }));
        try {
        await roiApi.patch(id, { isEnabled });
        } catch {
        set({ error: 'No se pudo actualizar el estado de la zona.' });
        }
    },

    // Eliminar ROI
    removeRoi: async (id) => {
        set(s => ({
        rois:       s.rois.filter(r => r.id !== id),
        selectedId: s.selectedId === id ? null : s.selectedId,
        }));
        try {
        await roiApi.remove(id);
        } catch {
        set({ error: 'No se pudo eliminar la zona de interés.' });
        }
    },

    selectRoi: (id) => {
        set({ selectedId: id });
    },

    clearRois: () => set({ rois: [], selectedId: null, error: null }),
}));
