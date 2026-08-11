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
      <span className={`result-image-fallback ${className}`} role="img" aria-label={alt}>
        <span aria-hidden="true">×</span>
        Image unavailable
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
