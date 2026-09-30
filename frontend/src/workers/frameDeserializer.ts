/**
 * T-11: Web Worker — frame deserialization
 * Protocol: [4-byte uint32 BE JSON length][JSON][JPEG]
 * postMessage back { meta, jpeg } transferring jpeg (zero-copy).
 */

interface FrameWorkerResult {
  meta: unknown;
  jpeg: ArrayBuffer;
}

self.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  const buffer = event.data;
  if (!(buffer instanceof ArrayBuffer)) return;

  const view = new DataView(buffer);
  const jsonLen = view.getUint32(0, false);
  const jpegOffset = 4 + jsonLen;

  let meta: unknown = null;
  let jpeg: ArrayBuffer;

  if (jpegOffset < buffer.byteLength) {
    try {
      const jsonBytes = buffer.slice(4, jpegOffset);
      meta = JSON.parse(new TextDecoder().decode(jsonBytes));
    } catch {
      meta = null;
    }
    jpeg = buffer.slice(jpegOffset);
  } else {
    // Fallback: pure JPEG (no JSON header)
    jpeg = buffer;
  }

  const result: FrameWorkerResult = { meta, jpeg };
  (self as unknown as Worker).postMessage(result, [jpeg]);
};
