/**
 * HU-11: congela un valor mientras una condición está activa.
 *
 * Se usa para el ROI de la inspección: la URL del WebSocket de inferencia lleva el ROI,
 * así que si el ROI se movía durante la inspección el stream se reconectaba en cada
 * cambio. Con esto el ROI se fija al iniciar y los cambios se aplican al siguiente inicio.
 *
 * - Inactivo → no hay snapshot (null).
 * - Activo y sin snapshot → toma el valor actual.
 * - Activo y con snapshot → lo conserva, sin importar cómo cambie el valor.
 *
 * El snapshot va en una caja ({ value }) para distinguir "congelado sin ROI" (value null)
 * de "no congelado" (null).
 */
export type Snapshot<T> = { value: T } | null;

export function nextSnapshot<T>(current: Snapshot<T>, active: boolean, live: T): Snapshot<T> {
  if (!active) return null;
  return current ?? { value: live };
}