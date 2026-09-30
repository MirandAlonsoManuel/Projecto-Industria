import { useEffect, useRef, useState } from 'react';

interface ImageDropzoneProps {
  label: string;
  file: File | null;
  onChange: (file: File | null) => void;
}

export function ImageDropzone({ label, file, onChange }: ImageDropzoneProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const apply = () => {
      if (!file) {
        setPreviewUrl(null);
        return undefined;
      }
      const url = URL.createObjectURL(file);
      setPreviewUrl(url);
      return url;
    };
    const url = apply();
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [file]);

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280]">
        {label}
      </span>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="h-32 rounded-lg border border-dashed border-[#c7ccd3] bg-[#f5f6f8] flex items-center justify-center overflow-hidden cursor-pointer hover:bg-[#f1f2f4]"
      >
        {previewUrl ? (
          <img src={previewUrl} alt={label} className="h-full w-full object-contain" />
        ) : (
          <span className="text-[13px] text-[#6b7280]">Haz clic para subir una imagen</span>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {file && (
        <div className="flex items-center justify-between text-[11px] text-[#6b7280]">
          <span className="truncate">{file.name}</span>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="text-[#d64545] font-semibold cursor-pointer"
          >
            Quitar
          </button>
        </div>
      )}
    </div>
  );
}
