import { ReactNode } from "react";

type Props = {
  id?: string;
  title: ReactNode;
  sub?: ReactNode;
  align?: "center" | "left";
};

/** Serif section title with an optional plain sub line. */
export function SectionHeading({ id, title, sub, align = "left" }: Props) {
  const alignCls = align === "center" ? "text-center items-center mx-auto" : "text-left items-start";
  return (
    <div className={`flex flex-col gap-3 max-w-2xl ${alignCls}`}>
      <h2
        id={id}
        className="font-display text-[30px] sm:text-[38px] leading-[1.1] tracking-editorial text-ink"
      >
        {title}
      </h2>
      {sub && <p className="text-[16px] sm:text-[17px] leading-relaxed text-text-muted">{sub}</p>}
    </div>
  );
}

/** A readable column of plain paragraphs, used under a section heading. */
export function Prose({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 flex flex-col gap-4 text-[17px] leading-[1.7] text-text-muted [&_strong]:text-ink [&_strong]:font-semibold">
      {children}
    </div>
  );
}
