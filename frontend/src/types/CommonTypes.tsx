/**
 * Tipos comunes compartidos por los modelos del dominio
 */

export type ID = string;
export type Timestamp = number;

/** Resultado de una inspección */
export type InspectionResult = 'ok' | 'nok' | 'pending';