// Inline stroke icons (Lucide-style paths), so the page needs no icon font or extra request.
const PATHS: Record<string, string[]> = {
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "m20 20-4-4"],
  x: ["M18 6 6 18", "m6 6 12 12"],
  arrow: ["M5 12h14", "m13 6 6 6-6 6"],
  sun: [
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    "M12 2v2",
    "M12 20v2",
    "m4.9 4.9 1.4 1.4",
    "m17.7 17.7 1.4 1.4",
    "M2 12h2",
    "M20 12h2",
    "m6.3 17.7-1.4 1.4",
    "m19.1 4.9-1.4 1.4",
  ],
  moon: ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"],
  image: ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M9 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4z", "m21 15-5-5L5 21"],
  user: ["M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2", "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"],
  bolt: ["M13 2 3 14h9l-1 8 10-12h-9l1-8z"],
  clock: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M12 6v6l4 2"],
  spark: ["M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"],
  pin: ["M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z", "M12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"],
  help: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3", "M12 17h.01"],
  alert: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M12 8v4", "M12 16h.01"],
  link: ["M15 3h6v6", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
  "chevron-left": ["m15 18-6-6 6-6"],
  "chevron-right": ["m9 18 6-6-6-6"],
  github: [
    "M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.1-1.3-.3-2.5-1-3.5.3-1.2.3-2.4 0-3.5 0 0-1 0-3 1.5-2.6-.5-5.4-.5-8 0C6 2 5 2 5 2c-.3 1.1-.3 2.3 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.4.5-.7 1.1-.8 1.7-.2.6-.2 1.2-.2 1.8v4",
    "M9 18c-4.5 2-5-2-7-2",
  ],
};

export function Icon({ name }: { name: string }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {(PATHS[name] ?? []).map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
