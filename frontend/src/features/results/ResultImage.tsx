import { useState } from "react";

import { resolveMediaUrl } from "../../api/client";

interface ResultImageProps {
  src: string;
  alt: string;
  className?: string;
  eager?: boolean;
}

export function ResultImage({ src, alt, className = "", eager = false }: ResultImageProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span className={`image-missing ${className}`.trim()} role="img" aria-label={alt}>
        Không có ảnh
      </span>
    );
  }

  return (
    <img
      className={className}
      src={resolveMediaUrl(src)}
      alt={alt}
      loading={eager ? "eager" : "lazy"}
      onError={() => setFailed(true)}
    />
  );
}
