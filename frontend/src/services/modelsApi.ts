import { api } from './httpClient';
import type { ApiModel } from '../types';

export const getModels = (): Promise<ApiModel[]> =>
  api.get<ApiModel[]>('/models').then((r) => r.data);
