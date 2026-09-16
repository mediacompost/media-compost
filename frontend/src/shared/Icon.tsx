import React from "react";

export function Icon({
  name,
  size = 18,
  color,
  style,
  spin,
  className,
  ...rest
}: {
  name: string;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
  /** A class of the caller's own beside the font's. */
  className?: string;
  /** A running spinner. The ONE spelling of `mc-spin` (`tokens.css`): the
   *  inline `animation:` string it replaced was written out at nineteen
   *  sites while five others named the class, and the class did not exist
   *  for a while — a running job that looked stuck. */
  spin?: boolean;
} & Omit<React.HTMLAttributes<HTMLSpanElement>, "color" | "style" | "className">) {
  const cls = ["msym", spin ? "mc-spin" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <span className={cls} style={{ fontSize: size, color, ...style }} {...rest}>
      {name}
    </span>
  );
}
