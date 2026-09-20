import { useEffect, useRef, type ReactNode } from "react";

/** Horizontal snap carousel with edge-aware arrows (hidden at both ends). */
export function Carousel(props: { label: string; prev: string; next: string; children: ReactNode }) {
  const track = useRef<HTMLDivElement>(null);
  const prevBtn = useRef<HTMLButtonElement>(null);
  const nextBtn = useRef<HTMLButtonElement>(null);

  const update = () => {
    const t = track.current;
    if (!t || !prevBtn.current || !nextBtn.current) return;
    const max = t.scrollWidth - t.clientWidth;
    prevBtn.current.disabled = t.scrollLeft < 8;
    nextBtn.current.disabled = t.scrollLeft > max - 8;
  };

  useEffect(update, [props.children]);

  const step = () => ((track.current?.querySelector<HTMLElement>(".mcard")?.offsetWidth ?? 180) + 16) * 2;

  return (
    <div className="carousel" data-od-id="picks-carousel">
      <button
        ref={prevBtn}
        type="button"
        className="car-btn prev"
        aria-label={props.prev}
        onClick={() => track.current?.scrollBy({ left: -step(), behavior: "smooth" })}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M14.5 5.5 8 12l6.5 6.5" />
        </svg>
      </button>
      <div className="car-fade l" aria-hidden="true" />
      <div className="car-track" ref={track} tabIndex={0} role="group" aria-label={props.label} onScroll={update}>
        {props.children}
      </div>
      <div className="car-fade r" aria-hidden="true" />
      <button
        ref={nextBtn}
        type="button"
        className="car-btn next"
        aria-label={props.next}
        onClick={() => track.current?.scrollBy({ left: step(), behavior: "smooth" })}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M9.5 5.5 16 12l-6.5 6.5" />
        </svg>
      </button>
    </div>
  );
}
