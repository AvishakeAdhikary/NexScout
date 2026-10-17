// A template remounts on every navigation (unlike a layout), so each page gets a gentle
// entrance. Disabled automatically for people who prefer reduced motion (globals.css).
export default function CaseTemplate({ children }: { children: React.ReactNode }) {
  return <div className="animate-page">{children}</div>;
}
